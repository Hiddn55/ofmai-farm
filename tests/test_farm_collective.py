"""Collective health rules S3 / S4 — docs/social/health-canaries.md §4, §8.

Two red accounts within 48 h pause a platform; three suspended ones cut it. No
device, no network: the whole file is SQLite plus datetimes.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from gitd.farm import alerts, collective, ledger, planner, policy
from gitd.farm.models import FarmAccount, FarmAction, FarmSignal
from gitd.models.base import SessionLocal


@pytest.fixture(autouse=True)
def no_discord(monkeypatch):
    """No test ever posts to the real webhook (the keychain holds a live one)."""
    monkeypatch.delenv(alerts.ENV_VAR, raising=False)
    monkeypatch.setattr(alerts, "_settings_webhook", lambda: "")
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "")
    sent: list[tuple] = []
    monkeypatch.setattr(alerts, "notify", lambda level, title, message, **kw: sent.append((level, title, message)))
    return sent


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A farm database with no account and no platform state left over."""
    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    planner.init()
    collective.init()
    session = SessionLocal()
    for account in ledger.list_accounts(session):
        session.delete(account)
    for table in (FarmAction, FarmSignal, collective.FarmPlatform, planner.FarmPlanned):
        session.query(table).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _account(db, platform="instagram", handle="a1", serial="dev-a1"):
    return ledger.add_account(
        db,
        platform=platform,
        handle=handle,
        device_serial=serial,
        created_on=date.today() - timedelta(days=20),
    )


def _signal(db, account, kind, *, hours_ago=0.0):
    at = collective.utcnow() - timedelta(hours=hours_ago)
    db.add(FarmSignal(account_id=account.id, kind=kind, matched=kind, at=at.isoformat(sep=" ", timespec="seconds")))
    db.commit()


# ── S3: two red accounts pause the platform ──────────────────────────────────


def test_second_red_account_pauses_the_platform(db, no_discord):
    first = _account(db, handle="red1", serial="dev-red1")
    second = _account(db, handle="red2", serial="dev-red2")

    _signal(db, first, "action_blocked")
    collective.evaluate(db, "instagram")
    assert not collective.is_blocked(db, "instagram"), "one red account is not enough"

    _signal(db, second, "verification")
    state = collective.evaluate(db, "instagram")

    assert state.paused_until is not None and not state.cut
    assert collective.is_blocked(db, "instagram")
    # 48 h, from now
    assert timedelta(hours=47) < state.paused_until - collective.utcnow() <= timedelta(hours=48)
    # and a human is told, once, on the transition (health-canaries.md §5)
    assert [level for level, _t, _m in no_discord] == ["critical"]


def test_two_signals_from_the_same_account_count_once(db):
    only = _account(db, handle="solo", serial="dev-solo")
    _signal(db, only, "action_blocked")
    _signal(db, only, "verification")

    assert collective.red_accounts(db, "instagram") == {only.id}
    collective.evaluate(db, "instagram")
    assert not collective.is_blocked(db, "instagram")


def test_logged_out_is_never_red(db):
    first = _account(db, handle="out1", serial="dev-out1")
    second = _account(db, handle="out2", serial="dev-out2")
    _signal(db, first, "logged_out")
    _signal(db, second, "logged_out")

    assert collective.red_accounts(db, "instagram") == set()
    collective.evaluate(db, "instagram")
    assert not collective.is_blocked(db, "instagram")


def test_a_signal_older_than_48h_does_not_count(db):
    first = _account(db, handle="old1", serial="dev-old1")
    second = _account(db, handle="old2", serial="dev-old2")
    _signal(db, first, "action_blocked", hours_ago=49)
    _signal(db, second, "action_blocked", hours_ago=1)

    assert collective.red_accounts(db, "instagram") == {second.id}
    collective.evaluate(db, "instagram")
    assert not collective.is_blocked(db, "instagram")


def test_a_red_account_on_another_platform_does_not_count(db):
    instagram = _account(db, handle="ig", serial="dev-ig")
    tiktok = _account(db, platform="tiktok", handle="tt", serial="dev-tt")
    _signal(db, instagram, "action_blocked")
    _signal(db, tiktok, "action_blocked")

    collective.evaluate(db, "instagram")
    collective.evaluate(db, "tiktok")
    assert not collective.is_blocked(db, "instagram")
    assert not collective.is_blocked(db, "tiktok")


