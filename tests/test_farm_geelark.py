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


def test_relogin_reconnects_and_logs_in_without_leaking_the_password(monkeypatch, caplog):
    monkeypatch.setenv("FARM_GEELARK_PROFILE_IDS", "1")
    open_, _ = _opener({"code": 0, "data": {"items": [{"id": "1", "ip": "1.2.3.4", "port": 20056, "pwd": "s3cret"}]}})
    calls = []
    states = iter(["offline", "offline", "device"])  # the transport settles after a reconnect

    def fake_run(argv, **k):
        calls.append(argv)
        if argv[-1] == "get-state":
            return subprocess.CompletedProcess(argv, 0, next(states) + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    with caplog.at_level("INFO"):
        assert geelark.relogin("1.2.3.4:20056", run=fake_run, sleep=lambda s: None, app_id="APP", key="KEY", opener=open_) is True
    assert calls[0][:2] == ["adb", "disconnect"]
    assert calls[1][:2] == ["adb", "connect"]
    assert [c[-1] for c in calls].count("get-state") == 3  # polled until "device"
    assert calls[-1][:5] == ["adb", "-s", "1.2.3.4:20056", "shell", "glogin"]
    assert "s3cret" not in caplog.text


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
