"""The four skills load through ghost's Skill machinery, a warm_session
workflow runs end to end against a fake device (FARM_FAST=1, no sleeps), and
the posting workflows behave on a scripted screen.

The reply workflows have their own file, ``tests/test_farm_replies.py``."""

import importlib
from datetime import date, timedelta

import pytest

from gitd.farm import ledger, policy

FEED_XML = (
    '<hierarchy><node content-desc="Like" bounds="[980,1400][1060,1480]"/>'
    '<node content-desc="Comment" bounds="[980,1520][1060,1600]"/>'
    '<node content-desc="Profile picture" bounds="[40,1900][120,1980]"/>'
    '<node content-desc="Reels" bounds="[600,2300][700,2380]"/></hierarchy>'
)


class FakeDevice:
    serial = "fake-skill"

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

    # ghost Element.find() needs these two
    def find_bounds(self, xml, *, text=None, content_desc=None, resource_id=None, class_name=None):
        from gitd.bots.common.adb import Device

        return Device.find_bounds(self, xml, text=text, content_desc=content_desc, resource_id=resource_id, class_name=class_name)

    def bounds_center(self, b):
        from gitd.bots.common.adb import Device

        return Device.bounds_center(self, b)


class ScreenDevice(FakeDevice):
    """A fake phone whose screen can change: a tap inside a known box flips state.

    ``HumanInput.tap`` emits a *very short* ``input swipe`` (a real finger-down
    duration), so a tap is recognised here by its near-zero travel — that is
    also what keeps the "no bare ``input tap``" assertion meaningful.
    """

    serial = "fake-screen"

    def __init__(self):
        super().__init__()
        self.taps = []

    def adb(self, *args, timeout=30):
        out = super().adb(*args, timeout=timeout)
        if args[:3] == ("shell", "input", "swipe") and len(args) >= 7:
            x1, y1, x2, y2 = (int(a) for a in args[3:7])
            if abs(x2 - x1) <= 30 and abs(y2 - y1) <= 30:
                self.taps.append((x1, y1))
                self.on_tap(x1, y1)
        return out

    def on_tap(self, x, y):  # pragma: no cover - overridden
        pass

    def dump_xml(self):
        return self.screen()

    def screen(self):  # pragma: no cover - overridden
        raise NotImplementedError


def _postable_account(db, platform, device_serial, prefix, days=40, action=policy.POST):
    """A cruise-phase account whose "today" is not its weekly rest day.

    The rest day is seeded from the account key, which carries the row id, so
    the only way to land on a non-resting account is to insert another row —
    one per fake device, since a device carries one account per platform (R8).
    """
    created = date.today() - timedelta(days=days)
    for i in range(40):
        acc = ledger.add_account(
            db, platform=platform, handle=f"{prefix}{i}", device_serial=f"{device_serial}-{i}", created_on=created
        )
        budget = ledger.budget_for(acc)
        if not budget.rest_day and budget.caps[action]:
            return acc
    raise AssertionError("could not build a non-rest-day account")  # pragma: no cover


@pytest.fixture()
def db():
    """A clean ledger. SQLite reuses row ids, so the action rows of a deleted
    account would otherwise be inherited by the next one and eat its budget."""
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


# ── loading ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "skill_name,workflows",
    [
        ("ofmai_instagram", {"warm_session", "post_video", "post_photo", "post_story", "comment_reply", "dm_reply"}),
        ("ofmai_tiktok", {"warm_session", "post_video", "comment_reply", "dm_reply"}),
        # X and Reddit publish through their APIs, never from the device
        ("ofmai_x", {"warm_session", "comment_reply"}),
        ("ofmai_reddit", {"warm_session", "comment_reply"}),
    ],
)
def test_skill_loads_with_workflows(skill_name, workflows):
    mod = importlib.import_module(f"gitd.skills.{skill_name}")
    s = mod.load()
    assert s.name == skill_name
    assert set(s.list_workflows()) == workflows
    assert "open_app" in s.list_actions()
    assert s.popup_detectors
    # R34: a skill runs on a real account only once its selectors were verified
    # on a device. Reddit was (docs/social/screens-reddit-actions.md); X has no
    # device path at all (the cloud phone is refused), so it stays empty.
    tested_on = s.metadata.get("tested_on")
    assert isinstance(tested_on, list)
    if skill_name == "ofmai_x":
        assert tested_on == []
    else:
        assert tested_on and tested_on[0]["app_version"] and tested_on[0]["date"], skill_name


