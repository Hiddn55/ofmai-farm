"""Tests for the Device.adb error contract (bots/common/adb.py).

The core guarantee under test: a failed adb call raises ADBError instead of
silently returning "" (the old phantom-success bug that every tool inherited).
The happy path (exit 0) is unchanged — it still returns stripped stdout — and
adb_soft() is the escape hatch for callers that tolerate a nonzero exit.
"""

import shutil
import subprocess

import pytest

from gitd.bots.common.adb import ADBError, ADBResult, Device


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_adb_success_returns_stripped_stdout(monkeypatch):
    """Exit 0 → stripped stdout, contract unchanged from before the fix."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(0, "  hello\n", "")
    )
    assert Device("serial").adb("shell", "echo", "hello") == "hello"


def test_adb_nonzero_raises_adberror(monkeypatch):
    """Nonzero exit → ADBError carrying the exit code and stderr message."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(1, "", "error: device 'x' not found"),
    )
    with pytest.raises(ADBError) as exc:
        Device("x").adb("shell", "echo", "hi")
    assert exc.value.returncode == 1
    assert "not found" in str(exc.value)


def test_adberror_is_runtimeerror(monkeypatch):
    """ADBError must subclass RuntimeError so existing `except Exception` /
    `except RuntimeError` call sites keep degrading gracefully."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(1, "", "boom")
    )
    with pytest.raises(RuntimeError):
        Device("x").adb("shell", "whatever")


def test_adb_missing_binary_raises_adberror(monkeypatch):
    """adb not on PATH → ADBError(127), never a silent empty string."""

    def _raise(*a, **k):
        raise FileNotFoundError("adb")

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(ADBError) as exc:
        Device("x").adb("devices")
    assert exc.value.returncode == 127


def test_adb_timeout_raises_adberror(monkeypatch):
    """A timeout is a hard failure → ADBError, not a swallowed TimeoutExpired."""

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="adb", timeout=1)

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(ADBError):
        Device("x").adb("shell", "sleep", "5", timeout=1)


def test_adb_soft_does_not_raise_on_nonzero(monkeypatch):
    """adb_soft returns the result on a nonzero exit instead of raising."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(1, "out", "err")
    )
    res = Device("x").adb_soft("shell", "cmd", "clipboard", "get-text")
    assert isinstance(res, ADBResult)
    assert res.returncode == 1
    assert res.stdout == "out"
    assert res.stderr == "err"
    assert res.ok is False


def test_adb_soft_ok_property(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(0, "x", "")
    )
    assert Device("x").adb_soft("shell", "true").ok is True


@pytest.mark.skipif(shutil.which("adb") is None, reason="adb not installed")
def test_adb_real_bad_serial_raises():
    """End-to-end: a bogus serial against real adb raises ADBError.

    This is the acceptance test from the task — a failing adb command
    (unknown device) must raise with a meaningful message, not return "".
    """
    with pytest.raises(ADBError):
        Device("no-such-device-serial-xyz").adb("shell", "echo", "hi", timeout=5)


# ── dump_xml never serves a stale tree ───────────────────────────────────────
#
# `uiautomator dump` exits 0 and writes nothing when the screen never settles
# (a playing video, autoplaying thumbnails — verified on TikTok 2026-09-18). It
# prints "ERROR: could not get idle state." to stderr, and the *previous*
# /sdcard/tt.xml is still on the device. Serving that file would hand every
# adapter the last screen as if it were the current one.


