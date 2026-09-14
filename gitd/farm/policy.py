"""Warming policy: what an account may do on a given day of its life.

Mirrors ``documentation/social/warming-policy.md`` in the OFMAI repo. Numbers
here are **caps**, never targets: each day the budget draws a value between
40 % and 100 % of the cap, deterministically for (account, date), so a retry
of the same day never grants more.

Everything is pure: no device, no database. The ledger feeds counts in.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from enum import Enum

# ── Actions ───────────────────────────────────────────────────────────────────

VIEW = "view"  # one video/post seen
LIKE = "like"
SAVE = "save"
FOLLOW = "follow"
COMMENT = "comment"
POST = "post"
STORY_VIEW = "story_view"
PROFILE_VISIT = "profile_visit"
SEARCH = "search"
DM_REPLY = "dm_reply"
COMMENT_REPLY = "comment_reply"

ACTIONS = (VIEW, LIKE, SAVE, FOLLOW, COMMENT, POST, STORY_VIEW, PROFILE_VISIT, SEARCH, DM_REPLY, COMMENT_REPLY)

# Ratios that must hold at all times within a day (numerator / denominator).
MAX_LIKE_PER_VIEW = 0.15
MAX_FOLLOW_PER_PROFILE_VISIT = 0.30


class Phase(str, Enum):
    CONSUME = "consume"  # days 1-3: only watch
    LIGHT = "light"  # days 4-7: a few likes and saves
    NETWORK = "network"  # days 8-14: follows, first comments, first posts
    CRUISE = "cruise"  # day 15+: steady state


@dataclass(frozen=True)
class PhaseCaps:
    """Per-day caps (max) and session shape for one phase."""

    likes: int
    saves: int
    follows: int
    comments: int
    posts_per_week: int
    story_views: int
    profile_visits: int
    searches: int
    session_minutes: tuple[int, int]  # total per day (min, max)
    sessions_per_day: tuple[int, int]


CAPS: dict[Phase, PhaseCaps] = {
    Phase.CONSUME: PhaseCaps(0, 0, 0, 0, 0, 20, 4, 2, (15, 40), (2, 3)),
    Phase.LIGHT: PhaseCaps(25, 6, 3, 0, 0, 30, 8, 3, (20, 50), (2, 3)),
    Phase.NETWORK: PhaseCaps(50, 10, 12, 3, 3, 40, 20, 4, (30, 60), (2, 4)),
    Phase.CRUISE: PhaseCaps(80, 15, 15, 8, 7, 60, 30, 5, (30, 60), (2, 4)),
}

# TikTok is harsher on multi-account detection: each phase lasts 3 more days.
PHASE_EXTRA_DAYS = {"instagram": 0, "tiktok": 3}

# Local hours during which nothing ever happens.
QUIET_HOURS = range(1, 7)


def phase_for_day(day_of_life: int, platform: str = "instagram") -> Phase:
    """``day_of_life`` is 1 on the account's creation day."""
    extra = PHASE_EXTRA_DAYS.get(platform, 0)
    d = max(1, day_of_life)
    if d <= 3 + extra:
        return Phase.CONSUME
    if d <= 7 + 2 * extra:
        return Phase.LIGHT
    if d <= 14 + 3 * extra:
        return Phase.NETWORK
    return Phase.CRUISE


def day_of_life(created_on: date, today: date) -> int:
    return (today - created_on).days + 1


def _seed(*parts: object) -> int:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big")


# ── Daily budget ──────────────────────────────────────────────────────────────


@dataclass
class DailyBudget:
    account_key: str
    platform: str
    day: date
    day_of_life: int
    phase: Phase
    rest_day: bool
    caps: dict[str, int]  # action → allowed today
    session_minutes: int
    sessions: int

    @classmethod
    def build(cls, account_key: str, platform: str, created_on: date, day: date) -> DailyBudget:
        dol = day_of_life(created_on, day)
        phase = phase_for_day(dol, platform)
        pc = CAPS[phase]
        rng = random.Random(_seed("budget", account_key, day.isoformat()))
        # one full rest day per ISO week, chosen per (account, week)
        week_rng = random.Random(_seed("rest", account_key, day.isocalendar()[:2]))
        rest_weekday = week_rng.randrange(7)
        rest_day = day.weekday() == rest_weekday and dol > 3  # never rest during the first 3 days

        def draw(cap: int) -> int:
            if cap <= 0:
                return 0
            return int(math.floor(cap * rng.uniform(0.4, 1.0)))

        caps = {
            LIKE: draw(pc.likes),
            SAVE: draw(pc.saves),
            FOLLOW: draw(pc.follows),
            COMMENT: draw(pc.comments),
            STORY_VIEW: draw(pc.story_views),
            PROFILE_VISIT: draw(pc.profile_visits),
            SEARCH: draw(pc.searches),
            # posting: at most one a day; the weekly cap is enforced by the ledger
            POST: 1 if pc.posts_per_week > 0 else 0,
            VIEW: 10_000,  # bounded by session time, not by count
            DM_REPLY: 20 if phase == Phase.CRUISE else 0,
            COMMENT_REPLY: 20 if phase in (Phase.NETWORK, Phase.CRUISE) else 0,
        }
        if rest_day:
            caps = {k: 0 for k in caps}
        minutes = rng.randint(*pc.session_minutes)
        sessions = rng.randint(*pc.sessions_per_day)
        return cls(account_key, platform, day, dol, phase, rest_day, caps, 0 if rest_day else minutes, 0 if rest_day else sessions)


