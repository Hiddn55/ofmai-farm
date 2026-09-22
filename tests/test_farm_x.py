"""The X warming adapter: what each primitive means on a timeline of cards.

No device is needed — the adapter is driven against XML dumps, exactly as the
warming loop drives it. What *cannot* be checked here is whether the selectors
match the real app: that is Skill Miner's job on the phone (R34), which is why
`tested_on` is still empty in skill.yaml.
"""

import importlib
from datetime import date, timedelta

import pytest

from gitd.farm import ledger
from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
from gitd.skills.ofmai_x.actions.core import XAdapter
from tests.farm_helpers import typed_text

TIMELINE_XML = (
    "<hierarchy>"
    '<node content-desc="Home" resource-id="com.twitter.android:id/home" bounds="[100,2300][180,2380]"/>'
    '<node text="For you" bounds="[200,200][360,260]"/>'
    '<node content-desc="Profile image" bounds="[40,1200][120,1280]"/>'
    '<node resource-id="com.twitter.android:id/user_name" text="Someone" bounds="[140,1200][500,1250]"/>'
    '<node content-desc="Reply. 3 replies" bounds="[200,1400][280,1480]"/>'
    '<node content-desc="Like. 12 likes" bounds="[600,1400][680,1480]"/>'
    '<node content-desc="Bookmark" bounds="[800,1400][880,1480]"/>'
    "</hierarchy>"
)

LIKED_XML = TIMELINE_XML.replace('content-desc="Like. 12 likes"', 'content-desc="Liked. 13 likes"')
BOOKMARKED_XML = TIMELINE_XML.replace('content-desc="Bookmark"', 'content-desc="Remove bookmark"')

PROFILE_XML = (
    "<hierarchy>"
    '<node resource-id="com.twitter.android:id/screen_name" text="@someone" bounds="[60,400][500,460]"/>'
    '<node text="Followers" bounds="[60,520][300,570]"/>'
    '<node text="Follow" bounds="[800,400][1000,470]"/>'
    "</hierarchy>"
)
FOLLOWING_XML = PROFILE_XML.replace('text="Follow"', 'text="Following"')


class FakeDevice:
    serial = "fake-x"

    def __init__(self, xml=TIMELINE_XML):
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


def _adapter(xml=TIMELINE_XML):
    dev = FakeDevice(xml)
    skill = importlib.import_module("gitd.skills.ofmai_x").load()
    human = HumanInput(dev, SessionProfile.generate(3), screen=ScreenSize(1080, 2400), sleep=lambda s: None)
    return dev, XAdapter(dev, skill._elements_for_device(dev), human)


def _near(point, box, pad=40):
    x, y = point
    x1, y1, x2, y2 = box
    return x1 - pad <= x <= x2 + pad and y1 - pad <= y <= y2 + pad


# ── the unit of a view is a post card ─────────────────────────────────────────


def test_on_feed_recognises_the_timeline():
    _, ad = _adapter()
    assert ad.on_feed(TIMELINE_XML)
    assert not ad.on_feed('<node content-desc="Like"/>')  # no Reply: not a timeline
    assert not ad.on_feed("")


def test_next_item_is_a_humanised_swipe_never_a_tap():
    dev, ad = _adapter()
    ad.next_video()
    swipes = [c for c in dev.calls if c[:3] == ("shell", "input", "swipe")]
    assert len(swipes) == 1
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []


# ── like / save ───────────────────────────────────────────────────────────────


def test_like_taps_the_heart():
    dev, ad = _adapter()
    assert ad.like(TIMELINE_XML)
    assert any(_near(t, (600, 1400, 680, 1480)) for t in dev.taps())


def test_like_never_unlikes_an_already_liked_post():
    dev, ad = _adapter(LIKED_XML)
    assert ad.like(LIKED_XML) is False
    assert dev.taps() == []


def test_save_is_the_bookmark_and_never_removes_one():
    dev, ad = _adapter()
    assert ad.save(TIMELINE_XML)
    assert any(_near(t, (800, 1400, 880, 1480)) for t in dev.taps())

    dev2, ad2 = _adapter(BOOKMARKED_XML)
    assert ad2.save(BOOKMARKED_XML) is False
    assert dev2.taps() == []


# ── profile visit and follow (R16) ────────────────────────────────────────────


def test_open_author_returns_the_handle():
    dev, ad = _adapter(TIMELINE_XML)
    dev.xml = PROFILE_XML  # the profile is what the next dump shows
    assert ad.open_author(TIMELINE_XML) == "someone"


def test_open_author_gives_up_when_the_screen_is_not_a_profile():
    dev, ad = _adapter(TIMELINE_XML)
    dev.xml = "<hierarchy></hierarchy>"
    assert ad.open_author(TIMELINE_XML) is None
    assert ("back",) in dev.calls


def test_follow_only_taps_an_exact_follow_button():
    dev, ad = _adapter(PROFILE_XML)
    assert ad.follow(PROFILE_XML)
    assert any(_near(t, (800, 400, 1000, 470)) for t in dev.taps())

    dev2, ad2 = _adapter(FOLLOWING_XML)
    assert ad2.follow(FOLLOWING_XML) is False
    assert dev2.taps() == []


# ── detours ───────────────────────────────────────────────────────────────────


def test_detour_is_search_only_no_stories():
    dev, ad = _adapter()
    assert ad.detour("stories", None) is False
    assert ad.detour("search", None) is False  # no query, no detour
    assert dev.taps() == []


def test_search_types_a_hashtag():
    dev, ad = _adapter()
    dev.xml = (
        "<hierarchy>"
        '<node content-desc="Search and Explore" resource-id="com.twitter.android:id/explore" bounds="[300,2300][380,2380]"/>'
        '<node text="Search X" resource-id="com.twitter.android:id/query_view" bounds="[100,200][900,270]"/>'
        "</hierarchy>"
    )
    assert ad._search("gymgirl")
    # the field is reconstructed (typos and their backspaces replayed), so the
    # query can be asserted exactly instead of by a substring that a simulated
    # typo would break
    assert typed_text(dev.calls) == "#gymgirl"
    assert ("enter",) in dev.calls


def test_the_x_skill_declares_search_as_its_only_detour():
    from gitd.skills.ofmai_x.workflows import XWarmAction

    assert XWarmAction.default_detours == ("search",)
    assert XWarmAction.platform == "x"


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
    # the rest day is seeded from the row id: insert rows until today is not one
    for i in range(40):
        acc = ledger.add_account(db, platform="x", handle=f"x_fake_{i}", device_serial=f"fake-x-{i}", created_on=created)
        if not ledger.budget_for(acc).rest_day:
            break
    else:  # pragma: no cover
        raise AssertionError("could not build a non-rest-day X account")

    skill = importlib.import_module("gitd.skills.ofmai_x").load()
    dev = FakeDevice()
    wf = skill.get_workflow("warm_session", dev, handle=f"@{acc.handle}", minutes=10, seed=5, comments="nice\ncool")
    result = wf.run()
    assert result.success, result.error
    step = result.data["step_results"][0]["data"]
    assert step["videos"] > 10
    assert step["phase"] == "network"  # X follows the Instagram calendar
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []
