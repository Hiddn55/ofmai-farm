import json
from datetime import date, datetime, timedelta

from sqlalchemy import select

from gitd.farm import ledger, planner, policy
from gitd.models.base import SessionLocal
from gitd.models.schedule import JobQueue


def _fresh_db():
    planner.init()
    db = SessionLocal()
    for a in ledger.list_accounts(db):
        db.delete(a)
    for p in db.execute(select(planner.FarmPlanned)).scalars():
        db.delete(p)
    for j in db.execute(select(JobQueue).where(JobQueue.trigger == "farm")).scalars():
        db.delete(j)
    db.commit()
    return db


def test_tick_enqueues_due_slot_once():
    db = _fresh_db()
    acc = ledger.add_account(db, platform="tiktok", handle="plan_me", device_serial="dev-plan", created_on=date.today() - timedelta(days=15))
    day = ledger.local_today(acc)
    slots = policy.plan_sessions(ledger.budget_for(acc, day))
    if not slots:  # rest day for this (account, date): pick tomorrow's plan instead
        day = day + timedelta(days=1)
        slots = policy.plan_sessions(ledger.budget_for(acc, day))
    assert slots
    fake_now = slots[0].start + timedelta(minutes=1)

    ids = planner.tick(db, now_for=lambda _acc: fake_now)
    assert len(ids) == 1
    job = db.get(JobQueue, ids[0])
    assert job.phone_serial == "dev-plan" and job.job_type == "skill_workflow" and job.trigger == "farm"
    cfg = json.loads(job.config_json)
    assert cfg["skill"] == "ofmai_tiktok" and cfg["params"]["handle"] == "plan_me"
    assert job.max_duration_s == (slots[0].minutes + planner.GRACE_MINUTES) * 60

    # same minute again: nothing new
    assert planner.tick(db, now_for=lambda _acc: fake_now) == []
    # too late: skipped
    late = slots[0].start + timedelta(minutes=planner.LATE_TOLERANCE_MINUTES + 5)
    assert planner.tick(db, now_for=lambda _acc: late) == []


def test_tick_skips_unhealthy_and_api_mode_accounts():
    db = _fresh_db()
    acc = ledger.add_account(db, platform="instagram", handle="sick", device_serial="dev-sick", created_on=date.today() - timedelta(days=15))
    acc.health = policy.Health.VERIFICATION.value
    db.commit()
    slots = policy.plan_sessions(ledger.budget_for(acc, date.today() + timedelta(days=1)))
    when = (slots[0].start if slots else datetime.now()) + timedelta(minutes=1)
    assert planner.tick(db, now_for=lambda _a: when) == []
    acc.health = "ok"
    acc.api_mode = 1
    db.commit()
    assert planner.tick(db, now_for=lambda _a: when) == []
