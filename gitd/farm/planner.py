"""Planner: turns today's session plan into ghost jobs at the right minute.

Runs as its own process (``python -m gitd.farm.cli daemon``) next to ghost's
server: every minute it looks at every enabled account, computes today's
:func:`policy.plan_sessions` and, when a slot's start time has come, enqueues
a ``skill_workflow`` job for that device. Ghost's scheduler (one job per
phone, priorities, timeouts) does the rest.

Two kinds of job come out of here:

* the **warming session** itself (``warm_session``), one per slot;
* the **answering passes** that hang off a session — ``comment_reply`` and
  ``dm_reply`` — one per slot, a few minutes after the session's planned end
  (``publishing.md`` §9: "une passe par session de chauffe"). They carry the
  reply pools OFMAI reserved for the account; the farm never writes a text.

Publishing jobs (``post_video``, ``post_photo``, ``post_story``) are *not*
planned here: OFMAI decides them and serves them through ``GET /api/farm/queue``,
so the bridge enqueues them from the queue item's ``format``
(``bridge.WORKFLOW_BY_FORMAT``, ``build-plan.md`` E7.4).

Idempotence: a slot is identified by ``account:date:start``, an answering pass
by ``account:workflow:start``; the planner remembers what it enqueued in
``farm_planned`` so a restart never doubles a session nor a pass.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import Integer, Text, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from gitd.farm import collective, ledger, policy
from gitd.farm.models import FarmAccount
from gitd.models.base import Base, SessionLocal, engine

log = logging.getLogger(__name__)

# Platforms with a warming skill. ``telegram`` is deliberately absent (M2): an
# account may be registered on it, nothing schedules a session for it.
SKILL_BY_PLATFORM = {
    "instagram": "ofmai_instagram",
    "tiktok": "ofmai_tiktok",
    "x": "ofmai_x",
    "reddit": "ofmai_reddit",
}
# a session may run at most this much longer than planned before ghost kills it
GRACE_MINUTES = 10
# a slot older than this is skipped rather than run late (looks robotic to catch up)
LATE_TOLERANCE_MINUTES = 20

# ── Answering passes (comment_reply / dm_reply) ───────────────────────────────

#: ``farm_comment_cache`` kinds that feed an answering pass → the ``params`` key
#: each one lands in (``replykit.pools_from_params``). OFMAI writes every one of
#: those texts and reserves it for 24 h; the farm only copies them into the job
#: (``bridge-ofmai-farm.md`` §3.4, ``publishing.md`` §9).
REPLY_POOLS = {
    "reply_ai": "replies_ai",
    "reply_thanks": "replies_thanks",
    "reply_question": "replies_question",
}
#: Texts handed to one pass, per pool (§3.4: "5 chacun").
REPLY_POOL_SIZE = 5
#: How long ghost may drive the phone for one pass: ten comments or ten threads.
REPLY_MAX_MINUTES = 10
#: Below a warming session and below a publication, so a due session always takes
#: the phone first (``job_engine`` orders pending jobs by ``priority ASC``).
REPLY_PRIORITY = 3


@dataclass(frozen=True)
class ReplyPass:
    """One answering gesture, hung off the warming sessions of the day.

    ``platforms`` is the list of skills that actually carry the workflow: X and
    Reddit have no direct messages at all in V1 (``publishing.md`` §9), so
    ``dm_reply`` is never planned for them — and ``post_story`` is nowhere here
    because it is a publication, decided by OFMAI and enqueued by the bridge.
    """

    action: str  # the ledger action it spends (the cap lives in policy.py)
    workflow: str
    platforms: tuple[str, ...]
    offset_minutes: int  # after the session's *planned* end


#: The two passes, in the order they run after a session. The first waits out
#: ``GRACE_MINUTES`` — ghost kills a session at ``minutes + GRACE_MINUTES``, so
#: by then the phone is free; the second waits for the first to be over. Two
#: sessions are at least 45 min apart (``policy.plan_sessions``), so both passes
#: are finished before the next one starts.
REPLY_PASSES = (
    ReplyPass(policy.COMMENT_REPLY, "comment_reply", ("instagram", "tiktok", "x", "reddit"), GRACE_MINUTES),
    ReplyPass(policy.DM_REPLY, "dm_reply", ("instagram", "tiktok"), GRACE_MINUTES + REPLY_MAX_MINUTES + 5),
)


class FarmPlanned(Base):
    __tablename__ = "farm_planned"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    slot_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    job_id: Mapped[Optional[int]] = mapped_column(Integer)
    at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))


def init() -> None:
    from gitd.models.schedule import JobQueue

    ledger.init()
    # job_queue normally exists (ghost's server creates it); harmless if it does
    Base.metadata.create_all(engine, tables=[FarmPlanned.__table__, JobQueue.__table__])


def slot_key(account: FarmAccount, slot: policy.SessionSlot) -> str:
    return f"{account.id}:{slot.start.isoformat(timespec='minutes')}"


def due_slots(account: FarmAccount, now: datetime) -> list[policy.SessionSlot]:
    """Slots whose start is in [now - LATE_TOLERANCE, now]."""
    budget = ledger.budget_for(account, now.date())
    out = []
    for slot in policy.plan_sessions(budget):
        if slot.start <= now <= slot.start + timedelta(minutes=LATE_TOLERANCE_MINUTES):
            out.append(slot)
    return out


def job_config(
    account: FarmAccount,
    slot: policy.SessionSlot,
    minutes: float,
    comments: list[str] | None = None,
) -> dict:
    """Config of one warming job. ``comments`` come from ``farm_comment_cache``.

    ``WarmSessionAction`` expects them ``\\n``-separated (``gitd/farm/skillkit.py``);
    OFMAI owns the pool and reserves each text for 24 h
    (``bridge-ofmai-farm.md`` §3.4).
    """
    return {
        "skill": SKILL_BY_PLATFORM[account.platform],
        "workflow": "warm_session",
        "params": {
            "handle": account.handle,
            "minutes": minutes,
            "niche": account.niche or "",
            "comments": "\n".join(comments or []),
        },
        "farm_slot": slot.start.isoformat(timespec="minutes"),
    }


def comments_for(
    db: Session,
    account: FarmAccount,
    limit: int = 5,
    kind: str = "comment",
    *,
    take: bool = False,
) -> list[str]:
    """Unused texts cached for this account, oldest first. Never blocks a session.

    ``take`` stamps ``used_at`` on the rows handed out: a text given to a job is
    spent on this side, so the next job gets different words and the bridge's
    low-water mark (``bridge.COMMENT_CACHE_LOW_WATER``) sees the cache drain and
    asks OFMAI for more. OFMAI stays the owner of the pool — a reservation it
    served but nobody typed simply expires and comes back (§3.4).
    """
    from gitd.farm.models import FarmCommentCache

    try:
        rows = list(
            db.execute(
                select(FarmCommentCache)
                .where(
                    FarmCommentCache.account_id == account.id,
                    FarmCommentCache.kind == kind,
                    FarmCommentCache.used_at.is_(None),
                )
                .order_by(FarmCommentCache.id)
                .limit(limit)
            ).scalars()
        )
        texts = [r.text_ for r in rows if r.text_]
        if take and texts:
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            for row in rows:
                row.used_at = stamp
            db.commit()
        return texts
    except Exception:  # noqa: BLE001 — a missing cache is not a missing session
        db.rollback()
        return []


def reply_pools_for(db: Session, account: FarmAccount, *, take: bool = False) -> dict[str, str]:
    """The three reply pools of this account, in the shape the workflow wants.

    An empty ``replies_ai`` is normal for an undeclared character: it never
    answers "are you real?" rather than denying it (``publishing.md`` §1.1).
    All three empty means OFMAI has nothing for this account, and then nothing
    is planned at all — the farm never invents a reply (R13).
    """
    return {
        param: "\n".join(comments_for(db, account, REPLY_POOL_SIZE, kind, take=take))
        for kind, param in REPLY_POOLS.items()
    }


def reply_start(slot: policy.SessionSlot, reply: ReplyPass) -> datetime:
    """When a pass hung off ``slot`` starts, in the account's own clock."""
    return slot.start + timedelta(minutes=slot.minutes + reply.offset_minutes)


