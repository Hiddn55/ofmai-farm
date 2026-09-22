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
replays the command once. That repair is reactive and costs 20-150 s in the
middle of a gesture; :class:`KeepAlive` (started by :func:`start_keepalive`)
is the preventive side: a daemon thread that re-runs ``glogin`` on the live
link every ~7 minutes, so a skill run never reaches the expiry. GeeLark
documents no lifetime, no keep-alive and no whitelist for that login
(docs/social/infrastructure-geelark-proxies.md §7 bis). Both are only
installed when the environment names the GeeLark app id and the profile ids;
on a farm of real phones nothing changes.

Environment:

``GEELARK_APP_ID``
    the API application id (the same for every profile).
``GEELARK_API_KEY``
    the API key; on macOS it may instead live in the Keychain under the
    service ``geelark-api-key`` (never in a file of this repo, R9).
``FARM_GEELARK_PROFILE_IDS``
    comma-separated profile ids of the phones this farm drives; the ADB
    ``ip:port`` of each is read from the API and matched to the serial.
``GEELARK_ADB_KEEPALIVE_S``
    seconds between two preventive ``glogin`` (default 420 = 7 min, under
    the ~10 min measured expiry). ``0`` disables the keep-alive.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
import uuid
from typing import Callable

log = logging.getLogger(__name__)

API = "https://openapi.geelark.com"
GLOGIN_NEEDED = "run glogin"
KEEPALIVE_DEFAULT_S = 420.0  # 7 min: under the ~10 min expiry measured on 2026-09-22


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
    """A GeeLark farm: the app id is set, and at least one profile is known —
    from the env list, or learnt by :func:`ensure_online` at run time."""
    return bool(os.environ.get("GEELARK_APP_ID") and (os.environ.get("FARM_GEELARK_PROFILE_IDS") or _known_profile_ids))


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


# profile ids the farm learnt at run time (ensure_online): they join the env list
_known_profile_ids: set[str] = set()


def profile_ids() -> list[str]:
    env = [s.strip() for s in os.environ.get("FARM_GEELARK_PROFILE_IDS", "").split(",") if s.strip()]
    return env + sorted(_known_profile_ids - set(env))


def _redact(text: str | None, pwd: str) -> str:
    """The first 80 chars of what adb answered, the password blanked if it echoed it."""
    text = (text or "").strip()
    return (text.replace(pwd, "***") if pwd else text)[:80]


