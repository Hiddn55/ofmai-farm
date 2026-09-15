"""The Reddit warming adapter: what each primitive means on a feed of cards.

No device is needed — the adapter is driven against XML dumps, exactly as the
warming loop drives it. What *cannot* be checked here is whether the selectors
match the real app: that is Skill Miner's job on the phone (R34), which is why
`tested_on` is still empty in skill.yaml.

Two Reddit-specific rules are tested here because they are the ones that get
accounts banned: the downvote is never tapped, and a community is never left.
"""

import importlib
from datetime import date, timedelta

import pytest

from gitd.farm import ledger
from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
from gitd.skills.ofmai_reddit.actions.core import RedditAdapter
from tests.farm_helpers import typed_text

FEED_XML = (
    "<hierarchy>"
    '<node content-desc="Home" bounds="[100,2300][180,2380]"/>'
    '<node resource-id="com.reddit.frontpage:id/subreddit_name" text="r/fitness" bounds="[60,300][400,350]"/>'
    '<node resource-id="com.reddit.frontpage:id/author" text="u/someone" bounds="[60,360][400,410]"/>'
    '<node text="Join" bounds="[820,300][1000,360]"/>'
    '<node content-desc="Upvote" bounds="[100,1400][180,1480]"/>'
    '<node content-desc="Downvote" bounds="[260,1400][340,1480]"/>'
    '<node content-desc="Comments" bounds="[440,1400][520,1480]"/>'
    '<node content-desc="More options" bounds="[900,1400][980,1480]"/>'
    "</hierarchy>"
)

UPVOTED_XML = FEED_XML.replace('content-desc="Upvote"', 'content-desc="Remove upvote"')
JOINED_XML = FEED_XML.replace('text="Join"', 'text="Joined"')

PROFILE_XML = (
    "<hierarchy>"
    '<node text="u/someone" bounds="[60,300][400,350]"/>'
    '<node text="1.2k karma" bounds="[60,400][400,450]"/>'
    '<node text="Follow" bounds="[800,300][1000,370]"/>'
    "</hierarchy>"
)

OVERFLOW_XML = "<hierarchy><node text=\"Save\" bounds=\"[100,1800][900,1880]\"/></hierarchy>"


class FakeDevice:
    serial = "fake-reddit"

    def __init__(self, xml=FEED_XML):
        self.calls = []
        self.xml = xml

    def adb(self, *args, timeout=30):
        self.calls.append(args)
        if args[:3] == ("shell", "wm", "size"):
            return "Physical size: 1080x2400"
        return ""

    def dump_xml(self):
        return self.xml

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

    def taps(self):
        out = []
        for c in self.calls:
            if c[:3] == ("shell", "input", "swipe") and len(c) >= 7:
                x1, y1, x2, y2 = (int(v) for v in c[3:7])
                if abs(x2 - x1) <= 30 and abs(y2 - y1) <= 30:
                    out.append((x1, y1))
        return out


def _adapter(xml=FEED_XML):
    dev = FakeDevice(xml)
    skill = importlib.import_module("gitd.skills.ofmai_reddit").load()
    human = HumanInput(dev, SessionProfile.generate(3), screen=ScreenSize(1080, 2400), sleep=lambda s: None)
    return dev, RedditAdapter(dev, skill._elements_for_device(dev), human)


def _near(point, box, pad=40):
    x, y = point
    x1, y1, x2, y2 = box
    return x1 - pad <= x <= x2 + pad and y1 - pad <= y <= y2 + pad


# ── the unit of a view is a post card ─────────────────────────────────────────


def test_on_feed_recognises_the_home_feed():
    _, ad = _adapter()
    assert ad.on_feed(FEED_XML)
    assert not ad.on_feed('<node content-desc="Upvote"/>')  # no Comments: not a feed
    assert not ad.on_feed("")


def test_next_item_is_a_humanised_swipe_never_a_tap():
    dev, ad = _adapter()
    ad.next_video()
    assert len([c for c in dev.calls if c[:3] == ("shell", "input", "swipe")]) == 1
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []


# ── votes: upvote only, never a downvote, never a toggle ──────────────────────


def test_like_is_the_upvote_and_never_the_downvote():
    dev, ad = _adapter()
    assert ad.like(FEED_XML)
    taps = dev.taps()
    assert any(_near(t, (100, 1400, 180, 1480)) for t in taps)
    assert not any(_near(t, (260, 1400, 340, 1480), pad=0) for t in taps)


