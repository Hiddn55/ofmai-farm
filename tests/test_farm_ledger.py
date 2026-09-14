from datetime import date, timedelta

import pytest

from gitd.farm import ledger, policy
from gitd.farm.models import FarmAccount
from gitd.models.base import SessionLocal


@pytest.fixture()
def db():
    ledger.init()
    s = SessionLocal()
    for acc in ledger.list_accounts(s):
        s.delete(acc)
    s.commit()
    yield s
    s.close()


def _add(db, handle="eva_test", platform="instagram", device="dev-1", created=None, tz="America/New_York"):
    return ledger.add_account(
        db,
        platform=platform,
        handle=handle,
        device_serial=device,
        created_on=created or date.today(),
        timezone=tz,
        niche="fitness,ootd",
    )


def test_one_account_per_platform_per_device(db):
    _add(db, "a1", device="dev-1")
    with pytest.raises(ValueError):
        _add(db, "a2", device="dev-1")
    _add(db, "a3", platform="tiktok", device="dev-1")  # other platform is fine
    with pytest.raises(ValueError):
        _add(db, "A1", device="dev-9")  # same handle, case-insensitive


def test_tracker_reads_spent_actions(db):
    acc = _add(db, created=date.today() - timedelta(days=20))
    s = ledger.open_session("instagram", acc.handle, db)
    assert s.tracker.budget.phase == policy.Phase.CRUISE
    for _ in range(30):
        s.record(policy.VIEW)
    s.record(policy.LIKE, "post-1")
    t2 = ledger.tracker_for(db, acc, s.day)
    assert t2.count(policy.VIEW) == 30 and t2.count(policy.LIKE) == 1


def test_signal_puts_account_in_cooldown_and_blocks_next_session(db):
    acc = _add(db, created=date.today() - timedelta(days=10))
    s = ledger.open_session("instagram", acc.handle, db)
    new = s.signal("action_blocked", "Action Blocked")
    assert new.status == policy.Health.COOLDOWN
    with pytest.raises(PermissionError):
        ledger.open_session("instagram", acc.handle, db)
    # while recovering, the budget uses the lower phase
    b = ledger.budget_for(acc)
    assert b.phase == policy.Phase.LIGHT
    # expired cooldown → ok again, override kept
    acc.health_until = (ledger.local_now(acc) - timedelta(hours=1)).isoformat()
    db.commit()
    s2 = ledger.open_session("instagram", acc.handle, db)
    assert s2.account.health == "ok"
    assert s2.tracker.budget.phase == policy.Phase.LIGHT


def test_verification_needs_a_human(db):
    acc = _add(db, "tt", platform="tiktok", device="dev-7", created=date.today() - timedelta(days=5))
    s = ledger.open_session("tiktok", acc.handle, db)
    s.signal("verification", "Verify to continue")
    with pytest.raises(PermissionError, match="human"):
        ledger.open_session("tiktok", acc.handle, db)


def test_unknown_and_disabled_accounts(db):
    with pytest.raises(LookupError):
        ledger.open_session("instagram", "nobody", db)
    acc = _add(db, "off")
    acc.enabled = 0
    db.commit()
    with pytest.raises(PermissionError):
        ledger.open_session("instagram", "off", db)


def test_weekly_post_count(db):
    acc = _add(db, created=date.today() - timedelta(days=12))
    s = ledger.open_session("instagram", acc.handle, db)
    s.record(policy.POST)
    assert ledger.posts_this_week(db, acc, s.day) == 1
    assert isinstance(db.get(FarmAccount, acc.id), FarmAccount)