def test_every_platform_with_a_skill_can_be_registered():
    from gitd.farm import planner

    assert set(planner.SKILL_BY_PLATFORM) <= set(policy.PLATFORMS)
    for platform, skill_name in planner.SKILL_BY_PLATFORM.items():
        mod = importlib.import_module(f"gitd.skills.{skill_name}")
        assert "warm_session" in mod.load().list_workflows(), platform


# ── warming ───────────────────────────────────────────────────────────────────


class FakeInstagram(ScreenDevice):
    """The verified home feed (720x1440, Instagram 443): a post whose buttons
    flip their content-desc when tapped — Like -> Liked, Add to Saved ->
    Remove from saved — and an author whose profile offers Follow -> Following.
    A feed swipe brings a fresh post. The adapter records nothing it cannot
    see flip, so a static screen would end the session as action_blocked."""

    serial = "fake-instagram"
    LIKE = (30, 900, 90, 960)
    COMMENT = (110, 900, 170, 960)
    SAVE = (630, 900, 690, 960)
    AUTHOR = (80, 200, 300, 240)
    FOLLOW = (400, 300, 700, 360)

    def __init__(self):
        super().__init__()
        self.liked = self.saved = self.followed = False
        self.view = "feed"

    def adb(self, *args, timeout=30):
        out = super().adb(*args, timeout=timeout)
        if args[:3] == ("shell", "wm", "size"):
            return "Physical size: 720x1440"
        if args[:3] == ("shell", "input", "swipe") and len(args) >= 7:
            x1, y1, x2, y2 = (int(a) for a in args[3:7])
            if abs(y2 - y1) > 30 and self.view == "feed":
                self.liked = self.saved = False  # a new post
        return out

    @staticmethod
    def _in(x, y, box, pad=30):
        return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad

    def on_tap(self, x, y):
        if self.view == "feed":
            if self._in(x, y, self.LIKE):
                self.liked = True
            elif self._in(x, y, self.SAVE):
                self.saved = True
            elif self._in(x, y, self.AUTHOR):
                self.view = "profile"
        elif self.view == "profile" and self._in(x, y, self.FOLLOW):
            self.followed = True

    def back(self, delay=1.0):
        super().back(delay)
        self.view = "feed"

    def screen(self):
        rid = "com.instagram.android:id/"
        if self.view == "profile":
            label = "Following jordan.reed.97" if self.followed else "Follow jordan.reed.97"
            return (
                "<hierarchy>"
                f'<node resource-id="{rid}profile_header_follow_button" content-desc="{label}" bounds="[400,300][700,360]"/>'
                f'<node resource-id="{rid}profile_header_familiar_followers_value" text="12" bounds="[300,200][360,240]"/>'
                "</hierarchy>"
            )
        return (
            "<hierarchy>"
            f'<node content-desc="Home" resource-id="{rid}feed_tab" bounds="[42,1300][102,1350]"/>'
            f'<node content-desc="Search and explore" resource-id="{rid}search_tab" bounds="[474,1300][534,1350]"/>'
            f'<node resource-id="{rid}row_feed_photo_profile_name" text="jordan.reed.97" bounds="[80,200][300,240]"/>'
            f'<node resource-id="{rid}row_feed_photo_imageview" content-desc="Photo by jordan.reed.97, 12 likes" bounds="[0,250][720,880]"/>'
            f'<node resource-id="{rid}row_feed_button_like" content-desc="{"Liked" if self.liked else "Like"}" bounds="[30,900][90,960]"/>'
            f'<node resource-id="{rid}row_feed_button_comment" content-desc="Comment" bounds="[110,900][170,960]"/>'
            f'<node resource-id="{rid}row_feed_button_share" content-desc="Share" bounds="[190,900][250,960]"/>'
            f'<node resource-id="{rid}row_feed_button_save" content-desc="{"Remove from saved" if self.saved else "Add to Saved"}" bounds="[630,900][690,960]"/>'
            "</hierarchy>"
        )