def due_reply_passes(account: FarmAccount, now: datetime) -> list[tuple[ReplyPass, datetime]]:
    """Passes whose start is in [now - LATE_TOLERANCE, now], for this account.

    Same rules as a session: nothing on a rest day (``plan_sessions`` returns
    nothing), nothing in the quiet hours and nothing spilling over midnight
    (R15, ``warming-policy.md`` §5).
    """
    budget = ledger.budget_for(account, now.date())
    out: list[tuple[ReplyPass, datetime]] = []
    for slot in policy.plan_sessions(budget):
        for reply in REPLY_PASSES:
            if account.platform not in reply.platforms:
                continue  # no such gesture on this platform — never planned
            start = reply_start(slot, reply)
            if start.date() != slot.start.date() or start.hour in policy.QUIET_HOURS:
                continue  # a late session never drags a pass into the next day
            if start <= now <= start + timedelta(minutes=LATE_TOLERANCE_MINUTES):
                out.append((reply, start))
    out.sort(key=lambda p: p[1])
    return out


def reply_slot_key(account: FarmAccount, reply: ReplyPass, start: datetime) -> str:
    return f"{account.id}:{reply.workflow}:{start.isoformat(timespec='minutes')}"


def reply_job_config(account: FarmAccount, reply: ReplyPass, start: datetime, pools: dict[str, str]) -> dict:
    """Config of one answering job: the handle, and the pools, and nothing else."""
    return {
        "skill": SKILL_BY_PLATFORM[account.platform],
        "workflow": reply.workflow,
        "params": {"handle": account.handle, **pools},
        "farm_slot": start.isoformat(timespec="minutes"),
    }