@dataclass
class BudgetTracker:
    """Today's budget plus what was already spent. Says yes or no to an action."""

    budget: DailyBudget
    spent: dict[str, int] = field(default_factory=dict)
    posts_this_week: int = 0

    def count(self, action: str) -> int:
        return self.spent.get(action, 0)

    def remaining(self, action: str) -> int:
        return max(0, self.budget.caps.get(action, 0) - self.count(action))

    def allow(self, action: str) -> bool:
        if self.budget.rest_day:
            return False
        if self.remaining(action) <= 0:
            return False
        if action == LIKE and self.count(LIKE) + 1 > MAX_LIKE_PER_VIEW * max(1, self.count(VIEW)):
            return False
        if action == FOLLOW and self.count(FOLLOW) + 1 > MAX_FOLLOW_PER_PROFILE_VISIT * max(1, self.count(PROFILE_VISIT)):
            return False
        if action == POST and self.posts_this_week >= CAPS[self.budget.phase].posts_per_week:
            return False
        return True

    def record(self, action: str, n: int = 1) -> None:
        self.spent[action] = self.count(action) + n
        if action == POST:
            self.posts_this_week += n


# ── Session planning ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionSlot:
    start: datetime  # naive local time
    minutes: int


# (window start hour, window end hour) — chosen in this order, then shifted.
_WINDOWS = [(8, 12), (12, 15), (18, 23), (15, 18)]


def plan_sessions(budget: DailyBudget) -> list[SessionSlot]:
    """Where in the day the sessions fall. Deterministic for (account, date).

    - never inside QUIET_HOURS
    - windows drift by up to ±90 min day to day, so no two days share a time
    - 10 % of sessions are very short ("just checking")
    - total duration ≈ the budget's session_minutes
    """
    if budget.rest_day or budget.sessions <= 0:
        return []
    rng = random.Random(_seed("sessions", budget.account_key, budget.day.isoformat()))
    n = budget.sessions
    windows = _WINDOWS[:n]
    # split minutes: log-normal weights, 10 % chance a slot is a 1-2 min check
    weights = [rng.lognormvariate(0, 0.5) for _ in range(n)]
    total_w = sum(weights)
    slots: list[SessionSlot] = []
    for (h0, h1), w in zip(windows, weights, strict=True):
        shift_min = rng.randint(-90, 90)
        start_min = rng.randint(h0 * 60, h1 * 60 - 1) + shift_min
        start_min = max(7 * 60 + 5, min(24 * 60 - 20, start_min))
        hour = (start_min // 60) % 24
        if hour in QUIET_HOURS:
            start_min = 7 * 60 + rng.randint(5, 55)
        minutes = max(1, int(round(budget.session_minutes * w / total_w)))
        if rng.random() < 0.10:
            minutes = rng.randint(1, 2)
        start = datetime.combine(budget.day, dtime(start_min // 60, start_min % 60))
        slots.append(SessionSlot(start, minutes))
    slots.sort(key=lambda s: s.start)
    # keep at least 45 min between sessions
    fixed: list[SessionSlot] = []
    for s in slots:
        if fixed and s.start < fixed[-1].start + timedelta(minutes=fixed[-1].minutes + 45):
            s = SessionSlot(fixed[-1].start + timedelta(minutes=fixed[-1].minutes + 45 + rng.randint(0, 30)), s.minutes)
        if s.start.hour in QUIET_HOURS or s.start.date() != budget.day:
            continue
        fixed.append(s)
    return fixed


# ── Health state machine ──────────────────────────────────────────────────────


class Health(str, Enum):
    OK = "ok"
    COOLDOWN = "cooldown"  # action block / rate limit: 48 h off, one phase back
    VERIFICATION = "verification_required"  # a human must act on the device
    SHADOWBAN_SUSPECT = "shadowban_suspect"  # 7 days consume-only, no post
    LOGGED_OUT = "logged_out"  # a human must act; never auto-login
    SUSPENDED = "suspended"  # device + IP quarantined 30 days


COOLDOWN_HOURS = 48
SHADOWBAN_DAYS = 7
QUARANTINE_DAYS = 30


@dataclass
class HealthState:
    status: Health = Health.OK
    until: datetime | None = None  # when a timed status expires
    phase_override: Phase | None = None  # forced phase while recovering

    def can_run(self, now: datetime) -> bool:
        if self.status == Health.OK:
            return True
        if self.status in (Health.COOLDOWN, Health.SHADOWBAN_SUSPECT):
            return self.until is not None and now >= self.until
        return False  # verification, logged out, suspended: a human decides

    def effective_phase(self, natural: Phase) -> Phase:
        if self.phase_override is None:
            return natural
        order = list(Phase)
        return order[min(order.index(natural), order.index(self.phase_override))]


def apply_signal(state: HealthState, signal: str, now: datetime, natural_phase: Phase) -> HealthState:
    """Transition on an on-screen signal kind (see ``health.py``)."""
    order = list(Phase)
    if signal == "action_blocked":
        prev = order[max(0, order.index(natural_phase) - 1)]
        return HealthState(Health.COOLDOWN, now + timedelta(hours=COOLDOWN_HOURS), prev)
    if signal == "verification":
        return HealthState(Health.VERIFICATION, None, state.phase_override)
    if signal == "shadowban":
        return HealthState(Health.SHADOWBAN_SUSPECT, now + timedelta(days=SHADOWBAN_DAYS), Phase.CONSUME)
    if signal == "logged_out":
        return HealthState(Health.LOGGED_OUT, None, state.phase_override)
    if signal == "suspended":
        return HealthState(Health.SUSPENDED, now + timedelta(days=QUARANTINE_DAYS), None)
    return state
