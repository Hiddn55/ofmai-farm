"""The measure of the oriented warm-up (warming-policy.md §7 bis, "Mesure").

At the end of an Instagram session the Explore page is captured, kept on disk
and scored by a vision model; the score and the screenshot path leave on the
``session_summary`` event exactly like Reddit's karma. Checked here without a
phone and without a model: the strict parser, a fake client that must receive
the image block and the niche, the no-op without credentials, the file under
the right path, and the two keys in the event envelope.
"""

from __future__ import annotations

import base64
from datetime import date, timedelta
from pathlib import Path

import pytest

from gitd.farm import bridge, explore_score, ledger, skillkit
from gitd.farm.models import FarmOutbox
from gitd.skills.base import Element

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-explore-grid"

FEED_XML = (
    "<hierarchy>"
    '<node content-desc="Home" resource-id="com.instagram.android:id/feed_tab" bounds="[42,1300][102,1350]"/>'
    '<node content-desc="Search and explore" resource-id="com.instagram.android:id/search_tab" bounds="[474,1300][534,1350]"/>'
    '<node content-desc="Like" bounds="[30,900][90,960]"/>'
    '<node content-desc="Comment" bounds="[110,900][170,960]"/>'
    "</hierarchy>"
)


# ── the parser ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"score": 35, "reason": "about a third of the tiles are gym content"}', (35, "about a third of the tiles are gym content")),
        ('Sure! {"score": 0, "reason": "nothing"}', (0, "nothing")),
        ('{"score": "72", "reason": "mostly"}', (72, "mostly")),
        ('{"score": 100.0}', (100, "")),
        ('{"score": 101, "reason": "x"}', (None, "")),
        ('{"score": -1}', (None, "")),
        ('{"score": 0.4}', (None, "")),
        ('{"score": true}', (None, "")),
        ('{"score": "40%"}', (None, "")),
        ('{"reason": "no score"}', (None, "")),
        ("around 40 percent", (None, "")),
        ("[40]", (None, "")),
        ("", (None, "")),
    ],
)
def test_parse_score_is_strict(text, expected):
    assert explore_score.parse_score(text) == expected


def test_parse_score_truncates_a_long_reason():
    score, reason = explore_score.parse_score('{"score": 5, "reason": "%s"}' % ("x" * 400))
    assert score == 5
    assert len(reason) == 200


# ── the niche line ────────────────────────────────────────────────────────────


def test_niche_description_is_built_from_the_account_niche_and_the_character():
    line = explore_score.niche_description(["gymgirl", "#fitnessmotivation", "@gymshark"], "eva")
    assert line == "character 'eva'; themes: gymgirl, fitnessmotivation; reference accounts: @gymshark"
    assert explore_score.niche_description([], None) == "unknown niche"


# ── the scorer and its fake client ────────────────────────────────────────────


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Messages:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return type("R", (), {"content": [_Block(self.answer)]})()


class FakeClient:
    def __init__(self, answer='{"score": 60, "reason": "most tiles are gym reels"}'):
        self.messages = _Messages(answer)


def test_the_scorer_sends_the_image_block_and_the_niche():
    client = FakeClient()
    score, reason = explore_score.ExploreScorer(client=client).score(PNG, "themes: gymgirl")
    assert (score, reason) == (60, "most tiles are gym reels")
    call = client.messages.calls[0]
    assert call["model"] == explore_score.MODEL
    assert call["system"] == explore_score.SYSTEM
    content = call["messages"][0]["content"]
    image = content[0]
    assert image["type"] == "image"
    assert image["source"]["type"] == "base64"
    assert image["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(image["source"]["data"]) == PNG
    assert content[1]["type"] == "text"
    assert "themes: gymgirl" in content[1]["text"]


def test_the_scorer_answers_none_on_an_unreadable_answer_or_a_failing_call():
    assert explore_score.ExploreScorer(client=FakeClient("I would say half")).score(PNG, "x") == (None, "")

    class Broken:
        class messages:
            @staticmethod
            def create(**kw):
                raise RuntimeError("model down")

    assert explore_score.ExploreScorer(client=Broken()).score(PNG, "x") == (None, "")
    assert explore_score.ExploreScorer(client=FakeClient()).score(b"", "x") == (None, "")


def test_the_scorer_is_absent_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FARM_ADVISOR", raising=False)
    assert explore_score.configured() is None


# ── the screen: a fake adapter with a phone ───────────────────────────────────


class FakeDevice:
    serial = "fake-explore"

    def __init__(self):
        self.calls = []

    def adb(self, *args, timeout=30):
        self.calls.append(args)
        if args[:3] == ("shell", "wm", "size"):
            return "Physical size: 720x1440"
        return ""

    def dump_xml(self):
        return FEED_XML

    def dismiss_popups(self, xml=None, popups=None):
        return False

    def back(self, delay=1.0):
        self.calls.append(("back",))

    def press_enter(self, delay=0.5):
        self.calls.append(("enter",))

    def find_bounds(self, xml, *, text=None, content_desc=None, resource_id=None, class_name=None):
        from gitd.bots.common.adb import Device

        return Device.find_bounds(self, xml, text=text, content_desc=content_desc, resource_id=resource_id, class_name=class_name)

    def bounds_center(self, b):
        from gitd.bots.common.adb import Device

        return Device.bounds_center(self, b)


class _Human:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, **kw):
        self.taps.append((x, y))

    def pause(self, s):
        pass


