"""The GeeLark ADB session repair: credentials from the API, relogin over adb,
and the hook that is only installed when the farm says it runs on GeeLark."""

import io
import json
import subprocess

from gitd.farm import geelark


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload):
    seen = {}

    def open_(req, timeout=0):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode())
        return _Resp(json.dumps(payload).encode())

    return open_, seen


def test_credentials_are_keyed_by_ip_port_and_skip_phones_that_are_off():
    payload = {"code": 0, "data": {"items": [
        {"id": "1", "ip": "1.2.3.4", "port": 20056, "pwd": "abc"},
        {"id": "2", "ip": None, "port": None, "pwd": None},  # phone off
    ]}}
    open_, seen = _opener(payload)
    creds = geelark.adb_credentials(["1", "2"], app_id="APP", key="KEY", opener=open_)
    assert creds == {"1.2.3.4:20056": "abc"}
    assert seen["url"].endswith("/open/v1/adb/getData")
    assert seen["body"] == {"ids": ["1", "2"]}
    assert {"Appid", "Traceid", "Ts", "Nonce", "Sign"} <= set(seen["headers"])


def test_relogin_logs_in_without_reconnecting_a_live_transport(monkeypatch, caplog):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    open_, _ = _opener({"code": 0, "data": {"items": [{"id": "1", "ip": "1.2.3.4", "port": 20056, "pwd": "s3cret"}]}})
    calls = []

    def fake_run(argv, **k):
        calls.append(argv)
        if argv[-1] == "get-state":
            return subprocess.CompletedProcess(argv, 0, "device\n", "")
        return subprocess.CompletedProcess(argv, 0, "glogin success\n", "")

    with caplog.at_level("INFO"):
        assert geelark.relogin("1.2.3.4:20056", run=fake_run, sleep=lambda s: None, app_id="APP", key="KEY", opener=open_) is True
    assert not any(c[1] in ("disconnect", "connect") for c in calls)  # a live link is never bounced
    assert calls[-1][:5] == ["adb", "-s", "1.2.3.4:20056", "shell", "glogin"]
    assert "s3cret" not in caplog.text


def test_relogin_reconnects_a_dead_transport_and_retries_the_login(monkeypatch):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    open_, _ = _opener({"code": 0, "data": {"items": [{"id": "1", "ip": "1.2.3.4", "port": 20056, "pwd": "s3cret"}]}})
    calls = []
    states = iter(["offline", "offline", "device"])
    logins = iter([(1, "", "adb: device offline\n"), (0, "glogin success\n", "")])

    def fake_run(argv, **k):
        calls.append(argv)
        if argv[-1] == "get-state":
            return subprocess.CompletedProcess(argv, 0, next(states) + "\n", "")
        if "glogin" in argv:
            rc, out, err = next(logins)
            return subprocess.CompletedProcess(argv, rc, out, err)
        return subprocess.CompletedProcess(argv, 0, "", "")

    assert geelark.relogin("1.2.3.4:20056", run=fake_run, sleep=lambda s: None, app_id="APP", key="KEY", opener=open_) is True
    assert [c[1] for c in calls if c[1] in ("disconnect", "connect")] == ["disconnect", "connect"]
    assert sum(1 for c in calls if "glogin" in c) == 2  # the first login hit the settling link


def test_relogin_refuses_a_serial_the_api_does_not_know(monkeypatch):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    open_, _ = _opener({"code": 0, "data": {"items": []}})
    assert geelark.relogin("9.9.9.9:1", run=lambda *a, **k: None, app_id="APP", key="KEY", opener=open_) is False


def test_the_hook_is_installed_only_on_a_geelark_farm(monkeypatch):
    from gitd.bots.common.adb import Device

    monkeypatch.setattr(Device, "session_repair", None)
    monkeypatch.delenv("GEELARK_APP_ID", raising=False)
    monkeypatch.delenv("FARM_GEELARK_PROFILE_IDS", raising=False)
    assert geelark.install_repair() is False
    assert Device.session_repair is None
    monkeypatch.setenv("GEELARK_APP_ID", "APP")
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1,2")
    assert geelark.install_repair() is True
    assert Device.session_repair is not None


