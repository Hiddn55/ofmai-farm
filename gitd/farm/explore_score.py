"""The measure of the oriented warm-up: how much of Explore is the niche.

docs/social/warming-policy.md §7 bis ("Mesure"). A session that watched the
niche's Reels for 80 % of its time is supposed to teach the algorithm what
this account wants to see; the only place that learning shows is the Explore
page. So, at the end of every Instagram session, :func:`measure` opens the
"Search and explore" tab, keeps a screenshot under
``data/explore/<platform>/<handle>/<YYYYMMDD-HHMMSS>.png``, asks a model
(vision) what share of the page is content of the niche — an integer 0-100
and a one-sentence reason — and comes back to the home feed. ``skillkit``
puts ``explore_niche_score`` and ``explore_shot`` on the ``session_summary``
event, the same way Reddit's karma travels.

Same gating as :mod:`gitd.farm.advisor`: nothing runs without credentials
(``ANTHROPIC_API_KEY``, or ``FARM_ADVISOR=1`` with an ``ant auth login``
profile) — :func:`configured` then answers None and the session ends as it
always did. Nothing here may fail a session: every step is caught and logged.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
SYSTEM = (
    "You are looking at a screenshot of the Explore page of a social app (a grid of recommended posts and Reels). "
    "You are given the niche of the account that is logged in. Estimate what share of the visible tiles is content "
    "of that niche — same theme, same kind of creators, same activity — and answer with a single JSON object and "
    'nothing else: {"score": <integer 0-100>, "reason": "<one sentence>"}. '
    "Count tiles, not pixels; a tile you cannot read counts as not of the niche. 0 = nothing of the niche, "
    "100 = every tile is of the niche."
)
EXPLORE_DIR = Path("data") / "explore"
# per platform: the tab that opens the Explore page, the tab that leaves it.
# TikTok has no Explore page the adapter can reach (its search page is
# suggestions, not a personalised grid): only Instagram is measured for now.
TABS = {"instagram": ("search_tab", "home_tab")}
_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_score(text: str) -> tuple[int | None, str]:
    """``(score, reason)`` from the model's answer; ``(None, "")`` when it is not one.

    Strict: the score must be an integer (or an integral number / digit string)
    between 0 and 100. A boolean, a fraction, a percentage string or a bare
    sentence is refused rather than guessed.
    """
    m = _JSON.search(text or "")
    if not m:
        return None, ""
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(d, dict):
        return None, ""
    raw = d.get("score")
    if isinstance(raw, bool):
        return None, ""
    if isinstance(raw, str) and raw.strip().isdigit():
        raw = int(raw.strip())
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    if not isinstance(raw, int) or not 0 <= raw <= 100:
        return None, ""
    reason = d.get("reason")
    return raw, (str(reason).strip()[:200] if reason else "")


def niche_description(niche: list[str] | None, character: str | None = None) -> str:
    """The niche as one line for the prompt, from ``farm_accounts.niche`` and the character."""
    parts = []
    if character:
        parts.append(f"character '{character}'")
    tags = [n.strip().lstrip("#") for n in (niche or []) if n.strip() and not n.strip().startswith("@")]
    handles = [n.strip() for n in (niche or []) if n.strip().startswith("@")]
    if tags:
        parts.append("themes: " + ", ".join(tags))
    if handles:
        parts.append("reference accounts: " + ", ".join(handles))
    return "; ".join(parts) or "unknown niche"


class ExploreScorer:
    """One vision call per session: the screenshot and the niche are the whole prompt."""

    def __init__(self, client=None, model: str = MODEL):
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self.client = client
        self.model = model

    def score(self, png_bytes: bytes, niche: str) -> tuple[int | None, str]:
        if not png_bytes:
            return None, ""
        image = base64.standard_b64encode(png_bytes).decode("ascii")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
                            {"type": "text", "text": f"Niche of the account: {niche}\nWhat share of this Explore page is content of that niche?"},
                        ],
                    }
                ],
            )
        except Exception as e:  # noqa: BLE001 — the model being down never costs the session
            log.warning("[explore] call failed: %s", type(e).__name__)
            return None, ""
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        score, reason = parse_score(text)
        if score is None:
            log.warning("[explore] unreadable answer: %r", text[:120])
        return score, reason


def configured() -> ExploreScorer | None:
    """The scorer when this farm may call a model, else None."""
    from gitd.farm.modelkey import ensure_api_key

    if not (ensure_api_key() or os.environ.get("FARM_ADVISOR") == "1"):
        return None
    try:
        return ExploreScorer()
    except Exception as e:  # noqa: BLE001 — no SDK, no credentials: the measure is simply absent
        log.warning("[explore] not available: %s", type(e).__name__)
        return None


# ── the screen ────────────────────────────────────────────────────────────────


def _tap_tab(adapter, name: str) -> bool:
    el = adapter.elements.get(name) if getattr(adapter, "elements", None) else None
    pos = el.find(adapter.device, adapter.dump()) if el else None
    if not pos:
        return False
    adapter.human.tap(*pos)
    return True


def open_explore(adapter, platform: str) -> bool:
    """Open the Explore page through the platform's tab. True when the tab was tapped."""
    tabs = TABS.get(platform)
    if not tabs or not _tap_tab(adapter, tabs[0]):
        return False
    adapter.human.pause(2.5)  # let the grid load its thumbnails
    return True


