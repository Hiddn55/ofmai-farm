"""On-screen health signals. Pure text matching on a UI dump.

The skill dumps the UI tree (or OCR text) after each step and calls
:func:`detect`. A hit stops the session immediately; the policy decides what
happens next (``policy.apply_signal``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# kind → patterns (case-insensitive, matched against the raw XML/text)
_PATTERNS: dict[str, dict[str, list[str]]] = {
    "instagram": {
        "action_blocked": [
            r"action blocked",
            r"try again later",
            r"we limit how often",
            r"we restrict certain",
            r"you.?re temporarily blocked",
            r"couldn.?t (like|follow|comment|post)",
        ],
        "verification": [
            r"confirm it.?s you",
            r"suspicious login",
            r"verify your (phone|email|account|identity)",
            r"enter the confirmation code",
            r"help us confirm",
            r"we.?ve detected unusual activity",
            r"add your phone number",
        ],
        "logged_out": [
            r'text="log in"',
            r'content-desc="log in"',
            r"create new account",
            r"forgot password",
        ],
        "suspended": [
            r"your account has been (suspended|disabled)",
            r"we suspended your account",
            r"we disabled your account",
            r"you can.?t use instagram",
        ],
    },
    "tiktok": {
        "action_blocked": [
            r"tapping too fast",
            r"too many attempts",
            r"you.?re (liking|following|commenting) too",
            r"try again later",
            r"maximum number of",
        ],
        "verification": [
            r"verify to continue",
            r"drag the slider",
            r"select 2 objects",
            r"unusual activity",
            r"verify your (phone|email|account)",
            r"enter (the )?\d-digit code",
        ],
        "logged_out": [
            r'text="log in"',
            r"sign up for tiktok",
            r"log in to tiktok",
        ],
        "suspended": [
            r"account (is|has been) (temporarily |permanently )?(suspended|banned)",
            r"we banned your account",
            r"community guidelines violation",
        ],
    },
    # X and Reddit patterns are written from the en-US strings both apps show
    # today; none has been seen on a device yet. Verify them with Skill Miner
    # before the first real run (R34) and widen or narrow here, never in a
    # prompt. A suspension costs a 30-day quarantine of the phone AND its exit
    # IP, so every "suspended" pattern names the account explicitly: a post in
    # the feed containing the bare word "suspended" must never match.
    "x": {
        "action_blocked": [
            r"rate limit",
            r"over the daily limit",
            r"you are unable to follow more people",
            r"something went wrong. try reloading",
        ],
        "verification": [
            r"suspicious activity",
            r"your account is locked",
            r"confirm your identity",
            r"verify your (phone|email|identity)",
            r"enter the code we sent",
        ],
        "logged_out": [
            r'text="log in"',
            r'content-desc="log in"',
            r"create your account",
            r"sign up for x",
        ],
        "suspended": [
            r"(your )?account (is|has been|was) suspended",
            r"we suspended your account",
            r"x suspends accounts",
        ],
    },
    "reddit": {
        # A subreddit ban ("banned from participating") is not a platform-wide
        # suspension: docs/social/health-canaries.md S6 treats it as an action
        # block (48 h) plus a strike on that sub, decided on the OFMAI side.
        "action_blocked": [
            r"you.?ve been doing that a lot",
            r"you are doing that too much",
            r"rate limit",
            r"banned from participating",
            r"try again in \d+ (second|minute|hour)",
        ],
        "verification": [
            r"verify your email",
            r"verify your account",
            r"we need to verify",
            r"enter the (code|verification code)",
        ],
        "logged_out": [
            r'text="log in"',
            r'content-desc="log in"',
            r"sign up to continue",
            r"log in to reddit",
        ],
        "suspended": [
            r"(your |this )?account (is|has been|was) suspended",
            r"we.?ve suspended your account",
            r"account (permanently|temporarily) suspended",
        ],
    },
}

# Signals that need attention in this order (most severe first)
_ORDER = ("suspended", "logged_out", "verification", "action_blocked")


@dataclass(frozen=True)
class HealthSignal:
    kind: str  # one of _ORDER, or "shadowban" (raised by analytics, not by screen)
    matched: str


def detect(platform: str, screen_text: str) -> HealthSignal | None:
    """Return the most severe signal present on screen, if any."""
    table = _PATTERNS.get(platform, {})
    text = screen_text or ""
    for kind in _ORDER:
        for pat in table.get(kind, []):
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                return HealthSignal(kind, m.group(0))
    return None


def zero_reach(view_counts: list[int], posts: int = 3) -> bool:
    """Shadowban heuristic: the last ``posts`` posts all have ~zero views."""
    tail = view_counts[-posts:]
    return len(tail) >= posts and all(v <= 2 for v in tail)
