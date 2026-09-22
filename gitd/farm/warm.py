"""The warming session loop, shared by the Instagram and TikTok skills.

A session is "a person opens the app for N minutes": watches the feed, now
and then likes, saves, opens a profile, follows, comments, takes a detour
(stories, a niche search) and puts the phone down for a while. Every counted
action asks the ledger first; a health signal on screen ends the session.

The platform specifics (which button is where, how to reach a profile) live
in a :class:`PlatformAdapter` implemented by each skill.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from gitd.farm import health, policy
from gitd.farm.human import HumanInput

log = logging.getLogger(__name__)


class LedgerLike(Protocol):
    def allow(self, action: str) -> bool: ...

    def record(self, action: str, target: str | None = None) -> None: ...

    def signal(self, kind: str, matched: str | None = None): ...


class PlatformAdapter(Protocol):
    """What a skill must provide. Every method may raise; the loop copes.

    One method is **optional** and is never called by :func:`run_session`:

        ``read_karma(self) -> int | None``

    It opens the account's *own* profile, reads the number with
    :func:`parse_karma` and comes back to the feed. ``WarmSessionAction`` calls
    it at the end of a session (``gitd/farm/skillkit.py``) and attaches the
    result to the ``session_summary`` event: OFMAI serves no Reddit publication
    below 100 karma (``docs/social/publishing.md`` §5) and that number exists
    nowhere else. An adapter without the hook simply reports nothing, and the
    account stays out of the Reddit queue for a stated reason.
    """

    platform: str

    def dump(self) -> str: ...

    def open_feed(self) -> bool: ...

    def on_feed(self, xml: str) -> bool: ...

    def next_video(self) -> None: ...

    def like(self, xml: str) -> bool: ...

    def save(self, xml: str) -> bool: ...

    def open_author(self, xml: str) -> str | None: ...

    def follow(self, xml: str) -> bool: ...

    def comment(self, text: str) -> bool: ...

    def back_to_feed(self) -> None: ...

    def detour(self, kind: str, query: str | None) -> bool: ...


# Propensities per phase: how eager the "person" is, before the ledger says no.
@dataclass(frozen=True)
class Propensity:
    like: float
    save: float
    visit: float
    follow_when_visiting: float
    comment: float


PROPENSITY: dict[policy.Phase, Propensity] = {
    policy.Phase.CONSUME: Propensity(0.0, 0.0, 0.02, 0.0, 0.0),
    policy.Phase.LIGHT: Propensity(0.09, 0.03, 0.05, 0.25, 0.0),
    policy.Phase.NETWORK: Propensity(0.11, 0.04, 0.07, 0.35, 0.04),
    policy.Phase.CRUISE: Propensity(0.12, 0.04, 0.08, 0.30, 0.05),
}

# Detours: every N videos (uniform in range) leave the feed for a moment.
DETOUR_EVERY = (12, 30)
# The oriented warm-up (warming-policy.md §7 bis): every ORIENTED_EVERY feed
# posts, one niche account of the list is searched and a run of ITS Reels is
# watched — that is where ~80 % of a session goes. Only when the niche list
# names accounts ("@handle" entries); a hashtag-only list keeps the old rhythm.
ORIENTED_EVERY = (3, 6)
# "Put the phone down": probability per video and duration range (seconds).
PHONE_DOWN_RATE = 0.03
PHONE_DOWN_S = (20.0, 90.0)
# Verified gestures that fired and proved nothing on screen, in a row, before
# the session stops as an ``action_blocked`` signal (see SessionStats.silent).
SILENT_GESTURES_MAX = 3


@dataclass
class SessionStats:
    videos: int = 0
    likes: int = 0
    saves: int = 0
    visits: int = 0
    follows: int = 0
    comments: int = 0
    detours: int = 0
    seconds: float = 0.0
    health: str | None = None
    error: str | None = None
    # Gestures the adapter fired and then could not confirm on screen (its
    # ``last_gesture_silent`` flag): a like that never turns into "Liked", a
    # join that never turns into "Joined". Three in a row end the session as
    # ``action_blocked`` — that is what a soft block looks like from the
    # device, long before any banner says so. An adapter that does not verify
    # never raises the flag, and this stays at zero.
    silent: int = 0
    oriented: int = 0  # runs of a niche account's Reels (§7 bis)
    discovered: list[str] = field(default_factory=list)  # accounts met in "Following" lists, depth 2
    # Texts actually posted, reported back to OFMAI so the pool can retire them
    # (bridge-ofmai-farm.md §4.1): a comment is drawn at random from the list, so
    # the order is not predictable without saying which ones were used.
    comments_used: list[str] = field(default_factory=list)
    replies_used: list[str] = field(default_factory=list)
    # Niche accounts opened for an oriented run this session ("@handle" as it
    # was searched): skillkit stamps them in farm_targets after the run, so the
    # next session does not open the same door (§7 bis).
    played: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class WarmConfig:
    minutes: float
    phase: policy.Phase
    comments: list[str] = field(default_factory=list)  # ASCII, ready to type
    niche: list[str] = field(default_factory=list)  # hashtags / queries for detours
    detour_kinds: tuple[str, ...] = ("search",)  # skill adds "stories" when it can
    handle: str = ""  # named in the unknown-screen evidence and alert
    advisor: Callable | None = None  # tier 2 of unstuck.py, None = no model


def run_session(
    adapter: PlatformAdapter,
    human: HumanInput,
    ledger: LedgerLike,
    cfg: WarmConfig,
    *,
    now: Callable[[], float] = time.monotonic,
) -> SessionStats:
    stats = SessionStats()
    prop = PROPENSITY[cfg.phase]
    rng = human.profile.rng
    deadline = now() + cfg.minutes * 60
    t0 = now()
    comments = list(cfg.comments)
    next_detour = rng.randint(*DETOUR_EVERY)
    handles = [q for q in cfg.niche if q.startswith("@")]
    hashtags = [q for q in cfg.niche if not q.startswith("@")]
    next_oriented = rng.randint(*ORIENTED_EVERY) if handles else None
    played = stats.played

    def silent_after(ok: bool) -> bool:
        """After a gesture the adapter verifies: count a silence, stop at the cap.

        ``ok`` is what the adapter returned. A False with ``last_gesture_silent``
        raised means "I tapped and the screen never changed" — the one thing a
        soft block looks like from the device. Adapters that do not verify never
        raise the flag; for them this is a no-op.
        """
        if ok or not getattr(adapter, "last_gesture_silent", False):
            return False
        stats.silent += 1
        if stats.silent < SILENT_GESTURES_MAX:
            return False
        matched = f"{stats.silent} gestures without a state change on screen"
        log.warning("[warm] %s — stopping session as action_blocked", matched)
        ledger.signal("action_blocked", matched)
        stats.health = "action_blocked"
        return True

    def check_health(xml: str) -> bool:
        sig = health.detect(adapter.platform, xml)
        if sig:
            log.warning("[warm] health signal %s (%s) — stopping session", sig.kind, sig.matched)
            ledger.signal(sig.kind, sig.matched)
            stats.health = sig.kind
            return True
        return False

    try:
        if not adapter.open_feed():
            stats.error = "feed not reachable"
            return stats
        xml = adapter.dump()
        if check_health(xml):
            return stats

        unreadable = 0
        while now() < deadline:
            xml = adapter.dump()
            if not xml:
                # uiautomator cannot read a screen that never settles — a card
                # with an autoplaying video (Reddit, Instagram, TikTok): that is
                # not a lost feed, it is a post to scroll past. Three in a row
                # is something else, and the tiers below get to look.
                unreadable += 1
                if unreadable < 3:
                    human.watch()
                    adapter.next_video()
                    continue
            else:
                unreadable = 0
            if check_health(xml):
                break
            if not adapter.on_feed(xml):
                adapter.back_to_feed()
                xml = adapter.dump()
                if not adapter.on_feed(xml):
                    # the script is blind here: the other two tiers (unstuck.py)
                    from gitd.farm import unstuck

                    if not unstuck.recover(adapter, adapter.platform, cfg.handle, advisor=cfg.advisor):
                        stats.error = "unknown screen"
                        break
                    xml = adapter.dump()

            # watch the current video
            human.watch()
            ledger.record(policy.VIEW)
            stats.videos += 1

            # like
            if prop.like and ledger.allow(policy.LIKE) and human.profile.chance(prop.like):
                human.pause(0.6)
                if adapter.like(xml):
                    ledger.record(policy.LIKE)
                    stats.likes += 1
                elif silent_after(False):
                    break

            # save
            if prop.save and ledger.allow(policy.SAVE) and human.profile.chance(prop.save):
                human.pause(0.5)
                if adapter.save(xml):
                    ledger.record(policy.SAVE)
                    stats.saves += 1
                elif silent_after(False):
                    break

            # profile visit, maybe follow
            if prop.visit and ledger.allow(policy.PROFILE_VISIT) and human.profile.chance(prop.visit):
                author = adapter.open_author(xml)
                if author is not None:
                    ledger.record(policy.PROFILE_VISIT, author)
                    stats.visits += 1
                    human.pause(2.5)  # read the bio, look at the grid
                    pxml = adapter.dump()
                    if check_health(pxml):
                        break
                    if ledger.allow(policy.FOLLOW) and human.profile.chance(prop.follow_when_visiting):
                        if adapter.follow(pxml):
                            ledger.record(policy.FOLLOW, author)
                            stats.follows += 1
                            human.pause(1.0)
                        elif silent_after(False):
                            adapter.back_to_feed()
                            break
                    adapter.back_to_feed()

            # comment
            if prop.comment and comments and ledger.allow(policy.COMMENT) and human.profile.chance(prop.comment):
                text = comments.pop(rng.randrange(len(comments)))
                human.pause(1.5)  # thinking
                if adapter.comment(text):
                    ledger.record(policy.COMMENT)
                    stats.comments += 1
                    # Only a text that really went through is consumed; anything
                    # else returns to the pool when its reservation expires.
                    stats.comments_used.append(text)
                elif silent_after(False):
                    break
                cxml = adapter.dump()
                if check_health(cxml):
                    break

            # the oriented run: a known niche account, its Reels (§7 bis)
            if next_oriented is not None and stats.videos >= next_oriented and "search" in cfg.detour_kinds:
                next_oriented = stats.videos + rng.randint(*ORIENTED_EVERY)
                fresh = [h for h in handles if h not in played] or handles
                if fresh and ledger.allow(policy.SEARCH):
                    handle = rng.choice(fresh)
                    played.append(handle)
                    if adapter.detour("search", handle):
                        ledger.record(policy.SEARCH, handle)
                        stats.detours += 1
                        stats.oriented += 1
                        for who in getattr(adapter, "discovered", []):
                            if who not in stats.discovered:
                                stats.discovered.append(who)
                    adapter.back_to_feed()

            # detour
            if stats.videos >= next_detour and cfg.detour_kinds:
                next_detour = stats.videos + rng.randint(*DETOUR_EVERY)
                kind = rng.choice(cfg.detour_kinds)
                query = rng.choice(hashtags) if hashtags else None
                if kind == "search" and (query is None or not ledger.allow(policy.SEARCH)):
                    kind = None
                if kind == "stories" and not ledger.allow(policy.STORY_VIEW):
                    kind = None
                if kind:
                    if adapter.detour(kind, query):
                        ledger.record(policy.SEARCH if kind == "search" else policy.STORY_VIEW, query)
                        stats.detours += 1
                    adapter.back_to_feed()

            # phone down
            if human.profile.chance(PHONE_DOWN_RATE):
                human.sleep(rng.uniform(*PHONE_DOWN_S))

            adapter.next_video()

    except Exception as e:  # noqa: BLE001 — a session must always return its stats
        log.exception("[warm] session aborted")
        stats.error = str(e)
    finally:
        stats.seconds = now() - t0
    return stats


# ── Shared XML helpers for adapters ──────────────────────────────────────────

_NODE = re.compile(r"<node[^>]+/?>")
_BOUNDS = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def nodes_where(xml: str, *, desc: str | None = None, text: str | None = None, rid: str | None = None) -> list[str]:
    """Nodes whose content-desc / text *contains* the given string (case-insensitive)."""
    out = []
    for n in _NODE.findall(xml or ""):
        if rid is not None and f'resource-id="{rid}"' not in n:
            continue
        low = n.lower()
        if desc is not None:
            m = re.search(r'content-desc="([^"]*)"', n)
            if not m or desc.lower() not in m.group(1).lower():
                continue
        if text is not None and f'text="{text.lower()}' not in low and text.lower() not in _text_of(n).lower():
            continue
        out.append(n)
    return out


def _text_of(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


def desc_of(node: str) -> str:
    m = re.search(r'content-desc="([^"]*)"', node)
    return m.group(1) if m else ""


def center(node: str) -> tuple[int, int] | None:
    m = _BOUNDS.search(node)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


# ── Reddit karma, read on screen ─────────────────────────────────────────────
#
# OFMAI refuses to serve a Reddit publication below 100 karma
# (docs/social/publishing.md §5) and no event carried that number until now: the
# gate was stuck shut. The only place it exists is the account's own profile
# screen, so an adapter reads it there (optional ``read_karma`` hook of
# PlatformAdapter) and ``skillkit`` puts it on the ``session_summary`` event.

_KARMA_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
#: "247", "1,234", "1.2" + "k" — digits and suffix captured apart.
_NUMBER = r"(\d+(?:[.,]\d+)*)\s*([kmb])?"
#: the profile header: "1.2k karma", "247 karma"
_KARMA_TOTAL = re.compile(_NUMBER + r"\s*karma\b", re.IGNORECASE)
#: the detailed rows: "Post karma 1.2k", "Comment karma: 340"
_KARMA_LABELLED = re.compile(r"\b(post|comment|link)\s+karma\b\D{0,3}" + _NUMBER, re.IGNORECASE)


def _karma_number(raw: str, suffix: str | None) -> int | None:
    """``"1,234"`` -> 1234, ``"1.2" + "k"`` -> 1200. None when it is not a number."""
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        if suffix:
            return int(float(cleaned) * _KARMA_SCALE[suffix.lower()])
        # No suffix: a dot can only be a thousands separator here (en-US Reddit
        # writes "1,234"), never a fraction of a karma point.
        return int(cleaned.replace(".", ""))
    except ValueError:
        return None


def parse_karma(xml: str) -> int | None:
    """Total karma shown on a Reddit profile screen, or None when it is absent.

    The **caller** guarantees the screen is the account's *own* profile: every
    other profile shows someone else's karma, and ``open_author`` spends the
    whole session on exactly those. A combined "N karma" wins; failing that, the
    sum of the labelled "post karma" / "comment karma" rows.
    """
    if not xml:
        return None
    labelled: dict[str, int] = {}
    for node in _NODE.findall(xml):
        haystack = f"{_text_of(node)} {desc_of(node)}"
        if "karma" not in haystack.lower():
            continue
        for kind, raw, suffix in _KARMA_LABELLED.findall(haystack):
            value = _karma_number(raw, suffix or None)
            if value is not None:
                labelled.setdefault("post" if kind.lower() == "link" else kind.lower(), value)
        match = _KARMA_TOTAL.search(haystack)
        if match:
            total = _karma_number(match.group(1), match.group(2) or None)
            if total is not None:
                return total
    return sum(labelled.values()) if labelled else None
