"""What the loop does on a screen it does not know — the three tiers.

docs/social/selectors-uiautomator.md §4 bis (decision of 2026-09-18): a gesture
runs on the first tier that can do it. The **script** replays what the survey
recorded. When the screen matches nothing it knows, an **agent** reads the tree
and clears the way. Failing that, a **human** — and identity gates (captcha,
SMS, biometrics) are human by construction, never the agent's.

Until 2026-09-22 only the script existed in the loop: an unknown sheet (the
"Saved" sheet after a first save, "Why you're seeing this post" after a stray
tap) swallowed three sessions of swipes in silence. This module is the other
two tiers:

1. :func:`generic_recovery` — no model: close whatever is on top with the
   buttons every app uses for that ("Not now", "Close", "Got it"…), or Back,
   then the home tab; a few rounds.
2. an ``advisor`` — a model given the tree, asked for ONE action towards the
   home feed; :mod:`gitd.farm.advisor` is the Claude one, installed when the
   farm has an API key. It never types into a field and never taps anything
   that looks like an identity gate.
3. :func:`escalate` — the tree and a screenshot are kept under
   ``data/unknown_screens/``, a Discord alert goes out, and the session ends
   with ``stats.error = "unknown screen"`` — a clean stop, never an hour on
   the same page.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from gitd.farm import alerts
from gitd.farm.warm import center, desc_of, nodes_where

log = logging.getLogger(__name__)

# the labels every app uses to close what it just put on top, most benign first
CLOSERS = ("Not now", "Not Now", "Close", "Got it", "Dismiss", "Skip", "No thanks", "Cancel", "OK", "Not really", "Maybe later")
# labels that mean an identity gate: the recovery never touches them (§4 bis)
IDENTITY = re.compile(
    r"captcha|confirm you.?re human|enter the confirmation code|verification code|video selfie|upload (a photo of )?your"
    r"|phone number|mobile number|password|log in|sign up|create new account",
    re.IGNORECASE,
)
UNKNOWN_DIR = Path("data") / "unknown_screens"
MAX_ROUNDS = 3


@dataclass
class Step:
    """One action an advisor may ask for."""

    action: str  # tap | back | home | give_up
    text: str | None = None
    desc: str | None = None
    why: str = ""


class Advisor(Protocol):
    def __call__(self, platform: str, summary: str) -> Step | None: ...


def summarize(xml: str, limit: int = 60) -> str:
    """The screen as a model (or a human) can read it: texts and labels, top to bottom."""
    rows = []
    for n in nodes_where(xml or "", text=""):
        t = re.search(r'\btext="([^"]*)"', n)
        t = (t.group(1) if t else "").strip()
        d = desc_of(n).strip()
        if not (t or d):
            continue
        c = center(n)
        rid = re.search(r'resource-id="[^"]*?([A-Za-z0-9_]+)"', n)
        rows.append((c[1] if c else 0, f"y={c[1] if c else '?'} text={t[:60]!r} desc={d[:60]!r} id={rid.group(1) if rid else ''}"))
    rows.sort()
    return "\n".join(r for _, r in rows[:limit])


def is_identity_gate(xml: str) -> bool:
    return bool(IDENTITY.search(summarize(xml)))


def _tap_label(adapter, xml: str, label: str) -> bool:
    for n in nodes_where(xml, text=label) + nodes_where(xml, desc=label):
        t = re.search(r'\btext="([^"]*)"', n)
        exact = (t.group(1).strip() if t else "") == label or desc_of(n).strip() == label
        c = center(n)
        if exact and c:
            adapter.human.tap(*c)
            return True
    return False


def generic_recovery(adapter, *, rounds: int = MAX_ROUNDS) -> bool:
    """Tier 1: close what is on top without knowing what it is. True when back on the feed."""
    for _ in range(rounds):
        xml = adapter.dump()
        if adapter.on_feed(xml):
            return True
        if is_identity_gate(xml):
            return False  # never ours to clear
        if not any(_tap_label(adapter, xml, label) for label in CLOSERS):
            adapter.device.back()
        adapter.human.pause(1.0)
        xml = adapter.dump()
        if adapter.on_feed(xml):
            return True
        home = adapter.elements.get("home_tab")
        pos = home.find(adapter.device, xml) if home else None
        if pos:
            adapter.human.tap(*pos)
            adapter.human.pause(1.5)
            if adapter.on_feed(adapter.dump()):
                return True
    return False


def advised_recovery(adapter, platform: str, advisor: Advisor, *, turns: int = MAX_ROUNDS) -> bool:
    """Tier 2: a model reads the screen and asks for one action at a time."""
    for _ in range(turns):
        xml = adapter.dump()
        if adapter.on_feed(xml):
            return True
        if is_identity_gate(xml):
            return False
        step = advisor(platform, summarize(xml))
        if step is None or step.action == "give_up":
            return False
        log.info("[unstuck] advisor: %s %s — %s", step.action, step.text or step.desc or "", step.why)
        if step.action == "back":
            adapter.device.back()
        elif step.action == "home":
            home = adapter.elements.get("home_tab")
            pos = home.find(adapter.device, xml) if home else None
            if pos:
                adapter.human.tap(*pos)
        elif step.action == "tap":
            label = step.text or step.desc or ""
            if not label or IDENTITY.search(label) or not _tap_label(adapter, xml, label):
                return False
        else:
            return False
        adapter.human.pause(1.5)
    return adapter.on_feed(adapter.dump())


def escalate(adapter, platform: str, handle: str, xml: str, *, out_dir: Path = UNKNOWN_DIR, notify: Callable = alerts.notify) -> Path:
    """Tier 3: keep the evidence, tell a human, let the caller stop the session."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"{platform}-{handle.lstrip('@')}-{stamp}"
    base.with_suffix(".xml").write_text(xml or "")
    try:
        from gitd.bots.common.adb import capture_screencap_png

        base.with_suffix(".png").write_bytes(capture_screencap_png(adapter.device.serial))
    except Exception:  # noqa: BLE001 — the tree alone is still evidence
        pass
    head = summarize(xml, limit=8)
    notify("warn", f"{platform} @{handle}: unknown screen, session stopped", f"{base.name}\n{head}")
    log.warning("[unstuck] %s @%s stuck on an unknown screen — saved %s", platform, handle, base)
    return base


def recover(adapter, platform: str, handle: str, *, advisor: Advisor | None = None, notify: Callable = alerts.notify) -> bool:
    """All three tiers in order. True when the feed is back; False after escalating."""
    if not hasattr(adapter, "device"):  # an adapter without a phone (tests): nothing to tap
        return False
    if generic_recovery(adapter):
        return True
    if advisor is not None and advised_recovery(adapter, platform, advisor):
        return True
    escalate(adapter, platform, handle, adapter.dump(), notify=notify)
    return False