def test_an_expired_pause_lifts_itself(db):
    first = _account(db, handle="exp1", serial="dev-exp1")
    second = _account(db, handle="exp2", serial="dev-exp2")
    _signal(db, first, "action_blocked", hours_ago=47.5)
    _signal(db, second, "shadowban", hours_ago=47.5)
    collective.evaluate(db, "instagram")
    assert collective.is_blocked(db, "instagram")

    # 49 h later both signals have aged out and the pause has expired.
    later = collective.utcnow() + timedelta(hours=49)
    state = collective.evaluate(db, "instagram", later)
    assert state.paused_until is None and not state.cut
    assert not collective.is_blocked(db, "instagram", later)


# ── S4: three suspended accounts cut the platform ────────────────────────────


def test_three_suspended_accounts_cut_the_platform(db):
    accounts = [_account(db, handle=f"sus{i}", serial=f"dev-sus{i}") for i in range(3)]
    for account in accounts[:2]:
        _signal(db, account, "suspended")
    collective.evaluate(db, "instagram")
    assert collective.state(db, "instagram").cut is False

    _signal(db, accounts[2], "suspended")
    state = collective.evaluate(db, "instagram")

    assert state.cut is True and state.paused_until is None
    assert collective.is_blocked(db, "instagram")


def test_a_cut_never_lifts_itself(db):
    accounts = [_account(db, handle=f"cut{i}", serial=f"dev-cut{i}") for i in range(3)]
    for account in accounts:
        _signal(db, account, "suspended", hours_ago=47)
    collective.evaluate(db, "instagram")
    assert collective.state(db, "instagram").cut

    # A week later, every signal long gone: still cut.
    later = collective.utcnow() + timedelta(days=7)
    collective.evaluate(db, "instagram", later)
    assert collective.is_blocked(db, "instagram", later)

    # Only a human lifts it (R30).
    collective.resume(db, "instagram")
    assert not collective.is_blocked(db, "instagram", later)


# ── The gestures ─────────────────────────────────────────────────────────────


def test_pause_cut_and_resume_by_hand(db):
    collective.pause(db, "tiktok", hours=48, reason="S3 by hand")
    assert collective.is_blocked(db, "tiktok")

    collective.resume(db, "tiktok")
    assert not collective.is_blocked(db, "tiktok")

    collective.cut(db, "tiktok", reason="3 suspended")
    state = collective.state(db, "tiktok")
    assert state.cut and state.reason == "3 suspended"
    assert collective.is_blocked(db, "tiktok")


def test_stop_file_is_the_machine_kill_switch(db):
    assert not collective.is_stopped()
    path = collective.stop()
    assert path.exists() and collective.is_stopped()
    collective.start()
    assert not collective.is_stopped()


# ── Wiring: a signal evaluates the rules in the same commit ──────────────────


def test_signal_evaluates_the_platform_in_the_same_commit(db, monkeypatch):
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    first = _account(db, handle="live1", serial="dev-live1")
    second = _account(db, handle="live2", serial="dev-live2")
    _signal(db, first, "action_blocked")

    session = ledger.open_session("instagram", "live2", db)
    session.signal("action_blocked", "try again later")

    # The second red account was enough: the platform is paused, without any tick.
    assert collective.is_blocked(db, "instagram")
    # And the ledger row is there too — one commit for both.
    kinds = [s.kind for s in db.execute(select(FarmSignal).where(FarmSignal.account_id == second.id)).scalars()]
    assert kinds == ["action_blocked"]
    assert db.get(FarmAccount, second.id).health == policy.Health.COOLDOWN.value


def test_clear_health_is_audited_and_never_red(db, monkeypatch):
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    account = _account(db, handle="clean", serial="dev-clean")
    _signal(db, account, "verification")
    account.health = policy.Health.VERIFICATION.value
    db.commit()

    ledger.clear_health(db, account, "code SMS entered on the device")

    assert account.health == policy.Health.OK.value
    assert account.phase_override is None
    kinds = [s.kind for s in db.execute(select(FarmSignal).where(FarmSignal.account_id == account.id)).scalars()]
    assert kinds == ["verification", "cleared"]
    # `cleared` is not a red kind: it must not pause anything.
    assert collective.red_accounts(db, "instagram") == {account.id}  # the verification, not the clear
    assert "cleared" not in collective.RED_KINDS


def test_utc_signals_are_compared_in_utc(db):
    """A signal written by SQLite (UTC) is not read against a local clock."""
    account = _account(db, handle="tz", serial="dev-tz")
    _signal(db, account, "action_blocked", hours_ago=47)
    assert collective.red_accounts(db, "instagram") == {account.id}
    assert collective.red_accounts(db, "instagram", collective.utcnow() + timedelta(hours=2)) == set()
    assert isinstance(collective.utcnow(), datetime) and collective.utcnow().tzinfo is None
