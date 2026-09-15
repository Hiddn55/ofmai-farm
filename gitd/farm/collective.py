"""Collective health: a platform stops when several accounts go red at once.

``docs/social/health-canaries.md`` §4, rules S3 and S4:

* **S3** — two *red* accounts within 48 h on a platform → the platform is paused
  for 48 h. A pause expires on its own.
* **S4** — three ``suspended`` accounts within 48 h → the platform is **cut**.
  Only a human lifts a cut, after a dated post-mortem (R30).

An account is *red* when it carries a ``farm_signals`` row of kind
``action_blocked``, ``verification``, ``suspended`` or ``shadowban`` less than
48 h old. ``logged_out`` is excluded: most of the time that is a wiped device,
not the platform. Two signals from the same account count once.

OFMAI runs the same rules on its own ``FarmEvent`` rows
(``lib/social/bridge-health.ts``); each side applies the **stricter** of the
two, so the platform still stops when the bridge is down.

There is also a kill-switch for the whole machine (R31): the file
``data/farm/STOP``, tested by ``planner.tick`` and ``bridge.tick`` before they
enqueue anything.

Everything here is pure SQLite + datetimes: testable without a device.

Time zones: ``farm_signals.at`` is written by SQLite's ``datetime('now')``,
which is **UTC**. Every instant in this module is therefore UTC, and
``paused_until`` is stored as an ISO UTC string — not the account-local ISO that
``farm_accounts.paused_until`` carries (that one is copied verbatim from OFMAI).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import Integer, Text, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from gitd.farm.models import FarmAccount, FarmSignal
from gitd.models.base import Base, engine

log = logging.getLogger(__name__)

# A signal of one of these kinds, less than RED_WINDOW_HOURS old, makes an
# account red. ``logged_out`` is deliberately absent (health-canaries.md §4).
RED_KINDS = ("action_blocked", "verification", "suspended", "shadowban")
RED_WINDOW_HOURS = 48
# S3: this many distinct red accounts pause the platform, for this long.
RED_ACCOUNTS_FOR_PAUSE = 2
PAUSE_HOURS = 48
# S4: this many distinct suspended accounts cut the platform until a human acts.
SUSPENDED_FOR_CUT = 3


class FarmPlatform(Base):
    """Kill-switch state of one platform, as the farm sees it."""

    __tablename__ = "farm_platforms"

    platform: Mapped[str] = mapped_column(Text, primary_key=True)
    paused_until: Mapped[Optional[str]] = mapped_column(Text)  # ISO UTC
    cut: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(Text)


def init() -> None:
    """Create ``farm_platforms`` if missing (same mechanism as the other farm tables)."""
    Base.metadata.create_all(engine, tables=[FarmPlatform.__table__])


# ── Time helpers ──────────────────────────────────────────────────────────────


def utcnow() -> datetime:
    """Naive UTC — the unit ``farm_signals.at`` is written in."""
    return datetime.now(UTC).replace(tzinfo=None)


def _as_utc_naive(moment: datetime | None) -> datetime:
    if moment is None:
        return utcnow()
    if moment.tzinfo is not None:
        return moment.astimezone(UTC).replace(tzinfo=None)
    return moment


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


# ── The rules ─────────────────────────────────────────────────────────────────


def red_accounts(db: Session, platform: str, now: datetime | None = None) -> set[int]:
    """Distinct account ids of ``platform`` red within the last 48 h."""
    now = _as_utc_naive(now)
    return _signalled_accounts(db, platform, now, RED_KINDS)


def suspended_accounts(db: Session, platform: str, now: datetime | None = None) -> set[int]:
    """Distinct account ids of ``platform`` suspended within the last 48 h (S4)."""
    now = _as_utc_naive(now)
    return _signalled_accounts(db, platform, now, ("suspended",))


def _signalled_accounts(db: Session, platform: str, now: datetime, kinds: tuple[str, ...]) -> set[int]:
    cutoff = now - timedelta(hours=RED_WINDOW_HOURS)
    rows = db.execute(
        select(FarmSignal.account_id, FarmSignal.at)
        .join(FarmAccount, FarmAccount.id == FarmSignal.account_id)
        .where(FarmAccount.platform == platform, FarmSignal.kind.in_(kinds))
    ).all()
    out: set[int] = set()
    for account_id, at in rows:
        when = _parse(at)
        # A row whose timestamp cannot be read counts: erring towards pausing.
        if when is None or when >= cutoff:
            out.add(account_id)
    return out


@dataclass(frozen=True)
class PlatformState:
    platform: str
    paused_until: datetime | None
    cut: bool
    reason: str | None

    def blocked(self, now: datetime | None = None) -> bool:
        if self.cut:
            return True
        now = _as_utc_naive(now)
        return bool(self.paused_until and now < self.paused_until)


def state(db: Session, platform: str) -> PlatformState:
    row = db.get(FarmPlatform, platform)
    if not row:
        return PlatformState(platform, None, False, None)
    return PlatformState(platform, _parse(row.paused_until), bool(row.cut), row.reason)


def is_blocked(db: Session, platform: str, now: datetime | None = None) -> bool:
    """True while the platform must not be served: cut, or still paused."""
    return state(db, platform).blocked(now)


def _write(
    db: Session,
    platform: str,
    *,
    paused_until: datetime | None,
    cut: bool,
    reason: str | None,
    now: datetime,
) -> FarmPlatform:
    row = db.get(FarmPlatform, platform)
    if not row:
        row = FarmPlatform(platform=platform)
        db.add(row)
    row.paused_until = paused_until.isoformat(timespec="seconds") if paused_until else None
    row.cut = 1 if cut else 0
    row.reason = reason
    row.updated_at = now.isoformat(timespec="seconds")
    return row


def evaluate(db: Session, platform: str, now: datetime | None = None, *, commit: bool = True) -> PlatformState:
    """Replay S3 and S4 for one platform. Called right after a signal is written.

    ``commit=False`` keeps the write inside the caller's transaction — that is how
    ``FarmSession.signal()`` gets the signal, the health transition and the
    platform pause in **one** commit.
    """
    now = _as_utc_naive(now)
    # ``SessionLocal`` is built with ``autoflush=False``: the signal row the
    # caller just added is still pending. Flush it — same transaction, so the
    # signal that triggers the rule is counted by the rule it triggers.
    db.flush()
    before = state(db, platform)

    reds = red_accounts(db, platform, now)
    suspended = suspended_accounts(db, platform, now)

    after = before
    if len(suspended) >= SUSPENDED_FOR_CUT and not before.cut:
        # S4 — no timer: a human lifts a cut, after a dated post-mortem (R30).
        reason = f"S4: {len(suspended)} suspended accounts within {RED_WINDOW_HOURS}h"
        _write(db, platform, paused_until=None, cut=True, reason=reason, now=now)
        after = PlatformState(platform, None, True, reason)
    elif not before.cut and len(reds) >= RED_ACCOUNTS_FOR_PAUSE:
        until = now + timedelta(hours=PAUSE_HOURS)
        # An already running pause is only ever pushed further away, never back.
        if before.paused_until and before.paused_until >= until:
            until = before.paused_until
        reason = f"S3: {len(reds)} red accounts within {RED_WINDOW_HOURS}h"
        _write(db, platform, paused_until=until, cut=False, reason=reason, now=now)
        after = PlatformState(platform, until, False, reason)
    elif before.paused_until and not before.cut and now >= before.paused_until:
        # An S3 pause expires on its own.
        _write(db, platform, paused_until=None, cut=False, reason=None, now=now)
        after = PlatformState(platform, None, False, None)

    if commit:
        db.commit()

    if after.blocked(now) and not before.blocked(now):
        _alert_transition(platform, after, reds, suspended)
    return after


def _alert_transition(platform: str, after: PlatformState, reds: set[int], suspended: set[int]) -> None:
    """Discord, best effort — never let an alert break the rule that fired it."""
    title = f"Plateforme coupee : {platform}" if after.cut else f"Plateforme en pause 48 h : {platform}"
    message = (
        f"{after.reason} · comptes rouges : {len(reds)} · suspendus : {len(suspended)} · "
        + ("post-mortem date exige avant toute reprise" if after.cut else "verifier les comptes, puis `platform resume`")
    )
    log.warning("[collective] %s — %s", title, message)
    try:  # gitd/farm/alerts.py arrives with E2.1; its absence must not matter here
        from gitd.farm import alerts

        alerts.notify("critical", title, message)
    except Exception as e:  # noqa: BLE001
        log.debug("[collective] no Discord alert: %s", e)


# ── Human gestures (R26, R30, R31) ────────────────────────────────────────────


def pause(db: Session, platform: str, hours: int = PAUSE_HOURS, reason: str | None = None) -> PlatformState:
    now = utcnow()
    until = now + timedelta(hours=hours)
    _write(db, platform, paused_until=until, cut=False, reason=reason or "paused by hand", now=now)
    db.commit()
    return state(db, platform)


def cut(db: Session, platform: str, reason: str | None = None) -> PlatformState:
    now = utcnow()
    _write(db, platform, paused_until=None, cut=True, reason=reason or "cut by hand", now=now)
    db.commit()
    return state(db, platform)


def resume(db: Session, platform: str) -> PlatformState:
    """Lift a pause **or** a cut. Always a human gesture (R30, R31)."""
    now = utcnow()
    _write(db, platform, paused_until=None, cut=False, reason=None, now=now)
    db.commit()
    return state(db, platform)


# ── Machine kill-switch: data/farm/STOP (R31) ─────────────────────────────────


def farm_dir() -> Path:
    """``data/farm/`` — overridable with FARM_DATA_DIR (tests, second checkout)."""
    override = os.environ.get("FARM_DATA_DIR")
    if override:
        return Path(override)
    from gitd.config import settings

    return Path(settings.base_dir) / "data" / "farm"


def stop_file() -> Path:
    return farm_dir() / "STOP"


def is_stopped() -> bool:
    """True while the machine kill-switch is on: nothing is enqueued anywhere."""
    return stop_file().exists()


def stop() -> Path:
    path = stop_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"stopped at {datetime.now(UTC).isoformat(timespec='seconds')}\n", encoding="utf-8")
    return path


def start() -> None:
    stop_file().unlink(missing_ok=True)
