"""Farm API — the human's side of the bridge, over SSH or from the dashboard.

``docs/social/bridge-ofmai-farm.md`` §6 and ``docs/social/health-canaries.md`` §7.
Nathan is in Thailand and the Mac mini is in Paris: every gesture the runbooks
ask for must be reachable without a Python shell.

Everything here is behind ``X-Ghost-Admin-Token`` (``GITD_ADMIN_TOKEN``) — the
same guard as ``POST /api/skills/install``. These endpoints are **not** the
OFMAI contract: OFMAI never calls the Mac mini (§1).

    GET  /api/farm/accounts                                  accounts + today's budget
    POST /api/farm/accounts/{platform}/{handle}/clear-health  {"reason": "..."} (R26)
    POST /api/farm/accounts/{platform}/{handle}/api-mode      {"state": "on"|"off"}
    GET  /api/farm/publications?status=needs_human
    POST /api/farm/publications/{publication_id}/retry        failed → staged
    GET  /api/farm/outbox?dead=1
    POST /api/farm/sync                                       one bridge tick, now
    GET  /api/farm/health                                     platforms + red accounts
    POST /api/farm/platform/{platform}/resume                 lift a pause or a cut
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from gitd.farm import bridge, collective, ledger
from gitd.farm.models import FarmOutbox, FarmPublication, FarmSignal
from gitd.services.admin_auth import require_admin_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/farm", tags=["farm"], dependencies=[Depends(require_admin_token)])


def get_db() -> Session:
    from gitd.models.base import SessionLocal

    ledger.init()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _account_or_404(db: Session, platform: str, handle: str):
    account = ledger.get_account(db, platform, handle)
    if not account:
        raise HTTPException(status_code=404, detail=f"unknown account {platform} @{handle.lstrip('@')}")
    return account


@router.get("/accounts", summary="Farm Accounts")
def farm_accounts(db: Session = Depends(get_db)) -> dict:
    out = []
    for account in ledger.list_accounts(db):
        now = ledger.local_now(account)
        budget = ledger.budget_for(account)
        out.append(
            {
                "id": account.id,
                "ofmai_account_id": account.ofmai_account_id,
                "platform": account.platform,
                "handle": account.handle,
                "device_serial": account.device_serial,
                "role": account.role,
                "enabled": bool(account.enabled),
                "api_mode": bool(account.api_mode),
                "disclosed": bool(account.disclosed),
                "day_of_life": budget.day_of_life,
                "natural_phase": budget.phase.value,
                "phase_override": account.phase_override,
                "rest_day": budget.rest_day,
                "health": account.health,
                "health_until": account.health_until,
                "paused_until": account.paused_until,
                "platform_blocked": collective.is_blocked(db, account.platform),
                "can_run": ledger.health_state(account).can_run(now),
            }
        )
    return {"accounts": out}


@router.post("/accounts/{platform}/{handle}/clear-health", summary="Clear Account Health")
def farm_clear_health(platform: str, handle: str, body: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        # R26: the gesture is only valid once a human has looked at the screen,
        # and the audit trail of the return to ok is that sentence.
        raise HTTPException(status_code=400, detail="reason is required")
    account = _account_or_404(db, platform, handle)
    ledger.clear_health(db, account, reason)
    return {"ok": True, "platform": platform, "handle": account.handle, "health": account.health}


@router.post("/accounts/{platform}/{handle}/api-mode", summary="Set Account API Mode")
def farm_api_mode(platform: str, handle: str, body: dict = Body(default={}), db: Session = Depends(get_db)) -> dict:
    state = str((body or {}).get("state") or "").lower()
    if state not in ("on", "off"):
        raise HTTPException(status_code=400, detail="state must be on or off")
    account = _account_or_404(db, platform, handle)
    account.api_mode = 1 if state == "on" else 0
    db.commit()
    # OFMAI owns api_mode: the next bridge tick overwrites this (§6 step 1).
    return {"ok": True, "handle": account.handle, "api_mode": bool(account.api_mode), "authoritative_side": "ofmai"}


@router.get("/publications", summary="Farm Publications")
def farm_publications(status: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    query = select(FarmPublication).order_by(FarmPublication.id.desc()).limit(max(1, min(limit, 500)))
    if status:
        query = query.where(FarmPublication.status == status)
    rows = db.execute(query).scalars()
    return {
        "publications": [
            {
                "publication_id": row.publication_id,
                "account_id": row.account_id,
                "status": row.status,
                "format": row.fmt,
                "channel": row.channel,
                "aigc_label": bool(row.aigc_label),
                "scheduled_at": row.scheduled_at,
                "posted_at": row.posted_at,
                "job_id": row.job_id,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "device_path": row.device_path,
            }
            for row in rows
        ]
    }


@router.post("/publications/{publication_id}/retry", summary="Retry Publication")
def farm_retry(publication_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        select(FarmPublication).where(FarmPublication.publication_id == publication_id)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="unknown publication")
    if row.status != "failed":
        # `needs_human` is never retried from here: a human looks at the profile
        # first, then either this retry or PATCH on the OFMAI side (§7).
        raise HTTPException(status_code=409, detail=f"only a failed publication can be retried (status {row.status})")
    if not row.device_path:
        raise HTTPException(status_code=409, detail="no media staged on the device — let the next tick re-claim it")
    row.status = "staged"
    row.last_error = None
    row.job_id = None
    db.commit()
    return {"ok": True, "publication_id": publication_id, "status": row.status, "attempts": row.attempts}


@router.get("/outbox", summary="Farm Outbox")
def farm_outbox(dead: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    query = (
        select(FarmOutbox)
        .where(FarmOutbox.dead == (1 if dead else 0))
        .order_by(FarmOutbox.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    rows = db.execute(query).scalars()
    return {
        "events": [
            {
                "event_id": row.event_id,
                "kind": row.kind,
                "account_id": row.account_id,
                "created_at": row.created_at,
                "sent_at": row.sent_at,
                "attempts": row.attempts,
                "next_try_at": row.next_try_at,
                "last_error": row.last_error,
                "dead": bool(row.dead),
            }
            for row in rows
        ]
    }


@router.post("/sync", summary="Run One Bridge Tick")
def farm_sync(db: Session = Depends(get_db)) -> dict:
    report = bridge.tick(db)
    return {"ok": report.error is None and not report.stopped, **report.as_dict()}


@router.get("/health", summary="Farm Health")
def farm_health(db: Session = Depends(get_db)) -> dict:
    platforms = []
    seen = set()
    for account in ledger.list_accounts(db):
        seen.add(account.platform)
    for platform in sorted(seen):
        state = collective.state(db, platform)
        platforms.append(
            {
                "platform": platform,
                "paused_until": state.paused_until.isoformat() if state.paused_until else None,
                "cut": state.cut,
                "reason": state.reason,
                "blocked": state.blocked(),
                "red_accounts": len(collective.red_accounts(db, platform)),
                "suspended_accounts": len(collective.suspended_accounts(db, platform)),
            }
        )
    accounts = []
    for account in ledger.list_accounts(db):
        if account.health == "ok" and not account.paused_until:
            continue
        last = db.execute(
            select(FarmSignal).where(FarmSignal.account_id == account.id).order_by(FarmSignal.id.desc()).limit(1)
        ).scalar_one_or_none()
        accounts.append(
            {
                "platform": account.platform,
                "handle": account.handle,
                "device_serial": account.device_serial,
                "health": account.health,
                "health_until": account.health_until,
                "phase_override": account.phase_override,
                "paused_until": account.paused_until,
                "last_signal": {"kind": last.kind, "matched": last.matched, "at": last.at} if last else None,
            }
        )
    return {"platforms": platforms, "accounts": accounts, "stopped": collective.is_stopped()}


@router.post("/platform/{platform}/resume", summary="Resume Platform")
def farm_platform_resume(platform: str, db: Session = Depends(get_db)) -> dict:
    # R30, R31: lifting a pause or a cut is always a human gesture.
    state = collective.resume(db, platform)
    return {"ok": True, "platform": platform, "cut": state.cut, "paused_until": None}
