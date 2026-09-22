"""The Reddit warming adapter, driven against a little Reddit of its own.

Every id, label and screen below comes from the survey on GeeLark
``explorer-us`` (Reddit 2026.35.0, 720x1440 — docs/social/screens-reddit.md
and screens-reddit-actions.md). Compose gives the vote buttons no id and no
label, so the fake renders the same ids the app does and answers taps by
geometry, the way the app does — and it can be told to be *dishonest*: to
swallow every gesture without changing anything on screen, which is what a
throttled account looks like from the outside.

What is checked here is the adapter's reasoning: which point it taps, what it
accepts as proof, when it declares a gesture silent, and the two Reddit rules
that get accounts banned — the downvote is never tapped, a community is never
left.
"""

import importlib
import shlex
from datetime import date, timedelta

import pytest

from gitd.farm import ledger
from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
from gitd.skills.ofmai_reddit.actions.core import FOOTER_X, RedditAdapter, _is_upvote_orange, comment_count
from gitd.skills.ofmai_reddit.actions.replies import RedditCommentAdapter
from tests.farm_helpers import typed_text

RID = ""  # Compose ids are bare on the device: resource-id="post_footer"
FOOTER = (0, 820, 720, 900)
JOIN = (560, 215, 660, 265)
MORE = (660, 215, 710, 265)
SEARCH_ICON = (640, 40, 700, 100)
HOME_TAB = (60, 1300, 120, 1340)
YOU_TAB = (600, 1300, 660, 1340)
POSTS_TAB = (20, 400, 120, 440)
CONVERSATION_BAR = (0, 1280, 640, 1340)
SEND = (640, 1290, 700, 1330)
COMMENT_FOOTER = (60, 700, 720, 760)
GOT_IT = (200, 1200, 520, 1260)
NOT_REALLY = (100, 1100, 300, 1150)
ORANGE = (255, 69, 0)
GREY = (120, 120, 120)
TITLE = "TIL the Master Sword was almost a spear"


def _fx(key: str) -> int:
    return int(FOOTER[0] + FOOTER_X[key] * (FOOTER[2] - FOOTER[0]))


def _inside(x, y, box, pad=30) -> bool:
    x1, y1, x2, y2 = box
    return x1 - pad <= x <= x2 + pad and y1 - pad <= y <= y2 + pad


def _node(rid=None, text=None, desc=None, bounds=None) -> str:
    attrs = []
    if rid:
        attrs.append(f'resource-id="{RID}{rid}"')
    if text is not None:
        attrs.append(f'text="{text}"')
    if desc is not None:
        attrs.append(f'content-desc="{desc}"')
    x1, y1, x2, y2 = bounds
    attrs.append(f'bounds="[{x1},{y1}][{x2},{y2}]"')
    return "<node " + " ".join(attrs) + "/>"


