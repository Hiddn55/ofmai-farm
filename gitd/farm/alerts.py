"""Discord alerts raised by the fork itself (R32, docs/social/health-canaries.md §5).

Nathan is in Thailand, the Mac mini is in Paris. Without an alert, a signup run
sitting at a captcha waits for hours and the login it half-created expires.

This module covers **only what does not travel through OFMAI**:

  - a recorded step that entered ``awaiting_human`` (checkpoint, E2.1),
  - a ``POST /api/farm/events`` that is 401 / unreachable (bridge, E7.3),
  - a ``stop`` / ``platform cut`` typed by hand (E5.3).

Health signals themselves keep going through the bridge to OFMAI, which owns
``sendDiscordAlert`` — so a signal is announced once, not twice.

Webhook resolution is the one used by ``.claude/loop/notify.mjs`` on the OFMAI
side: ``FARM_DISCORD_WEBHOOK_URL`` first, then the macOS Keychain entry
``ofmai-discord-webhook``. With neither, ``notify()`` is a no-op that returns
False — a farm with no webhook keeps running, it just stays silent.

Nothing here ever raises and nothing here ever blocks for long: an alert is a
courtesy to a human, never a step of the automation.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Callable

log = logging.getLogger(__name__)

# Discord truncates hard and returns 400 over the limit; the OFMAI loop notifier
# uses the same 1 900-character budget (.claude/loop/notify.mjs).
MAX_CONTENT = 1900

ENV_VAR = "FARM_DISCORD_WEBHOOK_URL"
KEYCHAIN_SERVICE = "ofmai-discord-webhook"
USERNAME = "OFMAI — ferme"
HTTP_TIMEOUT_S = 5.0

# level → prefix. The fork posts plain text (health-canaries.md §5): the coloured
# embeds are the OFMAI side's job.
_LEVELS: dict[str, str] = {
    "info": "",
    "warn": "[!] ",
    "error": "[ERREUR] ",
    "critical": "[CRITIQUE] ",
}

# The REST surface of ghost has no authentication and is only ever reached
# through an SSH tunnel (rules.md R25) — the resume line we print says so.
RESUME_BASE = "http://127.0.0.1:5055"


def _keychain_webhook() -> str:
    """Read the webhook from the macOS login keychain; '' when unavailable."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # not macOS, `security` missing, keychain locked…
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _settings_webhook() -> str:
    """The value pydantic-settings read from the environment or from `.env`."""
    try:
        from gitd.config import settings

        return (getattr(settings, "farm_discord_webhook_url", "") or "").strip()
    except Exception:
        return ""


def webhook_url() -> str:
    """The Discord webhook to post to, or '' when the farm has none.

    Environment first (so an operator can export one for a single run), then the
    settings object (which is also where a `.env` entry lands), then the keychain
    — the same order, and the same keychain entry, as `.claude/loop/notify.mjs`
    on the OFMAI side.
    """
    env = (os.environ.get(ENV_VAR) or "").strip()
    if env:
        return env
    from_settings = _settings_webhook()
    if from_settings:
        return from_settings
    return _keychain_webhook()


def _post(url: str, payload: dict) -> bool:
    """POST the payload. Isolated so tests can replace it without any HTTP."""
    import requests  # imported late: a farm without `requests` still imports this module

    resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT_S)
    return 200 <= resp.status_code < 300


def notify(
    level: str,
    title: str,
    message: str,
    *,
    poster: Callable[[str, dict], bool] | None = None,
) -> bool:
    """Post one plain-text alert on Discord. Returns True only when it landed.

    Never raises: no webhook, no network, a 500 from Discord — all of them are
    logged and swallowed. The caller is usually a run that is already waiting on
    a human; failing it because Discord is down would be the worse outcome.
    """
    url = webhook_url()
    if not url:
        log.info("[alerts] no webhook (%s / keychain %s) — alert dropped: %s", ENV_VAR, KEYCHAIN_SERVICE, title)
        return False

    prefix = _LEVELS.get(level, "")
    body = f"{prefix}**{title}**"
    if message:
        body = f"{body}\n{message}"
    payload = {"username": USERNAME, "content": body[:MAX_CONTENT]}

    try:
        return bool((poster or _post)(url, payload))
    except Exception as exc:  # network down, requests missing, Discord 500…
        log.warning("[alerts] Discord post failed: %s", exc if isinstance(exc, Exception) else str(exc))
        return False


def checkpoint_awaiting_human(
    *,
    reason: str,
    prompt: str,
    run_id: int | None,
    device: str = "",
    skill: str = "",
    poster: Callable[[str, dict], bool] | None = None,
) -> bool:
    """Announce a recorded step that just suspended on a human gate (R25, R32).

    Message shape is the one health-canaries.md §5 asks for: what is waiting,
    on which phone, and the exact command that releases it. No credential ever
    goes in — the prompt tells a human *where* to read a code or a password
    (Keychain, SIM, Gmail notification), it never carries one (R9).
    """
    head = f"AWAITING HUMAN — {reason}: {prompt or '(no prompt)'}"
    if run_id is not None:
        head = f"{head} (run {run_id})"

    context = " · ".join(p for p in (f"skill {skill}" if skill else "", f"device {device}" if device else "") if p)

    lines = [context] if context else []
    if run_id is not None:
        lines.append(
            f"```\ncurl -X POST {RESUME_BASE}/api/skills/runs/{run_id}/resume "
            "-H 'Content-Type: application/json' -d '{\"action\":\"resume\"}'\n```"
        )
    # verification_required / logged_out are the "within the hour" cases in
    # health-canaries.md §5; a creation gate is the same urgency for a human.
    return notify("error", head, "\n".join(lines), poster=poster)