def test_like_never_removes_an_existing_upvote():
    dev, ad = _adapter(UPVOTED_XML)
    assert ad.like(UPVOTED_XML) is False
    assert dev.taps() == []


# ── save lives in the overflow menu ───────────────────────────────────────────


def test_save_goes_through_more_options():
    dev, ad = _adapter()
    dev.xml = OVERFLOW_XML  # the sheet is what the next dump shows
    assert ad.save(FEED_XML)
    assert any(_near(t, (900, 1400, 980, 1480)) for t in dev.taps())  # the "..." button


def test_save_backs_out_when_the_sheet_has_no_save():
    dev, ad = _adapter()
    dev.xml = "<hierarchy></hierarchy>"
    assert ad.save(FEED_XML) is False
    assert ("back",) in dev.calls


# ── profile visit and join (R16) ──────────────────────────────────────────────


def test_open_author_opens_the_user_never_the_subreddit():
    dev, ad = _adapter(FEED_XML)
    dev.xml = PROFILE_XML
    assert ad.open_author(FEED_XML) == "someone"
    # the tap landed on the u/ row, not on the r/ row above it
    taps = dev.taps()
    assert any(_near(t, (60, 360, 400, 410)) for t in taps)
    assert not any(_near(t, (60, 300, 400, 350), pad=0) for t in taps)


def test_follow_joins_the_sub_from_the_feed_when_the_profile_has_no_join():
    dev, ad = _adapter(PROFILE_XML)
    dev.xml = FEED_XML  # back_to_feed lands here, where the Join button lives
    assert ad.follow(PROFILE_XML)
    assert any(_near(t, (820, 300, 1000, 360)) for t in dev.taps())


def test_follow_never_leaves_a_community_it_already_joined():
    dev, ad = _adapter(JOINED_XML)
    dev.xml = JOINED_XML
    assert ad.follow(JOINED_XML) is False
    assert dev.taps() == []


# ── detours ───────────────────────────────────────────────────────────────────


def test_detour_is_search_only_no_stories():
    dev, ad = _adapter()
    assert ad.detour("stories", None) is False
    assert ad.detour("search", None) is False  # no query, no detour
    assert dev.taps() == []


def test_search_types_a_subreddit_and_opens_hot():
    dev, ad = _adapter()
    dev.xml = (
        "<hierarchy>"
        '<node content-desc="Search" bounds="[900,200][980,270]"/>'
        '<node text="Search Reddit" resource-id="com.reddit.frontpage:id/search_view" bounds="[100,200][880,270]"/>'
        '<node text="Hot" bounds="[100,400][220,460]"/>'
        "</hierarchy>"
    )
    assert ad._search("fitness")
    # the field is reconstructed (typos and their backspaces replayed), so the
    # query can be asserted exactly instead of by a substring that a simulated
    # typo would break
    assert typed_text(dev.calls) == "r/fitness"
    assert ("enter",) in dev.calls


def test_the_reddit_skill_declares_search_as_its_only_detour():
    from gitd.skills.ofmai_reddit.workflows import RedditWarmAction

    assert RedditWarmAction.default_detours == ("search",)
    assert RedditWarmAction.platform == "reddit"


# ── end to end, no phone ──────────────────────────────────────────────────────


@pytest.fixture()
def db():
    ledger.init()
    from gitd.farm.models import FarmAction, FarmSignal
    from gitd.models.base import SessionLocal

    s = SessionLocal()
    for a in ledger.list_accounts(s):
        s.delete(a)
    for table in (FarmAction, FarmSignal):
        s.query(table).delete()
    s.commit()
    yield s
    s.close()


def test_warm_session_runs_against_fake_device(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    created = date.today() - timedelta(days=9)
    ledger.add_account(db, platform="reddit", handle="rd_fake", device_serial="fake-reddit", created_on=created)

    skill = importlib.import_module("gitd.skills.ofmai_reddit").load()
    dev = FakeDevice()
    wf = skill.get_workflow("warm_session", dev, handle="@rd_fake", minutes=10, seed=5, comments="nice\ncool")
    result = wf.run()
    assert result.success, result.error
    step = result.data["step_results"][0]["data"]
    assert step["videos"] > 10
    assert step["phase"] == "network"  # Reddit follows the Instagram calendar
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []
