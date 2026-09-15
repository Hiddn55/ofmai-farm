"""The OFMAI bridge, against a simulated OFMAI (docs/social/bridge-ofmai-farm.md §9).

No phone and no production here: a real HTTP server implementing the contract's
routes runs in a thread, ADB is an injected fake, and the database is the
throwaway SQLite of the test session. What is checked is the contract itself —
claim, staging, the AIGC label carried verbatim, idempotence, the backoff table
of §7 and the immediate flush of R32.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from gitd.farm import alerts, bridge, collective, ledger, planner, policy
from gitd.farm.models import FarmAction, FarmCommentCache, FarmOutbox, FarmPublication, FarmSignal
from gitd.models.base import SessionLocal
from gitd.models.schedule import JobQueue

SECRET = "s3cret-for-tests"
MEDIA = b"a tiny mp4 that is not really an mp4" * 8
MEDIA_SHA = hashlib.sha256(MEDIA).hexdigest()


@pytest.fixture(autouse=True)
def no_discord(monkeypatch):
    """No test ever posts to the real webhook (the keychain holds a live one)."""
    monkeypatch.delenv(alerts.ENV_VAR, raising=False)
    monkeypatch.setattr(alerts, "_settings_webhook", lambda: "")
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "")
    sent: list[tuple] = []
    monkeypatch.setattr(alerts, "notify", lambda level, title, message, **kw: sent.append((level, title, message)))
    return sent


# ── The simulated OFMAI ───────────────────────────────────────────────────────


class FakeOfmai:
    """The `app/api/farm/*` routes, reduced to what the bridge actually calls."""

    def __init__(self):
        self.accounts: list[dict] = []
        self.items: list[dict] = []
        self.comments: list[dict] = []
        self.claims: dict[str, str] = {}
        self.claim_status: dict[str, int] = {}
        self.events: list[dict] = []
        self.event_status: int | None = None
        self.event_body: dict | None = None
        self.calls: list[tuple[str, str]] = []
        self.media = MEDIA

    # helpers for the tests
    def queue_item(self, **overrides) -> dict:
        item = {
            "publication_id": "pub_9f",
            "variant_id": "cv_9f",
            "asset_id": "ca_31",
            "source_post_id": "scraped_1",
            "character_id": "cmf_sierra",
            "platform": "instagram",
            "handle": "sierra.cole",
            "channel": "device",
            "format": "reel",
            "scheduled_at": datetime.now().replace(microsecond=0).isoformat(),
            "caption": "post-run glow",
            "media": {
                "url": f"{self.url}/media/pub_9f.mp4",
                "kind": "video",
                "content_type": "video/mp4",
                "sha256": MEDIA_SHA,
                "bytes": len(MEDIA),
                "duration_s": 9.0,
                "aspect": "9:16",
            },
            "disclosed": True,
            "disclosed_since": None,
            "aigc_label": True,
            "content_type": "sfw",
        }
        item.update(overrides)
        self.items.append(item)
        return item

    def paths(self) -> list[str]:
        return [path for _, path in self.calls]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output clean
        pass

    @property
    def fake(self) -> FakeOfmai:
        return self.server.fake  # type: ignore[attr-defined]

    def _send(self, status: int, body: dict | bytes, content_type="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorised(self) -> bool:
        return self.headers.get("x-farm-secret") == SECRET

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        self.fake.calls.append(("GET", url.path))
        if url.path.startswith("/media/"):
            return self._send(200, self.fake.media, "video/mp4")
        if not self._authorised():
            return self._send(401, {"error": "Unauthorized"})
        params = parse_qs(url.query)
        if url.path == "/api/farm/accounts":
            return self._send(200, {"accounts": self.fake.accounts})
        if url.path == "/api/farm/queue":
            handle = (params.get("handle") or [""])[0]
            items = [i for i in self.fake.items if not handle or i["handle"] == handle]
            limit = int((params.get("limit") or ["3"])[0])
            return self._send(200, {"items": items[:limit]})
        if url.path == "/api/farm/comments":
            kind = (params.get("kind") or ["comment"])[0]
            pool = [c for c in self.fake.comments if (c.get("kind") or "comment") == kind]
            return self._send(200, {"comments": pool})
        return self._send(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        self.fake.calls.append(("POST", url.path))
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not self._authorised():
            return self._send(401, {"error": "Unauthorized"})
        body = json.loads(raw or b"{}")

        if url.path.endswith("/claim"):
            publication_id = url.path.split("/")[-2]
            forced = self.fake.claim_status.get(publication_id)
            if forced:
                return self._send(forced, {"error": "claimed_by_other" if forced == 409 else "not_queued"})
            self.fake.claims[publication_id] = body.get("device_serial", "")
            item = next((i for i in self.fake.items if i["publication_id"] == publication_id), None)
            return self._send(
                200,
                {
                    "ok": True,
                    "claim_expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "media": (item or {}).get("media", {}),
                },
            )

        if url.path == "/api/farm/events":
            events = body.get("events") or []
            if self.fake.event_status:
                return self._send(self.fake.event_status, {"error": "forced"})
            self.fake.events.extend(events)
            if self.fake.event_body is not None:
                return self._send(200, self.fake.event_body)
            return self._send(200, {"accepted": [e["event_id"] for e in events], "duplicates": [], "rejected": []})

        return self._send(404, {"error": "not_found"})


@pytest.fixture()
def ofmai():
    fake = FakeOfmai()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.fake = fake  # type: ignore[attr-defined]
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def client(ofmai):
    return bridge.OfmaiClient(base_url=ofmai.url, secret=SECRET)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    monkeypatch.delenv("FARM_BRIDGE_SECRET", raising=False)
    monkeypatch.delenv("FARM_OFMAI_BASE_URL", raising=False)
    bridge.init()
    session = SessionLocal()
    for account in ledger.list_accounts(session):
        session.delete(account)
    for table in (FarmAction, FarmSignal, FarmPublication, FarmOutbox, FarmCommentCache, collective.FarmPlatform, planner.FarmPlanned):
        session.query(table).delete()
    session.query(JobQueue).filter(JobQueue.trigger == "farm").delete()
    session.commit()
    bridge.clear_flush()
    try:
        yield session
    finally:
        session.close()


class FakeAdb:
    def __init__(self, push_ok=True):
        self.pushed: list[tuple[str, str]] = []
        self.scanned: list[str] = []
        self.removed: list[str] = []
        self.push_ok = push_ok

    def push(self, serial, local, remote):
        self.pushed.append((serial, remote))
        return self.push_ok

    def media_scan(self, serial, remote):
        self.scanned.append(remote)

    def exists(self, serial, remote):
        return True

    def remove(self, serial, remote):
        self.removed.append(remote)


def _account(db, **overrides):
    params = {
        "platform": "instagram",
        "handle": "sierra.cole",
        "device_serial": "R58N1234",
        "created_on": date.today() - timedelta(days=20),
        "character_id": "cmf_sierra",
    }
    params.update(overrides)
    return ledger.add_account(db, **params)


def _outbox(db) -> list[FarmOutbox]:
    return list(db.execute(select(FarmOutbox).order_by(FarmOutbox.id)).scalars())


# ── Configuration: nothing is set on a fresh machine ─────────────────────────


def test_missing_base_url_fails_cleanly(monkeypatch):
    monkeypatch.delenv("FARM_OFMAI_BASE_URL", raising=False)
    monkeypatch.setattr("gitd.config.settings.farm_ofmai_base_url", "", raising=False)
    with pytest.raises(bridge.BridgeNotConfigured) as excinfo:
        bridge.resolve_base_url()
    assert "FARM_OFMAI_BASE_URL" in str(excinfo.value)


def test_missing_secret_says_what_to_do(monkeypatch):
    monkeypatch.delenv("FARM_BRIDGE_SECRET", raising=False)
    with pytest.raises(bridge.BridgeNotConfigured) as excinfo:
        bridge.resolve_secret(run=lambda service: "")
    message = str(excinfo.value)
    assert "ofmai-farm-secret" in message and "security add-generic-password" in message


def test_secret_comes_from_the_keychain_when_the_env_is_empty(monkeypatch):
    monkeypatch.delenv("FARM_BRIDGE_SECRET", raising=False)
    assert bridge.resolve_secret(run=lambda service: "from-keychain\n") == "from-keychain"


def test_env_secret_wins_over_the_keychain(monkeypatch):
    monkeypatch.setenv("FARM_BRIDGE_SECRET", "from-env")
    assert bridge.resolve_secret(run=lambda service: "from-keychain") == "from-env"


def test_an_unconfigured_tick_changes_nothing(db, monkeypatch):
    monkeypatch.delenv("FARM_BRIDGE_SECRET", raising=False)
    monkeypatch.setattr(bridge, "_keychain", lambda service: "")
    account = _account(db)
    report = bridge.tick(db, adb=FakeAdb())
    assert report.error and "FARM_OFMAI_BASE_URL" in report.error
    assert db.execute(select(FarmPublication)).first() is None
    assert account.paused_until is None


# ── Step 0: the kill-switches ────────────────────────────────────────────────


def test_stop_file_stops_the_tick(db, client, ofmai):
    _account(db)
    ofmai.queue_item()
    collective.stop()
    report = bridge.tick(db, client, adb=FakeAdb())
    assert report.stopped is True
    assert ofmai.calls == []
    collective.start()


def test_a_blocked_platform_is_never_served(db, client, ofmai):
    _account(db)
    ofmai.queue_item()
    collective.cut(db, "instagram", reason="S4")
    report = bridge.tick(db, client, adb=FakeAdb())
    assert report.blocked_platforms == ["instagram"]
    assert "/api/farm/queue" not in ofmai.paths()


def test_paused_until_is_respected(db, client, ofmai):
    account = _account(db)
    account.paused_until = (ledger.local_now(account) + timedelta(hours=4)).isoformat()
    db.commit()
    ofmai.queue_item()
    bridge.tick(db, client, adb=FakeAdb())
    assert "/api/farm/queue" not in ofmai.paths()


def test_a_utc_pause_from_ofmai_is_read_in_the_account_clock(db, client, ofmai):
    """OFMAI serves `paused_until` in UTC: a 48 h pause must not last 55 h."""
    account = _account(db, timezone="America/Los_Angeles")
    ofmai.accounts = [
        {
            "id": "sa_01",
            "platform": "instagram",
            "handle": "sierra.cole",
            "role": "persona",
            "api_mode": False,
            "disclosed": False,
            # one hour ago, expressed in UTC — the pause is over
            "paused_until": (datetime.now(bridge.UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        }
    ]
    bridge.sync_accounts(db, client)
    db.refresh(account)
    assert ledger.paused(account, ledger.local_now(account)) is False

    ofmai.accounts[0]["paused_until"] = (
        (datetime.now(bridge.UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    )
    bridge.sync_accounts(db, client)
    db.refresh(account)
    assert ledger.paused(account, ledger.local_now(account)) is True


# ── Step 1: accounts ─────────────────────────────────────────────────────────


def test_sync_copies_what_ofmai_owns_and_ignores_the_observer(db, client, ofmai):
    account = _account(db, ofmai_account_id="sa_01")
    ofmai.accounts = [
        {
            "id": "sa_01",
            "platform": "instagram",
            "handle": "sierra.cole",
            "role": "persona",
            "api_mode": True,
            "disclosed": True,
            "niche": "fitness,ootd",
            "paused_until": "2026-09-20T10:00:00",
        },
        {"id": "sa_obs", "platform": "instagram", "handle": "watcher", "role": "observer", "api_mode": False},
    ]
    assert bridge.sync_accounts(db, client) == 1

    db.refresh(account)
    assert account.api_mode == 1 and account.disclosed == 1
    assert account.niche == "fitness,ootd"
    assert account.paused_until == "2026-09-20T10:00:00"
    assert ledger.get_account(db, "instagram", "watcher") is None


# ── Steps 2 and 3: claim, stage, publish ─────────────────────────────────────


def _stage_one(db, client, ofmai, adb, **item_overrides):
    account = _account(db)
    ofmai.queue_item(**item_overrides)
    staged = bridge.pull_queue(db, client, account, adb)
    return account, staged


def test_a_due_item_is_claimed_downloaded_checked_and_pushed(db, client, ofmai):
    adb = FakeAdb()
    account, staged = _stage_one(db, client, ofmai, adb)

    assert staged == ["pub_9f"]
    assert ofmai.claims["pub_9f"] == "R58N1234"
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "staged"
    assert row.sha256 == MEDIA_SHA
    assert row.device_path == "/sdcard/DCIM/Camera/pub_9f.mp4"
    assert adb.pushed == [("R58N1234", "/sdcard/DCIM/Camera/pub_9f.mp4")]
    assert adb.scanned == ["/sdcard/DCIM/Camera/pub_9f.mp4"]
    # the file really landed on disk, with the right bytes
    assert (bridge.media_dir() / "pub_9f.mp4").read_bytes() == MEDIA


def test_a_corrupt_download_is_never_pushed(db, client, ofmai):
    adb = FakeAdb()
    ofmai.media = b"not the file we asked for"
    account, staged = _stage_one(db, client, ofmai, adb)

    assert staged == []
    assert adb.pushed == []
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "claimed" and "sha256" in (row.last_error or "")


def test_one_media_per_device(db, client, ofmai):
    adb = FakeAdb()
    account = _account(db)
    ofmai.queue_item(publication_id="pub_1")
    ofmai.queue_item(publication_id="pub_2")
    ofmai.items[1]["media"] = dict(ofmai.items[0]["media"], url=f"{ofmai.url}/media/pub_2.mp4")

    staged = bridge.pull_queue(db, client, account, adb, limit=5)

    assert staged == ["pub_1"], "the gallery workflows take the most recent item"
    assert len(adb.pushed) == 1
    assert bridge.device_busy(db, account) is True


def test_a_format_without_a_workflow_is_failed_without_claim_or_push(db, client, ofmai):
    adb = FakeAdb()
    account, staged = _stage_one(db, client, ofmai, adb, format="tweet")

    assert staged == []
    assert ofmai.claims == {} and adb.pushed == []
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "failed" and row.last_error == "unsupported_format"
    event = _outbox(db)[-1]
    assert event.kind == "post_failed"
    assert json.loads(event.payload_json)["error"] == "unsupported_format"


def test_every_published_format_names_a_workflow_the_skill_really_has():
    """A format mapped to a workflow that does not exist dies on the phone."""
    import importlib

    for platform, formats in bridge.WORKFLOW_BY_FORMAT.items():
        skill = importlib.import_module(f"gitd.skills.{planner.SKILL_BY_PLATFORM[platform]}").load()
        names = set(skill.list_workflows())
        for fmt, workflow in formats.items():
            assert workflow in names, f"{platform}/{fmt} → {workflow} is not a workflow of that skill"


def test_a_story_is_published_by_post_story_and_never_spends_a_post(db, client, ofmai):
    """E3.4: OFMAI queues the story, the bridge hands it to the story workflow."""
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(format="story", scheduled_at=now.isoformat())

    assert bridge.pull_queue(db, client, account, adb) == ["pub_9f"]
    jobs = bridge.publish_staged(db, account, now)

    assert len(jobs) == 1
    config = json.loads(db.get(JobQueue, jobs[0]).config_json)
    assert config["skill"] == "ofmai_instagram" and config["workflow"] == "post_story"
    assert config["farm_publication"] == "pub_9f"
    # the cap is the ledger's: the story workflow spends STORY_POST, not POST
    assert policy.STORY_POST in policy.ACTIONS
    budget = ledger.budget_for(account)
    assert budget.caps[policy.STORY_POST] <= 1
    # …and the planner has nothing to do with it
    assert planner.due_reply_passes(account, now) == [] or all(
        p.workflow != "post_story" for p, _ in planner.due_reply_passes(account, now)
    )


def test_a_platform_without_stories_never_receives_one(db, client, ofmai):
    """TikTok has no story workflow: refused before the claim and the push."""
    adb = FakeAdb()
    account = _account(db, platform="tiktok", handle="sierra.tiktok", device_serial="R58N7777")
    ofmai.queue_item(platform="tiktok", handle="sierra.tiktok", format="story")

    assert bridge.pull_queue(db, client, account, adb) == []
    assert ofmai.claims == {} and adb.pushed == []
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "failed" and row.last_error == "unsupported_format"
    assert bridge.workflow_for("tiktok", "story") is None
    for platform in bridge.API_ONLY_PLATFORMS:
        assert bridge.WORKFLOW_BY_FORMAT.get(platform) is None


def test_workflow_is_chosen_by_format():
    assert bridge.workflow_for("instagram", "reel") == "post_video"
    assert bridge.workflow_for("instagram", "feed") == "post_photo"
    assert bridge.workflow_for("instagram", "story") == "post_story"
    assert bridge.workflow_for("tiktok", "tiktok") == "post_video"
    assert bridge.workflow_for("instagram", "tweet") is None
    assert bridge.workflow_for("tiktok", "story") is None


@pytest.mark.parametrize("aigc_label", [True, False])
def test_params_aigc_label_comes_from_the_queue_item(db, client, ofmai, aigc_label):
    adb = FakeAdb()
    account = _account(db)
    # The account says the character is disclosed; the queue item says otherwise.
    account.disclosed = 1
    db.commit()
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(aigc_label=aigc_label, disclosed=True, scheduled_at=now.isoformat())

    bridge.pull_queue(db, client, account, adb)
    jobs = bridge.publish_staged(db, account, now)

    assert len(jobs) == 1
    config = json.loads(db.get(JobQueue, jobs[0]).config_json)
    assert config["params"]["aigc_label"] is aigc_label, "frozen on the queue item, never re-read"
    assert config["skill"] == "ofmai_instagram" and config["workflow"] == "post_video"
    assert config["farm_publication"] == "pub_9f"
    assert config["params"]["caption"] == "post-run glow"
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "posting" and row.job_id == jobs[0]


def test_a_utc_schedule_is_read_in_the_account_clock(db, client, ofmai):
    """OFMAI serves `scheduled_at` as `Date.toISOString()` — UTC, not local (§3.2)."""
    adb = FakeAdb()
    account = _account(db, timezone="America/Los_Angeles")
    local_now = ledger.local_now(account).replace(microsecond=0)
    utc_now = datetime.now(bridge.UTC).replace(microsecond=0)
    ofmai.queue_item(scheduled_at=utc_now.isoformat().replace("+00:00", "Z"))

    bridge.pull_queue(db, client, account, adb)
    jobs = bridge.publish_staged(db, account, local_now)

    assert len(jobs) == 1, "the same instant, read in the account's clock, is due now"
    # ... and seven hours later in that clock it is far too late.
    row = db.execute(select(FarmPublication)).scalar_one()
    assert bridge.due_to_post(row, local_now, account.timezone) is True
    assert bridge.due_to_post(row, local_now + timedelta(hours=3), account.timezone) is False


def test_a_publication_is_not_enqueued_before_its_time(db, client, ofmai):
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(scheduled_at=(now + timedelta(hours=2)).isoformat())

    bridge.pull_queue(db, client, account, adb)
    assert bridge.publish_staged(db, account, now) == []
    assert db.execute(select(FarmPublication)).scalar_one().status == "staged"


def test_a_publication_too_late_is_failed_not_caught_up(db, client, ofmai):
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(scheduled_at=(now - timedelta(hours=3)).isoformat())

    bridge.pull_queue(db, client, account, adb)
    assert bridge.publish_staged(db, account, now) == []
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "failed" and "late" in (row.last_error or "")


# ── Step 4: results ──────────────────────────────────────────────────────────


def _finish_job(db, tmp_path, job_id: int, status: str, data: dict | None):
    job = db.get(JobQueue, job_id)
    job.status = status
    if data is not None:
        log = tmp_path / f"job_{job_id}.log"
        log.write_text(f"Running workflow\nData: {json.dumps(data)}\n", encoding="utf-8")
        job.log_file = str(log)
    db.commit()


def test_a_completed_job_becomes_a_posted_event(db, client, ofmai, tmp_path):
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(scheduled_at=now.isoformat())
    bridge.pull_queue(db, client, account, adb)
    job_id = bridge.publish_staged(db, account, now)[0]
    _finish_job(db, tmp_path, job_id, "completed", {"success": True, "post_id": "ig_42"})

    tally = bridge.collect_results(db, adb=adb)

    assert tally["posted"] == 1
    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "posted" and row.posted_at
    event = _outbox(db)[-1]
    payload = json.loads(event.payload_json)
    assert event.kind == "posted"
    assert payload == {
        "publication_id": "pub_9f",
        "variant_id": "cv_9f",
        "asset_id": "ca_31",
        "source_post_id": "scraped_1",
        "post_id": "ig_42",
        "post_url": None,
        "channel": "device",
    }
    # the media is removed from the phone and from the Mac mini
    assert adb.removed == ["/sdcard/DCIM/Camera/pub_9f.mp4"]
    assert not (bridge.media_dir() / "pub_9f.mp4").exists()


def test_ambiguous_is_needs_human_and_never_retried(db, client, ofmai, tmp_path):
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(scheduled_at=now.isoformat())
    bridge.pull_queue(db, client, account, adb)
    job_id = bridge.publish_staged(db, account, now)[0]
    _finish_job(db, tmp_path, job_id, "failed", {"success": False, "ambiguous": True, "error": "share tapped, no post"})

    bridge.collect_results(db, adb=adb)

    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "needs_human"
    assert json.loads(_outbox(db)[-1].payload_json)["ambiguous"] is True

    # A second pass enqueues nothing, and neither does a new tick.
    before = db.query(JobQueue).count()
    bridge.collect_results(db, adb=adb)
    bridge.publish_staged(db, account, now)
    assert db.query(JobQueue).count() == before
    assert db.execute(select(FarmPublication)).scalar_one().status == "needs_human"


def test_a_plain_failure_is_failed_not_needs_human(db, client, ofmai, tmp_path):
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(scheduled_at=now.isoformat())
    bridge.pull_queue(db, client, account, adb)
    job_id = bridge.publish_staged(db, account, now)[0]
    _finish_job(db, tmp_path, job_id, "failed", {"success": False, "ambiguous": False, "error": "gallery item not found"})

    bridge.collect_results(db, adb=adb)

    row = db.execute(select(FarmPublication)).scalar_one()
    assert row.status == "failed" and row.attempts == 1
    assert json.loads(_outbox(db)[-1].payload_json)["ambiguous"] is False


def test_a_killed_job_that_left_nothing_is_treated_as_ambiguous(db, client, ofmai):
    adb = FakeAdb()
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    ofmai.queue_item(scheduled_at=now.isoformat())
    bridge.pull_queue(db, client, account, adb)
    job_id = bridge.publish_staged(db, account, now)[0]
    job = db.get(JobQueue, job_id)
    job.status = "killed"
    job.log_file = "/nonexistent/log"
    db.commit()

    bridge.collect_results(db, adb=adb)

    # We cannot know whether Share went through: a human looks, we never repost.
    assert db.execute(select(FarmPublication)).scalar_one().status == "needs_human"


# ── Step 5: the outbox ───────────────────────────────────────────────────────


def test_a_signal_writes_ledger_and_outbox_in_one_commit(db):
    account = _account(db)
    session = ledger.open_session("instagram", "sierra.cole", db)
    session.signal("action_blocked", "try again later")

    signals = list(db.execute(select(FarmSignal)).scalars())
    events = _outbox(db)
    assert len(signals) == 1 and len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert events[0].kind == "health_signal"
    assert payload["signal_kind"] == "action_blocked"
    assert payload["new_health"] == policy.Health.COOLDOWN.value
    assert payload["matched"] == "try again later"
    assert payload["session_id"] == session.session_id
    # R32 — the daemon is told to leave now, not in five minutes.
    assert bridge.flush_requested() is True


def test_flush_now_empties_the_outbox_without_waiting_for_the_tick(db, client, ofmai):
    account = _account(db)
    session = ledger.open_session("instagram", "sierra.cole", db)
    session.signal("verification", "confirm it's you")
    assert bridge.flush_requested()

    result = bridge.flush_outbox(db, client)

    assert result["sent"] == 1
    assert ofmai.events[0]["kind"] == "health_signal"
    assert ofmai.events[0]["platform"] == "instagram" and ofmai.events[0]["handle"] == "sierra.cole"
    assert _outbox(db)[0].sent_at
    bridge.clear_flush()
    assert bridge.flush_requested() is False


def test_the_event_envelope_carries_an_offset(db, client, ofmai):
    account = _account(db, timezone="America/Los_Angeles")
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    bridge.flush_outbox(db, client)
    at = ofmai.events[0]["at"]
    assert datetime.fromisoformat(at).tzinfo is not None, "an ISO date without offset is read as UTC by OFMAI"


@pytest.mark.parametrize("status", [500, 502, 429, 503])
def test_a_transient_error_backs_off_and_never_dies(db, client, ofmai, status):
    account = _account(db)
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    ofmai.event_status = status

    result = bridge.flush_outbox(db, client)

    assert result["retried"] == 1 and result["dead"] == 0
    row = _outbox(db)[0]
    assert row.dead == 0 and row.sent_at is None and row.attempts == 1
    assert bridge._parse_utc(row.next_try_at) > datetime.now(bridge.UTC)


def test_the_backoff_doubles_up_to_thirty_minutes():
    assert bridge._backoff_minutes(0) == 1
    assert bridge._backoff_minutes(1) == 2
    assert bridge._backoff_minutes(4) == 16
    assert bridge._backoff_minutes(10) == 30


@pytest.mark.parametrize("status", [400, 404, 409, 422])
def test_a_permanent_error_parks_the_event(db, client, ofmai, status):
    account = _account(db)
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    ofmai.event_status = status

    result = bridge.flush_outbox(db, client)

    assert result["dead"] == 1
    row = _outbox(db)[0]
    assert row.dead == 1 and row.sent_at is None


def test_a_parked_event_reaches_a_human(db, client, ofmai, no_discord):
    account = _account(db)
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    ofmai.event_status = 422

    bridge.flush_outbox(db, client)

    assert any(level == "error" for level, _title, _message in no_discord)


def test_a_broken_secret_pauses_the_loop(db, ofmai, no_discord):
    account = _account(db)
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    wrong = bridge.OfmaiClient(base_url=ofmai.url, secret="not-the-secret")

    result = bridge.flush_outbox(db, wrong)

    assert result["paused_until"] is not None
    row = _outbox(db)[0]
    assert row.dead == 0, "a broken secret is fixed by a human, the events wait"
    delay = bridge._parse_utc(row.next_try_at) - datetime.now(bridge.UTC)
    assert timedelta(minutes=14) < delay <= timedelta(minutes=15)
    assert any("401" in title for _level, title, _message in no_discord)


def test_a_batch_stays_under_the_body_limit(db, client, ofmai):
    """OFMAI answers 413 over 256 Ko: the bridge splits before it gets there."""
    account = _account(db)
    big = "x" * 40_000
    for i in range(10):
        bridge.queue_event(db, account, "session_summary", {"session_id": f"s{i}", "comments_used": [big]})

    first = bridge.flush_outbox(db, client)

    assert 0 < first["sent"] < 10
    assert len(json.dumps({"events": ofmai.events}).encode()) < bridge.MAX_BODY_BYTES
    # the rest leaves on the next pass, still without a duplicate
    second = bridge.flush_outbox(db, client)
    assert first["sent"] + second["sent"] <= 10
    assert len({e["event_id"] for e in ofmai.events}) == len(ofmai.events)


def test_a_duplicate_is_not_sent_twice(db, client, ofmai):
    account = _account(db)
    event_id = bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    ofmai.event_body = {"accepted": [], "duplicates": [event_id], "rejected": []}

    result = bridge.flush_outbox(db, client)

    assert result["duplicates"] == 1
    assert _outbox(db)[0].sent_at
    assert bridge.pending_events(db) == []


def test_a_rejected_event_is_parked_not_replayed_for_ever(db, client, ofmai):
    account = _account(db)
    event_id = bridge.queue_event(db, account, "posted", {"publication_id": "gone"})
    ofmai.event_body = {
        "accepted": [],
        "duplicates": [],
        "rejected": [{"event_id": event_id, "error": "unknown publication_id"}],
    }

    result = bridge.flush_outbox(db, client)

    assert result["dead"] == 1
    row = _outbox(db)[0]
    assert row.dead == 1 and row.last_error == "unknown publication_id"


def test_an_unreachable_ofmai_changes_nothing_locally(db, ofmai):
    account = _account(db)
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    dead_client = bridge.OfmaiClient(base_url="http://127.0.0.1:1", secret=SECRET)

    report = bridge.tick(db, dead_client, adb=FakeAdb())

    assert report.outbox["retried"] == 1
    assert _outbox(db)[0].sent_at is None and _outbox(db)[0].dead == 0
    assert db.execute(select(FarmPublication)).first() is None


def test_a_restart_never_sends_an_event_twice(db, client, ofmai):
    account = _account(db)
    bridge.queue_event(db, account, "posted", {"publication_id": "pub_1"})
    bridge.flush_outbox(db, client)
    # "restarting the daemon": a fresh session on the same database
    other = SessionLocal()
    try:
        bridge.flush_outbox(other, client)
    finally:
        other.close()
    assert len(ofmai.events) == 1


# ── Step 6: comments ─────────────────────────────────────────────────────────


def test_comments_are_cached_and_handed_to_the_warming_job(db, client, ofmai):
    account = _account(db)
    ofmai.comments = [
        {"id": "cp_1", "kind": "comment", "text": "the light in this one!!"},
        {"id": "cp_2", "kind": "comment", "text": "obsessed"},
    ]

    assert bridge.refresh_comments(db, client, account) == 2
    # a second pass does not duplicate them
    assert bridge.refresh_comments(db, client, account) == 0

    texts = planner.comments_for(db, account)
    assert texts == ["the light in this one!!", "obsessed"]
    slot = policy.SessionSlot(datetime.now().replace(microsecond=0), 20)
    config = planner.job_config(account, slot, 20, texts)
    assert config["params"]["comments"] == "the light in this one!!\nobsessed"


def test_the_reply_pools_are_cached_and_reach_the_answering_job(db, client, ofmai):
    """E3.2 / E3.3: the three pools come from OFMAI and nowhere else (§3.4)."""
    account = _account(db)
    ofmai.comments = [
        {"id": "cp_1", "kind": "comment", "text": "the light in this one!!"},
        {"id": "rp_ai", "kind": "reply_ai", "text": "100 percent ai and proud of it"},
        {"id": "rp_th", "kind": "reply_thanks", "text": "thank you!"},
        {"id": "rp_q", "kind": "reply_question", "text": "los angeles!"},
    ]

    assert bridge.refresh_comments(db, client, account, bridge.COMMENT_KINDS) == 4
    assert set(bridge.COMMENT_KINDS) == {"comment", "reply_ai", "reply_thanks", "reply_question"}

    pools = planner.reply_pools_for(db, account)
    assert pools == {
        "replies_ai": "100 percent ai and proud of it",
        "replies_thanks": "thank you!",
        "replies_question": "los angeles!",
    }
    # the warming pool stays its own thing: a comment is never used as a reply
    assert planner.comments_for(db, account) == ["the light in this one!!"]


def test_a_phase_that_answers_nobody_reserves_no_reply_text(db, client, ofmai):
    """A served text is reserved for 24 h: a young account never holds one."""
    young = _account(db, handle="day.two", device_serial="R58N0002", created_on=date.today() - timedelta(days=1))
    now = ledger.local_now(young)
    assert bridge.comment_kinds_for(young, now) == ("comment",)

    grown = _account(db, handle="day.forty", device_serial="R58N0040", created_on=date.today() - timedelta(days=40))
    now = ledger.local_now(grown)
    budget = ledger.budget_for(grown, now.date())
    expected = bridge.COMMENT_KINDS if not budget.rest_day else ("comment",)
    assert bridge.comment_kinds_for(grown, now) == expected

    ofmai.comments = [{"id": "rp_ai", "kind": "reply_ai", "text": "100 percent ai"}]
    assert bridge.refresh_comments(db, client, young, bridge.comment_kinds_for(young, ledger.local_now(young))) == 0
    assert planner.reply_pools_for(db, young) == {"replies_ai": "", "replies_thanks": "", "replies_question": ""}


def test_a_reservation_that_expired_unused_comes_back(db, client, ofmai):
    """A text handed to a job that never typed it is not lost for good (§3.4)."""
    account = _account(db)
    ofmai.comments = [{"id": "cp_1", "kind": "comment", "text": "the light in this one!!"}]
    assert bridge.refresh_comments(db, client, account) == 1

    # the planner hands it to a session; nothing comes back in `comments_used`
    assert planner.comments_for(db, account, take=True) == ["the light in this one!!"]
    assert planner.comments_for(db, account) == []

    # OFMAI serves it again once its 24 h reservation lapses: available again
    assert bridge.refresh_comments(db, client, account) == 1
    assert planner.comments_for(db, account) == ["the light in this one!!"]
    assert len(bridge.cached_comments(db, account)) == 1, "one row, never a duplicate"


def test_a_full_cache_is_not_topped_up(db, client, ofmai):
    account = _account(db)
    for i in range(bridge.COMMENT_CACHE_LOW_WATER):
        db.add(FarmCommentCache(comment_id=f"cp_{i}", account_id=account.id, kind="comment", text_=f"t{i}"))
    db.commit()
    assert bridge.refresh_comments(db, client, account) == 0
    assert "/api/farm/comments" not in ofmai.paths()


# ── Step 7: metric pulls ─────────────────────────────────────────────────────


def _posted_row(db, account, posted_at: datetime, publication_id="pub_m") -> FarmPublication:
    row = FarmPublication(
        publication_id=publication_id,
        account_id=account.id,
        variant_id="cv_m",
        asset_id="ca_m",
        channel="device",
        fmt="reel",
        status="posted",
        posted_at=posted_at.isoformat(),
    )
    db.add(row)
    db.commit()
    return row


def _a_session_moment(account, day):
    slots = policy.plan_sessions(ledger.budget_for(account, day))
    return slots[0].start + timedelta(minutes=1) if slots else None


def test_metrics_pull_enqueued_once_per_horizon(db):
    account = _account(db)
    day = ledger.local_today(account)
    moment = _a_session_moment(account, day)
    if moment is None:  # rest day for this (account, date): take tomorrow's plan
        day = day + timedelta(days=1)
        moment = _a_session_moment(account, day)
    assert moment is not None
    row = _posted_row(db, account, moment - timedelta(hours=24))

    first = bridge.enqueue_metric_pulls(db, account, moment)
    assert len(first) == 1
    config = json.loads(db.get(JobQueue, first[0]).config_json)
    assert config["workflow"] == "metrics_pull"
    assert config["params"]["at_hours"] == 24
    assert db.get(JobQueue, first[0]).priority == 3
    assert db.get(JobQueue, first[0]).max_duration_s == bridge.METRIC_MAX_DURATION_S

    # Same horizon again, in the same window: nothing new (slot_key is unique).
    assert bridge.enqueue_metric_pulls(db, account, moment + timedelta(minutes=5)) == []

    # The 72 h horizon is a different slot_key, so it is enqueued in its turn.
    row.posted_at = (moment - timedelta(hours=72)).isoformat()
    db.commit()
    second = bridge.enqueue_metric_pulls(db, account, moment)
    assert len(second) == 1
    assert json.loads(db.get(JobQueue, second[0]).config_json)["params"]["at_hours"] == 72


def test_no_metric_pull_outside_a_session_window(db):
    account = _account(db)
    day = ledger.local_today(account)
    quiet = datetime.combine(day, datetime.min.time()) + timedelta(hours=3)  # QUIET_HOURS
    _posted_row(db, account, quiet - timedelta(hours=24))
    assert bridge.enqueue_metric_pulls(db, account, quiet) == []


def test_horizons_are_measured_from_the_post(db):
    account = _account(db)
    now = datetime.now().replace(microsecond=0)
    row = _posted_row(db, account, now - timedelta(hours=24))
    assert bridge.due_metric_horizons(row, now) == [24]
    assert bridge.due_metric_horizons(row, now + timedelta(hours=3)) == []
    row.posted_at = (now - timedelta(hours=167)).isoformat()
    assert bridge.due_metric_horizons(row, now) == [168]


# ── The whole tick ───────────────────────────────────────────────────────────


def test_a_full_tick_walks_the_seven_steps(db, client, ofmai):
    adb = FakeAdb()
    account = _account(db, ofmai_account_id="sa_01")
    ofmai.accounts = [
        {"id": "sa_01", "platform": "instagram", "handle": "sierra.cole", "role": "persona", "api_mode": False, "disclosed": True}
    ]
    now = ledger.local_now(account).replace(microsecond=0)
    ofmai.queue_item(scheduled_at=now.isoformat())
    ofmai.comments = [{"id": "cp_1", "kind": "comment", "text": "love this"}]

    report = bridge.tick(db, client, adb=adb, now_for=lambda _a: now)

    assert report.stopped is False and report.error is None
    assert report.accounts == 1
    assert report.staged == ["pub_9f"]
    assert len(report.published) == 1
    assert report.comments == 1
    assert "/api/farm/accounts" in ofmai.paths()
    assert "/api/farm/queue" in ofmai.paths()
    assert "/api/farm/events" not in ofmai.paths(), "nothing to send yet"
    assert db.execute(select(FarmPublication)).scalar_one().status == "posting"


def test_x_and_reddit_are_never_pulled_on_the_device_channel(db, client, ofmai):
    """OFMAI only serves them on channel=api (E8): the device bridge does not ask."""
    account = _account(db, platform="reddit", handle="sierra_cole", device_serial="R58N5555")
    ofmai.queue_item(platform="reddit", handle="sierra_cole", format="reddit_post")
    assert bridge.pull_queue(db, client, account, FakeAdb()) == []
    assert "/api/farm/queue" not in ofmai.paths()


def test_an_api_mode_account_is_never_served_on_the_device_channel(db, client, ofmai):
    account = _account(db)
    account.api_mode = 1
    db.commit()
    ofmai.queue_item()
    report = bridge.tick(db, client, adb=FakeAdb())
    assert report.staged == []
    assert "/api/farm/queue" not in ofmai.paths()
