"""Device presence and timezone alignment (R20), with ADB injected as a function.

Nothing here talks to a phone: the only thing a real device adds is the *value*
`adb` returns. What cannot be tested without hardware is whether the cloud phone
really exposes ADB over TCP and keeps its `glogin` shell authenticated after a
drop — that is what `scripts/farm_adb_connect.sh` exists for.
"""

from dataclasses import dataclass
from datetime import date

import pytest

from gitd.farm import devices, ledger


@dataclass
class FakeAccount:
    platform: str = "instagram"
    handle: str = "sierra"
    device_serial: str = "10.0.0.4:20899"
    timezone: str = "America/Los_Angeles"


def fake_adb(devices_out="", tz_by_serial=None, calls=None):
    """An `adb` stand-in: answers `devices` and `getprop persist.sys.timezone`."""
    tz_by_serial = tz_by_serial or {}

    def run(*args, timeout=10.0):
        if calls is not None:
            calls.append(args)
        if args and args[0] == "devices":
            return devices_out
        if len(args) >= 5 and args[0] == "-s" and args[2:5] == ("shell", "getprop", "persist.sys.timezone"):
            return tz_by_serial.get(args[1], "")
        return ""

    return run


DEVICES_OUT = """List of devices attached
10.0.0.4:20899	device
10.0.0.9:20904	offline
R58N1234	device
"""


@pytest.fixture(autouse=True)
def _clean_cache():
    devices.clear_cache()
    yield
    devices.clear_cache()


# ── what adb sees ─────────────────────────────────────────────────────────────


def test_online_serials_keeps_only_the_device_state():
    run = fake_adb(DEVICES_OUT)
    assert devices.online_serials(run=run, use_cache=False) == {"10.0.0.4:20899", "R58N1234"}


def test_is_online():
    run = fake_adb(DEVICES_OUT)
    assert devices.is_online("10.0.0.4:20899", run=run, use_cache=False)
    assert not devices.is_online("10.0.0.9:20904", run=run, use_cache=False)  # offline
    assert not devices.is_online("nope", run=run, use_cache=False)
    assert not devices.is_online("", run=run, use_cache=False)


def test_no_adb_at_all_is_not_a_crash(monkeypatch):
    """A Mac without `adb`, or with a dead server, must not break a session."""

    def boom(*args, **kwargs):
        raise FileNotFoundError("adb")

    monkeypatch.setattr(devices.subprocess, "run", boom)
    assert devices._adb("devices") == ""
    assert devices.online_serials(use_cache=False) == set()
    assert devices.device_timezone("whatever", use_cache=False) is None
    assert devices.timezone_mismatch(FakeAccount(), use_cache=False) is None


def test_device_timezone_reads_the_system_property():
    run = fake_adb(DEVICES_OUT, {"10.0.0.4:20899": "America/Los_Angeles\n"})
    assert devices.device_timezone("10.0.0.4:20899", run=run, use_cache=False) == "America/Los_Angeles"
    assert devices.device_timezone("R58N1234", run=run, use_cache=False) is None  # empty answer


def test_the_devices_listing_is_cached_between_calls():
    calls = []
    run = fake_adb(DEVICES_OUT, calls=calls)
    devices.online_serials(run=run)
    devices.online_serials(run=run)
    assert len([c for c in calls if c[0] == "devices"]) == 1


# ── alignment ─────────────────────────────────────────────────────────────────


def test_check_alignment_when_everything_agrees():
    acc = FakeAccount()
    run = fake_adb(DEVICES_OUT, {acc.device_serial: "America/Los_Angeles"})
    st = devices.check_alignment(acc, run=run, use_cache=False)
    assert st.online and st.aligned
    assert st.tz_device == st.tz_ledger == "America/Los_Angeles"
    assert "ok" in st.as_line()


def test_check_alignment_spots_a_phone_that_moved():
    acc = FakeAccount()
    run = fake_adb(DEVICES_OUT, {acc.device_serial: "America/New_York"})
    st = devices.check_alignment(acc, run=run, use_cache=False)
    assert st.online and not st.aligned
    assert "MISMATCH" in st.as_line()


def test_an_offline_phone_is_reported_offline_not_misaligned():
    acc = FakeAccount(device_serial="10.0.0.9:20904")
    run = fake_adb(DEVICES_OUT, {"10.0.0.9:20904": "America/Los_Angeles"})
    st = devices.check_alignment(acc, run=run, use_cache=False)
    assert not st.online
    assert st.tz_device is None and not st.aligned
    assert "OFFLINE" in st.as_line()


# ── the guard the ledger uses ─────────────────────────────────────────────────


def test_timezone_mismatch_only_speaks_when_it_read_a_real_zone():
    acc = FakeAccount()
    agrees = fake_adb(DEVICES_OUT, {acc.device_serial: "America/Los_Angeles"})
    differs = fake_adb(DEVICES_OUT, {acc.device_serial: "Europe/Paris"})
    unreadable = fake_adb(DEVICES_OUT, {})

    assert devices.timezone_mismatch(acc, run=agrees, use_cache=False) is None
    assert "Europe/Paris" in devices.timezone_mismatch(acc, run=differs, use_cache=False)
    # fail open: an unreachable phone is a separate, louder failure
    assert devices.timezone_mismatch(acc, run=unreadable, use_cache=False) is None


def test_dry_runs_never_touch_adb(monkeypatch):
    acc = FakeAccount()
    calls = []
    run = fake_adb(DEVICES_OUT, {acc.device_serial: "Europe/Paris"}, calls=calls)
    monkeypatch.setenv("FARM_FAST", "1")
    assert devices.timezone_mismatch(acc, run=run, use_cache=False) is None
    assert calls == []
    monkeypatch.delenv("FARM_FAST")
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    assert devices.timezone_mismatch(acc, run=run, use_cache=False) is None
    assert calls == []


def test_open_session_refuses_a_phone_in_the_wrong_timezone(monkeypatch):
    ledger.init()
    from gitd.farm.models import FarmAction, FarmSignal
    from gitd.models.base import SessionLocal

    db = SessionLocal()
    for a in ledger.list_accounts(db):
        db.delete(a)
    for table in (FarmAction, FarmSignal):
        db.query(table).delete()
    db.commit()
    acc = ledger.add_account(
        db,
        platform="instagram",
        handle="drifted",
        device_serial="10.0.0.4:20899",
        created_on=date.today(),
        timezone="America/Los_Angeles",
    )

    monkeypatch.setattr(devices, "_adb", fake_adb(DEVICES_OUT, {acc.device_serial: "Europe/Paris"}))
    with pytest.raises(PermissionError, match="timezone mismatch"):
        ledger.open_session("instagram", acc.handle, db)

    # same phone, right zone: the session opens
    devices.clear_cache()
    monkeypatch.setattr(devices, "_adb", fake_adb(DEVICES_OUT, {acc.device_serial: "America/Los_Angeles"}))
    assert ledger.open_session("instagram", acc.handle, db).account.id == acc.id
    db.close()
