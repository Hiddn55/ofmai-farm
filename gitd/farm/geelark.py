"""GeeLark cloud phones: the ADB session that expires, and how to get it back.

A GeeLark phone is reached over ``adb connect <ip>:<port>`` and then
``adb shell glogin <password>``; the password comes from the GeeLark API
(``POST /open/v1/adb/getData``) and **the login expires about ten minutes
after it was made**. Past that point every ``adb shell`` either answers
``error: you should run glogin to login first`` on stdout with exit code 0,
or simply never answers (both seen on ``explorer-us``, 2026-09-19,
docs/social/screens-instagram.md §3). A farm that does not repair the session
believes the app is not installed, the feed unreachable, the account mute.

:func:`install_repair` hands :class:`gitd.bots.common.adb.Device` a repair
hook: on a hang or on the ``glogin`` message it reconnects, logs in again and
replays the command once. The hook is only installed when the environment
names the GeeLark app id and the profile ids; on a farm of real phones nothing
changes.

Environment:

``GEELARK_APP_ID``
    the API application id (the same for every profile).
``GEELARK_API_KEY``
    the API key; on macOS it may instead live in the Keychain under the
    service ``geelark-api-key`` (never in a file of this repo, R9).
``FARM_GEELARK_PROFILE_IDS``
    comma-separated profile ids of the phones this farm drives; the ADB
    ``ip:port`` of each is read from the API and matched to the serial.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
import urllib.request
import uuid
from typing import Callable

log = logging.getLogger(__name__)

API = "https://openapi.geelark.com"
GLOGIN_NEEDED = "run glogin"


def _api_key() -> str:
    key = os.environ.get("GEELARK_API_KEY", "")
    if key:
        return key
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "geelark-api-key", "-w"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def configured() -> bool:
    return bool(os.environ.get("GEELARK_APP_ID") and os.environ.get("FARM_GEELARK_PROFILE_IDS"))


def call(path: str, body: dict, *, app_id: str | None = None, key: str | None = None, opener=None) -> dict:
    """One signed call to the GeeLark API (the signature scheme of their docs)."""
    app_id = app_id or os.environ.get("GEELARK_APP_ID", "")
    key = key or _api_key()
    trace = str(uuid.uuid4())
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex[:6]
    sign = hashlib.sha256(f"{app_id}{trace}{ts}{nonce}{key}".encode()).hexdigest().upper()
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "traceId": trace, "appId": app_id, "ts": ts, "nonce": nonce, "sign": sign,
        },
        method="POST",
    )
    with (opener or urllib.request.urlopen)(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def adb_credentials(profile_ids: list[str], **kw) -> dict[str, str]:
    """``{"ip:port": password}`` for every profile whose phone is up."""
    data = call("/open/v1/adb/getData", {"ids": profile_ids}, **kw)
    out: dict[str, str] = {}
    for item in ((data.get("data") or {}).get("items") or []):
        ip, port, pwd = item.get("ip"), item.get("port"), item.get("pwd")
        if ip and port and pwd:
            out[f"{ip}:{port}"] = pwd
    return out


def relogin(
    serial: str,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    settle_s: float = 15.0,
    **kw,
) -> bool:
    """Reconnect ``serial`` and log in again. True when the login went through.

    The password never reaches a log line or an exception message.
    """
    ids = [s.strip() for s in os.environ.get("FARM_GEELARK_PROFILE_IDS", "").split(",") if s.strip()]
    if not ids:
        return False
    try:
        creds = adb_credentials(ids, **kw)
    except Exception as e:  # noqa: BLE001 — the API being down is not a reason to crash a session
        log.warning("[geelark] adb credentials unavailable: %s", type(e).__name__)
        return False
    pwd = creds.get(serial)
    if not pwd:
        log.warning("[geelark] no ADB password for %s (phone off, or not in FARM_GEELARK_PROFILE_IDS)", serial)
        return False
    try:
        run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=10)
        run(["adb", "connect", serial], capture_output=True, text=True, timeout=15)
        # right after a reconnect the transport reads "offline" for a few
        # seconds: a glogin sent then is lost, and so is the replayed command
        for _ in range(int(settle_s * 2)):
            state = run(["adb", "-s", serial, "get-state"], capture_output=True, text=True, timeout=10)
            if (state.stdout or "").strip() == "device":
                break
            sleep(0.5)
        r = run(["adb", "-s", serial, "shell", "glogin", pwd], capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        log.warning("[geelark] relogin of %s timed out", serial)
        return False
    ok = r.returncode == 0 and GLOGIN_NEEDED not in (r.stdout or "")
    log.info("[geelark] %s session %s", serial, "repaired" if ok else "NOT repaired")
    return ok


def install_repair() -> bool:
    """Give ``Device`` the repair hook when this farm runs on GeeLark phones."""
    from gitd.bots.common.adb import Device

    if not configured():
        return False
    Device.session_repair = staticmethod(relogin)
    return True