def test_instagram_warm_session_runs_against_fake_device(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    # a network-phase account whose today is not its weekly rest day: on a rest
    # day the action correctly answers {"skipped": "rest day"} and there is no
    # session to measure (R17)
    acc = _postable_account(db, "instagram", "fake-skill", "eva_fake_", days=9, action=policy.LIKE)
    # the account lives in New York time: its "today" may lag the container's UTC date
    expected_day = (ledger.local_today(acc) - (date.today() - timedelta(days=9))).days + 1

    mod = importlib.import_module("gitd.skills.ofmai_instagram")
    skill = mod.load()
    dev = FakeInstagram()
    wf = skill.get_workflow("warm_session", dev, handle=f"@{acc.handle}", minutes=10, seed=5, comments="nice\ncool")
    result = wf.run()
    assert result.success, result.error
    step = result.data["step_results"][0]["data"]
    assert step["videos"] > 10
    assert step["phase"] == "network"
    assert step["day_of_life"] == expected_day
    assert step.get("health") is None  # a feed whose buttons flip never trips the silent guard
    # every gesture went through humanised swipes, never a bare `input tap`
    taps = [c for c in dev.calls if c[:3] == ("shell", "input", "tap")]
    assert taps == []
    swipes = [c for c in dev.calls if c[:3] == ("shell", "input", "swipe")]
    assert len(swipes) >= step["videos"]  # at least one feed swipe per video, plus taps


def test_warm_session_refuses_unregistered_handle():
    mod = importlib.import_module("gitd.skills.ofmai_tiktok")
    skill = mod.load()
    wf = skill.get_workflow("warm_session", FakeDevice(), handle="ghost_nobody", minutes=1)
    result = wf.run()
    assert not result.success
    assert "not registered" in (result.error or "")


# ── E3.5: the TikTok AIGC toggle follows params.aigc_label ────────────────────


def _tiktok_post_xml(aigc: bool | None) -> str:
    """The publish screen. ``aigc=None`` means the toggle is not on screen at all."""
    toggle = ""
    if aigc is not None:
        state = "true" if aigc else "false"
        toggle = f'<node text="AI-generated content" checked="{state}" bounds="[100,900][900,1000]"/>'
    return (
        "<hierarchy>"
        '<node content-desc="Like" bounds="[980,1400][1060,1480]"/>'
        '<node content-desc="Comment" bounds="[980,1520][1060,1600]"/>'
        '<node content-desc="Create" resource-id="com.zhiliaoapp.musically:id/m76" bounds="[500,2300][580,2380]"/>'
        '<node text="Upload" bounds="[760,1700][960,1780]"/>'
        '<node content-desc="Video" bounds="[100,300][260,460]"/>'
        '<node text="Next" bounds="[840,180][1000,260]"/>'
        '<node text="Describe your video" resource-id="com.zhiliaoapp.musically:id/caption_input" bounds="[60,500][1000,700]"/>'
        + toggle
        + '<node text="Post" bounds="[700,2100][1000,2170]"/>'
        "</hierarchy>"
    )


class TikTokPostDevice(ScreenDevice):
    serial = "fake-tt-post"

    def __init__(self, aigc: bool | None):
        super().__init__()
        self.aigc = aigc
        self.toggle_taps = 0

    def screen(self):
        return _tiktok_post_xml(self.aigc)

    def on_tap(self, x, y):
        # the AI-generated-content row, generously padded for the hand tremor
        if self.aigc is not None and 60 <= x <= 940 and 860 <= y <= 1040:
            self.toggle_taps += 1
            self.aigc = not self.aigc


def _run_tiktok_post(db, dev, *, aigc_label, handle_prefix, **extra):
    from gitd.skills.ofmai_tiktok.workflows import PostVideoAction

    acc = _postable_account(db, "tiktok", dev.serial, handle_prefix)
    skill = importlib.import_module("gitd.skills.ofmai_tiktok").load()
    params = {"handle": acc.handle, "caption": "morning light", **extra}
    if aigc_label is not _MISSING:
        params["aigc_label"] = aigc_label
    action = PostVideoAction(dev, skill._elements_for_device(dev), **params)
    return acc, action.execute()


_MISSING = object()


@pytest.mark.parametrize(
    "label,on_screen,expect_ok,expect_taps",
    [
        (True, False, True, 1),  # declared, toggle off  → tapped on, published
        (True, None, False, 0),  # declared, no toggle   → refused
        (True, True, True, 0),  # declared, already on  → left alone, published
        (False, False, True, 0),  # undeclared, toggle off → never touched
        (False, None, False, 0),  # undeclared, no toggle → refused (state unknown)
        (False, True, False, 0),  # undeclared, left on by the previous post → refused
    ],
)
def test_tiktok_post_aigc_follows_label(monkeypatch, db, label, on_screen, expect_ok, expect_taps):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = TikTokPostDevice(on_screen)
    acc, result = _run_tiktok_post(db, dev, aigc_label=label, handle_prefix=f"tt_{label}_{on_screen}_")
    assert result.success is expect_ok, result.error
    assert dev.toggle_taps == expect_taps
    if expect_ok:
        assert result.data["aigc"] is label
        assert dev.aigc is label  # the screen really ends up in that state
        assert ledger.spent_on(db, acc, ledger.local_today(acc)).get(policy.POST) == 1
    else:
        assert result.error == "aigc toggle not confirmed"
        # nothing was published: the post budget is untouched
        assert ledger.spent_on(db, acc, ledger.local_today(acc)).get(policy.POST) is None


def test_tiktok_post_refuses_without_an_aigc_label(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = TikTokPostDevice(False)
    acc, result = _run_tiktok_post(db, dev, aigc_label=_MISSING, handle_prefix="tt_none_")
    assert not result.success
    assert "aigc_label is required" in result.error
    assert dev.toggle_taps == 0
    assert ledger.spent_on(db, acc, ledger.local_today(acc)).get(policy.POST) is None


def test_aigc_label_parsing_is_strict():
    from gitd.skills.ofmai_tiktok.workflows import parse_aigc_label

    assert parse_aigc_label(True) is True
    assert parse_aigc_label(False) is False
    assert parse_aigc_label("true") is True
    assert parse_aigc_label("false") is False
    for junk in (None, "", "maybe", "  ", 2.5):
        assert parse_aigc_label(junk) is None


# ── E3.6: Instagram post_photo ────────────────────────────────────────────────

# the composers reach the home feed first (the "+" only lives there), so the
# scripted screen carries a feed pair too
_IG_FEED_PAIR = (
    '<node content-desc="Home" resource-id="com.instagram.android:id/feed_tab" bounds="[100,2300][180,2380]"/>'
    '<node content-desc="Like" bounds="[30,1500][90,1560]"/><node content-desc="Comment" bounds="[110,1500][170,1560]"/>'
)
_IG_POST_XML = (
    "<hierarchy>" + _IG_FEED_PAIR +
    '<node content-desc="Create" resource-id="com.instagram.android:id/creation_tab" bounds="[500,2300][580,2380]"/>'
    '<node text="POST" bounds="[300,2180][420,2250]"/>'
    '<node resource-id="com.instagram.android:id/gallery_grid_item_thumbnail" bounds="[40,400][360,720]"/>'
    '<node content-desc="Next" bounds="[880,180][1030,260]"/>'
    '<node text="Write a caption..." resource-id="com.instagram.android:id/caption_input_text_view" bounds="[60,760][1000,900]"/>'
    '<node text="Share" bounds="[700,2100][1000,2170]"/>'
    "</hierarchy>"
)
_IG_DONE_XML = (
    "<hierarchy>"
    '<node content-desc="Home" resource-id="com.instagram.android:id/feed_tab" bounds="[100,2300][180,2380]"/>'
    '<node text="Posted" bounds="[100,300][900,360]"/>'
    "</hierarchy>"
)


class InstagramPostDevice(ScreenDevice):
    serial = "fake-ig-post"

    def __init__(self):
        super().__init__()
        self.shared = False

    def screen(self):
        return _IG_DONE_XML if self.shared else _IG_POST_XML

    def on_tap(self, x, y):
        if 660 <= x <= 1040 and 2050 <= y <= 2220:  # the Share button, padded
            self.shared = True


def test_instagram_post_photo(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = InstagramPostDevice()
    acc = _postable_account(db, "instagram", dev.serial, "ig_photo_")
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    wf = skill.get_workflow("post_photo", dev, handle=acc.handle, caption="sunday morning")
    result = wf.run()
    assert result.success, result.error
    step = result.data["step_results"][0]["data"]
    assert step["format"] == "feed"
    assert dev.shared
    # the shared POST budget is spent, like a Reel would have spent it (R14)
    assert ledger.spent_on(db, acc, ledger.local_today(acc)).get(policy.POST) == 1
    # humanised gestures only
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []


def test_instagram_post_photo_refuses_when_the_post_budget_is_spent(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = InstagramPostDevice()
    acc = _postable_account(db, "instagram", dev.serial, "ig_spent_")
    session = ledger.open_session("instagram", acc.handle, db)
    session.record(policy.POST, "already posted today")

    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    wf = skill.get_workflow("post_photo", dev, handle=acc.handle, caption="second one")
    result = wf.run()
    assert not result.success
    assert "post budget exhausted" in result.error
    assert not dev.shared


# ── E3.4: Instagram post_story ────────────────────────────────────────────────

# Hit boxes are kept far apart on purpose. Every tap goes through
# `HumanInput.tap`, which jitters by a few pixels (`tap_sigma` 4-9 px): two
# adjacent boxes would let a tap on one land on the other every few hundred
# runs, and the test would fail with no code change behind it.
_IG_STORY_XML = (
    "<hierarchy>" + _IG_FEED_PAIR +
    '<node content-desc="Create" resource-id="com.instagram.android:id/creation_tab" bounds="[500,2300][580,2380]"/>'
    '<node text="STORY" bounds="[700,2300][860,2370]"/>'
    '<node resource-id="com.instagram.android:id/gallery_grid_item_thumbnail" bounds="[40,400][360,720]"/>'
    '<node text="Share to" bounds="[60,1100][400,1160]"/>'
    '<node content-desc="Your story" text="Your story" bounds="[60,1200][400,1280]"/>'
    "</hierarchy>"
)
_IG_STORY_DONE_XML = (
    "<hierarchy>"
    '<node content-desc="Home" resource-id="com.instagram.android:id/feed_tab" bounds="[100,2300][180,2380]"/>'
    '<node content-desc="Your story" bounds="[100,300][200,400]"/>'  # the home ring, not the composer
    "</hierarchy>"
)


class InstagramStoryDevice(ScreenDevice):
    serial = "fake-ig-story"

    def __init__(self):
        super().__init__()
        self.shared = False

    def screen(self):
        return _IG_STORY_DONE_XML if self.shared else _IG_STORY_XML

    def on_tap(self, x, y):
        if 20 <= x <= 440 and 1160 <= y <= 1320:  # the "Your story" button, padded
            self.shared = True


def test_instagram_post_story(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = InstagramStoryDevice()
    acc = _postable_account(db, "instagram", dev.serial, "ig_story_", action=policy.STORY_POST)
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    wf = skill.get_workflow("post_story", dev, handle=acc.handle)
    result = wf.run()
    assert result.success, result.error
    assert result.data["step_results"][0]["data"]["format"] == "story"
    assert dev.shared
    spent = ledger.spent_on(db, acc, ledger.local_today(acc))
    assert spent.get(policy.STORY_POST) == 1
    # a story is not a publication: the feed post of the day is still available
    assert spent.get(policy.POST) is None
    assert ledger.tracker_for(db, acc).allow(policy.POST)
    # the home feed's own "Your story" ring (a content-desc) does not keep the
    # postcondition from clearing — only a composer button (a text) would
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []


def test_instagram_post_story_is_capped_at_one_a_day(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = InstagramStoryDevice()
    acc = _postable_account(db, "instagram", dev.serial, "ig_story2_", action=policy.STORY_POST)
    session = ledger.open_session("instagram", acc.handle, db)
    session.record(policy.STORY_POST)

    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    result = skill.get_workflow("post_story", dev, handle=acc.handle).run()
    assert not result.success
    assert "story budget exhausted" in result.error
    assert not dev.shared


def test_no_story_and_no_dm_reply_where_the_platform_has_none():
    """TikTok has no story workflow; X and Reddit answer no DM in V1 (publishing.md §9)."""
    for skill_name, absent in [
        ("ofmai_tiktok", {"post_story"}),
        ("ofmai_x", {"post_story", "dm_reply", "post_video", "post_photo"}),
        ("ofmai_reddit", {"post_story", "dm_reply", "post_video", "post_photo"}),
    ]:
        workflows = set(importlib.import_module(f"gitd.skills.{skill_name}").load().list_workflows())
        assert workflows & absent == set(), skill_name


def test_instagram_a_suggested_reel_is_not_a_feed_post():
    """Seen on the explorer (2026-09-22): the home feed opened on a "Suggested
    Reel by …, 8,732 likes" carousel; a *contains* match on "like" took it for
    a post and tapped its middle. Only the exact label, or the id, is a button."""
    import importlib

    from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
    from gitd.skills.ofmai_instagram.actions.core import InstagramAdapter

    dev = FakeDevice()
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    ad = InstagramAdapter(dev, skill._elements_for_device(dev), HumanInput(dev, SessionProfile.generate(1), screen=ScreenSize(720, 1440), sleep=lambda s: None))
    carousel = (
        '<hierarchy><node content-desc="Suggested Reel by Ben Francis MBE, 8,732 likes, 86 comments" bounds="[0,300][720,1100]"/>'
        '<node content-desc="Follow Ben Francis MBE" bounds="[500,1120][700,1170]"/></hierarchy>'
    )
    assert not ad.on_feed(carousel)
    assert ad._like_node(carousel) is None
    assert ad.on_feed(FEED_XML)  # the exact "Like" + "Comment" pair still is a feed


def test_instagram_the_saved_sheet_is_closed_and_is_not_the_feed():
    """The first save opens "Saved — Collect the posts you love" (seen on the
    explorer 2026-09-22); it swallowed three sessions of swipes. It is not the
    feed, and settling it is one Back."""
    import importlib

    from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
    from gitd.skills.ofmai_instagram.actions.core import InstagramAdapter

    dev = FakeDevice()
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    ad = InstagramAdapter(dev, skill._elements_for_device(dev), HumanInput(dev, SessionProfile.generate(1), screen=ScreenSize(720, 1440), sleep=lambda s: None))
    sheet = FEED_XML.replace("</hierarchy>", '<node text="Collect the posts you love" bounds="[40,860][680,900]"/><node text="Start a collection" bounds="[40,1220][680,1290]"/></hierarchy>')
    assert not ad.on_feed(sheet)
    assert ad._settle(sheet) is True
    assert ("back",) in dev.calls


# ── TikTok: what the explorer showed on 2026-09-22 (46.8.2, 720x1440) ─────────


def _tt_feed(*, likes="Like video. 6,589 likes", like_text="6,589", liked=False, fav_text="27.2K", comments="Read or add comments. 8 comments"):
    """One For You post as dumped on the explorer: the counts of the like and
    the favourite are text nodes drawn INSIDE their buttons; a lit like is
    labelled "Video liked" and loses the count from its label."""
    like_desc = "Video liked" if liked else likes
    return (
        "<hierarchy>"
        '<node content-desc="Search" bounds="[20,1241][46,1267]"/>'  # the bottom "Search · suggestion" bar comes FIRST
        '<node content-desc="Search" bounds="[629,41][720,132]"/>'  # the magnifier
        '<node content-desc="Ashley_Recipes profile" bounds="[634,634][707,707]"/>'
        '<node content-desc="Follow Ashley_Recipes" bounds="[621,678][720,733]"/>'
        f'<node content-desc="{like_desc}" bounds="[616,733][720,831]"/>'
        '<node content-desc="Like" bounds="[635,733][708,806]"/>'
        f'<node text="{like_text}" bounds="[616,806][720,820]"/>'
        f'<node content-desc="{comments}" bounds="[616,831][720,929]"/>'
        '<node content-desc="Add or remove this video from Favorites." bounds="[616,929][720,1027]"/>'
        f'<node text="{fav_text}" bounds="[616,1002][720,1016]"/>'
        '<node content-desc="Share video. 17.6K shares" bounds="[616,1027][720,1125]"/>'
        '<node text="17.6K" bounds="[623,1089][720,1123]"/>'
        '<node text="Home" bounds="[0,1332][144,1353]"/>'
        '<node text="Profile" bounds="[576,1332][720,1353]"/>'
        "</hierarchy>"
    )


def _tt_adapter(dev):
    from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
    from gitd.skills.ofmai_tiktok.actions.core import TikTokAdapter

    skill = importlib.import_module("gitd.skills.ofmai_tiktok").load()
    return TikTokAdapter(dev, skill._elements_for_device(dev), HumanInput(dev, SessionProfile.generate(1), screen=ScreenSize(720, 1440), sleep=lambda s: None))


def test_tiktok_counts_are_read_as_the_device_writes_them():
    from gitd.skills.ofmai_tiktok.actions.core import parse_count

    assert parse_count("Like video. 6,589 likes") == (6589, False)  # the comma groups thousands
    assert parse_count("Like video. 51.9K likes") == (51900, True)
    assert parse_count("3,514") == (3514, False)
    assert parse_count("Read or add comments. Add 1st comments") == (0, False)  # no comment yet
    assert parse_count("Video liked") == (None, False)


def test_tiktok_favourite_and_lit_like_counts_sit_inside_the_button():
    ad = _tt_adapter(FakeDevice())
    xml = _tt_feed()
    assert ad._count_of(xml, "favorite_button") == (27200, True)  # label carries no count
    assert ad._count_of(xml, "like_button") == (6589, False)
    assert ad._count_of(xml, "comment_button") == (8, False)
    lit = _tt_feed(liked=True, like_text="6,590")
    assert ad._count_of(lit, "like_button") == (6590, False)  # read under the "Video liked" label


def test_tiktok_never_unlikes_a_video_already_liked():
    """The bare "Like" node inside the button never changes: read alone it
    passed a lit video for a fresh one, and the second tap would have unliked it."""
    dev = FakeDevice()
    dev.dump_xml = lambda: _tt_feed(liked=True, like_text="6,590")
    ad = _tt_adapter(dev)
    assert ad.like(dev.dump_xml()) is False
    assert ad.last_gesture_silent is False
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "swipe")] == []


def test_tiktok_search_taps_the_magnifier_not_the_suggestion_bar():
    class Dev(FakeDevice):
        def dump_xml(self):
            return _tt_feed()

    dev = Dev()
    ad = _tt_adapter(dev)
    ad.detour("search", "fitness")
    first = next(c for c in dev.calls if c[:3] == ("shell", "input", "swipe"))
    x, y = int(first[3]), int(first[4])
    assert y < 200 and x > 600, (x, y)  # top right, not the bar at y=1254


def test_tiktok_follow_is_proven_only_by_the_own_following_count():
    """Both UI flips the explorer showed — the feed's "+" vanishing, the
    profile button turning into "Message" — happened while the account's own
    Following stayed at 0. Only that count proves a follow."""

    class Dev(FakeDevice):
        def __init__(self):
            super().__init__()
            self.view = "feed"
            self.following = 0
            self.persists = True

        def adb(self, *args, timeout=30):
            out = super().adb(*args, timeout=timeout)
            if args[:3] == ("shell", "input", "swipe") and len(args) >= 7:
                x, y = int(args[3]), int(args[4])
                if abs(int(args[5]) - x) <= 30 and abs(int(args[6]) - y) <= 30:
                    self.on_tap(x, y)
            return out

        def on_tap(self, x, y):
            if self.view in ("feed", "profile") and 1300 <= y <= 1380:  # the tab bar: Home left, Profile right
                self.view = "profile" if x > 500 else "feed"
            elif self.view == "feed" and 620 <= x <= 720 and 600 <= y <= 720:
                self.view = "author"
            elif self.view == "author" and 129 <= x <= 318 and 423 <= y <= 495:
                self.view = "author_followed"
                if self.persists:
                    self.following += 1

        def back(self, delay=1.0):
            self.calls.append(("back",))
            if self.view in ("author", "author_followed", "profile"):
                self.view = "feed"

        def dump_xml(self):
            if self.view == "feed":
                return _tt_feed()
            if self.view == "profile":
                return (
                    "<hierarchy>"
                    f'<node text="{self.following}" bounds="[114,348][277,384]"/><node text="Following" bounds="[114,381][277,407]"/>'
                    '<node text="0" bounds="[336,348][383,384]"/><node text="Followers" bounds="[314,384][405,407]"/>'
                    '<node text="Home" bounds="[0,1332][144,1353]"/><node text="Profile" bounds="[576,1332][720,1353]"/>'
                    "</hierarchy>"
                )
            button = '<node text="Follow" bounds="[129,423][318,495]"/><node text="Message" bounds="[324,423][513,495]"/>'
            if self.view == "author_followed":  # what TikTok shows after the tap: Message + the suggested strip
                button = '<node text=" Message" bounds="[148,423][416,495]"/><node text="Follow" bounds="[45,897][267,943]"/>'
            return (
                "<hierarchy>"
                '<node text="61" bounds="[114,348][277,384]"/><node text="Following" bounds="[114,381][277,407]"/>'
                '<node text="56.1K" bounds="[324,348][396,384]"/><node text="Followers" bounds="[314,384][405,407]"/>' + button + "</hierarchy>"
            )

    for persists, expected in ((True, True), (False, False)):
        dev = Dev()
        dev.persists = persists
        ad = _tt_adapter(dev)
        assert ad.open_author(dev.dump_xml()) == "Ashley_Recipes"
        assert ad._following == 0  # the baseline was read from the feed before leaving it
        assert dev.view == "author"
        assert ad.follow(dev.dump_xml()) is expected
        assert ad.last_gesture_silent is (not expected)
        assert dev.view == "feed"


def test_instagram_an_at_handle_search_watches_that_accounts_reels():
    """The oriented warm-up: "@handle" in the niche list means search the
    account, open its profile, its Reels tab, and watch a run of its Reels —
    never the untrained Reels feed (warming-policy.md, chauffe orientée)."""
    import importlib

    from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
    from gitd.skills.ofmai_instagram.actions.core import InstagramAdapter

    rid = "com.instagram.android:id/"
    screens = {
        "feed": f'<hierarchy><node content-desc="Search and explore" resource-id="{rid}search_tab" bounds="[474,1300][534,1350]"/></hierarchy>',
        "search": f'<hierarchy><node resource-id="{rid}action_bar_search_edit_text" bounds="[60,60][600,120]"/></hierarchy>',
        "results": f'<hierarchy><node resource-id="{rid}row_search_user_username" text="gymshark" bounds="[80,200][400,240]"/></hierarchy>',
        "profile": (
            f'<hierarchy><node resource-id="{rid}profile_header_follow_button" content-desc="Follow Gymshark" bounds="[20,413][219,465]"/>'
            f'<node resource-id="{rid}profile_tab_icon_view" content-desc="Grid view" bounds="[100,700][260,760]"/>'
            f'<node resource-id="{rid}profile_tab_icon_view" content-desc="Reels" bounds="[300,700][460,760]"/></hierarchy>'
        ),
        "grid": '<hierarchy><node content-desc="Reel by Gymshark at Row 1, Column 1" bounds="[0,800][240,1120]"/></hierarchy>',
        "viewer": '<hierarchy><node content-desc="Like" bounds="[640,900][700,960]"/><node content-desc="Comment" bounds="[640,1000][700,1060]"/></hierarchy>',
    }

    class Dev(ScreenDevice):
        serial = "fake-reels"

        def __init__(self):
            super().__init__()
            self.view = "feed"
            self.reels_seen = 0

        def adb(self, *args, timeout=30):
            out = super().adb(*args, timeout=timeout)
            if args[:3] == ("shell", "wm", "size"):
                return "Physical size: 720x1440"
            if args[:3] == ("shell", "input", "swipe") and len(args) >= 7 and self.view == "viewer":
                x1, y1, x2, y2 = (int(a) for a in args[3:7])
                if abs(y2 - y1) > 30:
                    self.reels_seen += 1
            return out

        def on_tap(self, x, y):
            self.view = {"feed": "search", "search": "results", "results": "profile", "profile": "grid", "grid": "viewer"}.get(self.view, self.view)

        def back(self, delay=1.0):
            super().back(delay)
            self.view = "feed"

        def screen(self):
            return screens[self.view]

    dev = Dev()
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    ad = InstagramAdapter(dev, skill._elements_for_device(dev), HumanInput(dev, SessionProfile.generate(4), screen=ScreenSize(720, 1440), sleep=lambda s: None))
    assert ad.detour("search", "@gymshark") is True
    assert dev.reels_seen >= 4  # a run of Reels, not one
    assert dev.view == "feed"  # left with Back


def test_tiktok_an_at_handle_search_watches_that_accounts_videos():
    """Same oriented run as Instagram (warming-policy.md §7 bis): the handle is
    searched, the Users tab opened, the profile's first video played and a run
    of its videos watched — the For You feed is never entered."""
    import importlib

    from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
    from gitd.skills.ofmai_tiktok.actions.core import TikTokAdapter

    rid = "com.zhiliaoapp.musically:id/"
    rail = '<node content-desc="Like video. 5,120 likes" bounds="[640,800][700,860]"/><node content-desc="Read or add comments. 91 comments" bounds="[640,900][700,960]"/>'
    screens = {
        "feed": '<hierarchy>' + rail + '<node content-desc="Search" bounds="[640,40][700,100]"/><node text="Home" bounds="[40,1300][100,1340]"/></hierarchy>',
        "search": '<hierarchy><node class="android.widget.EditText" text="" bounds="[60,40][600,100]"/></hierarchy>',
        "results": '<hierarchy><node text="Users" bounds="[200,140][300,180]"/><node text="gymshark" bounds="[80,300][400,340]"/></hierarchy>',
        "profile": f'<hierarchy><node text="Followers" bounds="[300,400][400,430]"/><node resource-id="{rid}cover" bounds="[0,600][240,900]"/><node resource-id="{rid}cover" bounds="[240,600][480,900]"/></hierarchy>',
        "viewer": '<hierarchy>' + rail + '</hierarchy>',
    }

    class Dev(ScreenDevice):
        serial = "fake-tt-reels"

        def __init__(self):
            super().__init__()
            self.view = "feed"
            self.videos_seen = 0
            self.enters = 0

        def adb(self, *args, timeout=30):
            out = super().adb(*args, timeout=timeout)
            if args[:3] == ("shell", "wm", "size"):
                return "Physical size: 720x1440"
            if args[:3] == ("shell", "input", "swipe") and len(args) >= 7 and self.view == "viewer":
                x1, y1, x2, y2 = (int(a) for a in args[3:7])
                if abs(y2 - y1) > 30:
                    self.videos_seen += 1
            return out

        def press_enter(self, delay=0.5):
            self.enters += 1
            if self.view == "search":
                self.view = "results"

        def on_tap(self, x, y):
            if self.view == "feed" and 20 <= y <= 120:
                self.view = "search"
            elif self.view == "results" and 280 <= y <= 360:
                self.view = "profile"
            elif self.view == "profile" and y >= 580:
                self.view = "viewer"

        def back(self, delay=1.0):
            super().back(delay)
            self.view = "feed"

        def screen(self):
            return screens[self.view]

    dev = Dev()
    skill = importlib.import_module("gitd.skills.ofmai_tiktok").load()
    ad = TikTokAdapter(dev, skill._elements_for_device(dev), HumanInput(dev, SessionProfile.generate(4), screen=ScreenSize(720, 1440), sleep=lambda s: None))
    assert ad.detour("search", "@gymshark") is True
    assert dev.enters == 1 and dev.videos_seen >= 4
    assert dev.view == "feed"
