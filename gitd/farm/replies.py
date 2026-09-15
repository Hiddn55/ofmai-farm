"""Answering under your own post, and in a DM thread.

Two loops, one rule: **the farm never writes the text**. Replies are written on
the OFMAI side from the persona sheet, pass the compliance gate and land in
``SocialCommentPool``; the bridge serves them through ``GET /api/farm/comments``
and hands them to the workflow as ``params.replies_ai`` / ``replies_thanks`` /
``replies_question`` (docs/social/publishing.md §1.2 and §9,
bridge-ofmai-farm.md §3.4). Here they are only classified, budgeted and typed
exactly as they arrived.

What this module decides:

* which comments deserve an answer, and in which order — questions first, then
  compliments (publishing.md §9); an insult or a link is left alone;
* which pool a comment draws from: ``ai`` for "are you real / how / what tool"
  (the same four trigger words as the comment-to-DM automation, §8),
  ``question`` for any other question, ``thanks`` for a compliment. An
  **undeclared** character has an empty ``ai`` pool, so it simply never answers
  that question rather than denying anything (§1.1);
* that every reply asks the ledger first — ``COMMENT_REPLY`` 20/day in network
  and cruise, ``DM_REPLY`` 20/day in cruise (policy.py) — that a like back is a
  plain ``LIKE`` under the 15 % ratio like any other like, and that the first
  health signal ends the pass without a retry (R27).

Nothing here touches a device: the platform gestures live in a
:class:`CommentAdapter` / :class:`DmAdapter` implemented by each skill, and the
ghost ``Action`` wrapper lives in :mod:`gitd.farm.replykit`.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Protocol

from gitd.farm import health, policy
from gitd.farm.human import HumanInput
from gitd.farm.warm import center, nodes_where

log = logging.getLogger(__name__)

# How many comments one pass reads under a post (build-plan E3.2).
MAX_COMMENTS = 10
# How many messages of a DM thread are read to decide who spoke last.
MAX_DM_THREADS = 10
# A thread is answered at most twice, ever (build-plan E3.3).
MAX_DM_EXCHANGES = 2
# How far back the ledger is read for "have I already answered this one".
HANDLED_DAYS = 30

# ── Classification ────────────────────────────────────────────────────────────

AI = "ai"
QUESTION = "question"
THANKS = "thanks"
# The order a pass answers in: the "are you real?" crowd, then the other
# questions, then the compliments (publishing.md §9).
KIND_ORDER = (AI, QUESTION, THANKS)
POOL_PARAM = {AI: "replies_ai", QUESTION: "replies_question", THANKS: "replies_thanks"}

# The four trigger words of the comment-to-DM automation (publishing.md §8), so
# a public reply and the private DM react to the same comments.
_AI_WORDS = re.compile(r"\b(real|ai|a\.i\.|how|tool)\b", re.IGNORECASE)
# A URL in either direction is a hard stop: we never publish one in a reply
# (R22), and a comment carrying one is spam, not a conversation.
_LINK = re.compile(
    r"https?://|www\.[a-z0-9-]|\b[a-z0-9-]{2,}\.(com|net|org|io|ai|co|me|link|bio|tv|xyz|onl|vip)\b|t\.me/",
    re.IGNORECASE,
)
_INSULT = re.compile(
    r"\b(ugly|fat|gross|disgusting|trash|garbage|whore|slut|bitch|hoe|cunt|retard|stupid|idiot|scam|scammer|kys|"
    r"kill yourself|shut up|nobody cares)\b",
    re.IGNORECASE,
)
_INTERROGATIVE = re.compile(r"^\s*(what|where|when|which|who|whose|why|how|can|could|do|does|did|is|are|was|will|would)\b", re.IGNORECASE)
# A DM that asks for a private photo, a phone number or a meeting is left
# unanswered — no exception, whatever the pool says (build-plan E3.3).
_DM_UNSAFE = re.compile(
    r"\b(nude|nudes|naked|pic|pics|picture|photo|photos|selfie|number|phone|whatsapp|telegram|snap|snapchat|kik|"
    r"facetime|call me|meet|meetup|hook ?up|address|hotel|in person|see you)\b",
    re.IGNORECASE,
)


def classify(text: str) -> str | None:
    """``ai`` | ``question`` | ``thanks``, or ``None`` when the comment is left alone.

    Order matters: a comment is dropped for a link or an insult before anything
    else, then the four AI trigger words win over the generic question test —
    "how was this made?" belongs to the ``ai`` pool, not to ``question``.
    """
    t = (text or "").strip()
    if not t:
        return None
    if _LINK.search(t) or _INSULT.search(t):
        return None
    if _AI_WORDS.search(t):
        return AI
    if "?" in t or _INTERROGATIVE.search(t):
        return QUESTION
    return THANKS


def is_safe_dm(text: str) -> bool:
    """False for a DM asking for a private photo, a number or a meeting."""
    t = (text or "").strip()
    if not t:
        return False
    return not (_LINK.search(t) or _INSULT.search(t) or _DM_UNSAFE.search(t))


def is_postable(text: str) -> bool:
    """A pool text we are willing to type: pure ASCII (R12), no link (R22).

    The pools are built and checked on the OFMAI side; this is the last gate
    before the characters reach the keyboard. ``HumanInput.type_text`` drops
    non-ASCII silently, and a truncated word reads exactly like a bot.
    """
    t = (text or "").strip()
    return bool(t) and all(ord(c) < 128 for c in t) and not _LINK.search(t)


# ── Screen helpers (pure, shared by the four skills) ──────────────────────────


@dataclass(frozen=True)
class Comment:
    author: str
    text: str
    y: int  # vertical centre of the row, used to find its Like / Reply buttons


@dataclass(frozen=True)
class DmThread:
    peer: str
    y: int
    unread: bool


def rows_by_rid(xml: str, rid: str | None) -> list[tuple[str, tuple[int, int]]]:
    """Every node carrying ``rid``, with its centre, top to bottom."""
    if not rid:
        return []
    out = []
    for node in nodes_where(xml or "", rid=rid):
        c = center(node)
        if c:
            out.append((node, c))
    out.sort(key=lambda p: p[1][1])
    return out


def text_of(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node or "")
    return m.group(1) if m else ""


def pair_comments(xml: str, *, author_rid: str | None, text_rid: str | None, tolerance: int = 220) -> list[Comment]:
    """Pair each author row with the comment body nearest below it.

    Comment lists have no per-row container we can rely on across app versions,
    so the pairing is geometric: the body of a comment sits just under its
    author, within ``tolerance`` pixels. Every body is used at most once, which
    keeps a two-line comment from stealing the next one's author.
    """
    authors = rows_by_rid(xml, author_rid)
    bodies = rows_by_rid(xml, text_rid)
    used: set[int] = set()
    out: list[Comment] = []
    for node, (_, ay) in authors:
        best, best_d = None, None
        for i, (bnode, (_, by)) in enumerate(bodies):
            if i in used or by < ay - 40:
                continue
            d = abs(by - ay)
            if d <= tolerance and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is None:
            continue
        used.add(best)
        author = text_of(node).lstrip("@").strip()
        body = text_of(bodies[best][0]).strip()
        if author and body:
            out.append(Comment(author=author, text=body, y=bodies[best][1][1]))
    return out


def tap_in_row(human: HumanInput, xml: str, y: int, *, desc: str | None = None, text: str | None = None, band: int = 160) -> bool:
    """Tap a button that belongs to the comment row centred on ``y``."""
    for node in nodes_where(xml or "", desc=desc, text=text):
        c = center(node)
        if c and abs(c[1] - y) <= band:
            human.tap(*c)
            return True
    return False


def row_has(xml: str, y: int, *, desc: str | None = None, text: str | None = None, band: int = 160) -> bool:
    """Is there such a node in the row centred on ``y``? (e.g. an already-lit heart)"""
    for node in nodes_where(xml or "", desc=desc, text=text):
        c = center(node)
        if c and abs(c[1] - y) <= band:
            return True
    return False


def post_key(raw: str | None, *, limit: int = 40) -> str:
    """A short, stable-enough key for "the post I answered under".

    The device never gives us a post id (docs/social/publishing.md §2), so the
    key is whatever the screen names the media — the accessibility label of the
    media, or the first words of the caption. It only has to stay the same
    between two passes over the same post, which is what
    ``farm_actions.target = "<post>:<author>"`` needs.
    """
    s = "".join(ch for ch in (raw or "") if 32 <= ord(ch) < 127)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] or "last"


# ── Ledger helpers ────────────────────────────────────────────────────────────


def handled_targets(db, account, kind: str, *, days: int = HANDLED_DAYS) -> set[str]:
    """Targets this account already recorded for ``kind`` in the last ``days``.

    The key is ``"<post>:<author>"`` for a comment and the peer for a DM
    (build-plan E3.2/E3.3): the ledger *is* the memory of what was answered, so
    a second pass over the same post never answers the same person twice.
    """
    from sqlalchemy import select

    from gitd.farm import ledger as _ledger
    from gitd.farm.models import FarmAction

    since = (_ledger.local_today(account) - timedelta(days=days)).isoformat()
    rows = db.execute(
        select(FarmAction.target).where(
            FarmAction.account_id == account.id, FarmAction.kind == kind, FarmAction.day >= since
        )
    ).all()
    return {r[0] for r in rows if r[0]}


def target_counts(db, account, kind: str, *, days: int = HANDLED_DAYS) -> dict[str, int]:
    """How many times each target was recorded for ``kind`` (DM exchanges)."""
    from sqlalchemy import func, select

    from gitd.farm import ledger as _ledger
    from gitd.farm.models import FarmAction

    since = (_ledger.local_today(account) - timedelta(days=days)).isoformat()
    rows = db.execute(
        select(FarmAction.target, func.count())
        .where(FarmAction.account_id == account.id, FarmAction.kind == kind, FarmAction.day >= since)
        .group_by(FarmAction.target)
    ).all()
    return {t: n for t, n in rows if t}


# ── Adapters ──────────────────────────────────────────────────────────────────


class LedgerLike(Protocol):
    def allow(self, action: str) -> bool: ...

    def record(self, action: str, target: str | None = None) -> None: ...

    def signal(self, kind: str, matched: str | None = None): ...


class CommentAdapter(Protocol):
    """What a skill provides so the account can answer under its own post."""

    platform: str

    def dump(self) -> str: ...

    def open_own_post(self) -> str | None:
        """Profile → newest post → its comments. Returns a stable-ish post key."""

    def read_comments(self, xml: str) -> list[Comment]: ...

    def like_comment(self, comment: Comment, xml: str) -> bool:
        """Like the comment received. Reddit never does (vote manipulation)."""

    def reply_to_comment(self, comment: Comment, text: str, xml: str) -> bool: ...

    def leave_post(self) -> None: ...


class CommentRowsMixin:
    """The part of a comment adapter that is the same on all four apps.

    Mixed into a skill's warming adapter, it reads the comment list from the
    two resource ids named in ``elements.yaml`` (``comment_author_row`` and
    ``comment_text_row``), likes a comment by finding the heart on its row, and
    leaves the post with Back. Each skill still writes the two platform-specific
    halves: how to reach its newest post (``open_own_post``) and how to send a
    reply (``reply_to_comment``).

    ``likes_back = False`` turns the like into a no-op — Reddit, where casting a
    vote in return for one received is vote manipulation (publishing.md §9).
    """

    likes_back: bool = True
    # content-desc of the per-comment like button, and of its "already on" state
    like_desc: str = "Like"
    liked_descs: tuple[str, ...] = ("Liked", "Unlike")

    def _rid(self, name: str) -> str | None:
        el = self.elements.get(name)
        return el.resource_id if el else None

    def read_comments(self, xml: str) -> list[Comment]:
        return pair_comments(xml, author_rid=self._rid("comment_author_row"), text_rid=self._rid("comment_text_row"))

    def like_comment(self, comment: Comment, xml: str) -> bool:
        if not self.likes_back:
            return False
        if any(row_has(xml, comment.y, desc=d) for d in self.liked_descs):
            return False  # never un-like what is already liked
        return tap_in_row(self.human, xml, comment.y, desc=self.like_desc)

    def leave_post(self) -> None:
        for _ in range(3):
            self.device.back(delay=0.6)


class DmAdapter(Protocol):
    """What a skill provides so the account can answer a DM it received."""

    platform: str

    def dump(self) -> str: ...

    def open_inbox(self) -> bool: ...

    def read_threads(self, xml: str) -> list[DmThread]: ...

    def open_thread(self, thread: DmThread) -> str | None:
        """Open it and return the last **incoming** message, or None."""

    def send_dm(self, text: str) -> bool: ...

    def back_to_inbox(self) -> None: ...


# ── Comment replies ───────────────────────────────────────────────────────────


@dataclass
class ReplyConfig:
    pools: dict[str, list[str]] = field(default_factory=dict)
    max_comments: int = MAX_COMMENTS


@dataclass
class ReplyStats:
    comments_read: int = 0
    replies: int = 0
    likes: int = 0
    ignored: int = 0  # insults, links, already answered, empty pool
    dropped: int = 0  # a pool text refused at the keyboard (link or non-ASCII)
    seconds: float = 0.0
    health: str | None = None
    error: str | None = None
    post: str | None = None
    replies_used: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def run_comment_replies(
    adapter: CommentAdapter,
    human: HumanInput,
    ledger: LedgerLike,
    cfg: ReplyConfig,
    *,
    handled: frozenset[str] | set[str] = frozenset(),
    now: Callable[[], float] = time.monotonic,
) -> ReplyStats:
    """One pass under the account's newest post. Never raises."""
    stats = ReplyStats()
    pools = {k: list(v) for k, v in cfg.pools.items()}
    rng = human.profile.rng
    t0 = now()

    def check_health(xml: str) -> bool:
        sig = health.detect(adapter.platform, xml)
        if sig:
            log.warning("[replies] health signal %s (%s) — stopping", sig.kind, sig.matched)
            ledger.signal(sig.kind, sig.matched)
            stats.health = sig.kind
            return True
        return False

    try:
        post = adapter.open_own_post()
        if not post:
            stats.error = "no post to reply under"
            return stats
        stats.post = post
        xml = adapter.dump()
        if check_health(xml):
            return stats

        comments = adapter.read_comments(xml)[: cfg.max_comments]
        stats.comments_read = len(comments)
        queue: list[tuple[int, str, Comment, str]] = []
        for c in comments:
            target = f"{post}:{c.author}"
            kind = classify(c.text)
            if kind is None or target in handled:
                stats.ignored += 1
                continue
            queue.append((KIND_ORDER.index(kind), kind, c, target))
        queue.sort(key=lambda q: q[0])

        for _, kind, comment, target in queue:
            pool = pools.get(kind) or []
            if not pool:
                # An undeclared character's `ai` pool is empty on purpose: the
                # question is left unanswered, never denied (publishing.md §1.1).
                stats.ignored += 1
                continue
            if not ledger.allow(policy.COMMENT_REPLY):
                break
            text = pool.pop(rng.randrange(len(pool)))
            if not is_postable(text):
                log.warning("[replies] pool text refused (link or non-ASCII) — skipped")
                stats.dropped += 1
                continue
            xml = adapter.dump()
            if check_health(xml):
                break
            # The like back is a plain like: same cap, same 15 % ratio (R14).
            if ledger.allow(policy.LIKE) and adapter.like_comment(comment, xml):
                ledger.record(policy.LIKE, target)
                stats.likes += 1
                human.pause(0.6)
            human.pause(1.5)  # reading the comment
            if adapter.reply_to_comment(comment, text, adapter.dump()):
                ledger.record(policy.COMMENT_REPLY, target)
                stats.replies += 1
                stats.replies_used.append(text)
            if check_health(adapter.dump()):
                break
        adapter.leave_post()
    except Exception as e:  # noqa: BLE001 — a pass always returns its counters
        log.exception("[replies] comment pass aborted")
        stats.error = str(e)
    finally:
        stats.seconds = now() - t0
    return stats