def test_a_frozen_link_is_reconnected_even_when_adb_still_calls_it_a_device(monkeypatch):
    """reason="hang": the expired login freezes every command; adb's own view
    ("device") is stale, and only a disconnect + reconnect revives the link."""
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    open_, _ = _opener({"code": 0, "data": {"items": [{"id": "1", "ip": "1.2.3.4", "port": 20056, "pwd": "s3cret"}]}})
    calls = []

    def fake_run(argv, **k):
        calls.append(argv)
        if argv[-1] == "get-state":
            return subprocess.CompletedProcess(argv, 0, "device\n", "")
        return subprocess.CompletedProcess(argv, 0, "glogin success\n" if "glogin" in argv else "", "")

    assert geelark.relogin("1.2.3.4:20056", "hang", run=fake_run, sleep=lambda s: None, app_id="APP", key="KEY", opener=open_) is True
    assert [c[1] for c in calls if c[1] in ("disconnect", "connect")] == ["disconnect", "connect"]


# ── preventive keep-alive ────────────────────────────────────────────────


def _keepalive(serial="1.2.3.4:20056", pwd="s3cret", **kw):
    """A KeepAlive on a fake clock and a fake adb; returns (ka, calls, clock)."""
    now = {"t": 0.0}
    calls = []

    def fake_run(argv, **k):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "glogin success\n", "")

    ka = geelark.KeepAlive(
        [serial],
        interval_s=420,
        run=kw.pop("run", fake_run),
        clock=lambda: now["t"],
        credentials=kw.pop("credentials", lambda ids: {serial: pwd}),
        **kw,
    )
    return ka, calls, now


def test_keepalive_refreshes_on_schedule_and_never_bounces_the_link(monkeypatch):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    ka, calls, now = _keepalive()
    assert ka.tick() == ["1.2.3.4:20056"]  # first tick: nobody knows when the last login was
    now["t"] = 300
    assert ka.tick() == []  # 5 min: not yet
    now["t"] = 419
    assert ka.tick() == []
    now["t"] = 420
    assert ka.tick() == ["1.2.3.4:20056"]  # 7 min: refreshed
    now["t"] = 900
    assert ka.tick() == ["1.2.3.4:20056"]
    assert all(c[:5] == ["adb", "-s", "1.2.3.4:20056", "shell", "glogin"] for c in calls)
    assert not any(c[1] in ("disconnect", "connect") for c in calls)  # a live link is never bounced
    assert ka.refreshes["1.2.3.4:20056"] == 3


def test_keepalive_restarts_its_clock_when_the_reactive_repair_logs_in(monkeypatch):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    ka, calls, now = _keepalive()
    ka.tick()
    now["t"] = 400
    ka.touch("1.2.3.4:20056")  # relogin() just did a glogin
    now["t"] = 500
    assert ka.tick() == []  # 100 s since that login: nothing to do
    now["t"] = 820
    assert ka.tick() == ["1.2.3.4:20056"]


def test_relogin_touches_the_active_keepalive(monkeypatch):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    ka, _, now = _keepalive()
    monkeypatch.setattr(geelark, "_active_keepalive", ka)
    ka.tick()
    now["t"] = 400
    open_, _ = _opener({"code": 0, "data": {"items": [{"id": "1", "ip": "1.2.3.4", "port": 20056, "pwd": "s3cret"}]}})

    def fake_run(argv, **k):
        out = "device\n" if argv[-1] == "get-state" else "glogin success\n"
        return subprocess.CompletedProcess(argv, 0, out, "")

    assert geelark.relogin("1.2.3.4:20056", run=fake_run, sleep=lambda s: None, app_id="APP", key="KEY", opener=open_)
    now["t"] = 700
    assert ka.tick() == []  # 300 s since the repair's login
    now["t"] = 820
    assert ka.tick() == ["1.2.3.4:20056"]


