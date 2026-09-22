"""Tier 2 of the unknown-screen recovery: a model reads the tree, names one action.

docs/social/selectors-uiautomator.md §4 bis. The script is blind on a screen
it never surveyed; a model is good at "what is this, and what closes it". It
is asked for ONE action towards the home feed, in JSON, and
:func:`gitd.farm.unstuck.advised_recovery` executes it — never a text entry,
never a tap on anything that reads like an identity gate (captcha, code,
selfie, password): those stay human by construction, whatever the model says.

Installed only when the farm has credentials (``ANTHROPIC_API_KEY``, or an
``ant auth login`` profile with ``FARM_ADVISOR=1``); otherwise
:func:`configured` returns None and the loop goes straight to tier 3.
"""

from __future__ import annotations

import json
import logging
import os
import re

from gitd.farm.unstuck import Step

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
SYSTEM = (
    "You are looking at the accessibility tree of an Android social app driven by an automation that got lost. "
    "Your only goal: get back to the app's HOME FEED with ONE safe action. "
    "Answer with a single JSON object and nothing else: "
    '{"action": "tap"|"back"|"home"|"give_up", "text": "<exact visible label to tap, or null>", "why": "<10 words>"}. '
    "Rules: prefer closing what is on top (Not now, Close, Got it, Skip, Cancel) or Back; use home for the bottom-bar Home tab. "
    "NEVER tap Log in, Sign up, Continue, Next, Send code, Verify, Submit, Upload, Allow, Start, Upgrade, or anything on a "
    "captcha, code, password, phone-number or selfie screen: answer give_up there. Never type text."
)
_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_step(text: str) -> Step | None:
    """The model's answer as a Step, or None when it is not one."""
    m = _JSON.search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    action = str(d.get("action", "")).lower()
    if action not in ("tap", "back", "home", "give_up"):
        return None
    label = d.get("text")
    return Step(action=action, text=str(label) if label else None, why=str(d.get("why", ""))[:80])


class ClaudeAdvisor:
    """One call per turn; the screen summary is the whole prompt."""

    def __init__(self, client=None, model: str = MODEL):
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self.client = client
        self.model = model

    def __call__(self, platform: str, summary: str) -> Step | None:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=SYSTEM,
                messages=[{"role": "user", "content": f"App: {platform}\nScreen (top to bottom):\n{summary}"}],
            )
        except Exception as e:  # noqa: BLE001 — the model being down is tier 3's problem, not a crash
            log.warning("[advisor] call failed: %s", type(e).__name__)
            return None
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        step = parse_step(text)
        log.info("[advisor] %s -> %s", platform, step)
        return step


def configured():
    """The advisor when this farm may call a model, else None."""
    from gitd.farm.modelkey import ensure_api_key

    if not (ensure_api_key() or os.environ.get("FARM_ADVISOR") == "1"):
        return None
    try:
        return ClaudeAdvisor()
    except Exception as e:  # noqa: BLE001 — no SDK, no credentials: tier 2 is simply absent
        log.warning("[advisor] not available: %s", type(e).__name__)
        return None