class FakeReddit:
    """A 720x1440 Reddit that renders its screen from a little state."""

    serial = "fake-reddit"

    def __init__(self, *, honest=True, upvoted=False, joined=False, saved=False, screen="feed"):
        self.calls = []
        self.honest = honest
        self.upvoted, self.joined, self.saved = upvoted, joined, saved
        self.screen = screen  # feed | sheet | post | search | profile
        self.composer = False
        self.comments = 12
        self.posted: list[str] = []
        self.typed = ""
        self.query = ""
        self.searched: list[str] = []
        self.overlay = ""  # an interstitial drawn on top of the screen
        self.downvotes = self.unsaves = self.leaves = self.cards = 0

    # ── rendering ────────────────────────────────────────────────────

    def dump_xml(self) -> str:
        body = getattr(self, f"_render_{self.screen}")()
        return "<hierarchy>" + body + self.overlay + "</hierarchy>"

    def _nav(self) -> str:
        return (
            _node(text="Home", bounds=HOME_TAB)
            + _node(text="You", bounds=YOU_TAB)
            + _node(rid="main_top_app_bar_search", bounds=SEARCH_ICON)
        )

    def _card(self) -> str:
        return (
            _node(rid="post_unit", bounds=(0, 200, 720, 900))
            + _node(rid="post_header", bounds=(0, 200, 720, 280))
            + _node(rid="post_join_button", text="Joined" if self.joined else "Join", bounds=JOIN)
            + _node(rid="post_overflow", bounds=MORE)
            + _node(text=TITLE, bounds=(20, 300, 700, 360))
            + _node(rid="post_footer", bounds=FOOTER)
        )

    def _render_feed(self) -> str:
        return self._nav() + self._card()

    def _render_sheet(self) -> str:
        return (
            self._render_feed()
            + _node(rid="action_item_title", text="Share", bounds=(0, 1100, 720, 1160))
            + _node(rid="action_item_title", text="Unsave" if self.saved else "Save", bounds=(0, 1160, 720, 1220))
        )

    def _render_post(self) -> str:
        out = (
            _node(rid="title_text", text="r/zelda", bounds=(100, 40, 400, 100))
            + _node(text=f"{self.comments} comments", bounds=(20, 600, 200, 640))
            + _node(rid="comment_layout", bounds=(0, 650, 720, 770))
            + _node(rid="comment_header", desc="Level 1 comment by link_fan, 2 hours ago, 3 votes", bounds=(60, 650, 700, 690))
            + _node(text="what a great find", bounds=(60, 690, 700, 720))
            + _node(rid="fbp_comment_footer", text="3 votes", bounds=COMMENT_FOOTER)
        )
        for i, t in enumerate(self.posted):
            out += _node(text=t, bounds=(60, 800 + i * 60, 700, 850 + i * 60))
        if self.composer:
            out += _node(desc="Send comment", bounds=SEND)
        else:
            out += _node(desc="Join the conversation", bounds=CONVERSATION_BAR)
        return out

    def _render_search(self) -> str:
        return _node(rid="expanded_search_field", text=self.query or "Search Reddit", bounds=(60, 40, 660, 100)) + "".join(
            _node(text=q, bounds=(20, 300, 700, 360)) for q in self.searched
        )

    def _render_profile(self) -> str:
        return (
            self._nav()
            + _node(rid="profile_name", text="u/jordan_reed97", bounds=(20, 200, 400, 240))
            + _node(rid="profile_highlights_karma", text="1 Karma", bounds=(20, 260, 200, 300))
            + _node(rid="profile_tab_text", text="Posts", bounds=POSTS_TAB)
            + self._card()
        )

    # ── the screen as the adapter probes it ──────────────────────────

    def pixel_at(self, x, y):
        if self.upvoted and _inside(x, y, (_fx("upvote"), 860, _fx("upvote"), 860), pad=25):
            return ORANGE
        return GREY

    def find_bounds(self, xml, *, text=None, content_desc=None, resource_id=None, class_name=None):
        from gitd.bots.common.adb import Device

        return Device.find_bounds(self, xml, text=text, content_desc=content_desc, resource_id=resource_id, class_name=class_name)

    def bounds_center(self, b):
        from gitd.bots.common.adb import Device

        return Device.bounds_center(self, b)

    # ── gestures ─────────────────────────────────────────────────────

    def adb(self, *args, timeout=30):
        self.calls.append(args)
        if args[:3] == ("shell", "wm", "size"):
            return "Physical size: 720x1440"
        if args[:3] == ("shell", "input", "swipe") and len(args) >= 7:
            x1, y1, x2, y2 = (int(v) for v in args[3:7])
            if abs(x2 - x1) <= 30 and abs(y2 - y1) <= 30:
                self._tap(x1, y1)
            else:
                self._scroll()
        elif args[:3] == ("shell", "input", "text") and len(args) >= 4:
            chunk = "".join(shlex.split(args[3])).replace("%s", " ")
            if self.screen == "search":
                self.query += chunk
            else:
                self.typed += chunk
        elif args[:4] == ("shell", "input", "keyevent", "KEYCODE_DEL"):
            if self.screen == "search":
                self.query = self.query[:-1]
            else:
                self.typed = self.typed[:-1]
        return ""

    def _tap(self, x, y):
        if self.overlay:
            if _inside(x, y, NOT_REALLY) or _inside(x, y, GOT_IT):
                self.overlay = ""
            return
        s = self.screen
        if s in ("feed", "profile"):
            if _inside(x, y, (_fx("upvote"), 860, _fx("upvote"), 860)):
                self.upvoted = self.upvoted or self.honest
            elif _inside(x, y, (_fx("downvote"), 860, _fx("downvote"), 860)):
                self.downvotes += 1
            elif _inside(x, y, (_fx("comments"), 860, _fx("comments"), 860)):
                self.screen = "post"
            elif _inside(x, y, MORE):
                self.screen = "sheet"
            elif _inside(x, y, JOIN):
                if self.joined:
                    self.leaves += 1
                elif self.honest:
                    self.joined = True
            elif _inside(x, y, SEARCH_ICON):
                self.screen = "search"
            elif _inside(x, y, YOU_TAB):
                self.screen = "profile"
            elif _inside(x, y, HOME_TAB):
                self.screen = "feed"
        elif s == "sheet":
            if _inside(x, y, (0, 1160, 720, 1220), pad=0):
                if self.saved:
                    self.unsaves += 1
                elif self.honest:
                    self.saved = True
            self.screen = "feed"
        elif s == "post":
            if _inside(x, y, SEND, pad=10) and self.composer:
                if self.typed and self.honest:
                    self.comments += 1
                    self.posted.append(self.typed)
                self.typed = ""
                self.composer = False
            elif _inside(x, y, CONVERSATION_BAR, pad=10) or _inside(x, y, COMMENT_FOOTER, pad=10):
                self.composer = True

    def _scroll(self):
        if self.screen == "feed":  # a new card comes up
            self.cards += 1
            self.upvoted = self.joined = self.saved = False

    def back(self, delay=1.0):
        self.calls.append(("back",))
        if self.composer:
            self.composer = False
        elif self.screen != "feed":
            self.screen = "feed"

    def press_enter(self, delay=0.5):
        self.calls.append(("enter",))
        if self.screen == "search" and self.query:
            self.searched.append(self.query)

    def dismiss_popups(self, xml=None, popups=None):
        return False

    def taps(self):
        out = []
        for c in self.calls:
            if c[:3] == ("shell", "input", "swipe") and len(c) >= 7:
                x1, y1, x2, y2 = (int(v) for v in c[3:7])
                if abs(x2 - x1) <= 30 and abs(y2 - y1) <= 30:
                    out.append((x1, y1))
        return out


