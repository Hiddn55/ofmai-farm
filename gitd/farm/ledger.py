"""Ledger: the database side of the policy.

Loads an account, builds today's :class:`BudgetTracker` from what was already
spent, records actions and signals, and applies health transitions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gitd.farm import policy
from gitd.farm.models import FarmAccount, FarmAction, FarmSignal
from gitd.models.base import Base, SessionLocal, engine

_TABLES = (FarmAccount.__table__, FarmAction.__table__, FarmSignal.__table__)


def init() -> None:
    """Create the farm tables if missing (idempotent)."""
    Base.metadata.create_all(engine, tables=list(_TABLES))


def local_now(account: FarmAccount) -> datetime:
    return datetime.now(ZoneInfo(account.timezone)).replace(tzinfo=None)


def local_today(account: FarmAccount) -> date:
    return local_now(account).date()


def account_key(account: FarmAccount) -> str:
    return f"{account.platform}:{account.id}"


def get_account(db: Session, platform: str, handle: str) -> FarmAccount | None:
    h = handle.lstrip("@").lower()
    return db.execute(
        select(FarmAccount).where(FarmAccount.platform == platform, func.lower(FarmAccount.handle) == h)
    ).scalar_one_or_none()


def list_accounts(db: Session, *, enabled_only: bool = False) -> list[FarmAccount]:
    q = select(FarmAccount).order_by(FarmAccount.platform, FarmAccount.handle)
    if enabled_only:
        q = q.where(FarmAccount.enabled == 1)
    return list(db.execute(q).scalars())


def add_account(
    db: Session,
    *,
    platform: str,
    handle: str,
    device_serial: str,
    created_on: date | None = None,
    timezone: str = "America/New_York",
    character_id: str | None = None,
    niche: str | None = None,
) -> FarmAccount:
    if platform not in ("instagram", "tiktok"):
        raise ValueError(f"unknown platform {platform!r}")
    if get_account(db, platform, handle):
        raise ValueError(f"{platform} account @{handle.lstrip('@')} already registered")
    other = db.execute(
        select(FarmAccount).where(FarmAccount.device_serial == device_serial, FarmAccount.platform == platform)
    ).scalar_one_or_none()
    if other:
        raise ValueError(f"device {device_serial} already carries {platform} account @{other.handle} (one per device)")
    ZoneInfo(timezone)  # validates the name
    acc = FarmAccount(
        platform=platform,
        handle=handle.lstrip("@"),
        device_serial=device_serial,
        created_on=(created_on or datetime.now(ZoneInfo(timezone)).date()).isoformat(),
        timezone=timezone,
        character_id=character_id,
        niche=niche,
    )
    db.add(acc)
    db.commit()
    return acc


def health_state(account: FarmAccount) -> policy.HealthState:
    until = datetime.fromisoformat(account.health_until) if account.health_until else None
    override = policy.Phase(account.phase_override) if account.phase_override else None
    return policy.HealthState(policy.Health(account.health), until, override)


def _first_day_of_phase(phase: policy.Phase, platform: str) -> int:
    d = 1
    while policy.phase_for_day(d, platform) != phase:
        d += 1
    return d


def budget_for(account: FarmAccount, day: date | None = None) -> policy.DailyBudget:
    """Today's budget, lowered to the forced phase while the account recovers."""
    day = day or local_today(account)
    created = date.fromisoformat(account.created_on)
    natural = policy.DailyBudget.build(account_key(account), account.platform, created, day)
    eff = health_state(account).effective_phase(natural.phase)
    if eff == natural.phase:
        return natural
    # Same seed (account, day), caps of the forced phase, real day-of-life kept.
    pretend_created = day - timedelta(days=_first_day_of_phase(eff, account.platform) - 1)
    forced = policy.DailyBudget.build(account_key(account), account.platform, pretend_created, day)
    forced.day_of_life = natural.day_of_life
    return forced


def spent_on(db: Session, account: FarmAccount, day: date) -> dict[str, int]:
    rows = db.execute(
        select(FarmAction.kind, func.count())
        .where(FarmAction.account_id == account.id, FarmAction.day == day.isoformat())
        .group_by(FarmAction.kind)
    ).all()
    return {k: n for k, n in rows}


def posts_this_week(db: Session, account: FarmAccount, day: date) -> int:
    start = day - timedelta(days=day.weekday())
    return db.execute(
        select(func.count()).where(
            FarmAction.account_id == account.id,
            FarmAction.kind == policy.POST,
            FarmAction.day >= start.isoformat(),
            FarmAction.day <= day.isoformat(),
        )
    ).scalar_one()


def tracker_for(db: Session, account: FarmAccount, day: date | None = None) -> policy.BudgetTracker:
    day = day or local_today(account)
    return policy.BudgetTracker(budget_for(account, day), spent_on(db, account, day), posts_this_week(db, account, day))


@dataclass
class FarmSession:
    """One running session: records into the ledger and the in-memory tracker."""

    db: Session
    account: FarmAccount
    tracker: policy.BudgetTracker
    session_id: str
    day: date

    def allow(self, action: str) -> bool:
        return self.tracker.allow(action)

    def record(self, action: str, target: str | None = None) -> None:
        self.tracker.record(action)
        self.db.add(
            FarmAction(
                account_id=self.account.id,
                day=self.day.isoformat(),
                kind=action,
                target=target,
                session_id=self.session_id,
            )
        )
        self.db.commit()

    def signal(self, kind: str, matched: str | None = None) -> policy.HealthState:
        self.db.add(FarmSignal(account_id=self.account.id, kind=kind, matched=matched, session_id=self.session_id))
        now = local_now(self.account)
        new = policy.apply_signal(health_state(self.account), kind, now, self.tracker.budget.phase)
        self.account.health = new.status.value
        self.account.health_until = new.until.isoformat() if new.until else None
        self.account.phase_override = new.phase_override.value if new.phase_override else None
        self.account.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.db.commit()
        return new


def open_session(platform: str, handle: str, db: Session | None = None) -> FarmSession:
    """Load the account, refuse if unhealthy or disabled, return a live session."""
    db = db or SessionLocal()
    acc = get_account(db, platform, handle)
    if not acc:
        raise LookupError(f"{platform} account @{handle.lstrip('@')} is not registered (farm accounts add ...)")
    if not acc.enabled:
        raise PermissionError(f"@{acc.handle} is disabled")
    now = local_now(acc)
    hs = health_state(acc)
    if not hs.can_run(now):
        why = f" until {hs.until}" if hs.until else " — a human must act on the device"
        raise PermissionError(f"@{acc.handle} is {hs.status.value}{why}")
    if hs.status in (policy.Health.COOLDOWN, policy.Health.SHADOWBAN_SUSPECT):
        # timed status expired: back to ok; the phase override stays until cleared by hand
        acc.health = policy.Health.OK.value
        acc.health_until = None
        db.commit()
    day = now.date()
    return FarmSession(db, acc, tracker_for(db, acc, day), uuid.uuid4().hex[:12], day)