def relogin(
    serial: str,
    reason: str = "expired",
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    settle_s: float = 20.0,
    **kw,
) -> bool:
    """Log in again on ``serial``. True when the login went through.

    ``reason`` is what the link did (measured on ``explorer-us``, 2026-09-22):

    ``"hang"``
        the login expired and the GeeLark link FROZE — every command hangs,
        ``glogin`` included. Only a disconnect + reconnect revives it.
    ``"expired"``
        the "run glogin" answer: the link is alive, a plain ``glogin`` does.
    ``"offline"``
        "adb: device offline" — the few seconds after a reconnect. Reconnecting
        again would only prolong it: wait, then log in.

    A reconnect on the wrong reason is what turned a 10-minute login into a
    flapping link (152 s of a 159 s session lost). The password never reaches
    a log line or an exception message.
    """
    ids = profile_ids()
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

    def state() -> str:
        r = run(["adb", "-s", serial, "get-state"], capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()

    try:
        if reason == "hang" or state() != "device":
            run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=10)
            run(["adb", "connect", serial], capture_output=True, text=True, timeout=15)
            for _ in range(int(settle_s * 2)):
                if state() == "device":
                    break
                sleep(0.5)
        r = None
        for attempt in range(4):
            r = run(["adb", "-s", serial, "shell", "glogin", pwd], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and GLOGIN_NEEDED not in (r.stdout or ""):
                break
            sleep(2.0)  # "device offline" right after a reconnect clears by itself
    except subprocess.TimeoutExpired:
        log.warning("[geelark] relogin of %s timed out", serial)
        return False
    ok = r is not None and r.returncode == 0 and GLOGIN_NEEDED not in (r.stdout or "")
    # what glogin answered (never the password: it is an argument, not output)
    log.info("[geelark] %s session %s — glogin rc=%s out=%r err=%r", serial, "repaired" if ok else "NOT repaired",
             r.returncode if r else None, _redact(r.stdout, pwd) if r else "", _redact(r.stderr, pwd) if r else "")
    if ok and _active_keepalive is not None:
        _active_keepalive.touch(serial)  # the reactive repair just logged in: the clock restarts here
    return ok


def install_repair() -> bool:
    """Give ``Device`` the repair hook when this farm runs on GeeLark phones."""
    from gitd.bots.common.adb import Device

    if not configured():
        return False
    Device.session_repair = staticmethod(relogin)
    return True


class KeepAlive:
    """Preventive ``glogin`` on live links, so the ~10 min expiry is never hit.

    Every ``interval_s`` (default 7 min) each serial gets a plain
    ``adb -s <serial> shell glogin <pwd>`` — **never** a disconnect: a
    reconnect puts the link offline for a few seconds and is exactly what the
    reactive repair is for. Nothing here changes what :func:`relogin` does;
    when the reactive repair logs in, it calls :meth:`touch` and the clock
    restarts from there.

    ``tick()`` is the whole logic and takes no time source of its own: the
    thread started by :meth:`start` calls it every ``poll_s``; tests call it
    by hand with a fake ``clock`` and a fake ``run``. The password is fetched
    from the API at each refresh (cached when the API is down) and is never
    logged, not even through an exception message.
    """

    def __init__(
        self,
        serials: list[str],
        *,
        interval_s: float = KEEPALIVE_DEFAULT_S,
        poll_s: float = 5.0,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
        credentials: Callable[[list[str]], dict[str, str]] | None = None,
    ):
        self.serials = list(serials)
        self.interval_s = float(interval_s)
        self.poll_s = float(poll_s)
        self._run = run
        self._clock = clock
        self._credentials = credentials or (lambda ids: adb_credentials(ids))
        self._creds: dict[str, str] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.refreshes: dict[str, int] = {s: 0 for s in self.serials}
        self.failures: dict[str, int] = {s: 0 for s in self.serials}

    # ── schedule ─────────────────────────────────────────────────────────

    def due(self, serial: str) -> bool:
        last = self._last.get(serial)
        return last is None or (self._clock() - last) >= self.interval_s

    def touch(self, serial: str) -> None:
        """Someone else just logged ``serial`` in: count from now."""
        with self._lock:
            self._last[serial] = self._clock()

    def tick(self) -> list[str]:
        """Refresh every serial whose login is due. Returns the serials refreshed."""
        done: list[str] = []
        due = [s for s in self.serials if self.due(s)]
        if not due:
            return done
        try:
            self._creds = self._credentials(profile_ids()) or self._creds
        except Exception as e:  # noqa: BLE001 — the API being down is not a reason to stop a session
            log.warning("[geelark] keep-alive: adb credentials unavailable (%s), using the cached ones",
                        type(e).__name__)
        for serial in due:
            if self._refresh(serial):
                done.append(serial)
        return done

    def _refresh(self, serial: str) -> bool:
        pwd = self._creds.get(serial)
        if not pwd:
            log.warning("[geelark] keep-alive: no ADB password for %s (phone off, or not in FARM_GEELARK_PROFILE_IDS)",
                        serial)
            self.touch(serial)  # do not hammer the API every poll; try again next interval
            return False
        try:
            r = self._run(["adb", "-s", serial, "shell", "glogin", pwd], capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            # the link is frozen: that is the reactive repair's job (reason "hang"), not ours
            log.warning("[geelark] keep-alive: glogin on %s timed out — leaving it to the session repair", serial)
            self.failures[serial] = self.failures.get(serial, 0) + 1
            self.touch(serial)
            return False
        ok = r.returncode == 0 and GLOGIN_NEEDED not in (r.stdout or "")
        self.touch(serial)
        if ok:
            self.refreshes[serial] = self.refreshes.get(serial, 0) + 1
            log.info("[geelark] keep-alive: %s login refreshed (#%d)", serial, self.refreshes[serial])
        else:
            self.failures[serial] = self.failures.get(serial, 0) + 1
            log.warning("[geelark] keep-alive: %s glogin rc=%s out=%r err=%r", serial, r.returncode,
                        _redact(r.stdout, pwd), _redact(r.stderr, pwd))
        return ok

    # ── thread ───────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 — a keep-alive must never take the session down
                log.warning("[geelark] keep-alive tick failed: %s", type(e).__name__)
            if self._stop.wait(self.poll_s):
                return

    def start(self) -> "KeepAlive":
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="geelark-keepalive", daemon=True)
            self._thread.start()
        return self

    def stop(self, join_s: float = 5.0) -> None:
        global _active_keepalive
        self._stop.set()
        t, self._thread = self._thread, None
        if t is not None:
            t.join(join_s)
        if _active_keepalive is self:
            _active_keepalive = None

    def __enter__(self) -> "KeepAlive":
        return self.start()

    def __exit__(self, *a) -> None:
        self.stop()


_active_keepalive: KeepAlive | None = None


def start_keepalive(serials: list[str], **kw) -> KeepAlive | None:
    """Start the preventive keep-alive for a skill run. None when this farm is
    not on GeeLark (or ``GEELARK_ADB_KEEPALIVE_S=0``): nothing runs, nothing
    is imported by the tests unless they ask for it."""
    global _active_keepalive
    if not configured():
        return None
    interval = kw.pop("interval_s", None)
    if interval is None:
        try:
            interval = float(os.environ.get("GEELARK_ADB_KEEPALIVE_S", KEEPALIVE_DEFAULT_S))
        except ValueError:
            interval = KEEPALIVE_DEFAULT_S
    if interval <= 0:
        return None
    ka = KeepAlive(serials, interval_s=interval, **kw).start()
    _active_keepalive = ka
    log.info("[geelark] keep-alive started for %s every %.0f s", ", ".join(serials), interval)
    return ka


# ── The phone's lifecycle around a session ────────────────────────────────────
#
# The ledger names a phone by its GeeLark PROFILE (``sierra-us``): that name is
# stable, the ADB ``ip:port`` is not — it changes at every start. A session
# therefore starts the phone, reads today's endpoint, connects and logs in
# before the skill runs, and stops the phone after (a running cloud phone is
# billed by the minute). ``docs/social/infrastructure-geelark-proxies.md`` §5.

_SERIAL = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d+$")
STATUS_STARTED = 0


def is_serial(device: str) -> bool:
    return bool(_SERIAL.match(device or ""))


def profile_by_name(name: str, **kw) -> dict | None:
    """The GeeLark profile whose ``serialName`` is ``name`` (or whose id is), or None."""
    page = 1
    while page <= 10:
        data = call("/open/v1/phone/list", {"page": page, "pageSize": 100}, **kw)
        items = (data.get("data") or {}).get("items") or []
        for it in items:
            if it.get("serialName") == name or str(it.get("id")) == name:
                return it
        if len(items) < 100:
            break
        page += 1
    return None


def ensure_online(
    device: str,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    boot_timeout_s: float = 180.0,
    **kw,
) -> str:
    """``sierra-us`` -> today's ``ip:port``, phone started, ADB on, logged in.

    An ``ip:port`` is returned as is. Raises RuntimeError when the profile is
    unknown or the phone never comes up: a session must not start on a phone
    that is not there.
    """
    if is_serial(device):
        return device
    profile = profile_by_name(device, **kw)
    if not profile:
        raise RuntimeError(f"GeeLark profile {device!r} not found")
    pid = str(profile["id"])
    _known_profile_ids.add(pid)
    if profile.get("status") != STATUS_STARTED:
        call("/open/v1/phone/start", {"ids": [pid]}, **kw)
        log.info("[geelark] %s: phone starting", device)
    call("/open/v1/adb/setStatus", {"ids": [pid], "open": True}, **kw)
    deadline = time.monotonic() + boot_timeout_s
    serial = ""
    while time.monotonic() < deadline:
        creds = adb_credentials([pid], **kw)
        if creds:
            serial = next(iter(creds))
            break
        sleep(10.0)
    if not serial:
        raise RuntimeError(f"GeeLark profile {device!r}: ADB endpoint not up after {boot_timeout_s:.0f}s")
    run(["adb", "connect", serial], capture_output=True, text=True, timeout=15)
    if not relogin(serial, "hang", run=run, sleep=sleep, **kw):
        raise RuntimeError(f"GeeLark profile {device!r}: glogin failed on {serial}")
    log.info("[geelark] %s is %s", device, serial)
    return serial


def stop(device: str, **kw) -> bool:
    """Stop the phone behind a profile name or a learnt serial. True when GeeLark said so."""
    profile = profile_by_name(device, **kw) if not is_serial(device) else None
    pid = str(profile["id"]) if profile else None
    if pid is None and is_serial(device):
        for cand in profile_ids():
            if device in adb_credentials([cand], **kw):
                pid = cand
                break
    if pid is None:
        return False
    data = call("/open/v1/phone/stop", {"ids": [pid]}, **kw)
    ok = data.get("code") == 0
    log.info("[geelark] %s: phone %s", device, "stopped" if ok else "NOT stopped")
    return ok


def stop_after_run() -> bool:
    """Whether a run stops its phone on exit — on by default (a cloud phone is billed by the minute)."""
    return os.environ.get("FARM_GEELARK_STOP_AFTER", "1") != "0"