WELCOME_SHEET = _node(text="Welcome to the r/zelda community", bounds=(40, 1000, 680, 1060)) + _node(
    rid="got_it_button", text="Got it", bounds=GOT_IT
)
SURVEY = _node(text="Are you enjoying Reddit?", bounds=(40, 1040, 680, 1090)) + _node(text="Not really", bounds=NOT_REALLY)


def _adapter(cls=RedditAdapter, **state):
    dev = FakeReddit(**state)
    skill = importlib.import_module("gitd.skills.ofmai_reddit").load()
    human = HumanInput(dev, SessionProfile.generate(3), screen=ScreenSize(720, 1440), sleep=lambda s: None)
    return dev, cls(dev, skill._elements_for_device(dev), human)


def _near(point, x, y, pad=30):
    return abs(point[0] - x) <= pad and abs(point[1] - y) <= pad


# ── the unit of a view is a post card ─────────────────────────────────────────


def test_on_feed_is_a_card_with_neither_conversation_bar_nor_profile_header():
    dev, ad = _adapter()
    assert ad.on_feed(dev.dump_xml())
    dev.screen = "post"
    assert not ad.on_feed(dev.dump_xml())  # the post page carries the card's footer too
    dev.screen = "profile"
    assert not ad.on_feed(dev.dump_xml())  # own posts look like a feed, are not one
    assert not ad.on_feed("")


def test_next_item_is_a_humanised_swipe_never_a_tap():
    dev, ad = _adapter()
    ad.next_video()
    assert len([c for c in dev.calls if c[:3] == ("shell", "input", "swipe")]) == 1
    assert dev.taps() == []
    assert dev.cards == 1


# ── votes: the upvote, proven by its colour; never a downvote, never a toggle ──


def test_like_taps_the_upvote_and_proves_it_by_the_orange_arrow():
    dev, ad = _adapter()
    assert ad.like(dev.dump_xml()) is True
    assert ad.last_gesture_silent is False
    assert dev.upvoted and dev.downvotes == 0
    assert any(_near(t, _fx("upvote"), 860) for t in dev.taps())
    assert not any(_near(t, _fx("downvote"), 860, pad=20) for t in dev.taps())