def test_keepalive_never_logs_the_password(monkeypatch, caplog):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    calls = []
    answers = iter([
        subprocess.CompletedProcess([], 0, "logged in with s3cret\n", ""),  # glogin echoing the code
        subprocess.CompletedProcess([], 1, "", "bad code s3cret\n"),  # a failure that echoes it
        subprocess.TimeoutExpired(["adb", "shell", "glogin", "s3cret"], 15),  # str() of it holds the argv
    ])

    def fake_run(argv, **k):
        calls.append(argv)
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    ka, _, now = _keepalive(run=fake_run)
    with caplog.at_level("DEBUG"):
        ka.tick()
        now["t"] = 420
        ka.tick()
        now["t"] = 840
        ka.tick()
    assert len(calls) == 3
    assert "s3cret" not in caplog.text
    assert ka.failures["1.2.3.4:20056"] == 2
    assert ka.tick() == []  # a timeout does not trigger a retry on the next poll: that is the repair's job


def test_keepalive_keeps_the_cached_password_when_the_api_is_down(monkeypatch, caplog):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    creds = iter([{"1.2.3.4:20056": "s3cret"}, RuntimeError("api down")])

    def credentials(ids):
        c = next(creds)
        if isinstance(c, Exception):
            raise c
        return c

    ka, calls, now = _keepalive(credentials=credentials)
    ka.tick()
    now["t"] = 420
    with caplog.at_level("WARNING"):
        assert ka.tick() == ["1.2.3.4:20056"]
    assert "credentials unavailable" in caplog.text
    assert "s3cret" not in caplog.text


def test_keepalive_is_a_noop_when_geelark_is_not_configured(monkeypatch):
    import threading

    monkeypatch.delenv("GEELARK_APP_ID", raising=False)
    monkeypatch.delenv("FARM_GEELARK_PROFILE_IDS", raising=False)
    before = threading.active_count()
    assert geelark.start_keepalive(["1.2.3.4:20056"]) is None
    assert threading.active_count() == before
    assert geelark._active_keepalive is None
    # configured but explicitly disabled
    monkeypatch.setenv("GEELARK_APP_ID", "APP")
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    monkeypatch.setenv("GEELARK_ADB_KEEPALIVE_S", "0")
    assert geelark.start_keepalive(["1.2.3.4:20056"]) is None
    assert threading.active_count() == before


def test_keepalive_thread_ticks_and_stops(monkeypatch):
    import threading

    monkeypatch.setenv("GEELARK_APP_ID", "APP")
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    monkeypatch.delenv("GEELARK_ADB_KEEPALIVE_S", raising=False)
    ticked = threading.Event()
    calls = []

    def fake_run(argv, **k):
        calls.append(argv)
        ticked.set()
        return subprocess.CompletedProcess(argv, 0, "glogin success\n", "")

    ka = geelark.start_keepalive(
        ["1.2.3.4:20056"], run=fake_run, poll_s=0.01, credentials=lambda ids: {"1.2.3.4:20056": "s3cret"}
    )
    try:
        assert ka is not None and ka.interval_s == 420
        assert geelark._active_keepalive is ka
        assert ticked.wait(2.0)
    finally:
        ka.stop()
    assert ka._thread is None
    assert geelark._active_keepalive is None
    assert calls and calls[0][:5] == ["adb", "-s", "1.2.3.4:20056", "shell", "glogin"]
    ka.stop()  # idempotent


# ── the phone's lifecycle around a session ────────────────────────────────────


