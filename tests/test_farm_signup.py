"""The four account-creation skills (E2.2-2.5, docs/social/account-creation.md §6).

No device, no network, no account: what is checked here is the *step list* and
the guard around it — the part that decides, before a phone is ever touched,
whether a creation is allowed to run. Whether the selectors match the real apps
is Skill Miner's job on the Mac mini (R34): the three walked platforms carry
their `tested_on` entry, and the screens nobody mined still say "verified": false.
"""

from unittest.mock import MagicMock

import pytest

import gitd.skills.base as base
from gitd.farm import signup
from gitd.skills.base import RecordedStepAction, RecordedWorkflow
from gitd.skills.checkpoint import VALID_REASONS


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """The engine's per-step settle sleep would make this suite take a minute."""
    monkeypatch.setattr(base.time, "sleep", lambda *a, **k: None)


def _device(xml: str = "<hierarchy/>"):
    dev = MagicMock()
    dev.serial = "fake-signup"
    dev.dump_xml.return_value = xml
    return dev


# ── The four step lists ───────────────────────────────────────────────────────


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_recorded_json_loads_and_obeys_every_rule(platform):
    steps = signup.load_steps(platform)
    assert steps, f"{platform}: empty"
    assert signup.validate_steps(steps, platform) == []


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_every_checkpoint_is_a_real_gate(platform):
    """Valid reason, a prompt a human can act on, and no timeout.

    `DEFAULT_TIMEOUT_S` is 600 s: a creation that times out leaves a half-made
    account nobody owns, so every gate of a signup waits indefinitely instead
    (account-creation.md §4.2).
    """
    gates = [s for s in signup.load_steps(platform) if s.get("action") == "checkpoint"]
    assert gates, f"{platform}: a signup with no human gate is not a signup (R25)"
    for gate in gates:
        assert gate["reason"] in VALID_REASONS
        assert gate.get("prompt")
        assert gate.get("timeout_s") == 0


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_email_and_login_gates_exist(platform):
    reasons = {s.get("reason") for s in signup.load_steps(platform) if s.get("action") == "checkpoint"}
    assert "email" in reasons  # the confirmation code, always asked
    assert "login" in reasons  # the password, typed by a human, never a parameter


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_no_secret_ever_becomes_a_parameter(platform):
    """R9: _run_skill.py writes params_json into an unencrypted SQLite behind an
    unauthenticated REST port. A {password} placeholder would put it there."""
    blob = str(signup.load_steps(platform))
    for forbidden in signup.FORBIDDEN_PLACEHOLDERS:
        assert "{" + forbidden + "}" not in blob


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_nothing_typed_carries_a_link_or_a_provider_name(platform):
    """R22 (no link before cruise) and R10 (no provider name in published text)."""
    for step in signup.load_steps(platform):
        if step.get("action") != "type":
            continue
        assert not signup._URL_RE.search(step["text"])
        assert not signup._PROVIDER_RE.search(step["text"])
        assert step["text"].isascii()  # R12: adb shell input text drops the rest


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_first_step_launches_the_same_app_as_the_warming_skill(platform):
    first = signup.load_steps(platform)[0]
    assert first["action"] == "launch"
    assert first["package"] == signup.APP_PACKAGE[platform]


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_the_run_ends_on_the_profile_screen_with_the_handle(platform):
    last = signup.load_steps(platform)[-1]
    assert last["action"] == "checkpoint"
    assert last["success"]["screen_has"] == "{handle}"


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_no_tap_falls_back_to_coordinates(platform):
    """A coordinate tap survives no app update; on a creation screen the button
    next to the right one is a phone number or a follow (R34)."""
    for step in signup.load_steps(platform):
        if step.get("action") == "tap":
            assert step.get("x") is None and step.get("y") is None
            assert any(step.get(k) for k in ("text", "resource_id", "content_desc", "class_name"))