def test_like_never_removes_an_existing_upvote():
    dev, ad = _adapter(upvoted=True)
    assert ad.like(dev.dump_xml()) is False
    assert dev.taps() == []
    assert dev.upvoted


def test_a_like_that_changes_nothing_on_screen_is_silent_not_recorded():
    dev, ad = _adapter(honest=False)
    assert ad.like(dev.dump_xml()) is False
    assert ad.last_gesture_silent is True
    assert len(dev.taps()) == 1


def test_upvote_orange_and_comment_counter_parsers():
    assert _is_upvote_orange(*ORANGE)
    assert _is_upvote_orange(240, 90, 30)  # anti-aliased edge
    assert not _is_upvote_orange(*GREY)
    assert not _is_upvote_orange(255, 255, 255)
    assert comment_count('<node text="345 comments" bounds="[0,0][1,1]"/>') == 345
    assert comment_count('<node content-desc="1.2K comments" bounds="[0,0][1,1]"/>') == 1200
    assert comment_count('<node text="Join the conversation" bounds="[0,0][1,1]"/>') is None


# ── save lives in the overflow menu, and is proven by "Unsave" ────────────────


def test_save_goes_through_more_options_and_reopens_the_menu_to_check():
    dev, ad = _adapter()
    assert ad.save(dev.dump_xml()) is True
    assert dev.saved and dev.unsaves == 0
    assert sum(1 for t in dev.taps() if _inside(*t, MORE)) == 2  # once to save, once to verify
    assert dev.screen == "feed"  # the menu was closed again


def test_save_never_unsaves_what_is_already_saved():
    dev, ad = _adapter(saved=True)
    assert ad.save(dev.dump_xml()) is False
    assert dev.unsaves == 0
    assert ("back",) in dev.calls


def test_save_that_leaves_the_menu_unchanged_is_silent():
    dev, ad = _adapter(honest=False)
    assert ad.save(dev.dump_xml()) is False
    assert ad.last_gesture_silent is True


# ── the visit is the post page, the follow is the join (R16) ──────────────────


def test_open_author_opens_the_post_page_and_names_its_community():
    dev, ad = _adapter()
    assert ad.open_author(dev.dump_xml()) == "r/zelda"
    assert dev.screen == "post"
    assert any(_near(t, _fx("comments"), 860) for t in dev.taps())


def test_follow_from_the_post_page_comes_back_and_joins_from_the_card():
    dev, ad = _adapter(screen="post")
    assert ad.follow(dev.dump_xml()) is True
    assert dev.joined and dev.leaves == 0
    assert any(_inside(*t, JOIN) for t in dev.taps())


def test_follow_never_leaves_a_community_it_already_joined():
    dev, ad = _adapter(joined=True)
    assert ad.follow(dev.dump_xml()) is False
    assert dev.taps() == [] and dev.leaves == 0


def test_a_join_that_stays_join_is_silent():
    dev, ad = _adapter(honest=False)
    assert ad.follow(dev.dump_xml()) is False
    assert ad.last_gesture_silent is True


def test_the_welcome_sheet_and_the_survey_on_top_of_it_are_settled():
    dev, ad = _adapter()
    dev.overlay = SURVEY + WELCOME_SHEET
    assert ad._settle(dev.dump_xml()) is True
    assert any(_inside(*t, NOT_REALLY) for t in dev.taps())  # the survey first: it swallows Got it
    dev.overlay = WELCOME_SHEET
    assert ad._settle(dev.dump_xml()) is True
    assert any(_inside(*t, GOT_IT) for t in dev.taps())
    assert ad._settle(dev.dump_xml()) is False


# ── comment: proven by the counter ────────────────────────────────────────────


def test_comment_opens_the_conversation_and_proves_it_by_the_counter():
    dev, ad = _adapter()
    assert ad.comment("nice one") is True
    assert dev.comments == 13 and dev.posted == ["nice one"]
    assert typed_text(dev.calls) == "nice one"
    assert dev.screen == "feed"