ELEMENTS = {
    "search_tab": Element(name="search_tab", content_desc="Search and explore"),
    "home_tab": Element(name="home_tab", content_desc="Home"),
}


class FakeAdapter:
    platform = "instagram"

    def __init__(self, device=None, elements=None):
        self.device = device or FakeDevice()
        self.elements = ELEMENTS if elements is None else elements
        self.human = _Human()
        self.back_to_feed_calls = 0

    def dump(self):
        return self.device.dump_xml()

    def open_feed(self):
        return True

    def on_feed(self, xml):
        return "Like" in xml

    def next_video(self):
        pass

    def like(self, xml):
        return True

    def save(self, xml):
        return True

    def open_author(self, xml):
        return "someone"

    def follow(self, xml):
        return True

    def comment(self, text):
        return True

    def back_to_feed(self):
        self.back_to_feed_calls += 1

    def detour(self, kind, query):
        return True


class FakeScorer:
    def __init__(self, score=60, reason="most tiles are gym reels"):
        self.answer = (score, reason)
        self.calls = []

    def score(self, png, niche):
        self.calls.append((png, niche))
        return self.answer


def test_measure_writes_the_screenshot_under_platform_and_handle(tmp_path):
    adapter = FakeAdapter()
    scorer = FakeScorer()
    out = explore_score.measure(
        adapter, "instagram", "@sierra.cole", ["gymgirl", "@gymshark"], character="eva", scorer=scorer,
        screencap=lambda serial: PNG, out_dir=tmp_path / "explore",
    )
    assert out["explore_niche_score"] == 60
    shot = Path(out["explore_shot"])
    assert shot.parent == tmp_path / "explore" / "instagram" / "sierra.cole"
    assert shot.suffix == ".png" and len(shot.stem) == len("20260922-181500")
    assert shot.read_bytes() == PNG
    # the model saw the bytes on disk and the niche line
    assert scorer.calls == [(PNG, "character 'eva'; themes: gymgirl; reference accounts: @gymshark")]
    # the Explore tab, then the Home tab, then the adapter's own way home
    assert adapter.human.taps == [(504, 1325), (72, 1325)]
    assert adapter.back_to_feed_calls == 1


