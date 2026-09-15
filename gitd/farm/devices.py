"""Device presence and timezone alignment for farm accounts.

A cloud phone is reachable over ADB as ``<host>:<port>``; that serial is the
only link between the phone provider, ghost's ``phones`` table, the farm ledger
and OFMAI (docs/social/infrastructure-geelark-proxies.md §1). Two things must
hold before an account may run:

* the serial answers ``adb devices`` in state ``device``;
* the phone's system timezone equals ``farm_accounts.timezone`` — the whole
  session plan (``plan_sessions``, ``QUIET_HOURS``) is computed in that zone,
  so a mismatch puts an American account's sessions in the middle of her night
  (rule R20).

Everything here takes its ADB access as an injected callable, so the logic is
unit-testable without a phone. The *only* thing that needs a real device is the
value the callable returns.

Fail-open on purpose: when ADB cannot be reached at all (no ``adb`` binary,
phone offline, server down) we do **not** claim a mismatch — being offline is a
separate, louder failure that ``devices check`` and ``farm_preflight.sh``
report. We refuse a session only when a timezone was actually read and differs.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Protocol

log = logging.getLogger(__name__)

AdbRunner = Callable[..., str]

# `adb devices` is re-read at most this often (the planner opens many sessions).
_DEVICES_TTL_S = 30.0
# a phone's timezone barely ever changes; re-read it at most this often
_TZ_TTL_S = 300.0

_devices_cache: tuple[float, set[str]] | None = None
_tz_cache: dict[str, tuple[float, str | None]] = {}


class AccountLike(Protocol):
    platform: str
    handle: str
    device_serial: str
    timezone: str


def _adb(*args: str, timeout: float = 10.0) -> str:
    """Run a raw ``adb`` command. Returns "" instead of raising."""
    try:
        out = subprocess.run(  # noqa: S603 — fixed binary, arguments are serials
            ["adb", *args], capture_output=True, timeout=timeout, check=False
        )
        return out.stdout.decode(errors="replace")
    except Exception as e:  # noqa: BLE001 — no adb, no server, timeout…
        log.debug("[devices] adb %s failed: %s", " ".join(args), e)
        return ""


def clear_cache() -> None:
    """Forget what ADB said (tests, and after a reconnect script ran)."""
    global _devices_cache
    _devices_cache = None
    _tz_cache.clear()


def online_serials(*, run: AdbRunner | None = None, use_cache: bool = True) -> set[str]:
    """Serials listed by ``adb devices`` in state ``device``."""
    global _devices_cache
    run = run or _adb
    now = time.monotonic()
    if use_cache and _devices_cache and now - _devices_cache[0] < _DEVICES_TTL_S:
        return _devices_cache[1]
    out = run("devices") or ""
    serials = set()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.add(parts[0])
    if use_cache:
        _devices_cache = (now, serials)
    return serials


def is_online(serial: str, *, run: AdbRunner | None = None, use_cache: bool = True) -> bool:
    return bool(serial) and serial in online_serials(run=run, use_cache=use_cache)


def device_timezone(serial: str, *, run: AdbRunner | None = None, use_cache: bool = True) -> str | None:
    """``persist.sys.timezone`` of the phone, or None when it cannot be read."""
    run = run or _adb
    now = time.monotonic()
    if use_cache:
        hit = _tz_cache.get(serial)
        if hit and now - hit[0] < _TZ_TTL_S:
            return hit[1]
    raw = run("-s", serial, "shell", "getprop", "persist.sys.timezone") or ""
    tz = raw.strip() or None
    if use_cache:
        _tz_cache[serial] = (now, tz)
    return tz


@dataclass(frozen=True)
class DeviceStatus:
    platform: str
    handle: str
    serial: str
    online: bool
    tz_device: str | None
    tz_ledger: str
    aligned: bool

    def as_line(self) -> str:
        state = "online " if self.online else "OFFLINE"
        tz = self.tz_device or "-"
        mark = "ok" if self.aligned else ("?" if self.tz_device is None else "MISMATCH")
        return f"{self.platform:9} @{self.handle:22} {self.serial:22} {state} {tz:20} {self.tz_ledger:20} {mark}"


def check_alignment(account: AccountLike, *, run: AdbRunner | None = None, use_cache: bool = True) -> DeviceStatus:
    """Read the phone and compare it to what the ledger believes (R20)."""
    serial = account.device_serial
    online = is_online(serial, run=run, use_cache=use_cache)
    tz_device = device_timezone(serial, run=run, use_cache=use_cache) if online else None
    return DeviceStatus(
        platform=account.platform,
        handle=account.handle,
        serial=serial,
        online=online,
        tz_device=tz_device,
        tz_ledger=account.timezone,
        aligned=bool(tz_device) and tz_device == account.timezone,
    )


def checks_disabled() -> bool:
    """Dry runs (``FARM_FAST=1``) and a documented escape hatch never touch ADB."""
    return os.environ.get("FARM_FAST") == "1" or os.environ.get("FARM_SKIP_TZ_CHECK") == "1"


def timezone_mismatch(account: AccountLike, *, run: AdbRunner | None = None, use_cache: bool = True) -> str | None:
    """A human-readable reason when the phone's zone contradicts the ledger.

    None when they agree **or** when the phone could not be read: an offline
    phone is reported by ``devices check``, not by refusing every session.
    """
    if checks_disabled():
        return None
    st = check_alignment(account, run=run, use_cache=use_cache)
    if st.tz_device is None or st.aligned:
        return None
    return f"{st.serial} is on {st.tz_device}, ledger says {st.tz_ledger}"
