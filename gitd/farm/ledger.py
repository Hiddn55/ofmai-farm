"""Ledger: the database side of the policy.

Loads an account, builds today's :class:`BudgetTracker` from what was already
spent, records actions and signals, and applies health transitions.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gitd.farm import devices, policy
from gitd.farm.models import (
    FarmAccount,
    FarmAction,
    FarmCommentCache,
    FarmOutbox,
    FarmPublication,
    FarmSignal,
    FarmTarget,
    ensure_farm_columns,
)
from gitd.models.base import Base, SessionLocal, engine

_TABLES = (
    FarmAccount.__table__,
    FarmAction.__table__,
    FarmSignal.__table__,
    # The bridge tables live here too: FarmSession.signal() writes to farm_outbox
    # in its own commit, so the table must exist as soon as the ledger does.
    FarmPublication.__table__,
    FarmOutbox.__table__,
    FarmCommentCache.__table__,
    FarmTarget.__table__,
)

#: A niche account is not opened again for an oriented run before this many
#: days (warming-policy.md §7 bis, "D'où viennent les comptes").
TARGET_COOLDOWN_DAYS = 14
#: Order of preference when picking today's doors: what OFMAI's radar served,
#: then what a run discovered in a "following" list, then hand-typed handles.
TARGET_SOURCES = ("radar", "following", "manual")


def init() -> None:
    """Create the farm tables if missing, then add post-hoc columns (idempotent)."""
    Base.metadata.create_all(engine, tables=list(_TABLES))
    ensure_farm_columns()
    # farm_platforms: the collective rules run inside FarmSession.signal().
    from gitd.farm import collective

    collective.init()


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
    role: str = "persona",
    market: str = "US",
    ofmai_account_id: str | None = None,
) -> FarmAccount:
    if platform not in policy.PLATFORMS:
        raise ValueError(f"unknown platform {platform!r} (known: {', '.join(policy.PLATFORMS)})")
    if role not in policy.ROLES:
        # "observer" is the common mistake: the observer phone is never warmed
        # and never enters the ledger (health-canaries.md §2).
        raise ValueError(f"unknown role {role!r} (known: {', '.join(policy.ROLES)})")
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
        role=role,
        market=market,
        ofmai_account_id=ofmai_account_id,
        # a brand account is registered but never warmed: it is enabled by hand
        enabled=0 if role == "brand" else 1,
    )
    db.add(acc)
    db.commit()
    return acc


def paused(account: FarmAccount, now: datetime) -> bool:
    """True while a platform kill-switch copied from OFMAI is still running.

    ``now`` is the account's own wall clock, so the deadline must be read in the
    same clock: OFMAI serves ``pausedUntil`` as ``Date.toISOString()`` — UTC,
    ending in ``Z`` — and reading that as a local time would stretch a 48 h pause
    by the account's offset.
    """
    if not account.paused_until:
        return False
    try:
        until = datetime.fromisoformat(account.paused_until)
    except ValueError:
        return False
    if until.tzinfo is not None:
        try:
            until = until.astimezone(ZoneInfo(account.timezone)).replace(tzinfo=None)
        except Exception:  # noqa: BLE001 — unknown zone: keep the raw instant
            until = until.replace(tzinfo=None)
    return now < until


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
    #: Set by the bridge when this session exists to publish one OFMAI
    #: publication: ``record(POST)`` then emits the ``posted`` event itself, in
    #: the same commit as the ledger row (bridge-ofmai-farm.md §5.2).
    publication_id: str | None = None

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
        if action == policy.POST and self.publication_id:
            # One commit for the ledger row and the outgoing event: an event can
            # never exist without its action, nor the other way round.
            self._queue_event(
                "posted",
                {"publication_id": self.publication_id, "post_id": target, "post_url": None, "channel": "device"},
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
        # Ledger row, health transition, outgoing event and collective rule all
        # land in the SAME commit (health-canaries.md §4, bridge §5.2).
        self._queue_event(
            "health_signal",
            {
                "signal_kind": kind,
                "matched": matched,
                "new_health": new.status.value,
                "health_until": new.until.isoformat() if new.until else None,
                "phase_override": new.phase_override.value if new.phase_override else None,
                "session_id": self.session_id,
            },
        )
        self._evaluate_platform()
        self.db.commit()
        # R32: the signal must be on Discord within the minute, not at the next tick.
        self._flush_now()
        return new

    # ── Bridge glue, imported late so ledger stays importable on its own ──────

    def _queue_event(self, kind: str, payload: dict) -> None:
        try:
            from gitd.farm import bridge

            bridge.queue_event(self.db, self.account, kind, payload, commit=False)
        except Exception as e:  # noqa: BLE001 — never lose a ledger write over an event
            import logging

            logging.getLogger(__name__).warning("[ledger] outbox write skipped: %s", e)

    def _evaluate_platform(self) -> None:
        try:
            from gitd.farm import collective

            # UTC on purpose: farm_signals.at is written by SQLite's datetime('now').
            collective.evaluate(self.db, self.account.platform, commit=False)
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("[ledger] collective rules skipped: %s", e)

    def _flush_now(self) -> None:
        try:
            from gitd.farm import bridge

            bridge.flush_now()
        except Exception:  # noqa: BLE001 — a missing daemon is not a failed signal
            pass


# ── Targets of the oriented warm-up (warming-policy.md §7 bis) ────────────────


def _bare_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def get_target(db: Session, account: FarmAccount, handle: str) -> FarmTarget | None:
    return db.execute(
        select(FarmTarget).where(FarmTarget.account_id == account.id, FarmTarget.handle == _bare_handle(handle))
    ).scalar_one_or_none()


def record_target(
    db: Session, account: FarmAccount, handle: str, source: str, *, now: datetime | None = None, commit: bool = True
) -> FarmTarget | None:
    """Upsert one known niche account. A handle already known keeps its source
    and its play history; only ``last_seen`` moves. Returns ``None`` for an
    empty handle."""
    bare = _bare_handle(handle)
    if not bare:
        return None
    if source not in TARGET_SOURCES:
        raise ValueError(f"unknown target source {source!r} (known: {', '.join(TARGET_SOURCES)})")
    stamp = (now or local_now(account)).isoformat(timespec="seconds")
    row = get_target(db, account, bare)
    if row:
        row.last_seen = stamp
    else:
        row = FarmTarget(
            account_id=account.id,
            handle=bare,
            platform=account.platform,
            source=source,
            first_seen=stamp,
            last_seen=stamp,
        )
        db.add(row)
    if commit:
        db.commit()
    return row


def record_discovered(db: Session, account: FarmAccount, handle: str, *, now: datetime | None = None) -> FarmTarget | None:
    """A niche account met in the "following" list of another one during a run."""
    return record_target(db, account, handle, "following", now=now)


def mark_played(db: Session, account: FarmAccount, handle: str, *, now: datetime | None = None) -> FarmTarget | None:
    """The run happened: stamp ``last_played`` and count it. A handle never
    recorded (typed by hand in ``farm_accounts.niche``) enters as ``manual`` so
    the same cooldown applies to it from now on."""
    row = record_target(db, account, handle, "manual", now=now, commit=False)
    if row is None:
        return None
    row.last_played = (now or local_now(account)).isoformat(timespec="seconds")
    row.plays = (row.plays or 0) + 1
    db.commit()
    return row


def pick_targets(
    db: Session,
    account: FarmAccount,
    n: int,
    *,
    cooldown_days: int = TARGET_COOLDOWN_DAYS,
    day: date | None = None,
) -> list[str]:
    """Up to ``n`` bare handles never played, or played more than ``cooldown_days`` ago.

    Radar accounts first, then the ones discovered in a following list, then
    the hand-typed ones; inside a source the order is shuffled with the same
    ``(account, day)`` seed as the daily budget, so every session of the day
    walks the same list — and since ``mark_played`` removes what a session
    opened, the next session of the day starts where the previous one stopped.
    """
    if n <= 0:
        return []
    day = day or local_today(account)
    limit = datetime.combine(day, datetime.min.time()) - timedelta(days=cooldown_days)
    rows = list(db.execute(select(FarmTarget).where(FarmTarget.account_id == account.id)).scalars())
    fresh = [r for r in rows if not r.last_played or datetime.fromisoformat(r.last_played) < limit]
    rng = random.Random(policy._seed("targets", account_key(account), day.isoformat()))
    picked: list[str] = []
    for source in TARGET_SOURCES:
        bucket = sorted((r.handle for r in fresh if r.source == source))
        rng.shuffle(bucket)
        picked.extend(bucket)
    return picked[:n]


def clear_health(db: Session, account: FarmAccount, reason: str) -> None:
    """The human gesture after fixing a device (R26, health-canaries.md §6).

    ``--reason`` is mandatory: the return to ``ok`` is audited by a
    ``farm_signals`` row of kind ``cleared`` — ignored by ``apply_signal``, so it
    has no effect on the state machine and never makes an account "red"
    (``collective.RED_KINDS``) — and pushed to OFMAI as a ``health_signal`` whose
    ``signal_kind`` is ``cleared`` (``bridge-ofmai-farm.md`` §4.1).
    """
    account.health = policy.Health.OK.value
    account.health_until = None
    account.phase_override = None
    account.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    db.add(FarmSignal(account_id=account.id, kind="cleared", matched=reason))
    try:
        from gitd.farm import bridge

        bridge.queue_event(
            db,
            account,
            "health_signal",
            {
                "signal_kind": "cleared",
                "matched": reason,
                "new_health": policy.Health.OK.value,
                "health_until": None,
                "phase_override": None,
                "session_id": None,
            },
            commit=False,
        )
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("[ledger] clear-health event skipped: %s", e)
    db.commit()
    try:
        from gitd.farm import bridge

        bridge.flush_now()
    except Exception:  # noqa: BLE001
        pass


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
    if paused(acc, now):
        raise PermissionError(f"@{acc.handle} is paused until {acc.paused_until} (platform kill-switch)")
    # R20: sessions are planned in the account's timezone — a phone that moved
    # would run them in the middle of its night. Silent when the phone cannot
    # be read at all (see devices.timezone_mismatch).
    drift = devices.timezone_mismatch(acc)
    if drift:
        raise PermissionError(f"timezone mismatch: @{acc.handle} — {drift}")
    if hs.status in (policy.Health.COOLDOWN, policy.Health.SHADOWBAN_SUSPECT):
        # timed status expired: back to ok; the phase override stays until cleared by hand
        acc.health = policy.Health.OK.value
        acc.health_until = None
        db.commit()
    day = now.date()
    return FarmSession(db, acc, tracker_for(db, acc, day), uuid.uuid4().hex[:12], day)
