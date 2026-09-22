"""Targets of the oriented warm-up (docs/social/warming-policy.md §7 bis).

Three things are checked, against a simulated OFMAI as in test_farm_bridge.py:
the radar list served by ``GET /api/farm/targets`` lands in ``farm_targets`` as
``source = radar`` without ever duplicating a handle; ``ledger.pick_targets``
never hands a door back before its cooldown, radar first and in a
deterministic order for (account, day); and ``skillkit`` puts today's doors at
the head of the session's ``niche`` list, then stamps what the run opened.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from gitd.farm import bridge, collective, ledger, planner, policy, skillkit
from gitd.farm.models import FarmAction, FarmCommentCache, FarmOutbox, FarmPublication, FarmSignal, FarmTarget
from gitd.farm.warm import SessionStats
from gitd.models.base import SessionLocal

SECRET = "s3cret-for-tests"


# ── The simulated OFMAI, reduced to §3.7 ─────────────────────────────────────


class FakeOfmai:
    def __init__(self):
        self.targets: list[dict] = []
        self.status = 200
        self.queries: list[dict[str, str]] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        fake: FakeOfmai = self.server.fake  # type: ignore[attr-defined]
        url = urlparse(self.path)
        if self.headers.get("x-farm-secret") != SECRET:
            return self._send(401, {"error": "Unauthorized"})
        if url.path != "/api/farm/targets":
            return self._send(404, {"error": "not_found"})
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        fake.queries.append(params)
        if fake.status != 200:
            return self._send(fake.status, {"error": "forced"})
        limit = int(params.get("limit") or "30")
        return self._send(200, {"targets": fake.targets[:limit]})


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
    for table in (
        FarmAction, FarmSignal, FarmPublication, FarmOutbox, FarmCommentCache, FarmTarget,
        collective.FarmPlatform, planner.FarmPlanned,
    ):
        session.query(table).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _account(db, handle="sierra_t", *, character_id="cmf_sierra", niche="@hand.one,#gymgirl", days=10):
    return ledger.add_account(
        db,
        platform="instagram",
        handle=handle,
        device_serial=f"dev-{handle}",
        created_on=date.today() - timedelta(days=days),
        character_id=character_id,
        niche=niche,
    )


def _target(handle, score=1.0, followers=1000):
    return {"handle": handle, "platform": "instagram", "followers": followers, "score": score, "niche": "fitness"}


def _rows(db, acc) -> dict[str, FarmTarget]:
    rows = db.execute(select(FarmTarget).where(FarmTarget.account_id == acc.id)).scalars()
    return {r.handle: r for r in rows}


# ── bridge.fetch_targets ──────────────────────────────────────────────────────


def test_fetch_targets_asks_for_the_character_and_remembers_the_radar(db, ofmai, client):
    acc = _account(db)
    ofmai.targets = [_target("lena.trains", 4.2), _target("nova.fit", 9.1)]
    now = datetime(2026, 9, 22, 10, 0)

    assert bridge.fetch_targets(db, client, acc, now=now) == ["lena.trains", "nova.fit"]
    assert ofmai.queries == [{"character": "cmf_sierra", "platform": "instagram", "limit": "30"}]
    rows = _rows(db, acc)
    assert set(rows) == {"lena.trains", "nova.fit"}
    assert all(r.source == "radar" and r.plays == 0 and r.last_played is None for r in rows.values())
    assert rows["lena.trains"].first_seen == "2026-09-22T10:00:00"

    # the same list a day later: nothing duplicated, only last_seen moves
    ledger.mark_played(db, acc, "lena.trains", now=now)
    later = now + timedelta(days=1)
    bridge.fetch_targets(db, client, acc, now=later)
    rows = _rows(db, acc)
    assert len(rows) == 2
    assert rows["lena.trains"].last_seen == "2026-09-23T10:00:00"
    assert rows["lena.trains"].first_seen == "2026-09-22T10:00:00"
    assert rows["lena.trains"].plays == 1  # the memory of what was played is local


def test_fetch_targets_without_a_character_or_without_ofmai_gives_nothing(db, ofmai, client):
    orphan = _account(db, "orphan_t", character_id=None)
    assert bridge.fetch_targets(db, client, orphan) == []
    assert ofmai.queries == []

    acc = _account(db)
    ofmai.status = 500
    assert bridge.fetch_targets(db, client, acc) == []  # logged, never raised
    assert _rows(db, acc) == {}


def test_tick_refreshes_targets_only_when_the_pool_runs_low(db, ofmai, client):
    acc = _account(db)
    now = ledger.local_now(acc)
    assert bridge.targets_need_refresh(db, acc, now)  # nothing known yet

    ofmai.targets = [_target(f"acc{i}") for i in range(8)]
    bridge.fetch_targets(db, client, acc, now=now)
    assert not bridge.targets_need_refresh(db, acc, now)  # 8 playable, fresh list
    assert not bridge.targets_need_refresh(db, acc, now + timedelta(days=2))  # still 8 playable

    for i in range(5):  # 3 left: below the low-water mark, and the list is a day old
        ledger.mark_played(db, acc, f"acc{i}", now=now)
    assert not bridge.targets_need_refresh(db, acc, now + timedelta(hours=1))  # asked less than 24 h ago
    assert bridge.targets_need_refresh(db, acc, now + timedelta(days=2))


# ── ledger.pick_targets / mark_played / record_discovered ─────────────────────


def test_pick_targets_respects_the_cooldown_and_the_source_order(db):
    acc = _account(db)
    today = ledger.local_today(acc)
    at = datetime.combine(today, datetime.min.time()) + timedelta(hours=12)
    for h in ("radar.a", "radar.b", "radar.c"):
        ledger.record_target(db, acc, h, "radar", now=at)
    ledger.record_discovered(db, acc, "@Found.One", now=at)  # "@" and case are dropped

    ledger.mark_played(db, acc, "radar.a", now=at - timedelta(days=1))  # yesterday: cooling
    ledger.mark_played(db, acc, "radar.b", now=at - timedelta(days=20))  # long ago: back in the pool

    picked = ledger.pick_targets(db, acc, 10, day=today)
    assert "radar.a" not in picked
    assert set(picked[:2]) == {"radar.b", "radar.c"}  # radar first
    assert picked[2] == "found.one"  # then what a run discovered
    assert ledger.pick_targets(db, acc, 10, day=today) == picked  # same day, same list
    assert ledger.pick_targets(db, acc, 1, day=today) == picked[:1]
    assert ledger.pick_targets(db, acc, 0, day=today) == []

    # a shorter cooldown lets yesterday's door back in, at the end of the radar bucket or not,
    # but never before a door that was not played
    assert "radar.a" in ledger.pick_targets(db, acc, 10, cooldown_days=0, day=today)


def test_pick_targets_is_seeded_by_account_and_day(db):
    acc = _account(db)
    other = _account(db, "other_t")
    day = date(2026, 9, 22)
    for h in (f"radar.{i}" for i in range(12)):
        ledger.record_target(db, acc, h, "radar")
        ledger.record_target(db, other, h, "radar")

    same_day = ledger.pick_targets(db, acc, 12, day=day)
    assert same_day == ledger.pick_targets(db, acc, 12, day=day)
    assert sorted(same_day) == sorted(f"radar.{i}" for i in range(12))
    # another day or another account walks the list differently (12! orders: a
    # collision would be a broken seed, not bad luck)
    assert same_day != ledger.pick_targets(db, acc, 12, day=day + timedelta(days=1))
    assert same_day != ledger.pick_targets(db, other, 12, day=day)


def test_mark_played_records_a_hand_typed_handle_as_manual(db):
    acc = _account(db)
    row = ledger.mark_played(db, acc, "@hand.one")
    assert row is not None and row.source == "manual" and row.plays == 1 and row.last_played
    ledger.mark_played(db, acc, "hand.one")
    assert _rows(db, acc)["hand.one"].plays == 2
    assert ledger.mark_played(db, acc, "@") is None
    with pytest.raises(ValueError):
        ledger.record_target(db, acc, "x", "explore")


# ── skillkit: the session's niche list, and the doors it opened ───────────────


def test_session_niche_puts_todays_doors_first(db, monkeypatch):
    acc = _account(db)
    for h in ("lena.trains", "nova.fit", "big.gym"):
        ledger.record_target(db, acc, h, "radar")
    called = []
    monkeypatch.setattr(bridge.OfmaiClient, "from_env", classmethod(lambda cls: called.append(1)))

    niche = skillkit.session_niche(db, acc, ["@hand.one", "#gymgirl"], 2)
    assert len(niche) == 4
    assert set(niche[:2]) <= {"@lena.trains", "@nova.fit", "@big.gym"}
    assert niche[2:] == ["@hand.one", "#gymgirl"]
    assert called == []  # the pool was not empty: OFMAI is not asked at session time

    # a door already in the hand-typed list is not listed twice
    ledger.record_target(db, acc, "hand.one", "radar")
    monkeypatch.setattr(ledger, "pick_targets", lambda db, account, n, **kw: ["hand.one", "lena.trains"])
    assert skillkit.session_niche(db, acc, ["@hand.one", "#gymgirl"], 2) == ["@hand.one", "@lena.trains", "#gymgirl"]


def test_session_niche_falls_back_to_hand_typed_handles_without_a_bridge(db, monkeypatch):
    acc = _account(db)

    def not_configured(cls):
        raise bridge.BridgeNotConfigured("FARM_OFMAI_BASE_URL is not set")

    monkeypatch.setattr(bridge.OfmaiClient, "from_env", classmethod(not_configured))
    assert skillkit.session_niche(db, acc, ["@hand.one", "#gymgirl"], 3) == ["@hand.one", "#gymgirl"]


def test_session_niche_asks_ofmai_once_when_the_table_is_empty(db, ofmai, client, monkeypatch):
    acc = _account(db)
    ofmai.targets = [_target("lena.trains")]
    monkeypatch.setattr(bridge.OfmaiClient, "from_env", classmethod(lambda cls: client))

    assert skillkit.session_niche(db, acc, ["#gymgirl"], 3) == ["@lena.trains", "#gymgirl"]
    assert len(ofmai.queries) == 1
    assert _rows(db, acc)["lena.trains"].source == "radar"


def _warmable_account(db, prefix="warm_t"):
    """An account whose today is not its weekly rest day (seeded from the row id)."""
    for i in range(40):
        acc = _account(db, f"{prefix}{i}")
        if not ledger.budget_for(acc).rest_day:
            return acc
    raise AssertionError("could not build a non-rest-day account")  # pragma: no cover


def test_warm_session_marks_the_doors_it_opened(db, monkeypatch):
    monkeypatch.setenv("FARM_FAST", "1")
    acc = _warmable_account(db)
    for h in ("lena.trains", "nova.fit"):
        ledger.record_target(db, acc, h, "radar")
    monkeypatch.setattr(bridge.OfmaiClient, "from_env", classmethod(lambda cls: (_ for _ in ()).throw(AssertionError)))

    seen: dict = {}

    def fake_run_session(adapter, human, session, cfg, *, now):
        seen["niche"] = list(cfg.niche)
        return SessionStats(videos=7, played=[cfg.niche[0]])

    monkeypatch.setattr(skillkit, "run_session", fake_run_session)
    from gitd.farm import explore_score

    monkeypatch.setattr(explore_score, "measure", lambda *a, **k: {})

    class Warm(skillkit.WarmSessionAction):
        platform = "instagram"
        adapter_factory = staticmethod(lambda device, elements, human: object())

    result = Warm(object(), {}, handle=f"@{acc.handle}", minutes=1, seed=5).run()
    assert result.success, result.error

    door = seen["niche"][0]
    assert door in ("@lena.trains", "@nova.fit")
    assert seen["niche"][-2:] == ["@hand.one", "#gymgirl"]
    assert result.data["played"] == [door]
    assert result.data["targets_used"] == [door.lstrip("@")]

    row = _rows(db, acc)[door.lstrip("@")]
    assert row.plays == 1 and row.last_played is not None
    # the next session of the day does not open the same door
    assert door.lstrip("@") not in ledger.pick_targets(db, acc, 5)