# ── DM replies ────────────────────────────────────────────────────────────────


@dataclass
class DmStats:
    threads_read: int = 0
    dms: int = 0
    ignored: int = 0  # read, closed, unsafe, already twice answered
    dropped: int = 0
    seconds: float = 0.0
    health: str | None = None
    error: str | None = None
    replies_used: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def run_dm_replies(
    adapter: DmAdapter,
    human: HumanInput,
    ledger: LedgerLike,
    cfg: ReplyConfig,
    *,
    exchanges: dict[str, int] | None = None,
    now: Callable[[], float] = time.monotonic,
) -> DmStats:
    """One pass over the unread DM threads. Never raises.

    A DM never starts a conversation: only an unread thread whose **last**
    message is incoming is answered, at most twice in its life, and never when
    it asks for a private photo, a number or a meeting (publishing.md §9).
    """
    stats = DmStats()
    pools = {k: list(v) for k, v in cfg.pools.items()}
    seen = dict(exchanges or {})
    rng = human.profile.rng
    t0 = now()

    def check_health(xml: str) -> bool:
        sig = health.detect(adapter.platform, xml)
        if sig:
            log.warning("[replies] health signal %s (%s) — stopping", sig.kind, sig.matched)
            ledger.signal(sig.kind, sig.matched)
            stats.health = sig.kind
            return True
        return False

    try:
        if not adapter.open_inbox():
            stats.error = "inbox not reachable"
            return stats
        xml = adapter.dump()
        if check_health(xml):
            return stats
        threads = [t for t in adapter.read_threads(xml) if t.unread][:MAX_DM_THREADS]
        stats.threads_read = len(threads)

        for thread in threads:
            if seen.get(thread.peer, 0) >= MAX_DM_EXCHANGES:
                stats.ignored += 1
                continue
            if not ledger.allow(policy.DM_REPLY):
                break
            incoming = adapter.open_thread(thread)
            if not incoming:
                # nothing came in since our last message: never a spontaneous DM
                stats.ignored += 1
                adapter.back_to_inbox()
                continue
            if check_health(adapter.dump()):
                break
            if not is_safe_dm(incoming):
                stats.ignored += 1
                adapter.back_to_inbox()
                continue
            kind = classify(incoming) or THANKS
            pool = pools.get(kind) or []
            if not pool:
                stats.ignored += 1
                adapter.back_to_inbox()
                continue
            text = pool.pop(rng.randrange(len(pool)))
            if not is_postable(text):
                log.warning("[replies] pool text refused (link or non-ASCII) — skipped")
                stats.dropped += 1
                adapter.back_to_inbox()
                continue
            human.pause(1.5)
            if adapter.send_dm(text):
                ledger.record(policy.DM_REPLY, thread.peer)
                stats.dms += 1
                stats.replies_used.append(text)
                seen[thread.peer] = seen.get(thread.peer, 0) + 1
            if check_health(adapter.dump()):
                break
            adapter.back_to_inbox()
    except Exception as e:  # noqa: BLE001
        log.exception("[replies] dm pass aborted")
        stats.error = str(e)
    finally:
        stats.seconds = now() - t0
    return stats