def test_measure_is_a_no_op_without_a_model(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FARM_ADVISOR", raising=False)
    adapter = FakeAdapter()
    taken = []
    out = explore_score.measure(adapter, "instagram", "sierra", ["gymgirl"], screencap=lambda s: taken.append(s) or PNG, out_dir=tmp_path)
    assert out == {}
    assert taken == []
    assert adapter.human.taps == []
    assert not list(tmp_path.rglob("*.png"))


def test_measure_skips_a_platform_without_an_explore_page(tmp_path):
    adapter = FakeAdapter()
    adapter.platform = "tiktok"
    assert explore_score.measure(adapter, "tiktok", "sierra", ["gymgirl"], scorer=FakeScorer(), screencap=lambda s: PNG, out_dir=tmp_path) == {}
    assert adapter.human.taps == []


def test_measure_never_raises_and_always_comes_back_to_the_feed(tmp_path):
    adapter = FakeAdapter()

    def broken(serial):
        raise RuntimeError("adb gone")

    out = explore_score.measure(adapter, "instagram", "sierra", ["gymgirl"], scorer=FakeScorer(), screencap=broken, out_dir=tmp_path)
    assert out == {}
    assert adapter.back_to_feed_calls == 1
    assert not list(tmp_path.rglob("*.png"))

    # the tab is missing: nothing is captured, the adapter is still walked home
    adapter = FakeAdapter(elements={})
    assert explore_score.measure(adapter, "instagram", "sierra", [], scorer=FakeScorer(), screencap=lambda s: PNG, out_dir=tmp_path) == {}
    assert adapter.back_to_feed_calls == 1


def test_measure_keeps_the_shot_when_the_model_gives_no_score(tmp_path):
    out = explore_score.measure(
        FakeAdapter(), "instagram", "sierra", ["gymgirl"], scorer=FakeScorer(score=None, reason=""),
        screencap=lambda s: PNG, out_dir=tmp_path,
    )
    assert out["explore_niche_score"] is None
    assert Path(out["explore_shot"]).exists()


# ── the session summary, all the way to the event envelope ────────────────────


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    monkeypatch.setenv("FARM_FAST", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FARM_ADVISOR", raising=False)
    monkeypatch.setattr(explore_score, "EXPLORE_DIR", tmp_path / "explore")
    bridge.init()
    from gitd.farm.models import FarmAction, FarmSignal
    from gitd.models.base import SessionLocal

    session = SessionLocal()
    for account in ledger.list_accounts(session):
        session.delete(account)
    for table in (FarmAction, FarmSignal, FarmOutbox):
        session.query(table).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _instagram_account(db):
    created = date.today() - timedelta(days=40)
    for i in range(40):
        acc = ledger.add_account(
            db, platform="instagram", handle=f"sierra_ig_{i}", device_serial=f"fake-explore-{i}", created_on=created, niche="gymgirl,@gymshark"
        )
        if not ledger.budget_for(acc).rest_day:
            return acc
    raise AssertionError("could not build a non-rest-day Instagram account")  # pragma: no cover


def _run_session(db, account, adapter, scorer):
    class _Action(skillkit.WarmSessionAction):
        platform = "instagram"
        adapter_factory = staticmethod(lambda device, elements, human: adapter)
        explore_scorer = scorer

    return _Action(FakeDevice(), ELEMENTS, handle=account.handle, minutes=0.05, seed=3).execute()


def _summary(db):
    rows = [r for r in db.query(FarmOutbox).all() if r.kind == "session_summary"]
    assert len(rows) == 1, f"expected one session_summary, got {[r.kind for r in rows]}"
    return rows[0]


def test_session_summary_carries_the_explore_score_and_the_shot(db, monkeypatch, tmp_path):
    monkeypatch.setattr(explore_score, "_screencap", lambda serial: PNG)
    account = _instagram_account(db)
    adapter = FakeAdapter()
    scorer = FakeScorer(score=42, reason="a few gym tiles")

    result = _run_session(db, account, adapter, scorer)

    assert result.success, result.error
    assert result.data["explore_niche_score"] == 42
    shot = Path(result.data["explore_shot"])
    assert shot.exists() and shot.parent == tmp_path / "explore" / "instagram" / account.handle
    assert len(scorer.calls) == 1
    assert "@gymshark" in scorer.calls[0][1] and "gymgirl" in scorer.calls[0][1]

    payload = bridge._envelope(db, _summary(db))["payload"]
    assert payload["explore_niche_score"] == 42
    assert payload["explore_shot"] == str(shot)


def test_session_summary_omits_the_keys_without_a_model(db, monkeypatch):
    """Absent, never zero: OFMAI must tell "not measured" from "nothing of the niche"."""
    taken = []
    monkeypatch.setattr(explore_score, "_screencap", lambda serial: taken.append(serial) or PNG)
    account = _instagram_account(db)

    result = _run_session(db, account, FakeAdapter(), None)

    assert result.success, result.error
    assert "explore_niche_score" not in result.data and "explore_shot" not in result.data
    assert taken == []
    payload = bridge._envelope(db, _summary(db))["payload"]
    assert "explore_niche_score" not in payload and "explore_shot" not in payload
