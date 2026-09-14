"""Planner: turns today's session plan into ghost jobs at the right minute.

Runs as its own process (``python -m gitd.farm.cli daemon``) next to ghost's
server: every minute it looks at every enabled account, computes today's
:func:`policy.plan_sessions` and, when a slot's start time has come, enqueues
a ``skill_workflow`` job for that device. Ghost's scheduler (one job per
phone, priorities, timeouts) does the rest.

Idempotence: a slot is identified by ``account:date:start``; the planner
remembers what it enqueued in ``farm_planned`` so a restart never doubles
a session.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Integer, Text, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from gitd.farm import ledger, policy
from gitd.farm.models import FarmAccount
from gitd.models.base import Base, SessionLocal, engine

log = logging.getLogger(__name__)

SKILL_BY_PLATFORM = {"instagram": "ofmai_instagram", "tiktok": "ofmai_tiktok"}
# a session may run at most this much longer than planned before ghost kills it
GRACE_MINUTES = 10
# a slot older than this is skipped rather than run late (looks robotic to catch up)
LATE_TOLERANCE_MINUTES = 20


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


def job_config(account: FarmAccount, slot: policy.SessionSlot, minutes: float) -> dict:
    return {
        "skill": SKILL_BY_PLATFORM[account.platform],
        "workflow": "warm_session",
        "params": {"handle": account.handle, "minutes": minutes, "niche": account.niche or ""},
        "farm_slot": slot.start.isoformat(timespec="minutes"),
    }


def tick(db: Session, now_for: callable = ledger.local_now) -> list[int]:
    """One planner pass. Returns the ids of the jobs enqueued."""
    from gitd.services.db_helpers import enqueue_job

    enqueued: list[int] = []
    for acc in ledger.list_accounts(db, enabled_only=True):
        if acc.api_mode:
            continue  # production accounts: publishing via API, no warming sessions
        now = now_for(acc)
        if not ledger.health_state(acc).can_run(now):
            continue
        for slot in due_slots(acc, now):
            key = slot_key(acc, slot)
            if db.execute(select(FarmPlanned).where(FarmPlanned.slot_key == key)).scalar_one_or_none():
                continue
            cfg = job_config(acc, slot, slot.minutes)
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