def test_a_comment_the_counter_ignores_is_silent():
    dev, ad = _adapter(honest=False)
    assert ad.comment("nice one") is False
    assert ad.last_gesture_silent is True


# ── detours ───────────────────────────────────────────────────────────────────


def test_detour_is_search_only_no_stories():
    dev, ad = _adapter()
    assert ad.detour("stories", None) is False
    assert ad.detour("search", None) is False  # no query, no detour
    assert dev.taps() == []


def test_search_types_a_subreddit_and_submits_it():
    dev, ad = _adapter()
    assert ad.detour("search", "fitness") is True
    assert dev.searched == ["r/fitness"]
    assert ("enter",) in dev.calls


def test_the_reddit_skill_declares_search_as_its_only_detour():
    from gitd.skills.ofmai_reddit.workflows import RedditWarmAction

    assert RedditWarmAction.default_detours == ("search",)
    assert RedditWarmAction.platform == "reddit"


# ── karma, read on the You tab ────────────────────────────────────────────────


def test_read_karma_visits_the_you_tab_and_comes_back():
    dev, ad = _adapter()
    assert ad.read_karma() == 1
    assert dev.screen == "feed"


# ── answering under one's own post ────────────────────────────────────────────


def test_read_comments_pairs_the_header_label_with_the_body_below():
    dev, ad = _adapter(RedditCommentAdapter, screen="post")
    comments = ad.read_comments(dev.dump_xml())
    assert [(c.author, c.text) for c in comments] == [("link_fan", "what a great find")]
    assert 690 <= comments[0].y <= 720


def test_reply_goes_through_the_reply_button_of_the_row_and_is_proven_by_its_text():
    dev, ad = _adapter(RedditCommentAdapter, screen="post")
    xml = dev.dump_xml()
    comment = ad.read_comments(xml)[0]
    assert ad.reply_to_comment(comment, "thanks a lot", xml) is True
    assert dev.posted == ["thanks a lot"]
    assert ad.like_comment(comment, xml) is False  # never a vote back
    assert dev.downvotes == 0 and not dev.upvoted


def test_open_own_post_goes_you_tab_posts_first_card():
    dev, ad = _adapter(RedditCommentAdapter)
    key = ad.open_own_post()
    assert key == TITLE[:40]
    assert dev.screen == "post"


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


def _warming_account(db, prefix, days=9):
    """A network-phase account whose "today" is not its weekly rest day.

    The rest day is seeded from the account key (its row id), so the only way
    to land on a non-resting account is to insert rows until one is (R17).
    """
    from gitd.farm import policy

    created = date.today() - timedelta(days=days)
    for i in range(40):
        acc = ledger.add_account(db, platform="reddit", handle=f"{prefix}{i}", device_serial=f"fake-reddit-{i}", created_on=created)
        budget = ledger.budget_for(acc)
        if not budget.rest_day and budget.caps[policy.LIKE]:
            return acc
    raise AssertionError("could not build a non-rest-day account")  # pragma: no cover


def test_warm_session_runs_against_the_fake_reddit(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    acc = _warming_account(db, "rd_fake_")

    skill = importlib.import_module("gitd.skills.ofmai_reddit").load()
    dev = FakeReddit()
    wf = skill.get_workflow("warm_session", dev, handle=f"@{acc.handle}", minutes=10, seed=5, comments="nice\ncool")
    result = wf.run()
    assert result.success, result.error
    step = result.data["step_results"][0]["data"]
    assert step["videos"] > 10
    assert step["phase"] == "network"  # Reddit follows the Instagram calendar
    assert step.get("health") is None  # an honest app never trips the silent guard
    assert dev.downvotes == 0 and dev.leaves == 0 and dev.unsaves == 0
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []


def test_a_dishonest_reddit_ends_the_session_as_action_blocked(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    acc = _warming_account(db, "rd_mute_")

    skill = importlib.import_module("gitd.skills.ofmai_reddit").load()
    dev = FakeReddit(honest=False)
    wf = skill.get_workflow("warm_session", dev, handle=f"@{acc.handle}", minutes=10, seed=5, comments="nice\ncool")
    result = wf.run()
    step = result.data["step_results"][0]["data"]
    assert step.get("health") == "action_blocked"
    assert step["likes"] == 0  # nothing unproven reached the ledger
