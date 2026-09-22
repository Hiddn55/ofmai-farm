"""The farm side of the OFMAI bridge: pull work, push events.

Contract: ``docs/social/bridge-ofmai-farm.md``. Three principles decide every
line here:

* **The farm pulls, OFMAI never pushes.** The Mac mini has no public entrance;
  every HTTP call starts here.
* **Nothing is lost when one side falls.** A publication stays ``queued`` on the
  OFMAI side until it is claimed; every outgoing event is written to
  ``farm_outbox`` *before* it is sent, in the same commit as the ledger row it
  belongs to.
* **Nothing is duplicated.** ``publication_id`` on the way in, ``event_id``
  (uuid4, generated here) on the way out.

One tick (§6):

0. ``data/farm/STOP`` or a blocked platform → nothing for that platform.
1. ``GET /api/farm/accounts`` → refresh ``paused_until``, ``api_mode``,
   ``disclosed``, ``niche`` on ``farm_accounts``.
2. ``GET /api/farm/queue?channel=device`` → claim, download, check the sha256,
   push to the phone, ``staged``.
3. At ``scheduled_at`` ± 20 min → enqueue the ghost job, ``posting``.
4. Read the job result → ``posted`` / ``failed`` / ``needs_human`` + outbox event.
5. Flush ``farm_outbox`` to ``POST /api/farm/events``.
6. Refresh ``farm_comment_cache``.
7. Enqueue the ``metrics_pull`` jobs due at +24 h, +72 h, +168 h.

Secrets (§2): the shared secret is read from ``FARM_BRIDGE_SECRET`` or from the
macOS keychain entry ``ofmai-farm-secret``; the platform address from
``FARM_OFMAI_BASE_URL``. Neither exists on a fresh machine: the bridge then
raises :class:`BridgeNotConfigured`, says exactly what to set, and stops — it
never crashes the daemon and never touches a device.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from gitd.farm import collective, devices, ledger, planner, policy
from gitd.farm.models import FarmAccount, FarmCommentCache, FarmOutbox, FarmPublication, FarmTarget
from gitd.models.base import Base, SessionLocal, engine

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

#: macOS keychain entry holding the shared secret (architecture.md §Secrets).
KEYCHAIN_SECRET_SERVICE = "ofmai-farm-secret"
#: Header OFMAI expects (`lib/social/bridge-auth.ts`).
SECRET_HEADER = "x-farm-secret"

DEFAULT_INTERVAL_S = 300
HTTP_TIMEOUT_S = 30.0
DOWNLOAD_TIMEOUT_S = 180.0

#: Outbox delivery, §7.
MAX_EVENTS_PER_BATCH = 100
#: OFMAI refuses a body over 256 Ko (413): batches are split before that.
MAX_BODY_BYTES = 256 * 1024
BACKOFF_BASE_MINUTES = 1
BACKOFF_MAX_MINUTES = 30
#: A body OFMAI answers with one of these is a bug in the payload, not a blip:
#: the row is parked (``dead = 1``) instead of being retried for ever.
DEAD_STATUSES = (400, 404, 409, 422)
#: 401 = broken secret: alert and stand still rather than hammer the door.
PAUSE_ON_401_MINUTES = 15

#: Platforms OFMAI only ever serves on ``channel=api`` (`lib/social/bridge-queue.ts`
#: ``API_ONLY_PLATFORMS``): asking for their device queue always returns nothing.
#: Their publishing is E8 (`growth-publish-api.js`), their warming stays here.
API_ONLY_PLATFORMS = ("x", "reddit")

#: Publication workflow per queue ``format`` and platform (§6 step 3). The names
#: are the ones the skills register, checked by
#: ``test_every_published_format_names_a_workflow_the_skill_really_has``: a
#: format mapped to a workflow that does not exist would claim the publication,
#: push the media and only then die on the phone.
#: A platform simply absent from its own row has no such gesture at all — TikTok
#: has no story workflow, so a story queued for it is refused (§7
#: ``unsupported_format``) instead of being staged.
WORKFLOW_BY_FORMAT: dict[str, dict[str, str]] = {
    "instagram": {"reel": "post_video", "feed": "post_photo", "story": "post_story"},
    "tiktok": {"tiktok": "post_video", "reel": "post_video"},
}
#: How long a publication job may run before ghost kills it.
PUBLISH_MAX_DURATION_S = 900
#: Staging (download + push) is retried this many ticks before giving up.
MAX_STAGE_ATTEMPTS = 3
#: Metric horizons, in hours after the post, and how far from them a pull counts.
METRIC_HORIZONS = (24, 72, 168)
METRIC_TOLERANCE_HOURS = 2
METRIC_MAX_DURATION_S = 600
#: Below this many unused cached texts, the tick asks OFMAI for more (§6 step 6).
COMMENT_CACHE_LOW_WATER = 5
COMMENT_CACHE_FETCH = 10
#: Every pool kind OFMAI serves: the warming comments, plus the three reply
#: pools the answering passes hand to their workflow (``planner.REPLY_POOLS``,
#: kept as the single source so a renamed pool cannot drift between the two).
COMMENT_KINDS = ("comment", *planner.REPLY_POOLS)
#: Oriented warm-up (§3.7): how many radar accounts one fetch asks for, below
#: how many playable ones the tick asks again, and how long a fresh list lasts.
TARGETS_FETCH = 30
TARGETS_LOW_WATER = 5
TARGETS_REFRESH_HOURS = 24


class BridgeNotConfigured(RuntimeError):
    """The secret or the platform address is missing on this machine."""


class OfmaiError(RuntimeError):
    """A non-2xx answer from OFMAI. ``status`` is None for a transport failure."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def resolve_base_url() -> str:
    """``FARM_OFMAI_BASE_URL`` — the node that carries the farm routes."""
    url = os.environ.get("FARM_OFMAI_BASE_URL", "").strip()
    if not url:
        try:
            from gitd.config import settings

            url = str(getattr(settings, "farm_ofmai_base_url", "") or "").strip()
        except Exception:  # noqa: BLE001 — settings are optional here
            url = ""
    if not url:
        raise BridgeNotConfigured(
            "FARM_OFMAI_BASE_URL is not set — the bridge does not know which OFMAI to call. "
            "Set it in the environment or in .env, e.g. FARM_OFMAI_BASE_URL=https://ofmai.ai"
        )
    return url.rstrip("/")