# The platforms whose signup was walked on a device (docs/social/screens-*.md):
# their skill.yaml carries a `tested_on` entry and every screen that was seen
# is "verified": true. X has no device path at all (the cloud phone is refused,
# screens-x.md) and stays empty.
WALKED = {"instagram", "reddit", "tiktok"}


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_not_ready_for_a_real_run_while_a_step_is_unverified(platform):
    """A walked skill still has human-only screens nobody mined (profile editor,
    settings): they keep the real-run gate shut, which is the point of R34."""
    ready, reasons = signup.ready_for_real_run(platform)
    assert ready is False
    if platform in WALKED:
        assert not any("tested_on" in r for r in reasons)
        assert any("unverified" in r for r in reasons)
    else:
        assert any("tested_on" in r for r in reasons)


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_skill_yaml_declares_its_guard_and_its_app(platform):
    meta = signup.load_metadata(platform)
    assert meta["kind"] == "hard"  # the checkpoint step only exists in a recorded skill
    assert meta["health_platform"] == platform
    assert meta["app_package"] == signup.APP_PACKAGE[platform]
    if platform in WALKED:
        entry = meta["tested_on"][0]
        assert entry["app_version"] and entry["date"] and entry["verified"]
    else:
        assert meta["tested_on"] == []


# ── The validator catches what a careless edit would introduce ────────────────


def _ok_step(**over):
    step = {"action": "wait", "seconds": 1, "description": "d", "verified": True}
    step.update(over)
    return step


def _list(*steps):
    """A minimal-but-valid instagram list, plus whatever is inserted in the middle."""
    head = _ok_step(action="launch", package=signup.APP_PACKAGE["instagram"])
    gates = [
        _ok_step(action="checkpoint", reason="email", prompt="p", timeout_s=0),
        _ok_step(action="checkpoint", reason="login", prompt="p", timeout_s=0),
    ]
    tail = _ok_step(action="checkpoint", reason="generic", prompt="p", timeout_s=0, success={"screen_has": "{handle}"})
    return [head, *gates, *steps, tail]


def test_a_clean_list_has_no_problem():
    assert signup.validate_steps(_list(), "instagram") == []


@pytest.mark.parametrize(
    "bad, expected",
    [
        (_ok_step(action="type", text="{password}"), "forbidden placeholder"),
        (_ok_step(action="checkpoint", reason="banana", prompt="p", timeout_s=0), "not in"),
        (_ok_step(action="checkpoint", reason="sms", prompt="p", timeout_s=600), "expected 0"),
        (_ok_step(action="checkpoint", reason="sms", prompt="", timeout_s=0), "without a prompt"),
        (_ok_step(action="type", text="https://ofmai.ai"), "no link before cruise"),
        (_ok_step(action="type", text="made with higgsfield"), "provider name"),
        (_ok_step(action="type", text="cafe creme"), None),  # a plain ASCII bio is fine
        (_ok_step(action="type", text="café crème"), "non-ASCII"),
        (_ok_step(action="tap", text="Next", x=10, y=20), "coordinates"),
        (_ok_step(action="tap"), "without a locator"),
        (_ok_step(action="scroll_down"), "unknown action"),
        ({"action": "wait", "seconds": 1}, "missing 'verified' flag"),
    ],
)
def test_validator_catches_it(bad, expected):
    problems = signup.validate_steps(_list(bad), "instagram")
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


def test_validator_refuses_a_list_that_launches_the_wrong_app():
    steps = _list()
    steps[0] = _ok_step(action="launch", package="com.zhiliaoapp.musically")
    assert any("expected 'com.instagram.android'" in p for p in signup.validate_steps(steps, "instagram"))


def test_validator_refuses_a_list_that_does_not_end_on_the_handle():
    steps = _list()
    steps[-1] = _ok_step(action="home")
    assert any("profile screen" in p for p in signup.validate_steps(steps, "instagram"))


def test_validator_refuses_a_list_without_a_login_gate():
    steps = [s for s in _list() if s.get("reason") != "login"]
    assert any("'login' checkpoint" in p for p in signup.validate_steps(steps, "instagram"))


# ── The parameters of one run ─────────────────────────────────────────────────

GOOD_PARAMS = {
    "email": "sierra.cole.ai@gmail.com",
    "handle": "sierra.cole",
    "name": "Sierra Cole",
    "birthday": "2001-03-14",
    "bio_line1": "sierra, 25, la",
    "bio_line2": "AI character, made on ofmai",
    "bio_line3": "6am club",
}


def test_a_persona_sheet_copied_correctly_passes():
    assert signup.validate_params(GOOD_PARAMS, "instagram") == []


def test_a_password_parameter_is_refused():
    problems = signup.validate_params({**GOOD_PARAMS, "password": "hunter2"}, "instagram")
    assert any("R9" in p for p in problems)


