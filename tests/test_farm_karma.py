"""Reddit karma: read on screen, carried by ``session_summary``, read by OFMAI.

OFMAI serves no Reddit publication below 100 karma (docs/social/publishing.md
§5) and, until this file existed, **no event carried the number**: the karma
stayed at zero on the OFMAI side and the Reddit queue could never open. What is
checked here is the farm half of that path — the parser, the optional adapter
hook, and the fact that the number really leaves in the event envelope.

No phone: the adapter is a fake, exactly as the warming loop drives a real one.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from gitd.farm import bridge, ledger, policy, skillkit
from gitd.farm.models import FarmOutbox
from gitd.farm.warm import parse_karma

# The Reddit profile header, as the accessibility tree exposes it.
OWN_PROFILE_XML = (
    "<hierarchy>"
    '<node text="u/sierra_rd" bounds="[60,300][400,350]"/>'
    '<node text="1.2k karma" bounds="[60,400][400,450]"/>'
    '<node text="Sep 2026 cake day" bounds="[60,460][400,510]"/>'
    "</hierarchy>"
)

FEED_XML = (
    "<hierarchy>"
    '<node content-desc="Upvote" bounds="[100,1400][180,1480]"/>'
    '<node content-desc="Comments" bounds="[440,1400][520,1480]"/>'
    "</hierarchy>"
)


# ── the parser ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1.2k karma", 1200),
        ("247 karma", 247),
        ("1,234 karma", 1234),
        ("12.5m karma", 12_500_000),
        ("0 karma", 0),
        ("1.2k followers", None),
        ("Comment karma", None),
        ("Sep 2026 cake day", None),
    ],
)
def test_parse_karma_reads_the_profile_header(text, expected):
    assert parse_karma(f'<hierarchy><node text="{text}" bounds="[0,0][10,10]"/></hierarchy>') == expected


def test_parse_karma_sums_the_detailed_rows_when_there_is_no_total():
    xml = (
        "<hierarchy>"
        '<node text="Post karma 1.2k" bounds="[0,0][10,10]"/>'
        '<node text="Comment karma: 340" bounds="[0,20][10,30]"/>'
        "</hierarchy>"
    )
    assert parse_karma(xml) == 1540


def test_parse_karma_reads_a_content_desc_too():
    xml = '<hierarchy><node content-desc="132 karma" bounds="[0,0][10,10]"/></hierarchy>'
    assert parse_karma(xml) == 132


def test_parse_karma_on_the_whole_profile_screen():
    """The cake day next to the karma must not be mistaken for a count."""
    assert parse_karma(OWN_PROFILE_XML) == 1200


def test_parse_karma_is_none_on_a_screen_without_karma():
    assert parse_karma(FEED_XML) is None
    assert parse_karma("") is None


# ── the optional adapter hook ─────────────────────────────────────────────────


class _Adapter:
    platform = "reddit"

    def __init__(self, karma=None, raises=False):
        self._karma = karma
        self._raises = raises
        self.read_calls = 0

    def dump(self):
        return FEED_XML

    def open_feed(self):
        return True

    def on_feed(self, xml):
        return "Upvote" in xml

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
        pass

    def detour(self, kind, query):
        return True


class _AdapterWithKarma(_Adapter):
    def read_karma(self):
        self.read_calls += 1
        if self._raises:
            raise RuntimeError("profile screen never opened")
        return self._karma


def test_read_karma_is_none_when_the_adapter_has_no_hook():
    """The Reddit skill does not read the screen yet: the key is simply absent."""
    assert skillkit.read_karma(_Adapter()) is None


def test_read_karma_returns_what_the_adapter_read():
    assert skillkit.read_karma(_AdapterWithKarma(karma=137)) == 137
    assert skillkit.read_karma(_AdapterWithKarma(karma=0)) == 0


def test_read_karma_swallows_a_broken_reading():
    """A phone that could not open the profile never fails the whole session."""
    assert skillkit.read_karma(_AdapterWithKarma(raises=True)) is None


@pytest.mark.parametrize("value", [None, "1.2k", True, -5, [130]])
def test_read_karma_refuses_anything_that_is_not_a_count(value):
    assert skillkit.read_karma(_AdapterWithKarma(karma=value)) is None


# ── the session summary, all the way to the event envelope ────────────────────


class FakeDevice:
    serial = "fake-karma"

    def __init__(self):
        self.calls = []

    def adb(self, *args, timeout=30):
        self.calls.append(args)
        if args[:3] == ("shell", "wm", "size"):
            return "Physical size: 1080x2400"
        return ""

    def dump_xml(self):
        return FEED_XML

    def dismiss_popups(self, xml=None, popups=None):
        return False

    def back(self, delay=1.0):
        self.calls.append(("back",))

    def press_enter(self, delay=0.5):
        self.calls.append(("enter",))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_DATA_DIR", str(tmp_path / "farm"))
    monkeypatch.setenv("FARM_SKIP_TZ_CHECK", "1")
    monkeypatch.setenv("FARM_FAST", "1")
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


def _cruising_reddit_account(db):
    """A Reddit account old enough to be in cruise, on a day that is not a rest day."""
    created = date.today() - timedelta(days=40)
    for i in range(40):
        acc = ledger.add_account(
            db,
            platform="reddit",
            handle=f"sierra_rd_{i}",
            device_serial=f"fake-karma-{i}",
            created_on=created,
        )
        if not ledger.budget_for(acc).rest_day:
            return acc
        db.delete(acc)
        db.commit()
    raise AssertionError("could not build a non-rest-day Reddit account")  # pragma: no cover


def _run_session(db, account, adapter):
    class _Action(skillkit.WarmSessionAction):
        platform = "reddit"
        adapter_factory = staticmethod(lambda device, elements, human: adapter)

    action = _Action(FakeDevice(), {}, handle=account.handle, minutes=0.05, seed=3)
    return action.execute()


def _summary(db):
    rows = [r for r in db.query(FarmOutbox).all() if r.kind == "session_summary"]
    assert len(rows) == 1, f"expected one session_summary, got {[r.kind for r in rows]}"
    return rows[0]


def test_session_summary_carries_the_karma_read_on_screen(db):
    account = _cruising_reddit_account(db)
    adapter = _AdapterWithKarma(karma=137)

    result = _run_session(db, account, adapter)

    assert result.success, result.error
    assert result.data["karma"] == 137
    assert adapter.read_calls == 1

    # ...and it is still there in the envelope posted to /api/farm/events.
    envelope = bridge._envelope(db, _summary(db))
    assert envelope["kind"] == "session_summary"
    assert envelope["platform"] == "reddit"
    assert envelope["payload"]["karma"] == 137
    assert envelope["payload"]["day_of_life"] >= 40


def test_session_summary_omits_the_key_when_nothing_could_be_read(db):
    """Absent, never zero: OFMAI must be able to tell "unknown" from "low"."""
    account = _cruising_reddit_account(db)

    result = _run_session(db, account, _Adapter())

    assert result.success, result.error
    assert "karma" not in result.data
    assert "karma" not in bridge._envelope(db, _summary(db))["payload"]


def test_a_health_signal_stops_the_session_before_any_karma_reading(db):
    """R27: an account under suspicion is not walked through one more screen."""
    account = _cruising_reddit_account(db)

    class _Flagged(_AdapterWithKarma):
        def dump(self):
            # health.detect fires on this screen (suspended account)
            return '<hierarchy><node text="Your account has been suspended"/></hierarchy>'

        def on_feed(self, xml):
            return True

    adapter = _Flagged(karma=500)
    _run_session(db, account, adapter)

    assert adapter.read_calls == 0
    assert "karma" not in bridge._envelope(db, _summary(db))["payload"]


def test_reddit_is_a_platform_the_ledger_and_planner_know(db):
    """The karma only ever arrives if Reddit sessions are actually planned."""
    from gitd.farm import planner

    assert "reddit" in policy.PLATFORMS
    assert planner.SKILL_BY_PLATFORM["reddit"] == "ofmai_reddit"