def resolve_secret(*, run: Callable[..., str] | None = None) -> str:
    """The shared secret: environment first, then the macOS keychain.

    Raises :class:`BridgeNotConfigured` with the exact command to run when
    neither exists — which is the case on a machine that has never been set up.
    """
    env = os.environ.get("FARM_BRIDGE_SECRET", "").strip()
    if env:
        return env
    secret = (run or _keychain)(KEYCHAIN_SECRET_SERVICE).strip()
    if secret:
        return secret
    raise BridgeNotConfigured(
        "the bridge secret is missing: FARM_BRIDGE_SECRET is not in the environment and the macOS "
        f"keychain has no {KEYCHAIN_SECRET_SERVICE!r} entry. Store it once with: "
        f'security add-generic-password -s {KEYCHAIN_SECRET_SERVICE} -a ofmai -w "<the value of '
        'FARM_BRIDGE_SECRET on the OFMAI side>"'
    )


def _keychain(service: str) -> str:
    """``security find-generic-password -s <service> -w``; "" when absent."""
    try:
        out = subprocess.run(  # noqa: S603 — fixed binary, fixed arguments
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return out.stdout.decode(errors="replace") if out.returncode == 0 else ""
    except Exception as e:  # noqa: BLE001 — not a Mac, no keychain, timeout…
        log.debug("[bridge] keychain lookup failed: %s", e)
        return ""


# ── HTTP client ───────────────────────────────────────────────────────────────


@dataclass
class OfmaiClient:
    """Everything the farm is allowed to say to OFMAI, and nothing else."""

    base_url: str
    secret: str
    timeout: float = HTTP_TIMEOUT_S
    session: Any = None

    @classmethod
    def from_env(cls) -> OfmaiClient:
        return cls(base_url=resolve_base_url(), secret=resolve_secret())

    def _session(self):
        if self.session is None:
            import requests

            self.session = requests.Session()
        return self.session

    def request(self, method: str, path: str, **kwargs) -> Any:
        headers = {SECRET_HEADER: self.secret, **kwargs.pop("headers", {})}
        url = f"{self.base_url}{path}"
        try:
            response = self._session().request(
                method, url, headers=headers, timeout=kwargs.pop("timeout", self.timeout), **kwargs
            )
        except Exception as e:  # noqa: BLE001 — DNS, TLS, timeout: all "unreachable"
            raise OfmaiError(f"{method} {path}: {e}", None) from e
        if response.status_code >= 400:
            raise OfmaiError(f"{method} {path}: HTTP {response.status_code}", response.status_code)
        return response

    def json(self, method: str, path: str, **kwargs) -> dict:
        response = self.request(method, path, **kwargs)
        try:
            body = response.json()
        except Exception as e:  # noqa: BLE001
            raise OfmaiError(f"{method} {path}: body is not JSON ({e})", response.status_code) from e
        return body if isinstance(body, dict) else {"data": body}

    # §3.1
    def accounts(self) -> list[dict]:
        return list(self.json("GET", "/api/farm/accounts").get("accounts") or [])

    # §3.2
    def queue(self, *, platform: str, handle: str, limit: int = 3, channel: str = "device", device_serial: str = "") -> list[dict]:
        params = {"platform": platform, "handle": handle, "limit": limit, "channel": channel}
        if device_serial:
            params["device_serial"] = device_serial
        return list(self.json("GET", "/api/farm/queue", params=params).get("items") or [])

    # §3.3
    def claim(self, publication_id: str, device_serial: str) -> dict:
        return self.json(
            "POST",
            f"/api/farm/queue/{publication_id}/claim",
            json={"device_serial": device_serial},
        )

    # §3.4
    def comments(self, *, character_id: str, platform: str, kind: str = "comment", n: int = COMMENT_CACHE_FETCH) -> list[dict]:
        params = {"character_id": character_id, "platform": platform, "kind": kind, "n": n}
        return list(self.json("GET", "/api/farm/comments", params=params).get("comments") or [])

    # §3.7
    def targets(self, *, character: str, platform: str, limit: int = TARGETS_FETCH) -> list[dict]:
        params = {"character": character, "platform": platform, "limit": limit}
        return list(self.json("GET", "/api/farm/targets", params=params).get("targets") or [])

    # §4
    def events(self, events: list[dict]) -> dict:
        return self.json("POST", "/api/farm/events", json={"events": events})

    def download(self, url: str, destination: Path) -> str:
        """Stream a media file to ``destination``; returns its sha256."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        try:
            response = self._session().get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            raise OfmaiError(f"download: {e}", None) from e
        if response.status_code >= 400:
            raise OfmaiError(f"download: HTTP {response.status_code}", response.status_code)
        with open(destination, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if not chunk:
                    continue
                digest.update(chunk)
                fh.write(chunk)
        return digest.hexdigest()


# ── ADB, injectable so every test runs without a phone ────────────────────────


class Adb:
    """The four ADB gestures staging needs. Replaced wholesale in tests."""

    def push(self, serial: str, local: Path, remote: str) -> bool:
        out = devices._adb("-s", serial, "push", str(local), remote, timeout=300.0)
        return "error" not in out.lower() and bool(out)

    def media_scan(self, serial: str, remote: str) -> None:
        devices._adb(
            "-s",
            serial,
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d",
            f"file://{remote}",
        )

    def exists(self, serial: str, remote: str) -> bool:
        out = devices._adb("-s", serial, "shell", "ls", remote)
        return bool(out) and "No such file" not in out

    def remove(self, serial: str, remote: str) -> None:
        devices._adb("-s", serial, "shell", "rm", "-f", remote)


# ── Outbox ────────────────────────────────────────────────────────────────────


def media_dir() -> Path:
    return collective.farm_dir() / "media"


def flush_file() -> Path:
    return collective.farm_dir() / "FLUSH"


_flush_event = threading.Event()


def flush_now() -> None:
    """Ask the daemon to empty the outbox now, without waiting for the tick.

    A health signal must reach Discord within the minute (R32). The daemon may
    run in this very process (``threading.Event``) or in another one (the
    ``data/farm/FLUSH`` file, polled every 5 s) — both are set, both are cheap.
    """
    _flush_event.set()
    try:
        path = flush_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(UTC).isoformat(timespec="seconds"), encoding="utf-8")
    except OSError as e:
        log.debug("[bridge] could not write the FLUSH file: %s", e)


def flush_requested() -> bool:
    return _flush_event.is_set() or flush_file().exists()


def clear_flush() -> None:
    _flush_event.clear()
    try:
        flush_file().unlink(missing_ok=True)
    except OSError:
        pass


def init() -> None:
    """Create the bridge tables (same mechanism as the rest of the farm)."""
    # planner.init() brings ledger.init(), farm_planned (metric pulls) and job_queue.
    planner.init()
    collective.init()
    Base.metadata.create_all(
        engine,
        tables=[FarmPublication.__table__, FarmOutbox.__table__, FarmCommentCache.__table__],
    )


def account_local_now(account: FarmAccount) -> datetime:
    """Account-local *aware* datetime — the ``at`` of every outgoing event (§4)."""
    from zoneinfo import ZoneInfo

    try:
        return datetime.now(ZoneInfo(account.timezone))
    except Exception:  # noqa: BLE001 — an unknown zone must not lose the event
        return datetime.now(UTC)


def queue_event(
    db: Session,
    account: FarmAccount | None,
    kind: str,
    payload: dict,
    *,
    commit: bool = True,
    at: datetime | None = None,
) -> str:
    """Write one outgoing event to ``farm_outbox``. Returns its ``event_id``.

    ``commit=False`` leaves the row inside the caller's transaction: that is how
    ``FarmSession.record()`` / ``signal()`` guarantee an event can never exist
    without its ledger row, nor the other way round (§5.2).
    """
    when = at or (account_local_now(account) if account is not None else datetime.now(UTC))
    event_id = uuid.uuid4().hex
    db.add(
        FarmOutbox(
            event_id=event_id,
            account_id=getattr(account, "id", None),
            kind=kind,
            payload_json=json.dumps(payload, default=str),
            created_at=when.isoformat(timespec="seconds"),
            next_try_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    )
    if commit:
        db.commit()
    return event_id


def _envelope(db: Session, row: FarmOutbox) -> dict | None:
    account = db.get(FarmAccount, row.account_id) if row.account_id else None
    if account is None:
        return None
    try:
        payload = json.loads(row.payload_json)
    except json.JSONDecodeError:
        return None
    return {
        "event_id": row.event_id,
        "kind": row.kind,
        "at": row.created_at,
        "platform": account.platform,
        "handle": account.handle,
        "payload": payload,
    }


def _backoff_minutes(attempts: int) -> int:
    return min(BACKOFF_MAX_MINUTES, BACKOFF_BASE_MINUTES * (2 ** max(0, attempts)))


def pending_events(db: Session, now: datetime | None = None, limit: int = MAX_EVENTS_PER_BATCH) -> list[FarmOutbox]:
    now = now or datetime.now(UTC)
    rows = list(
        db.execute(
            select(FarmOutbox)
            .where(FarmOutbox.dead == 0, FarmOutbox.sent_at.is_(None))
            .order_by(FarmOutbox.id)
        ).scalars()
    )
    out = []
    for row in rows:
        due = _parse_utc(row.next_try_at)
        if due is None or due <= now:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def flush_outbox(db: Session, client: OfmaiClient, now: datetime | None = None) -> dict:
    """Send what is due. Returns ``{sent, duplicates, dead, retried, paused_until}``.

    Failure handling is §7, to the letter: 5xx / 429 / 503 / unreachable →
    exponential backoff, never ``dead``; 400 / 404 / 409 / 422 → ``dead = 1``
    and an alert; 401 → alert and a 15-minute pause of the whole loop.
    """
    now = now or datetime.now(UTC)
    result = {"sent": 0, "duplicates": 0, "dead": 0, "retried": 0, "paused_until": None}

    rows = pending_events(db, now)
    if not rows:
        return result

    events, by_id = [], {}
    budget = MAX_BODY_BYTES - 1024  # OFMAI answers 413 over 256 Ko: never get there
    used = 0
    for row in rows:
        envelope = _envelope(db, row)
        if envelope is None:
            # No account, or unreadable payload: nothing OFMAI could do with it.
            row.dead = 1
            row.last_error = "unroutable event (no account or invalid payload)"
            result["dead"] += 1
            continue
        size = len(json.dumps(envelope, default=str).encode())
        if events and used + size > budget:
            break  # the rest goes out in the next batch
        used += size
        events.append(envelope)
        by_id[row.event_id] = row
    if not events:
        db.commit()
        return result

    try:
        answer = client.events(events)
    except OfmaiError as e:
        status = e.status
        if status == 401:
            _alert("error", "Pont OFMAI : secret refuse (401)", str(e))
            pause_until = now + timedelta(minutes=PAUSE_ON_401_MINUTES)
            for row in by_id.values():
                row.attempts += 1
                row.last_error = str(e)
                row.next_try_at = pause_until.isoformat(timespec="seconds")
            db.commit()
            result["paused_until"] = pause_until
            result["retried"] = len(by_id)
            return result
        if status in DEAD_STATUSES:
            for row in by_id.values():
                row.dead = 1
                row.attempts += 1
                row.last_error = str(e)
            db.commit()
            result["dead"] += len(by_id)
            _alert("error", "Pont OFMAI : lot d'evenements refuse", str(e))
            return result
        # 5xx, 429, 503, unreachable: keep them, try again later.
        for row in by_id.values():
            row.attempts += 1
            row.last_error = str(e)
            row.next_try_at = (now + timedelta(minutes=_backoff_minutes(row.attempts))).isoformat(timespec="seconds")
        db.commit()
        result["retried"] = len(by_id)
        return result

    sent_at = now.isoformat(timespec="seconds")
    for event_id in answer.get("accepted") or []:
        row = by_id.pop(event_id, None)
        if row:
            row.sent_at = sent_at
            result["sent"] += 1
    for event_id in answer.get("duplicates") or []:
        row = by_id.pop(event_id, None)
        if row:
            row.sent_at = sent_at
            result["duplicates"] += 1
    for rejection in answer.get("rejected") or []:
        row = by_id.pop(rejection.get("event_id"), None)
        if not row:
            continue
        # A per-event rejection comes back inside a 200 body: it is the
        # equivalent of a 422 and must never be retried for ever.
        row.dead = 1
        row.attempts += 1
        row.last_error = str(rejection.get("error"))
        result["dead"] += 1
    for row in by_id.values():  # answered by neither list: try again later
        row.attempts += 1
        row.next_try_at = (now + timedelta(minutes=_backoff_minutes(row.attempts))).isoformat(timespec="seconds")
        result["retried"] += 1
    db.commit()
    if result["dead"]:
        _alert("error", "Pont OFMAI : evenements refuses", f"{result['dead']} evenement(s) parques (dead=1)")
    return result


def _alert(level: str, title: str, message: str) -> None:
    log.warning("[bridge] %s — %s", title, message)
    try:  # gitd/farm/alerts.py arrives with E2.1
        from gitd.farm import alerts

        alerts.notify(level, title, message)
    except Exception as e:  # noqa: BLE001
        log.debug("[bridge] no Discord alert: %s", e)


# ── Step 1: accounts ──────────────────────────────────────────────────────────


def sync_accounts(db: Session, client: OfmaiClient) -> int:
    """Copy what OFMAI owns onto ``farm_accounts``: pause, api_mode, disclosed, niche.

    Never ``created_on``, ``health`` or ``phase_override``: on those, the local
    ledger is the source of truth (§6 step 1). A ``role = observer`` account is
    never copied — the observer is not in the ledger at all.
    """
    updated = 0
    remote = client.accounts()
    by_ofmai_id = {}
    by_handle = {}
    for row in remote:
        if row.get("role") == "observer":
            continue
        if row.get("id"):
            by_ofmai_id[row["id"]] = row
        by_handle[(row.get("platform"), str(row.get("handle") or "").lstrip("@").lower())] = row

    for account in ledger.list_accounts(db):
        row = by_ofmai_id.get(account.ofmai_account_id or "") or by_handle.get(
            (account.platform, account.handle.lower())
        )
        if not row:
            continue
        account.paused_until = row.get("paused_until") or None
        account.api_mode = 1 if row.get("api_mode") else 0
        account.disclosed = 1 if row.get("disclosed") else 0
        if row.get("niche"):
            account.niche = row["niche"]
        if row.get("id") and not account.ofmai_account_id:
            account.ofmai_account_id = row["id"]
        updated += 1
    db.commit()
    return updated


# ── Steps 2 and 3: claim, stage, publish ──────────────────────────────────────


def workflow_for(platform: str, fmt: str) -> str | None:
    return WORKFLOW_BY_FORMAT.get(platform, {}).get(fmt)


def _extension(item: dict) -> str:
    media = item.get("media") or {}
    content_type = str(media.get("content_type") or "")
    if "/" in content_type:
        subtype = content_type.split("/", 1)[1].split(";")[0]
        return {"quicktime": "mov", "jpeg": "jpg"}.get(subtype, subtype) or "bin"
    return "mp4" if str(media.get("kind")) == "video" else "jpg"


def device_busy(db: Session, account: FarmAccount) -> bool:
    """One media at a time per phone, and never while a post job is running (§6 step 2)."""
    from gitd.models.schedule import JobQueue

    staged = db.execute(
        select(FarmPublication)
        .join(FarmAccount, FarmAccount.id == FarmPublication.account_id)
        .where(
            FarmAccount.device_serial == account.device_serial,
            FarmPublication.status.in_(("staged", "posting")),
        )
    ).first()
    if staged:
        return True
    # A phone being driven right now is busy; a merely pending job is not.
    running = db.execute(
        select(JobQueue).where(
            JobQueue.phone_serial == account.device_serial,
            JobQueue.status == "running",
        )
    ).first()
    return bool(running)


def _publication(db: Session, publication_id: str) -> FarmPublication | None:
    return db.execute(
        select(FarmPublication).where(FarmPublication.publication_id == publication_id)
    ).scalar_one_or_none()


def _row_from_item(account: FarmAccount, item: dict, status: str) -> FarmPublication:
    return FarmPublication(
        publication_id=item["publication_id"],
        account_id=account.id,
        variant_id=item.get("variant_id"),
        asset_id=item.get("asset_id"),
        source_post_id=item.get("source_post_id"),
        channel=item.get("channel") or "device",
        fmt=item.get("format"),
        caption=item.get("caption") or "",
        aigc_label=1 if item.get("aigc_label") else 0,
        sha256=(item.get("media") or {}).get("sha256"),
        scheduled_at=item.get("scheduled_at"),
        status=status,
    )


def pull_queue(db: Session, client: OfmaiClient, account: FarmAccount, adb: Adb | None = None, *, limit: int = 3) -> list[str]:
    """Claim, download, verify and push what is due for one account (§6 step 2)."""
    adb = adb or Adb()
    staged: list[str] = []
    if account.platform in API_ONLY_PLATFORMS:
        return staged
    try:
        items = client.queue(
            platform=account.platform, handle=account.handle, limit=limit, device_serial=account.device_serial
        )
    except OfmaiError as e:
        log.warning("[bridge] queue for @%s: %s", account.handle, e)
        return staged

    for item in items:
        publication_id = item.get("publication_id")
        if not publication_id:
            continue
        row = _publication(db, publication_id)
        if row and row.status not in ("claimed",):
            continue  # already staged, posting, or finished

        # A format this platform cannot post never gets claimed nor pushed (§6 step 3).
        if row is None and not workflow_for(account.platform, str(item.get("format") or "")):
            failed = _row_from_item(account, item, "failed")
            failed.last_error = "unsupported_format"
            db.add(failed)
            queue_event(
                db,
                account,
                "post_failed",
                {
                    "publication_id": publication_id,
                    "error": "unsupported_format",
                    "attempt": 0,
                    "ambiguous": False,
                },
                commit=False,
            )
            db.commit()
            continue

        if device_busy(db, account):
            break  # one media at a time on this phone

        if row is None:
            try:
                claim = client.claim(publication_id, account.device_serial)
            except OfmaiError as e:
                # 409 (someone else holds it) and 410 (no longer queued) are normal.
                log.info("[bridge] claim %s refused: %s", publication_id, e)
                continue
            media = claim.get("media") or item.get("media") or {}
            row = _row_from_item(account, item, "claimed")
            db.add(row)
            db.commit()
        else:
            try:
                media = (client.claim(publication_id, account.device_serial)).get("media") or {}
            except OfmaiError as e:
                log.info("[bridge] re-claim %s refused: %s", publication_id, e)
                continue

        if stage(db, client, account, row, media, adb=adb):
            staged.append(publication_id)
    return staged


def stage(
    db: Session,
    client: OfmaiClient,
    account: FarmAccount,
    row: FarmPublication,
    media: dict,
    *,
    adb: Adb | None = None,
) -> bool:
    """Download to ``data/farm/media/``, check the sha256, push to the phone.

    The gallery workflows take "the most recent item", which is why exactly one
    media is pushed at a time per device (§6 step 2).
    """
    adb = adb or Adb()
    extension = _extension({"media": media})
    local = media_dir() / f"{row.publication_id}.{extension}"
    expected = row.sha256 or media.get("sha256")

    try:
        if local.exists() and expected and _sha256_of(local) == expected:
            digest = expected  # already downloaded on a previous tick (§3.2)
        else:
            digest = client.download(str(media.get("url") or ""), local)
        if expected and digest != expected:
            raise OfmaiError(f"sha256 mismatch for {row.publication_id}")
    except OfmaiError as e:
        local.unlink(missing_ok=True)
        return _stage_failed(db, account, row, f"download: {e}")

    remote = f"/sdcard/DCIM/Camera/{local.name}"
    if not adb.push(account.device_serial, local, remote):
        return _stage_failed(db, account, row, "adb push failed")
    adb.media_scan(account.device_serial, remote)

    row.local_path = str(local)
    row.device_path = remote
    row.status = "staged"
    row.last_error = None
    db.commit()
    return True


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_failed(db: Session, account: FarmAccount, row: FarmPublication, error: str) -> bool:
    row.attempts += 1
    row.last_error = error
    if row.attempts >= MAX_STAGE_ATTEMPTS:
        row.status = "failed"
        queue_event(
            db,
            account,
            "post_failed",
            {"publication_id": row.publication_id, "error": error, "attempt": row.attempts, "ambiguous": False},
            commit=False,
        )
    db.commit()
    log.warning("[bridge] staging %s: %s", row.publication_id, error)
    return False


def due_to_post(row: FarmPublication, now: datetime, timezone: str | None = None) -> bool:
    """``scheduled_at`` ± LATE_TOLERANCE_MINUTES, in the account's own clock."""
    scheduled = _parse_local(row.scheduled_at, timezone)
    if scheduled is None:
        return True  # no schedule: post as soon as it is staged
    tolerance = timedelta(minutes=planner.LATE_TOLERANCE_MINUTES)
    return scheduled - tolerance <= now <= scheduled + tolerance


def _parse_local(value: str | None, timezone: str | None = None) -> datetime | None:
    """Parse an ISO datetime into the account's own wall clock.

    The contract shows ``scheduled_at`` in the account's timezone with an offset
    (§3.2), but OFMAI serves what ``Date.toISOString()`` produces — UTC, ending
    in ``Z``. Reading that as a local time would post a Los Angeles account seven
    hours early, so anything that carries an offset is converted; anything naive
    is already local.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    if timezone:
        from zoneinfo import ZoneInfo

        try:
            return parsed.astimezone(ZoneInfo(timezone)).replace(tzinfo=None)
        except Exception:  # noqa: BLE001 — unknown zone: fall back to UTC
            pass
    return parsed.replace(tzinfo=None)


def publish_staged(db: Session, account: FarmAccount, now: datetime) -> list[int]:
    """Hand every due staged publication to ghost's scheduler (§6 step 3)."""
    from gitd.services.db_helpers import enqueue_job

    enqueued: list[int] = []
    rows = list(
        db.execute(
            select(FarmPublication).where(
                FarmPublication.account_id == account.id, FarmPublication.status == "staged"
            )
        ).scalars()
    )
    for row in rows:
        scheduled = _parse_local(row.scheduled_at, account.timezone)
        if scheduled is not None and now < scheduled - timedelta(minutes=planner.LATE_TOLERANCE_MINUTES):
            continue  # not yet
        if not due_to_post(row, now, account.timezone):
            # Too late to look human: a human decides, we never catch up silently.
            row.status = "failed"
            row.last_error = "late: scheduled window missed"
            queue_event(
                db,
                account,
                "post_failed",
                {
                    "publication_id": row.publication_id,
                    "error": "late: scheduled window missed",
                    "attempt": row.attempts,
                    "ambiguous": False,
                },
                commit=False,
            )
            db.commit()
            continue

        workflow = workflow_for(account.platform, row.fmt or "")
        if not workflow:
            row.status = "failed"
            row.last_error = "unsupported_format"
            db.commit()
            continue

        config = {
            "skill": planner.SKILL_BY_PLATFORM.get(account.platform, ""),
            "workflow": workflow,
            "params": {
                "handle": account.handle,
                "caption": row.caption or "",
                # Copied verbatim from the queue item (§3.2, §7): never the persona
                # sheet, never farm_accounts.disclosed.
                "aigc_label": bool(row.aigc_label),
            },
            "farm_publication": row.publication_id,
        }
        job_id = enqueue_job(
            db,
            phone_serial=account.device_serial,
            job_type="skill_workflow",
            priority=2,
            config_json=json.dumps(config),
            max_duration_s=PUBLISH_MAX_DURATION_S,
            trigger="farm",
        )
        row.job_id = job_id
        row.status = "posting"
        db.commit()
        enqueued.append(job_id)
        log.info("[bridge] @%s %s → job #%s (%s)", account.handle, row.publication_id, job_id, workflow)
    return enqueued


# ── Step 4: results ───────────────────────────────────────────────────────────

_TERMINAL_JOB_STATUSES = ("completed", "failed", "killed", "timeout", "cancelled")


def _job_row(db: Session, job_id: int):
    from gitd.models.schedule import JobQueue, JobRun

    row = db.get(JobQueue, job_id)
    if row is not None:
        return row
    # ghost archives a finished job into job_runs, keeping the same id.
    return db.get(JobRun, job_id)


def _result_data(job_id: int, log_file: str | None) -> dict | None:
    from gitd.services._job_helpers import _parse_job_result_data

    return _parse_job_result_data(job_id, log_path=log_file)


def _flag(data: dict | None, key: str) -> Any:
    """Read ``key`` from the Data dict or from any nested step result."""
    if not isinstance(data, dict):
        return None
    if key in data:
        return data[key]
    nested = data.get("data")
    if isinstance(nested, dict):
        found = _flag(nested, key)
        if found is not None:
            return found
    for step in data.get("step_results") or []:
        if isinstance(step, dict):
            found = _flag(step.get("data") if isinstance(step.get("data"), dict) else step, key)
            if found is not None:
                return found
    return None


def collect_results(db: Session, now: datetime | None = None, *, adb: Adb | None = None) -> dict:
    """Turn finished publication jobs into ``posted`` / ``post_failed`` events (§6 step 4)."""
    adb = adb or Adb()
    tally = {"posted": 0, "failed": 0, "needs_human": 0}
    rows = list(db.execute(select(FarmPublication).where(FarmPublication.status == "posting")).scalars())
    for row in rows:
        if not row.job_id:
            continue
        job = _job_row(db, row.job_id)
        if job is None or (job.status or "") not in _TERMINAL_JOB_STATUSES:
            continue
        account = db.get(FarmAccount, row.account_id)
        if account is None:
            continue

        data = _result_data(row.job_id, getattr(job, "log_file", None))
        success = (job.status or "") == "completed" and bool(_flag(data, "success") is not False)
        if success:
            row.status = "posted"
            row.posted_at = (now or ledger.local_now(account)).isoformat(timespec="seconds")
            row.last_error = None
            queue_event(
                db,
                account,
                "posted",
                {
                    "publication_id": row.publication_id,
                    "variant_id": row.variant_id,
                    "asset_id": row.asset_id,
                    "source_post_id": row.source_post_id,
                    "post_id": _flag(data, "post_id"),
                    "post_url": _flag(data, "post_url"),
                    "channel": row.channel,
                },
                commit=False,
            )
            db.commit()
            tally["posted"] += 1
            _cleanup_media(row, account, adb)
            continue

        ambiguous = _is_ambiguous(data, job.status or "")
        row.attempts += 1
        row.status = "needs_human" if ambiguous else "failed"
        row.last_error = str(_flag(data, "error") or getattr(job, "error_msg", None) or job.status)
        queue_event(
            db,
            account,
            "post_failed",
            {
                "publication_id": row.publication_id,
                "error": row.last_error,
                "attempt": row.attempts,
                "ambiguous": ambiguous,
            },
            commit=False,
        )
        db.commit()
        tally["needs_human" if ambiguous else "failed"] += 1
    return tally


def _is_ambiguous(data: dict | None, job_status: str) -> bool:
    """« Share » was tapped but the postcondition is false → a human decides (§7).

    Never retried automatically: a duplicate post costs more than a missed one,
    and ``session.record(POST)`` has already spent the budget. When the job was
    killed or timed out and left nothing readable behind, we cannot know whether
    the tap went through — so we treat it as ambiguous too, on purpose.
    """
    flag = _flag(data, "ambiguous")
    if isinstance(flag, bool):
        return flag
    if _flag(data, "shared") is True or _flag(data, "share_tapped") is True:
        return True
    return job_status in ("killed", "timeout") and data is None


def _cleanup_media(row: FarmPublication, account: FarmAccount, adb: Adb) -> None:
    if row.device_path:
        adb.remove(account.device_serial, row.device_path)
    if row.local_path:
        Path(row.local_path).unlink(missing_ok=True)


# ── Step 6: comments ──────────────────────────────────────────────────────────


def cached_comments(db: Session, account: FarmAccount, kind: str = "comment") -> list[FarmCommentCache]:
    return list(
        db.execute(
            select(FarmCommentCache).where(
                FarmCommentCache.account_id == account.id,
                FarmCommentCache.kind == kind,
                FarmCommentCache.used_at.is_(None),
            )
        ).scalars()
    )


def comment_kinds_for(account: FarmAccount, now: datetime) -> tuple[str, ...]:
    """Which pools this account can actually spend today.

    Serving a text reserves it for 24 h on the OFMAI side (§3.4), so an account
    whose phase answers nothing — ``COMMENT_REPLY`` is 0 before ``network``,
    ``DM_REPLY`` before ``cruise``, both 0 on a rest day — never holds reply
    texts another account could have used. Warming comments are always fetched:
    every phase but ``consume`` may leave one.
    """
    budget = ledger.budget_for(account, now.date())
    if any(budget.caps.get(action, 0) > 0 for action in (policy.COMMENT_REPLY, policy.DM_REPLY)):
        return COMMENT_KINDS
    return ("comment",)


def refresh_comments(db: Session, client: OfmaiClient, account: FarmAccount, kinds: Iterable[str] = ("comment",)) -> int:
    """Top the local cache up when it falls under five texts (§6 step 6)."""
    if not account.character_id:
        return 0
    added = 0
    for kind in kinds:
        if len(cached_comments(db, account, kind)) >= COMMENT_CACHE_LOW_WATER:
            continue
        try:
            texts = client.comments(
                character_id=account.character_id, platform=account.platform, kind=kind, n=COMMENT_CACHE_FETCH
            )
        except OfmaiError as e:
            log.info("[bridge] comments for @%s (%s): %s", account.handle, kind, e)
            continue
        for text in texts:
            comment_id = text.get("id")
            if not comment_id:
                continue
            exists = db.execute(
                select(FarmCommentCache).where(FarmCommentCache.comment_id == comment_id)
            ).scalar_one_or_none()
            if exists:
                if exists.used_at:
                    # OFMAI only ever serves a text whose `usedAt` is null and
                    # whose 24 h reservation has run out: handing this one back
                    # means the job it was given to never typed it, so the local
                    # row becomes available again instead of being lost for good
                    # (§3.4 — "un texte non consommé redevient disponible").
                    exists.used_at = None
                    added += 1
                continue
            db.add(
                FarmCommentCache(
                    comment_id=comment_id,
                    account_id=account.id,
                    kind=text.get("kind") or kind,
                    text_=text.get("text") or "",
                )
            )
            added += 1
        db.commit()
    return added


# ── Step 6 bis: targets of the oriented warm-up (§3.7) ───────────────────────


def targets_need_refresh(db: Session, account: FarmAccount, now: datetime | None = None) -> bool:
    """True when the account has too few playable radar accounts and OFMAI has
    not been asked within the last ``TARGETS_REFRESH_HOURS``. The list is the
    same every day for a niche, so asking more often only repeats it."""
    now = now or ledger.local_now(account)
    rows = list(
        db.execute(
            select(FarmTarget).where(FarmTarget.account_id == account.id, FarmTarget.source == "radar")
        ).scalars()
    )
    if rows:
        last_seen = max(datetime.fromisoformat(r.last_seen) for r in rows)
        if now - last_seen < timedelta(hours=TARGETS_REFRESH_HOURS):
            return False
    playable = ledger.pick_targets(db, account, TARGETS_LOW_WATER, day=now.date())
    return len([h for h in playable if any(r.handle == h for r in rows)]) < TARGETS_LOW_WATER


def fetch_targets(
    db: Session, client: OfmaiClient, account: FarmAccount, *, limit: int = TARGETS_FETCH, now: datetime | None = None
) -> list[str]:
    """Ask OFMAI for the best radar accounts of the character's niche and
    remember them as ``source = radar`` (``farm_targets``). Returns the handles
    served, known ones included — the memory of what was played stays local.
    An account without a character, or an unreachable OFMAI, gives an empty
    list and the session falls back to the hand-typed ``@handles``."""
    if not account.character_id:
        return []
    try:
        served = client.targets(character=account.character_id, platform=account.platform, limit=limit)
    except OfmaiError as e:
        log.info("[bridge] targets for @%s: %s", account.handle, e)
        return []
    now = now or ledger.local_now(account)
    handles: list[str] = []
    for item in served:
        row = ledger.record_target(db, account, str(item.get("handle") or ""), "radar", now=now, commit=False)
        if row is not None:
            handles.append(row.handle)
    db.commit()
    return handles


# ── Step 7: metric pulls ──────────────────────────────────────────────────────


def _in_session_window(account: FarmAccount, now: datetime) -> bool:
    """True when ``now`` falls inside one of today's planned sessions.

    Reading metrics is a phone gesture like any other: it happens when the
    account would normally be awake — never in QUIET_HOURS, never on a rest day
    (``plan_sessions`` returns nothing then).
    """
    budget = ledger.budget_for(account, now.date())
    for slot in policy.plan_sessions(budget):
        if slot.start <= now <= slot.start + timedelta(minutes=slot.minutes + planner.GRACE_MINUTES):
            return True
    return False


def due_metric_horizons(row: FarmPublication, now: datetime) -> list[int]:
    posted = _parse_local(row.posted_at)
    if posted is None:
        return []
    tolerance = timedelta(hours=METRIC_TOLERANCE_HOURS)
    return [h for h in METRIC_HORIZONS if abs(now - (posted + timedelta(hours=h))) <= tolerance]


def _metrics_already_collected(db: Session, publication_id: str, at_hours: int) -> bool:
    """``farm_post_metrics`` belongs to E10; its absence must not block a pull."""
    from sqlalchemy import text as sql

    try:
        found = db.execute(
            sql("SELECT 1 FROM farm_post_metrics WHERE publication_id = :p AND at_hours = :h LIMIT 1"),
            {"p": publication_id, "h": at_hours},
        ).first()
    except Exception:  # noqa: BLE001 — table not created yet
        db.rollback()
        return False
    return bool(found)


def enqueue_metric_pulls(db: Session, account: FarmAccount, now: datetime) -> list[int]:
    """One ``metrics_pull`` job per (publication, horizon), at most once (§6 step 7)."""
    from gitd.services.db_helpers import enqueue_job

    if account.api_mode:
        return []  # X / Reddit in api_mode: read by publish-api.ts, not by the phone
    if not _in_session_window(account, now):
        return []

    enqueued: list[int] = []
    rows = list(
        db.execute(
            select(FarmPublication).where(
                FarmPublication.account_id == account.id, FarmPublication.status == "posted"
            )
        ).scalars()
    )
    for row in rows:
        for at_hours in due_metric_horizons(row, now):
            key = f"{account.id}:metrics:{row.publication_id}:{at_hours}"
            already = db.execute(
                select(planner.FarmPlanned).where(planner.FarmPlanned.slot_key == key)
            ).scalar_one_or_none()
            if already or _metrics_already_collected(db, row.publication_id, at_hours):
                continue
            config = {
                "skill": planner.SKILL_BY_PLATFORM.get(account.platform, ""),
                "workflow": "metrics_pull",
                "params": {"handle": account.handle, "post_ref": row.publication_id, "at_hours": at_hours},
                "farm_publication": row.publication_id,
            }
            job_id = enqueue_job(
                db,
                phone_serial=account.device_serial,
                job_type="skill_workflow",
                priority=3,
                config_json=json.dumps(config),
                max_duration_s=METRIC_MAX_DURATION_S,
                trigger="farm",
            )
            db.add(planner.FarmPlanned(account_id=account.id, slot_key=key, job_id=job_id))
            db.commit()
            enqueued.append(job_id)
    return enqueued


# ── The tick ──────────────────────────────────────────────────────────────────


@dataclass
class TickReport:
    stopped: bool = False
    accounts: int = 0
    staged: list[str] = field(default_factory=list)
    published: list[int] = field(default_factory=list)
    results: dict = field(default_factory=dict)
    outbox: dict = field(default_factory=dict)
    comments: int = 0
    targets: int = 0
    metrics: list[int] = field(default_factory=list)
    blocked_platforms: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def tick(
    db: Session,
    client: OfmaiClient | None = None,
    *,
    adb: Adb | None = None,
    now_for: Callable[[FarmAccount], datetime] = ledger.local_now,
) -> TickReport:
    """One pass of the bridge. Never raises: a broken tick is a logged tick."""
    report = TickReport()
    adb = adb or Adb()

    # Step 0 — the machine kill-switch wins over everything (R31).
    if collective.is_stopped():
        report.stopped = True
        log.warning("[bridge] data/farm/STOP is present — nothing is enqueued")
        return report

    try:
        client = client or OfmaiClient.from_env()
    except BridgeNotConfigured as e:
        report.error = str(e)
        log.error("[bridge] %s", report.error)
        return report

    try:
        report.accounts = sync_accounts(db, client)  # step 1
    except OfmaiError as e:
        log.warning("[bridge] accounts: %s", e)

    report.results = collect_results(db, adb=adb)  # step 4 (frees the phones)

    for account in ledger.list_accounts(db, enabled_only=True):
        if account.role == "brand" or account.api_mode:
            continue
        if account.platform not in planner.SKILL_BY_PLATFORM:
            continue
        if collective.is_blocked(db, account.platform):
            if account.platform not in report.blocked_platforms:
                report.blocked_platforms.append(account.platform)
            continue
        now = now_for(account)
        if not ledger.health_state(account).can_run(now):
            continue
        if ledger.paused(account, now):
            continue

        report.staged.extend(pull_queue(db, client, account, adb))  # step 2
        report.published.extend(publish_staged(db, account, now))  # step 3
        report.comments += refresh_comments(db, client, account, comment_kinds_for(account, now))  # step 6
        if targets_need_refresh(db, account, now):  # step 6 bis
            report.targets += len(fetch_targets(db, client, account, now=now))
        report.metrics.extend(enqueue_metric_pulls(db, account, now))  # step 7

    report.outbox = flush_outbox(db, client)  # step 5
    clear_flush()
    return report


def run_forever(interval_s: int = DEFAULT_INTERVAL_S, *, flush_poll_s: float = 5.0) -> None:
    """The ``bridge`` daemon: a tick every ``interval_s``, a flush on demand.

    Between two ticks the loop wakes every 5 s to see whether something asked
    for an immediate flush (``flush_now()``, R32) — a health signal must reach
    Discord within the minute, and the 300 s tick is only the safety net.
    """
    init()
    log.info("[bridge] running, tick every %ss", interval_s)
    next_tick = 0.0
    while True:
        db = SessionLocal()
        try:
            if time.monotonic() >= next_tick:
                tick(db)
                next_tick = time.monotonic() + interval_s
            elif flush_requested():
                try:
                    flush_outbox(db, OfmaiClient.from_env())
                except BridgeNotConfigured as e:
                    log.error("[bridge] %s", e)
                clear_flush()
        except Exception:  # noqa: BLE001 — a daemon never dies on one bad tick
            log.exception("[bridge] tick failed")
        finally:
            db.close()
        time.sleep(flush_poll_s)