def test_a_link_in_a_bio_is_refused():
    problems = signup.validate_params({**GOOD_PARAMS, "bio_line3": "linktr.ee/sierra"}, "instagram")
    assert any("R22" in p for p in problems)


def test_a_non_ascii_bio_is_refused():
    problems = signup.validate_params({**GOOD_PARAMS, "bio_line1": "sierra, 25, là"}, "instagram")
    assert any("R12" in p for p in problems)


def test_a_provider_name_in_a_bio_is_refused():
    problems = signup.validate_params({**GOOD_PARAMS, "bio_line2": "made with Higgsfield"}, "instagram")
    assert any("R10" in p for p in problems)


def test_a_bio_that_merely_contains_a_provider_substring_is_fine():
    """'wan' is a provider; 'I want' is not. Whole words only."""
    assert signup.validate_params({**GOOD_PARAMS, "bio_line3": "i want it all"}, "instagram") == []


def test_no_handle_is_refused():
    problems = signup.validate_params({k: v for k, v in GOOD_PARAMS.items() if k != "handle"}, "instagram")
    assert any("no handle" in p for p in problems)


# ── The screen guard ──────────────────────────────────────────────────────────


SUSPENDED = {
    "instagram": "<node text='Your account has been suspended'/>",
    "tiktok": "<node text='Your account is permanently banned'/>",
    "x": "<node text='Your account is suspended'/>",
    "reddit": "<node text='This account has been suspended'/>",
}


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_a_suspension_stops_the_creation(platform):
    reason = signup.guard_screen(platform, SUSPENDED[platform])
    assert reason and reason.startswith("suspended:")


@pytest.mark.parametrize(
    "platform, screen",
    [
        # Every one of these matches a health.py pattern — `logged_out` or
        # `verification` — and every one of them is a NORMAL signup screen. A
        # guard that used health.detect() as-is would stop each of the four runs
        # on its first or second step.
        ("instagram", "<node text='Create new account'/><node text='Enter the confirmation code'/>"),
        ("instagram", "<node text='Add your phone number'/>"),
        ("tiktok", "<node text='Sign up for TikTok'/><node text='drag the slider'/>"),
        ("tiktok", "<node text='Enter 6-digit code'/>"),
        ("x", "<node text='Create your account'/><node text='Enter the code we sent'/>"),
        ("reddit", "<node text='Verify your email'/><node text='Sign up to continue'/>"),
    ],
)
def test_a_normal_signup_screen_does_not_stop_anything(platform, screen):
    assert signup.guard_screen(platform, screen) is None


@pytest.mark.parametrize(
    "screen",
    [
        "<node text='Take a video selfie to confirm'/>",
        "<node text='We need to verify your identity'/>",
        "<node text='Upload a photo of your ID'/>",
        "<node text='government-issued ID'/>",
    ],
)
def test_an_identity_check_stops_the_creation(screen):
    """account-creation.md §9: a synthetic character has no identity to show, and
    trying to pass the check would be fraud. Abandon, never retry."""
    reason = signup.guard_screen("instagram", screen)
    assert reason and reason.startswith("identity_check:")


def test_confirm_its_you_alone_is_not_an_identity_check():
    """§6.1 abandons on 'Confirm it's you' *with* a selfie or an ID — the banner
    on its own is ambiguous during a signup and must not kill the run silently."""
    assert signup.guard_screen("instagram", "<node text=\"Confirm it's you\"/>") is None


# ── The guarded workflow ──────────────────────────────────────────────────────


def test_a_guarded_step_fails_when_the_screen_turned_suspended():
    dev = _device(SUSPENDED["instagram"])
    action = signup.GuardedRecordedStepAction(dev, {"action": "home"}, 0, platform="instagram")
    result = action.execute()
    assert not result.success
    assert "stopped by screen guard" in result.error
    assert "suspended" in result.error


def test_a_guarded_step_passes_on_an_ordinary_screen():
    dev = _device("<node text='Create a password'/>")
    action = signup.GuardedRecordedStepAction(dev, {"action": "home"}, 0, platform="instagram")
    assert action.execute().success


def test_a_guarded_step_without_a_platform_is_exactly_a_recorded_step():
    """The guard is opt-in: no platform, no extra behaviour and no extra dump."""
    dev = _device(SUSPENDED["instagram"])
    guarded = signup.GuardedRecordedStepAction(dev, {"action": "home"}, 0, platform="")
    plain = RecordedStepAction(_device(SUSPENDED["instagram"]), {"action": "home"}, 0)
    assert guarded.execute().success == plain.execute().success is True


