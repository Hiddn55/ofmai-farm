"""Account creation: the four recorded signup skills, their guard, their rules.

One account is created per platform, on the character's own phone, behind the
character's own static US address — never bought, never imported (R7). The
procedure itself lives in ``docs/social/account-creation.md`` §6; this module is
what the code needs to know about it:

  - :data:`SKILL_BY_PLATFORM` — where each ``recorded.json`` lives,
  - :func:`validate_steps` / :func:`validate_params` — the rules a step list and
    a run's parameters must obey *before* a phone is touched,
  - :func:`guard_screen` — the two screens that stop a creation dead,
  - :class:`GuardedRecordedWorkflow` — the workflow ``_run_skill.py`` uses when a
    ``skill.yaml`` declares ``health_platform``.

Why the creation is a **recorded** skill and not a coded ``Action``: the human
gate (``checkpoint``) only exists as a recorded step (``RecordedStepAction``),
and every creation has at least two — the email code and the password. A captcha,
an SMS code, a login are never solved by an agent (R25).

Nothing here registers the account in the ledger: ``accounts add`` is a separate,
human-verified step (``account-creation.md`` §7), because the day of creation is
day 1 of the whole warming policy and a wrong date silently mis-phases the
account for a month.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gitd.farm import health
from gitd.skills.base import ActionResult, RecordedStepAction, RecordedWorkflow
from gitd.skills.checkpoint import VALID_REASONS

# ── What exists ───────────────────────────────────────────────────────────────

PLATFORMS: tuple[str, ...] = ("instagram", "tiktok", "x", "reddit")

SKILL_BY_PLATFORM: dict[str, str] = {p: f"ofmai_signup_{p}" for p in PLATFORMS}

# Kept in step with the warming skills; both must name the same app or the
# creation and the warming would run against two different packages.
APP_PACKAGE: dict[str, str] = {
    "instagram": "com.instagram.android",
    "tiktok": "com.zhiliaoapp.musically",
    "x": "com.twitter.android",
    "reddit": "com.reddit.frontpage",
}

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

# ── Rules a step list must obey ───────────────────────────────────────────────

# Everything RecordedStepAction.execute() actually dispatches. An unknown action
# only logs a warning and reports success, so a typo would silently skip a step
# of a signup — hence this whitelist is checked, not trusted.
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "launch",
        "open_app",
        "tap",
        "type",
        "key",
        "back",
        "home",
        "swipe",
        "long_press",
        "open_url",
        "launch_intent",
        "checkpoint",
        "wait",
    }
)

# Placeholders that would put a secret into skill_runs.params_json — an unencrypted
# SQLite behind an unauthenticated REST port (R9). A password is typed by a human
# at a `login` checkpoint, read from the Keychain, and never passed as a parameter.
FORBIDDEN_PLACEHOLDERS: tuple[str, ...] = (
    "password",
    "passwd",
    "pwd",
    "pass",
    "secret",
    "token",
    "otp",
    "code",
    "pin",
    "sim",
    "recovery",
)

# A link in a bio before the first post is a spam-classifier magnet (R22); the
# link-in-bio is posted by hand on the day the account reaches cruise.
# Three shapes: a scheme, a "www.", a bare domain followed by a path (linktr.ee/x),
# or a bare domain on a TLD a link-in-bio actually uses (beacons.ai, fanvue.com).
_URL_RE = re.compile(
    r"(https?://"
    r"|www\."
    r"|\b[a-z0-9][a-z0-9-]*\.[a-z]{2,6}/"
    r"|\b[a-z0-9][a-z0-9-]*\.(com|ai|net|org|io|co|me|link|bio|app|page|gg|tv|xyz)\b)",
    re.IGNORECASE,
)

# Third-party provider names never appear in anything the public can read (R10).
PROVIDER_NAMES: tuple[str, ...] = (
    "higgsfield",
    "seedance",
    "seeddream",
    "wavespeed",
    "modal",
    "krea",
    "lustify",
    "wan",
    "grok",
    "gemini",
    "geelark",
    "iproyal",
    "manychat",
    "didit",
    "hive",
    "x.ai",
    "openai",
    "kie.ai",
    "nowpayments",
    "centrobill",
)

# Fields RecordedWorkflow.steps() substitutes parameters into.
# Whole words only: a substring match would read "wan" inside "want" and refuse a
# perfectly innocent bio.
_PROVIDER_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in PROVIDER_NAMES) + r")\b", re.IGNORECASE)

# ── Screens that stop a creation ──────────────────────────────────────────────

# A synthetic character has no identity to show, and trying to pass an identity
# check with one would be fraud (R1, R11). account-creation.md §9: a video-selfie
# or ID screen is an immediate abandon — not a retry, not a human workaround.
# These are deliberately *not* health.py's `verification` patterns: at signup,
# "verify your email" and "enter the code" are the normal gates, so matching them
# would stop every single run on its first checkpoint.
IDENTITY_PATTERNS: tuple[str, ...] = (
    r"video selfie",
    r"record a (short )?video of yourself",
    r"take a video selfie",
    r"verify your identity",
    r"confirm your identity",
    r"government[- ]issued (photo )?id",
    r"upload (a photo of )?your (id|passport|driver)",
    r"photo of your (id|passport|driver.?s licen[cs]e)",
    r"id verification",
)


def guard_screen(platform: str, screen_text: str) -> str | None:
    """Why this screen must stop the creation, or None to carry on.

    Two reasons only, in order of severity:

    ``suspended: <matched>``
        ``health.detect`` raised a suspension for this platform. One suspension
        costs the platform on that phone for 30 days (R18) — the run stops
        before it makes it worse.

    ``identity_check: <matched>``
        A video selfie or an ID was asked for (``account-creation.md`` §9).
    """
    text = screen_text or ""
    signal = health.detect(platform, text)
    if signal is not None and signal.kind == "suspended":
        return f"suspended: {signal.matched}"
    for pattern in IDENTITY_PATTERNS:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return f"identity_check: {m.group(0)}"
    return None


# ── Loading and validating ────────────────────────────────────────────────────


def skill_dir(platform: str) -> Path:
    if platform not in SKILL_BY_PLATFORM:
        raise ValueError(f"unknown signup platform: {platform!r} (expected one of {', '.join(PLATFORMS)})")
    return _SKILLS_DIR / SKILL_BY_PLATFORM[platform]


def load_steps(platform: str) -> list[dict]:
    """The recorded step list of one signup skill."""
    path = skill_dir(platform) / "workflows" / "recorded.json"
    steps = json.loads(path.read_text())
    if not isinstance(steps, list):
        raise ValueError(f"{path} does not hold a step list")
    return steps


def load_metadata(platform: str) -> dict:
    import yaml

    path = skill_dir(platform) / "skill.yaml"
    return yaml.safe_load(path.read_text()) or {}


def _placeholders(value: str) -> list[str]:
    return re.findall(r"\{([a-z0-9_]+)\}", value, flags=re.IGNORECASE)


def _strings_of(step: dict) -> list[tuple[str, str]]:
    """Every string a step carries, as (field path, value)."""
    out: list[tuple[str, str]] = []
    for key, value in step.items():
        if isinstance(value, str):
            out.append((key, value))
        elif isinstance(value, dict):
            for sub, sub_value in value.items():
                if isinstance(sub_value, str):
                    out.append((f"{key}.{sub}", sub_value))
    return out


def validate_steps(steps: list[dict], platform: str) -> list[str]:
    """Everything wrong with one signup step list. Empty list = ready to replay.

    This is the executable form of ``account-creation.md`` §4 and of the rules it
    cites; a signup skill that fails any of it must never touch a phone.
    """
    problems: list[str] = []

    if not steps:
        return [f"{platform}: empty step list"]

    first = steps[0]
    if first.get("action") not in ("launch", "open_app"):
        problems.append(f"{platform}: step 1 must launch the app, got {first.get('action')!r}")
    elif first.get("package") != APP_PACKAGE[platform]:
        problems.append(f"{platform}: step 1 launches {first.get('package')!r}, expected {APP_PACKAGE[platform]!r}")

    saw_checkpoint = {"email": False, "login": False}

    for index, step in enumerate(steps, start=1):
        where = f"{platform} step {index}"
        action = step.get("action")

        if action not in ALLOWED_ACTIONS:
            problems.append(f"{where}: unknown action {action!r} — it would be silently skipped")

        if "verified" not in step:
            problems.append(f"{where}: missing 'verified' flag (Skill Miner bookkeeping, R34)")

        for field, value in _strings_of(step):
            # R12 applies to what reaches the phone, not to what a human reads:
            # `text` is typed through `adb shell input text` (which silently drops
            # anything above ASCII), and a `success` needle is matched against a UI
            # dump. Prompts and descriptions are read in a terminal and on Discord
            # and may be written like prose.
            if field in ("text", "success.screen_has", "success.url_contains") and not value.isascii():
                problems.append(f"{where}: non-ASCII in {field} ({value!r}) — it would be typed mangled (R12)")
            for name in _placeholders(value):
                if name.lower() in FORBIDDEN_PLACEHOLDERS:
                    problems.append(f"{where}: forbidden placeholder {{{name}}} in {field} (R9)")

        if action == "type":
            text = step.get("text", "")
            if not text:
                problems.append(f"{where}: type step with no text")
            if _URL_RE.search(text):
                problems.append(f"{where}: a URL is typed ({text!r}) — no link before cruise (R22)")
            hit = _PROVIDER_RE.search(text)
            if hit:
                problems.append(f"{where}: provider name {hit.group(0)!r} in typed text (R10)")

        if action == "tap":
            if not any(step.get(k) for k in ("text", "resource_id", "content_desc", "class_name")):
                problems.append(f"{where}: tap without a locator")
            if step.get("x") is not None or step.get("y") is not None:
                problems.append(f"{where}: tap falls back to coordinates — locators only (R34)")

        if action == "checkpoint":
            reason = step.get("reason")
            if reason not in VALID_REASONS:
                problems.append(f"{where}: checkpoint reason {reason!r} not in {sorted(VALID_REASONS)}")
            elif reason in saw_checkpoint:
                saw_checkpoint[reason] = True
            if not step.get("prompt"):
                problems.append(f"{where}: checkpoint without a prompt — a human would not know what to do")
            if step.get("timeout_s") != 0:
                problems.append(
                    f"{where}: checkpoint timeout_s={step.get('timeout_s')!r}, expected 0 "
                    "(a timed_out gate leaves a half-created account)"
                )

    for reason, seen in saw_checkpoint.items():
        if not seen:
            problems.append(f"{platform}: no {reason!r} checkpoint — every signup has one (account-creation.md §4.2)")

    last = steps[-1]
    screen_has = (last.get("success") or {}).get("screen_has", "")
    if last.get("action") != "checkpoint" or "{handle}" not in screen_has:
        problems.append(
            f"{platform}: the run must end on a checkpoint whose success is the profile screen "
            'showing {handle}, got ' + repr(last.get("action"))
        )

    return problems


def validate_params(params: dict[str, Any], platform: str) -> list[str]:
    """Everything wrong with the parameters of one signup run.

    Checked at launch, not only at authoring time: the bio and the handle come
    from a persona sheet copied by hand, and the step list cannot see them.
    """
    problems: list[str] = []

    for key, value in params.items():
        if key.lower() in FORBIDDEN_PLACEHOLDERS:
            problems.append(f"{platform}: parameter {key!r} would write a secret to skill_runs.params_json (R9)")
        if not isinstance(value, str):
            continue
        if not value.isascii():
            problems.append(f"{platform}: parameter {key!r} is not ASCII ({value!r}) — it would be typed mangled (R12)")
        if key.startswith("bio") and _URL_RE.search(value):
            problems.append(f"{platform}: a URL in {key!r} — no link in a bio before cruise (R22)")
        hit = _PROVIDER_RE.search(value)
        if hit:
            problems.append(f"{platform}: provider name {hit.group(0)!r} in parameter {key!r} (R10)")

    if not params.get("handle"):
        problems.append(f"{platform}: no handle — the final gate checks the profile screen for it")

    return problems


def ready_for_real_run(platform: str) -> tuple[bool, list[str]]:
    """Whether this signup skill may touch a real account today (R34).

    False while any step is still unverified or ``tested_on`` is empty: a wrong
    selector on a creation screen taps the wrong button, and on these screens
    the wrong button is a phone number, a follow, or an identity check.
    """
    reasons: list[str] = list(validate_steps(load_steps(platform), platform))

    meta = load_metadata(platform)
    if not meta.get("tested_on"):
        reasons.append(f"{platform}: skill.yaml tested_on is empty — run Skill Miner on the app first (R34)")

    unverified = [i for i, s in enumerate(load_steps(platform), start=1) if not s.get("verified")]
    if unverified:
        reasons.append(f"{platform}: {len(unverified)} step(s) still unverified on a device: {unverified}")

    return (not reasons), reasons


# ── The guarded workflow ──────────────────────────────────────────────────────


class GuardedRecordedStepAction(RecordedStepAction):
    """A recorded step that reads the screen it left behind.

    ``RecordedStepAction`` only knows whether its own gesture landed. On a
    creation screen that is not enough: a suspension or an identity check can
    appear at any step, and every further tap on such a screen makes the outcome
    worse. So after each successful step the screen is re-read and matched
    against :func:`guard_screen`.
    """

    def __init__(
        self,
        device,
        step: dict,
        step_index: int,
        run_id: int | None = None,
        platform: str = "",
        skill_name: str = "",
    ):
        super().__init__(device, step, step_index, run_id=run_id)
        self.platform = platform
        # Read back by the checkpoint's Discord alert so the message names the
        # skill a human has to go and unblock, not just a run id.
        self.skill_name = skill_name

    def execute(self) -> ActionResult:
        result = super().execute()
        if not result or not self.platform:
            return result
        try:
            xml = self.device.dump_xml() or ""
        except Exception:
            return result  # a screen we cannot read is not a screen we may judge
        reason = guard_screen(self.platform, xml)
        if reason:
            return ActionResult(success=False, error=f"stopped by screen guard — {reason}", data=dict(result.data))
        return result


class GuardedRecordedWorkflow(RecordedWorkflow):
    """``RecordedWorkflow`` whose every step is guarded (see above).

    Used by ``_run_skill.py`` for any skill whose ``skill.yaml`` declares
    ``health_platform``. Parameter substitution, popup detection and checkpoint
    handling are unchanged — this only adds the stop.
    """

    def __init__(self, device, recorded_steps, params=None, run_id=None, platform: str = "", skill_name: str = ""):
        super().__init__(device, recorded_steps, params=params, run_id=run_id)
        self.platform = platform
        self.skill_name = skill_name

    def steps(self):
        # super().steps() has already substituted the parameters; only the class
        # of each step changes here.
        base_steps = super().steps()
        return [
            GuardedRecordedStepAction(
                self.device,
                action._step,
                index,
                run_id=self._run_id,
                platform=self.platform,
                skill_name=self.skill_name,
            )
            for index, action in enumerate(base_steps)
        ]


def build_workflow(device, platform: str, params: dict[str, Any], run_id: int | None = None) -> GuardedRecordedWorkflow:
    """The workflow that creates one account, with its steps already validated."""
    steps = load_steps(platform)
    problems = validate_steps(steps, platform) + validate_params(params, platform)
    if problems:
        raise ValueError("signup refused:\n  - " + "\n  - ".join(problems))
    workflow = GuardedRecordedWorkflow(
        device, steps, params=params, run_id=run_id, platform=platform, skill_name=SKILL_BY_PLATFORM[platform]
    )
    workflow.app_package = APP_PACKAGE[platform]
    workflow._popup_detectors = load_metadata(platform).get("popup_detectors") or None
    return workflow


def _main() -> int:
    """``python -m gitd.farm.signup`` — lint the four step lists, touch no phone."""
    failed = False
    for platform in PLATFORMS:
        ok, reasons = ready_for_real_run(platform)
        steps = load_steps(platform)
        gates = [s for s in steps if s.get("action") == "checkpoint"]
        print(f"{platform:10s} {len(steps):3d} steps, {len(gates)} human gates — {'ready' if ok else 'NOT ready'}")
        for reason in reasons:
            print(f"             · {reason}")
        # Only a rule violation is a failure; "unverified" is the expected state
        # until Skill Miner has been run on the phone.
        if validate_steps(steps, platform):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(_main())