def test_dump_xml_returns_no_tree_when_uiautomator_cannot_get_idle_state(monkeypatch):
    calls = []

    def fake_run(argv, *a, **k):
        calls.append(list(argv))
        if any("uiautomator" in a for a in argv):
            return _FakeCompleted(0, "", "ERROR: could not get idle state.\n")
        if any(a == "cat" for a in argv):
            return _FakeCompleted(0, '<hierarchy><node text="STALE"/></hierarchy>', "")
        return _FakeCompleted(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dev = Device("serial")
    monkeypatch.setattr(dev, "dump_portal_json", lambda: None)
    assert dev.dump_xml() == ""
    # the old file is removed before dumping, so it can never be served again
    assert any(any("rm -f /sdcard/tt.xml" in a for a in argv) for argv in calls)  # the stale file is dropped first


def test_dump_xml_serves_a_fresh_tree(monkeypatch):
    def fake_run(argv, *a, **k):
        if any(a == "cat" for a in argv):
            return _FakeCompleted(0, '<hierarchy><node text="LIVE"/></hierarchy>', "")
        return _FakeCompleted(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dev = Device("serial")
    monkeypatch.setattr(dev, "dump_portal_json", lambda: None)
    assert "LIVE" in dev.dump_xml()


def test_dump_xml_returns_no_tree_when_the_file_is_missing(monkeypatch):
    """`cat` of a missing file prints a shell error, never XML."""

    def fake_run(argv, *a, **k):
        if any(a == "cat" for a in argv):
            return _FakeCompleted(0, "cat: /sdcard/tt.xml: No such file or directory", "")
        return _FakeCompleted(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dev = Device("serial")
    monkeypatch.setattr(dev, "dump_portal_json", lambda: None)
    assert dev.dump_xml() == ""


# ── an expired cloud-phone login is repaired and the command replayed ─────────


def _expiring_adb(monkeypatch, *, hang_first: bool):
    """A fake adb whose first call is an expired session (a hang, or the
    "run glogin" answer), healthy once `repaired` is set."""
    from types import SimpleNamespace

    state = {"repaired": False, "calls": []}

    def fake_run(argv, *a, **k):
        state["calls"].append(argv)
        if not state["repaired"]:
            if hang_first:
                raise subprocess.TimeoutExpired(argv, k.get("timeout", 1))
            return SimpleNamespace(returncode=0, stdout="error: you should run glogin to login first\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return state


@pytest.mark.parametrize("hang_first", [True, False])
def test_an_expired_geelark_login_is_repaired_and_the_command_replayed(monkeypatch, hang_first):
    from gitd.bots.common.adb import Device

    state = _expiring_adb(monkeypatch, hang_first=hang_first)
    repaired_serials = []

    def repair(serial, reason):
        repaired_serials.append((serial, reason))
        state["repaired"] = True
        return True

    monkeypatch.setattr(Device, "session_repair", staticmethod(repair))
    assert Device("1.2.3.4:20056").adb("shell", "echo", "ok") == "ok"
    assert repaired_serials == [("1.2.3.4:20056", "hang" if hang_first else "expired")]
    assert len(state["calls"]) == 2  # the failed call, then its replay


def test_without_a_repair_hook_a_hang_is_still_a_hard_failure(monkeypatch):
    from gitd.bots.common.adb import ADBError, Device

    _expiring_adb(monkeypatch, hang_first=True)
    monkeypatch.setattr(Device, "session_repair", None)
    with pytest.raises(ADBError, match="timed out"):
        Device("1.2.3.4:20056").adb("shell", "echo", "ok")


def test_a_failed_repair_does_not_loop(monkeypatch):
    from gitd.bots.common.adb import ADBError, Device

    state = _expiring_adb(monkeypatch, hang_first=True)
    monkeypatch.setattr(Device, "session_repair", staticmethod(lambda serial, reason: False))
    with pytest.raises(ADBError, match="timed out"):
        Device("1.2.3.4:20056").adb("shell", "echo", "ok")
    assert len(state["calls"]) == 1


def test_a_dropped_cloud_transport_is_repaired_too(monkeypatch):
    """"adb: device offline" (exit 1) after the GeeLark link dropped — seen on
    the explorer 2026-09-22 — is repaired and replayed like an expired login."""
    from types import SimpleNamespace

    from gitd.bots.common.adb import Device

    state = {"repaired": False, "calls": 0}

    def fake_run(argv, *a, **k):
        state["calls"] += 1
        if not state["repaired"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="adb: device offline\n")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    reasons = []

    def repair(serial, reason):
        reasons.append(reason)
        state["repaired"] = True
        return True

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Device, "session_repair", staticmethod(repair))
    assert Device("1.2.3.4:20135").adb("shell", "echo", "ok") == "ok"
    assert state["calls"] == 2
    assert reasons == ["offline"]