def test_an_unreadable_screen_is_not_judged():
    """A dump that fails is not evidence of a suspension — carry on rather than
    kill a creation halfway through on an ADB hiccup."""
    dev = _device()
    dev.dump_xml.side_effect = RuntimeError("adb died")
    action = signup.GuardedRecordedStepAction(dev, {"action": "home"}, 0, platform="instagram")
    assert action.execute().success


def test_a_failed_step_is_not_second_guessed():
    dev = _device()
    dev.find_bounds.return_value = None
    action = signup.GuardedRecordedStepAction(dev, {"action": "tap", "text": "Nope"}, 0, platform="instagram")
    result = action.execute()
    assert not result.success
    assert "locator not found" in result.error  # the original cause, not the guard


def test_the_workflow_wraps_every_step_and_keeps_the_parameters():
    dev = _device()
    workflow = signup.GuardedRecordedWorkflow(
        dev,
        [{"action": "type", "text": "{handle}"}, {"action": "home"}],
        params={"handle": "sierra.cole"},
        platform="instagram",
        skill_name="ofmai_signup_instagram",
    )
    steps = workflow.steps()
    assert all(isinstance(s, signup.GuardedRecordedStepAction) for s in steps)
    assert steps[0]._step["text"] == "sierra.cole"
    assert steps[0].platform == "instagram"
    assert steps[0].skill_name == "ofmai_signup_instagram"


def test_build_workflow_refuses_bad_parameters_before_touching_the_phone():
    with pytest.raises(ValueError, match="signup refused"):
        signup.build_workflow(_device(), "instagram", {**GOOD_PARAMS, "bio_line1": "https://ofmai.ai"})


def test_build_workflow_returns_a_guarded_workflow_with_the_skill_popups():
    workflow = signup.build_workflow(_device(), "instagram", GOOD_PARAMS)
    assert isinstance(workflow, signup.GuardedRecordedWorkflow)
    assert workflow.app_package == "com.instagram.android"
    assert any("phone number" in (d.get("detect") or "").lower() for d in workflow._popup_detectors)


def test_unknown_platform_is_refused():
    with pytest.raises(ValueError, match="unknown signup platform"):
        signup.load_steps("telegram")


# ── A full dry replay, no phone ───────────────────────────────────────────────


class ReplayDevice:
    """A phone that answers yes to everything, showing one fixed screen.

    Enough to walk a whole step list end to end: every locator resolves, every
    gate that carries a `success` condition sees it met on its first poll, and
    every gate without one is skipped (no run_id to signal). What this proves is
    that the list *replays* — never that the selectors are right, which only
    Skill Miner on a real phone can say (R34).
    """

    serial = "fake-replay"

    def __init__(self, xml: str):
        self.xml = xml
        self.typed: list[str] = []
        self.taps = 0

    def dump_xml(self):
        return self.xml

    def adb(self, *args, timeout=30):
        if args[:3] == ("shell", "input", "text"):
            self.typed.append(args[3])
        return ""

    def dismiss_popups(self, xml=None, popups=None):
        return False

    def find_bounds(self, xml, **kw):
        return "[0,0][10,10]"

    def bounds_center(self, bounds):
        return (5, 5)

    def tap(self, x, y, delay=1.0):
        self.taps += 1

    def back(self, delay=1.0):
        pass

    def swipe(self, *a, **kw):
        pass

    def long_press(self, *a, **kw):
        pass