def close_explore(adapter, platform: str) -> None:
    """Back to the home feed: the home tab, then the adapter's own way home."""
    tabs = TABS.get(platform)
    if tabs:
        _tap_tab(adapter, tabs[1])
        adapter.human.pause(1.5)
    back = getattr(adapter, "back_to_feed", None)
    if callable(back):
        back()


def shot_path(platform: str, handle: str, *, out_dir: Path = EXPLORE_DIR, stamp: str | None = None) -> Path:
    return out_dir / platform / handle.lstrip("@") / f"{stamp or time.strftime('%Y%m%d-%H%M%S')}.png"


def _screencap(serial: str) -> bytes:
    from gitd.bots.common.adb import capture_screencap_png

    return capture_screencap_png(serial)


def measure(
    adapter,
    platform: str,
    handle: str,
    niche: list[str] | None,
    *,
    character: str | None = None,
    scorer: ExploreScorer | None = None,
    screencap: Callable[[str], bytes] | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Explore page → screenshot on disk → score. The keys for ``session_summary``.

    ``{}`` when there is nothing to measure: no model configured, a platform
    without an Explore page, an adapter without a phone, a tab that could not
    be tapped. ``explore_shot`` alone when the screenshot exists but the model
    gave no usable score (``explore_niche_score`` is then None, never 0).
    Whatever happens, the adapter is walked back to the feed.
    """
    if scorer is None:
        scorer = configured()
    if scorer is None or platform not in TABS or not hasattr(adapter, "device"):
        return {}
    screencap = screencap or _screencap  # resolved here so a test can patch the module's
    out_dir = out_dir or EXPLORE_DIR
    out: dict = {}
    try:
        if not open_explore(adapter, platform):
            log.warning("[explore] %s @%s: the Explore tab was not found", platform, handle)
            return {}
        png = screencap(adapter.device.serial)
        path = shot_path(platform, handle, out_dir=out_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        out["explore_shot"] = str(path)
        score, reason = scorer.score(png, niche_description(niche, character))
        out["explore_niche_score"] = score
        log.info("[explore] %s @%s: niche share %s — %s", platform, handle, score, reason or "no reason")
    except Exception as e:  # noqa: BLE001 — a session is never lost over a measure
        log.warning("[explore] %s @%s: not measured: %s: %s", platform, handle, type(e).__name__, e)
    finally:
        try:
            close_explore(adapter, platform)
        except Exception as e:  # noqa: BLE001 — the loop's own back_to_feed already ran once
            log.warning("[explore] %s @%s: could not come back to the feed: %s", platform, handle, type(e).__name__)
    return out
