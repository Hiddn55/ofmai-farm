"""The fork's farm API — auth and shape (bridge-ofmai-farm.md §6, health-canaries.md §7).

Pattern: tests/api/test_skill_install_auth.py. Every route is behind
``GITD_ADMIN_TOKEN``; without it, nobody reaches the ledger of the farm.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from gitd.farm import alerts, bridge, collective, ledger, planner
from gitd.farm.models import FarmAction, FarmCommentCache, FarmOutbox, FarmPublication, FarmSignal
from gitd.models.base import SessionLocal

TOKEN = "admin-token-for-tests"


@pytest.fixture(autouse=True)
def no_discord(monkeypatch):
    monkeypatch.delenv(alerts.ENV_VAR, raising=False)
    monkeypatch.setattr(alerts, "_settings_webhook", lambda: "")
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "")
    monkeypatch.setattr(alerts, "notify", lambda *a, **k: False)


@pytest.fixture()
def farm_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    bridge.init()
    db = SessionLocal()
    for account in ledger.list_accounts(db):
        db.delete(account)
    for table in (FarmAction, FarmSignal, FarmPublication, FarmOutbox, FarmCommentCache, collective.FarmPlatform, planner.FarmPlanned):
        db.query(table).delete()
    db.commit()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def anon(monkeypatch):
    """A client with no admin token configured at all."""
    monkeypatch.delenv("GITD_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GITD_ALLOW_UNAUTHENTICATED_ADMIN", raising=False)
    from gitd.app import app

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def admin(monkeypatch):
    monkeypatch.setenv("GITD_ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("GITD_ALLOW_UNAUTHENTICATED_ADMIN", raising=False)
    from gitd.app import app

    with TestClient(app) as client:
        client.headers.update({"X-Ghost-Admin-Token": TOKEN})
        yield client


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/farm/accounts"),
        ("get", "/api/farm/publications"),
        ("get", "/api/farm/outbox"),
        ("get", "/api/farm/health"),
        ("post", "/api/farm/sync"),
        ("post", "/api/farm/platform/instagram/resume"),
        ("post", "/api/farm/accounts/instagram/sierra.cole/clear-health"),
    ],
)
def test_every_route_refuses_without_a_token(anon, method, path):
    response = getattr(anon, method)(path)
    assert response.status_code == 401


def test_a_wrong_token_is_refused(admin, farm_db):
    response = admin.get("/api/farm/accounts", headers={"X-Ghost-Admin-Token": "nope"})
    assert response.status_code == 401


def test_accounts_lists_the_ledger(admin, farm_db):
    ledger.add_account(
        farm_db,
        platform="instagram",
        handle="sierra.cole",
        device_serial="R58N1234",
        created_on=date.today() - timedelta(days=20),
    )
    body = admin.get("/api/farm/accounts").json()
    assert [a["handle"] for a in body["accounts"]] == ["sierra.cole"]
    account = body["accounts"][0]
    assert account["natural_phase"] == "cruise"
    assert account["health"] == "ok" and account["platform_blocked"] is False


def test_clear_health_needs_a_reason(admin, farm_db):
    ledger.add_account(
        farm_db,
        platform="instagram",
        handle="sierra.cole",
        device_serial="R58N1234",
        created_on=date.today() - timedelta(days=20),
    )
    refused = admin.post("/api/farm/accounts/instagram/sierra.cole/clear-health", json={})
    assert refused.status_code == 400

    accepted = admin.post(
        "/api/farm/accounts/instagram/sierra.cole/clear-health",
        json={"reason": "SMS code entered on the device"},
    )
    assert accepted.status_code == 200 and accepted.json()["health"] == "ok"

    kinds = [s.kind for s in farm_db.query(FarmSignal).all()]
    assert kinds == ["cleared"]


def test_clear_health_on_an_unknown_account_is_404(admin, farm_db):
    response = admin.post("/api/farm/accounts/instagram/nobody/clear-health", json={"reason": "x"})
    assert response.status_code == 404


def test_health_shows_the_platform_state(admin, farm_db):
    ledger.add_account(
        farm_db,
        platform="tiktok",
        handle="sierra",
        device_serial="R58N9999",
        created_on=date.today() - timedelta(days=20),
    )
    collective.cut(farm_db, "tiktok", reason="S4: 3 suspended")

    body = admin.get("/api/farm/health").json()
    state = next(p for p in body["platforms"] if p["platform"] == "tiktok")
    assert state["cut"] is True and state["blocked"] is True
    assert state["reason"] == "S4: 3 suspended"

    assert admin.post("/api/farm/platform/tiktok/resume").status_code == 200
    assert admin.get("/api/farm/health").json()["platforms"][0]["blocked"] is False


def test_publications_and_retry(admin, farm_db):
    account = ledger.add_account(
        farm_db,
        platform="instagram",
        handle="sierra.cole",
        device_serial="R58N1234",
        created_on=date.today() - timedelta(days=20),
    )
    farm_db.add(
        FarmPublication(
            publication_id="pub_9f",
            account_id=account.id,
            status="failed",
            fmt="reel",
            device_path="/sdcard/DCIM/Camera/pub_9f.mp4",
            last_error="gallery item not found",
        )
    )
    farm_db.commit()

    listed = admin.get("/api/farm/publications", params={"status": "failed"}).json()
    assert [p["publication_id"] for p in listed["publications"]] == ["pub_9f"]

    retried = admin.post("/api/farm/publications/pub_9f/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "staged"

    # A publication waiting for a human is never re-queued from here (§7).
    row = farm_db.query(FarmPublication).one()
    row.status = "needs_human"
    farm_db.commit()
    assert admin.post("/api/farm/publications/pub_9f/retry").status_code == 409


def test_sync_reports_a_missing_configuration_instead_of_crashing(admin, farm_db, monkeypatch):
    monkeypatch.delenv("FARM_OFMAI_BASE_URL", raising=False)
    monkeypatch.setattr("gitd.config.settings.farm_ofmai_base_url", "", raising=False)
    monkeypatch.setattr(bridge, "_keychain", lambda service: "")

    body = admin.post("/api/farm/sync").json()
    assert body["ok"] is False
    assert "FARM_OFMAI_BASE_URL" in body["error"]