def _lifecycle_fakes(status=2, boots_after=2):
    """A GeeLark API and an adb whose phone comes up after `boots_after` polls."""
    state = {"calls": [], "polls": 0, "started": False, "stopped": False, "adb": []}

    def opener(req, timeout=0):
        path = req.full_url.rsplit("/open/v1", 1)[-1]
        body = json.loads(req.data.decode())
        state["calls"].append((path, body))
        if path == "/phone/list":
            payload = {"code": 0, "data": {"items": [{"id": "637420301105234213", "serialName": "sierra-us", "status": status}]}}
        elif path == "/phone/start":
            state["started"] = True
            payload = {"code": 0, "data": {"successAmount": 1}}
        elif path == "/adb/setStatus":
            payload = {"code": 0}
        elif path == "/adb/getData":
            state["polls"] += 1
            up = state["polls"] >= boots_after
            payload = {"code": 0, "data": {"items": [{"id": "637420301105234213", "ip": "1.2.3.4" if up else None, "port": 20437 if up else None, "pwd": "s3cret" if up else None}]}}
        elif path == "/phone/stop":
            state["stopped"] = True
            payload = {"code": 0}
        else:
            payload = {"code": 1, "msg": "unexpected"}
        return _Resp(json.dumps(payload).encode())

    def run(argv, **k):
        state["adb"].append(argv)
        if argv[-1] == "get-state":
            return subprocess.CompletedProcess(argv, 0, "device\n", "")
        return subprocess.CompletedProcess(argv, 0, "glogin success\n" if "glogin" in argv else "", "")

    return opener, run, state


def test_ensure_online_starts_the_phone_and_returns_todays_serial(monkeypatch):
    monkeypatch.delenv("FARM_GEELARK_PROFILE_IDS", raising=False)
    opener, run, state = _lifecycle_fakes(status=2, boots_after=3)
    serial = geelark.ensure_online("sierra-us", run=run, sleep=lambda s: None, app_id="APP", key="KEY", opener=opener)
    assert serial == "1.2.3.4:20437"
    assert state["started"] and state["polls"] >= 3  # boot polls, then the login re-reads the password
    assert [c[0] for c in state["calls"]][:3] == ["/phone/list", "/phone/start", "/adb/setStatus"]
    assert state["adb"][0][:2] == ["adb", "connect"]
    assert state["adb"][-1][:5] == ["adb", "-s", "1.2.3.4:20437", "shell", "glogin"]
    # the profile learnt here now counts as configured, and relogin can find its password
    assert "637420301105234213" in geelark.profile_ids()


def test_ensure_online_leaves_a_running_phone_alone_and_passes_a_serial_through(monkeypatch):
    opener, run, state = _lifecycle_fakes(status=0, boots_after=1)
    geelark.ensure_online("sierra-us", run=run, sleep=lambda s: None, app_id="APP", key="KEY", opener=opener)
    assert not state["started"]
    assert geelark.ensure_online("9.9.9.9:20000", run=run, opener=opener) == "9.9.9.9:20000"
    assert geelark.is_serial("sierra-us") is False


def test_ensure_online_refuses_an_unknown_profile_or_a_phone_that_never_boots():
    import pytest

    opener, run, _ = _lifecycle_fakes()
    with pytest.raises(RuntimeError, match="not found"):
        geelark.ensure_online("nobody-us", run=run, sleep=lambda s: None, app_id="APP", key="KEY", opener=opener)
    opener2, run2, _ = _lifecycle_fakes(boots_after=10_000)
    with pytest.raises(RuntimeError, match="not up"):
        geelark.ensure_online("sierra-us", run=run2, sleep=lambda s: None, boot_timeout_s=0.0, app_id="APP", key="KEY", opener=opener2)


def test_stop_stops_the_phone_behind_a_profile_name(monkeypatch):
    opener, run, state = _lifecycle_fakes(status=0)
    assert geelark.stop("sierra-us", app_id="APP", key="KEY", opener=opener) is True
    assert state["stopped"]
    monkeypatch.setenv("FARM_GEELARK_STOP_AFTER", "0")
    assert geelark.stop_after_run() is False
    monkeypatch.delenv("FARM_GEELARK_STOP_AFTER")
    assert geelark.stop_after_run() is True