def phone_busy(db: Session, account: FarmAccount) -> bool:
    """Is this phone already taken by a job? One gesture at a time, R8.

    A session enqueued by this very tick counts: an answering pass is never
    stacked on a phone that is about to scroll. The pass is simply not written
    down, so the next tick tries again while the slot is still fresh
    (``LATE_TOLERANCE_MINUTES``), and gives up after that rather than catching up.

    Not to be confused with ``bridge.device_busy``, which answers a different
    question — may this phone receive one more *media* — and looks at the
    publications staged on it as well as at the job that is actually running.
    """
    from gitd.models.schedule import JobQueue

    row = db.execute(
        select(JobQueue).where(
            JobQueue.phone_serial == account.device_serial,
            JobQueue.status.in_(("pending", "running")),
        )
    ).first()
    return bool(row)


def plan_replies(db: Session, account: FarmAccount, now: datetime) -> list[int]:
    """Enqueue the answering passes due for one account. Returns the job ids."""
    from gitd.services.db_helpers import enqueue_job

    enqueued: list[int] = []
    due = due_reply_passes(account, now)
    if not due:
        return enqueued
    tracker = ledger.tracker_for(db, account, now.date())
    for reply, start in due:
        key = reply_slot_key(account, reply, start)
        if db.execute(select(FarmPlanned).where(FarmPlanned.slot_key == key)).scalar_one_or_none():
            continue
        # The cap is the ledger's, never the skill's (R13): 0 before `network`
        # for comments and before `cruise` for DMs, 0 on a rest day, and 0 once
        # today's passes have spent the 20 of the day between them.
        if not tracker.allow(reply.action):
            continue
        if phone_busy(db, account):
            continue
        pools = reply_pools_for(db, account, take=True)
        if not any(pools.values()):
            continue  # OFMAI has no text for this account: nothing is typed, ever
        job_id = enqueue_job(
            db,
            phone_serial=account.device_serial,
            job_type="skill_workflow",
            priority=REPLY_PRIORITY,
            config_json=json.dumps(reply_job_config(account, reply, start, pools)),
            max_duration_s=REPLY_MAX_MINUTES * 60,
            trigger="farm",
        )
        db.add(FarmPlanned(account_id=account.id, slot_key=key, job_id=job_id))
        db.commit()
        enqueued.append(job_id)
        log.info("[planner] @%s %s: %s pass → job #%s", account.handle, account.platform, reply.workflow, job_id)
    return enqueued


def tick(db: Session, now_for: callable = ledger.local_now) -> list[int]:
    """One planner pass. Returns the ids of the jobs enqueued."""
    from gitd.services.db_helpers import enqueue_job

    enqueued: list[int] = []
    # R31 — the machine kill-switch: data/farm/STOP stops every enqueue, here and
    # in the bridge, before anything else is looked at.
    if collective.is_stopped():
        log.warning("[planner] data/farm/STOP is present — nothing is planned")
        return enqueued
    for acc in ledger.list_accounts(db, enabled_only=True):
        if acc.api_mode:
            continue  # production accounts: publishing via API, no warming sessions
        if acc.role == "brand":
            continue  # the brand account is Nathan's, never warmed by the farm
        if acc.platform not in SKILL_BY_PLATFORM:
            continue  # registered platform with no warming skill yet (telegram)
        now = now_for(acc)
        if not ledger.health_state(acc).can_run(now):
            continue
        if ledger.paused(acc, now):
            continue  # platform kill-switch decided on the OFMAI side
        if collective.is_blocked(db, acc.platform):
            continue  # S3 / S4 decided here (health-canaries.md §4)
        for slot in due_slots(acc, now):
            key = slot_key(acc, slot)
            if db.execute(select(FarmPlanned).where(FarmPlanned.slot_key == key)).scalar_one_or_none():
                continue
            cfg = job_config(acc, slot, slot.minutes, comments_for(db, acc, take=True))
            job_id = enqueue_job(
                db,
                phone_serial=acc.device_serial,
                job_type="skill_workflow",
                priority=2,
                config_json=json.dumps(cfg),
                max_duration_s=int((slot.minutes + GRACE_MINUTES) * 60),
                trigger="farm",
            )
            db.add(FarmPlanned(account_id=acc.id, slot_key=key, job_id=job_id))
            db.commit()
            enqueued.append(job_id)
            log.info("[planner] @%s %s: session %s min → job #%s", acc.handle, acc.platform, slot.minutes, job_id)
        # Answering passes come after the sessions of the same tick on purpose:
        # the session takes the phone, the pass waits for it (``phone_busy``).
        enqueued.extend(plan_replies(db, acc, now))
    return enqueued


def run_forever(interval_s: int = 60) -> None:
    init()
    log.info("[planner] running, tick every %ss", interval_s)
    while True:
        db = SessionLocal()
        try:
            tick(db)
        except Exception:  # noqa: BLE001
            log.exception("[planner] tick failed")
        finally:
            db.close()
        time.sleep(interval_s)