# Every screen the gates of the four lists wait on, in one dump.
FRIENDLY_SCREEN = (
    "<hierarchy>"
    "<node text='Create a password'/><node text='I agree'/>"
    "<node text='Create your username'/><node text='Set a password'/>"
    "<node text='What is your birthday'/><node text='What is your name'/>"
    "<node text='Home'/>"
    "<node text='sierra.cole'/>"
    "</hierarchy>"
)


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_the_whole_list_replays_without_a_phone(platform):
    dev = ReplayDevice(FRIENDLY_SCREEN)
    steps = signup.load_steps(platform)
    workflow = signup.GuardedRecordedWorkflow(
        dev,
        steps,
        params={
            **GOOD_PARAMS,
            "bio": "sierra, 25, la",
            "niche": "gymgirl, fitness, losangeles",
            "birthday_us": "06141997",  # Reddit types the date as eight digits
            "phone": "2062959463",  # TikTok signs up by the character's own line
        },
        platform=platform,
    )
    workflow.app_package = signup.APP_PACKAGE[platform]
    result = workflow.run()
    assert result.success, result.error
    assert result.data["completed_steps"] == len(steps)
    # the parameters really were substituted, not typed as placeholders
    assert not any("{" in t for t in dev.typed)
    # the email is typed wherever the list types it — TikTok signs up by phone
    # and only mentions the mailbox in a gate (account-creation.md §4 ter)
    types_email = any(s.get("text") == "{email}" for s in steps)
    assert (GOOD_PARAMS["email"] in dev.typed) is types_email
    # the handle is typed wherever the list types it — on Reddit it is not, because
    # the field arrives pre-filled and clearing it is a human gesture (§6.4)
    types_handle = any(s.get("text") == "{handle}" for s in steps)
    assert (GOOD_PARAMS["handle"] in dev.typed) is types_handle


@pytest.mark.parametrize("platform", signup.PLATFORMS)
def test_a_suspension_mid_replay_stops_the_run_there(platform):
    """The acceptance criterion of E2.2-2.5: a suspension screen ends the run."""
    dev = ReplayDevice(SUSPENDED[platform])
    workflow = signup.GuardedRecordedWorkflow(
        dev,
        signup.load_steps(platform),
        params={**GOOD_PARAMS, "bio": "sierra, 25, la", "niche": "gymgirl"},
        platform=platform,
    )
    workflow.app_package = signup.APP_PACKAGE[platform]
    result = workflow.run()
    assert not result.success
    assert "stopped by screen guard" in result.error
    assert result.data["completed_steps"] == 0  # it never got past the launch


# ── The three upstream changes are inert by default ───────────────────────────
#
# base.py and _run_skill.py come from the upstream ghost repo. Each change below
# is additive and must do nothing at all to a skill that does not ask for it.


def test_a_success_condition_without_a_placeholder_is_left_alone():
    """Upstream change 1b — inert half."""
    step = {"action": "checkpoint", "reason": "email", "success": {"screen_has": "/inbox"}, "prompt": "p"}
    resolved = RecordedWorkflow(_device(), [step], params={"handle": "sierra.cole"}).steps()[0]._step
    assert resolved["success"] == {"screen_has": "/inbox"}


def test_a_success_condition_with_a_placeholder_is_resolved():
    """Upstream change 1b — the fix itself.

    Without it a gate that waits for the profile screen of the account it just
    created compares the literal string "{handle}" to the screen and never
    resolves. Every signup skill ends on exactly such a gate.
    """
    step = {"action": "checkpoint", "reason": "generic", "success": {"screen_has": "{handle}"}, "prompt": "p"}
    resolved = RecordedWorkflow(_device(), [step], params={"handle": "sierra.cole"}).steps()[0]._step
    assert resolved["success"] == {"screen_has": "sierra.cole"}
    assert resolved["prompt"] == "p"  # the other fields still behave as before


def test_no_upstream_or_warming_skill_asks_for_the_guard():
    """Upstream change 2 — inert half: only the four signup skills carry
    `health_platform`, so every other recorded skill runs the plain workflow."""
    import yaml

    from pathlib import Path

    skills_root = Path(base.__file__).resolve().parent
    declaring = {
        path.parent.name
        for path in skills_root.glob("*/skill.yaml")
        if (yaml.safe_load(path.read_text()) or {}).get("health_platform")
    }
    assert declaring == set(signup.SKILL_BY_PLATFORM.values())


def test_a_checkpoint_without_a_webhook_is_not_delayed_by_discord(monkeypatch):
    """Upstream change 1a — inert half.

    The alert runs on a daemon thread and the farm has no webhook here, so the
    gate behaves exactly as it did before: it is skipped when there is neither a
    run to signal nor a condition to watch.
    """
    from gitd.farm import alerts

    monkeypatch.delenv(alerts.ENV_VAR, raising=False)
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "")

    action = RecordedStepAction(_device(), {"action": "checkpoint", "reason": "sms"}, 0, run_id=None)
    result = action.execute()
    assert result.success and result.data["resolution"] == "skipped"
