from datetime import date, timedelta

import pytest

from gitd.farm import ledger, policy
from gitd.farm.models import FarmAccount
from gitd.models.base import SessionLocal


@pytest.fixture()
def db():
    """A clean ledger. SQLite reuses row ids, so the action rows of a deleted
    account would otherwise be inherited by the next one."""
    ledger.init()
    from gitd.farm.models import FarmAction, FarmSignal

    s = SessionLocal()
    for acc in ledger.list_accounts(s):
        s.delete(acc)
    for table in (FarmAction, FarmSignal):
        s.query(table).delete()
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


# ── E1.1: the five platforms, the two roles ───────────────────────────────────


def test_add_x_and_reddit_accounts(db):
    """X and Reddit warm on the device like the other two."""
    x = _add(db, "x_handle", platform="x", device="dev-x")
    rd = _add(db, "rd_handle", platform="reddit", device="dev-rd")
    assert (x.platform, rd.platform) == ("x", "reddit")
    # both follow the Instagram calendar: cruise on day 15, not day 24
    assert ledger.budget_for(x, date.today() + timedelta(days=14)).phase == policy.Phase.CRUISE
    assert ledger.budget_for(rd, date.today() + timedelta(days=14)).phase == policy.Phase.CRUISE
    # the model is ready for telegram (M2) even though no skill answers for it
    assert _add(db, "tg_handle", platform="telegram", device="dev-tg").platform == "telegram"
    # one account per platform per device still holds across the new platforms
    with pytest.raises(ValueError):
        _add(db, "x_other", platform="x", device="dev-x")
    with pytest.raises(ValueError, match="unknown platform"):
        _add(db, "nope", platform="mastodon", device="dev-m")


def test_add_account_rejects_role_observer(db):
    """The observer phone is never warmed and never enters the ledger."""
    with pytest.raises(ValueError, match="unknown role"):
        ledger.add_account(db, platform="instagram", handle="observer-us", device_serial="dev-obs", role="observer")
    assert ledger.get_account(db, "instagram", "observer-us") is None


def test_brand_accounts_are_registered_disabled(db):
    acc = ledger.add_account(db, platform="instagram", handle="ofmai_brand", device_serial="dev-brand", role="brand")
    assert acc.role == "brand"
    assert acc.enabled == 0
    assert acc.handle in [a.handle for a in ledger.list_accounts(db)]
    assert acc.handle not in [a.handle for a in ledger.list_accounts(db, enabled_only=True)]


def test_defaults_for_role_market_and_ofmai_id(db):
    acc = _add(db, "plain")
    assert (acc.role, acc.market, acc.ofmai_account_id) == ("persona", "US", None)
    tagged = ledger.add_account(
        db, platform="tiktok", handle="tagged", device_serial="dev-tag", market="FR", ofmai_account_id="sa_01"
    )
    assert (tagged.market, tagged.ofmai_account_id) == ("FR", "sa_01")


# ── E1.2: additive columns and the platform kill-switch ───────────────────────


def test_additive_columns_idempotent(db):
    """init() runs on an existing database as often as it likes."""
    from sqlalchemy import text as _sql

    from gitd.farm.models import _FARM_ADDITIVE_COLUMNS, ensure_farm_columns

    for _ in range(3):
        ledger.init()
        ensure_farm_columns()
    cols = {r[1] for r in db.execute(_sql("PRAGMA table_info(farm_accounts)")).fetchall()}
    for _table, col, _decl in _FARM_ADDITIVE_COLUMNS:
        assert col in cols
    # and the ledger still works afterwards
    assert ledger.budget_for(_add(db, "after_alter")).day_of_life >= 1


def test_paused_until_blocks_a_session(db):
    acc = _add(db, "paused", created=date.today() - timedelta(days=20))
    acc.paused_until = (ledger.local_now(acc) + timedelta(hours=4)).isoformat()
    db.commit()
    assert ledger.paused(acc, ledger.local_now(acc))
    with pytest.raises(PermissionError, match="paused"):
        ledger.open_session("instagram", acc.handle, db)
    # an expired pause lifts itself
    acc.paused_until = (ledger.local_now(acc) - timedelta(minutes=1)).isoformat()
    db.commit()
    assert not ledger.paused(acc, ledger.local_now(acc))
    assert ledger.open_session("instagram", acc.handle, db).account.id == acc.id
    # garbage never blocks a healthy account
    acc.paused_until = "not-a-date"
    db.commit()
    assert not ledger.paused(acc, ledger.local_now(acc))
