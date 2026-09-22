"""Answering comments (E3.2) and DMs (E3.3).

Three layers, none of which needs a phone:

1. the pure decisions — which comment is answered, from which pool, in which
   order, and what is never typed;
2. the loop itself, against a fake adapter: caps come from the ledger, a health
   signal ends the pass, a comment already answered is not answered twice;
3. the real Instagram / Reddit adapters against XML dumps, and the two
   workflows end to end through the real ledger.

What cannot be checked here is whether the selectors match the real apps: that
is Skill Miner's job on the phone (R34), which is why `tested_on` is still empty
in every skill.yaml.
"""

import importlib
from datetime import date, timedelta

import pytest

from gitd.farm import ledger, policy, replies
from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
from gitd.farm.replies import AI, QUESTION, THANKS, Comment, DmThread
from tests.farm_helpers import typed_text

# ── 1. Pure decisions ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,kind",
    [
        ("are you real?", AI),
        ("is this AI", AI),
        ("how do you make these", AI),  # a trigger word wins over the question test
        ("what tool is this", AI),
        ("where is this gym?", QUESTION),
        ("which city", QUESTION),
        ("this is gorgeous", THANKS),
        ("love the light here", THANKS),
        ("", None),
        ("   ", None),
        ("you are ugly", None),
        ("nice, dm me at spamsite.com", None),
        ("https://t.me/whatever", None),
    ],
)
def test_classify(text, kind):
    assert replies.classify(text) == kind


def test_the_ai_words_are_the_same_four_as_the_comment_to_dm_automation():
    """publishing.md §8 triggers on real / how / ai / tool — §9 answers the same."""
    for word in ("real", "how", "ai", "tool"):
        assert replies.classify(f"hey {word} here") == AI
    # ...and not on a word that merely contains one of them
    assert replies.classify("realistic lighting") == THANKS
    assert replies.classify("what a great hairstyle") == QUESTION


def test_a_reply_is_never_typed_when_it_carries_a_link_or_an_accent():
    assert replies.is_postable("thanks! made my day")
    assert not replies.is_postable("thanks, see ofmai.ai")  # R22
    assert not replies.is_postable("https://example.org")
    assert not replies.is_postable("merci beaucoup \u00e7a va")  # R12: type_text would eat the cedilla
    assert not replies.is_postable("nice \U0001f525")
    assert not replies.is_postable("")


def test_a_dm_asking_for_a_photo_a_number_or_a_meeting_is_not_safe():
    assert replies.is_safe_dm("hey, love your posts")
    for ask in ("send me a pic", "what's your number", "can we meet", "add me on snapchat", "whatsapp?"):
        assert not replies.is_safe_dm(ask), ask


def test_post_key_is_ascii_and_short():
    key = replies.post_key("Photo by sierra.cole on September 14, 2026.")
    assert key.startswith("Photo by sierra.cole on September 14") and len(key) == 40
    assert replies.post_key("café  \n crème") == "caf crme"
    assert replies.post_key(None) == "last"
    assert replies.post_key("   ") == "last"


def test_pair_comments_matches_each_author_with_the_body_under_it():
    xml = _ig_comments_xml([("fan_one", "are you real?"), ("fan_two", "love this")])
    found = replies.pair_comments(xml, author_rid="a_rid", text_rid="t_rid")
    assert [(c.author, c.text) for c in found] == [("fan_one", "are you real?"), ("fan_two", "love this")]
    # a body is never stolen by the next author
    assert found[0].y < found[1].y


def test_pair_comments_needs_both_resource_ids():
    xml = _ig_comments_xml([("fan_one", "hi")])
    assert replies.pair_comments(xml, author_rid=None, text_rid="t_rid") == []
    assert replies.pair_comments(xml, author_rid="a_rid", text_rid=None) == []


# ── XML fixtures ──────────────────────────────────────────────────────────────


def _ig_comments_xml(comments, liked=(), rid_author="a_rid", rid_text="t_rid"):
    rows = []
    y = 600
    for author, text in comments:
        rows.append(f'<node resource-id="{rid_author}" text="{author}" bounds="[60,{y}][400,{y + 40}]"/>')
        rows.append(f'<node resource-id="{rid_text}" text="{text}" bounds="[60,{y + 50}][900,{y + 100}]"/>')
        rows.append(f'<node content-desc="{"Liked" if author in liked else "Like"}" bounds="[950,{y + 40}][1010,{y + 100}]"/>')
        rows.append(f'<node text="Reply" bounds="[420,{y + 110}][520,{y + 150}]"/>')
        y += 260
    return "<hierarchy>" + "".join(rows) + "</hierarchy>"


def _ig_full_screen(comments, liked=()):
    """Profile tab, grid, post and comment sheet at once.

    One static screen is enough for the loop: it exercises the ledger, the
    pools, the ordering and the recording. Whether the *navigation* between
    those screens is right can only be answered on a phone (R34).
    """
    head = (
        "<hierarchy>"
        '<node content-desc="Profile" resource-id="com.instagram.android:id/profile_tab" bounds="[900,2300][980,2380]"/>'
        '<node content-desc="Photo by sierra.cole on September 14" resource-id="com.instagram.android:id/media_thumbnail"'
        ' bounds="[0,300][360,660]"/>'
        '<node content-desc="Comment" bounds="[980,1520][1060,1600]"/>'
        '<node resource-id="com.instagram.android:id/layout_comment_thread_edittext" bounds="[60,2200][900,2260]"/>'
        '<node content-desc="Post" resource-id="com.instagram.android:id/layout_comment_thread_post_button"'
        ' bounds="[950,2200][1040,2260]"/>'
    )
    body = _ig_comments_xml(
        comments,
        liked,
        rid_author="com.instagram.android:id/row_comment_textview_username",
        rid_text="com.instagram.android:id/row_comment_textview_comment",
    ).replace("<hierarchy>", "").replace("</hierarchy>", "")
    return head + body + "</hierarchy>"


def _ig_dm_screen(peer="fan_one", *, unread=True, incoming="hey how do you make these", outgoing_last=False):
    bubble_x = "[600,900][1000,960]" if outgoing_last else "[60,900][600,960]"
    unread_node = f'<node content-desc="Unread" bounds="[900,500][950,560]"/>' if unread else ""
    return (
        "<hierarchy>"
        '<node content-desc="Home" resource-id="com.instagram.android:id/feed_tab" bounds="[100,2300][180,2380]"/>'
        '<node content-desc="Direct" bounds="[980,180][1050,240]"/>'
        f'<node resource-id="com.instagram.android:id/row_inbox_username" text="{peer}" bounds="[60,500][400,560]"/>'
        + unread_node
        + f'<node resource-id="com.instagram.android:id/direct_text_message_text_view" text="{incoming}" bounds="{bubble_x}"/>'
        '<node resource-id="com.instagram.android:id/row_thread_composer_edittext" bounds="[60,2200][900,2260]"/>'
        '<node content-desc="Send" bounds="[950,2200][1040,2260]"/>'
        "</hierarchy>"
    )




# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeLedger:
    """Just enough ledger to test the loop's decisions."""

    def __init__(self, allowed=None):
        self.allowed = {policy.COMMENT_REPLY: 99, policy.DM_REPLY: 99, policy.LIKE: 99} | (allowed or {})
        self.recorded: list[tuple[str, str | None]] = []
        self.signals: list[tuple[str, str]] = []

    def allow(self, action):
        return self.allowed.get(action, 0) > 0

    def record(self, action, target=None):
        self.allowed[action] = self.allowed.get(action, 0) - 1
        self.recorded.append((action, target))

    def signal(self, kind, matched=None):
        self.signals.append((kind, matched))


class FakeCommentAdapter:
    platform = "instagram"

    def __init__(self, comments, *, post="post1", screens=None, likes_back=True):
        self._comments = comments
        self._post = post
        self._screens = list(screens or [])
        self.likes_back = likes_back
        self.liked: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.left = False

    def dump(self):
        return self._screens.pop(0) if self._screens else "<hierarchy/>"

    def open_own_post(self):
        return self._post

    def read_comments(self, xml):
        return list(self._comments)

    def like_comment(self, comment, xml):
        if not self.likes_back:
            return False
        self.liked.append(comment.author)
        return True

    def reply_to_comment(self, comment, text, xml):
        self.typed.append((comment.author, text))
        return True

    def leave_post(self):
        self.left = True


class FakeDmAdapter:
    platform = "instagram"

    def __init__(self, threads, incoming, *, screens=None):
        self._threads = threads
        self._incoming = incoming  # peer -> last incoming message (or None)
        self._screens = list(screens or [])
        self.sent: list[str] = []
        self.opened: list[str] = []
        self._current = None

    def dump(self):
        return self._screens.pop(0) if self._screens else "<hierarchy/>"

    def open_inbox(self):
        return True

    def read_threads(self, xml):
        return list(self._threads)

    def open_thread(self, thread):
        self.opened.append(thread.peer)
        self._current = thread.peer
        return self._incoming.get(thread.peer)

    def send_dm(self, text):
        self.sent.append(text)
        return True

    def back_to_inbox(self):
        self._current = None


def _human(seed=7):
    class _Dev:
        serial = "fake"

        def adb(self, *a, timeout=30):
            return "Physical size: 1080x2400"

    return HumanInput(_Dev(), SessionProfile.generate(seed), screen=ScreenSize(1080, 2400), sleep=lambda s: None)


def _pools(ai=("100% ai and proud of it",), thanks=("thank you!",), question=("dm me? no. ask here",)):
    return {AI: list(ai), THANKS: list(thanks), QUESTION: list(question)}


# ── 2. The comment loop ───────────────────────────────────────────────────────


def test_questions_are_answered_before_compliments():
    comments = [
        Comment("fan_a", "love this", 100),
        Comment("fan_b", "where is this gym?", 400),
        Comment("fan_c", "are you real?", 700),
    ]
    ad = FakeCommentAdapter(comments)
    led = FakeLedger()
    stats = replies.run_comment_replies(ad, _human(), led, replies.ReplyConfig(pools=_pools()), now=_clock())
    assert [author for author, _ in ad.typed] == ["fan_c", "fan_b", "fan_a"]
    assert stats.replies == 3
    assert stats.replies_used == [text for _, text in ad.typed]
    assert ad.left


def test_insults_links_and_already_answered_comments_are_left_alone():
    comments = [
        Comment("hater", "you are ugly", 100),
        Comment("spammer", "check spamsite.com", 400),
        Comment("fan_a", "gorgeous", 700),
        Comment("fan_old", "still great", 1000),
    ]
    ad = FakeCommentAdapter(comments, post="p1")
    led = FakeLedger()
    stats = replies.run_comment_replies(
        ad, _human(), led, replies.ReplyConfig(pools=_pools(thanks=("thank you!", "appreciate it"))),
        handled={"p1:fan_old"}, now=_clock(),
    )
    assert [a for a, _ in ad.typed] == ["fan_a"]
    assert stats.ignored == 3
    assert stats.replies == 1


def test_an_undeclared_character_never_answers_are_you_real():
    """Its `ai` pool is empty: the question is left unanswered, never denied (§1.1)."""
    comments = [Comment("fan_a", "are you real?", 100), Comment("fan_b", "love this", 400)]
    ad = FakeCommentAdapter(comments)
    stats = replies.run_comment_replies(
        ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools(ai=())), now=_clock()
    )
    assert [a for a, _ in ad.typed] == ["fan_b"]
    assert stats.ignored == 1


def test_a_pool_text_with_a_link_is_never_typed():
    comments = [Comment("fan_a", "love this", 100)]
    ad = FakeCommentAdapter(comments)
    stats = replies.run_comment_replies(
        ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools(thanks=("thanks! ofmai.ai",))), now=_clock()
    )
    assert ad.typed == []
    assert stats.dropped == 1
    assert stats.replies == 0


def test_the_cap_comes_from_the_ledger_not_from_the_workflow():
    comments = [Comment(f"fan_{i}", "love this", 100 + 300 * i) for i in range(5)]
    ad = FakeCommentAdapter(comments)
    led = FakeLedger({policy.COMMENT_REPLY: 2})
    stats = replies.run_comment_replies(
        ad, _human(), led, replies.ReplyConfig(pools=_pools(thanks=tuple(f"nice {i}" for i in range(5)))), now=_clock()
    )
    assert stats.replies == 2
    assert [a for a, _ in led.recorded].count(policy.COMMENT_REPLY) == 2


def test_a_health_signal_stops_the_pass_at_once():
    comments = [Comment("fan_a", "love this", 100), Comment("fan_b", "so good", 400)]
    blocked = '<hierarchy><node text="Action Blocked"/></hierarchy>'
    ad = FakeCommentAdapter(comments, screens=["<hierarchy/>", blocked])
    led = FakeLedger()
    stats = replies.run_comment_replies(
        ad, _human(), led, replies.ReplyConfig(pools=_pools(thanks=("a", "b"))), now=_clock()
    )
    assert stats.health == "action_blocked"
    assert led.signals and led.signals[0][0] == "action_blocked"
    assert ad.typed == []  # nothing typed after the signal


def test_the_like_back_is_a_plain_like_under_its_own_budget():
    comments = [Comment("fan_a", "love this", 100)]
    ad = FakeCommentAdapter(comments)
    led = FakeLedger()
    replies.run_comment_replies(ad, _human(), led, replies.ReplyConfig(pools=_pools()), now=_clock())
    assert ad.liked == ["fan_a"]
    assert (policy.LIKE, "post1:fan_a") in led.recorded

    # ratio or cap exhausted → the reply still happens, the like does not
    ad2 = FakeCommentAdapter(comments)
    led2 = FakeLedger({policy.LIKE: 0})
    replies.run_comment_replies(ad2, _human(), led2, replies.ReplyConfig(pools=_pools()), now=_clock())
    assert ad2.liked == []
    assert len(ad2.typed) == 1


def test_only_the_first_ten_comments_are_read():
    comments = [Comment(f"fan_{i}", "love this", 100 + 300 * i) for i in range(25)]
    ad = FakeCommentAdapter(comments)
    stats = replies.run_comment_replies(
        ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools(thanks=tuple(str(i) for i in range(30)))), now=_clock()
    )
    assert stats.comments_read == replies.MAX_COMMENTS == 10


# ── 3. The DM loop ────────────────────────────────────────────────────────────


def test_a_thread_without_an_incoming_message_is_never_answered():
    threads = [DmThread("fan_a", 100, True)]
    ad = FakeDmAdapter(threads, {"fan_a": None})
    stats = replies.run_dm_replies(ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools()), now=_clock())
    assert ad.sent == []
    assert stats.dms == 0 and stats.ignored == 1


def test_a_read_thread_is_never_answered():
    threads = [DmThread("fan_a", 100, False)]
    ad = FakeDmAdapter(threads, {"fan_a": "hi"})
    stats = replies.run_dm_replies(ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools()), now=_clock())
    assert ad.opened == [] and stats.threads_read == 0


def test_a_thread_asking_for_a_photo_a_number_or_a_meeting_is_ignored():
    threads = [DmThread("fan_a", 100, True), DmThread("fan_b", 400, True)]
    ad = FakeDmAdapter(threads, {"fan_a": "send me a pic", "fan_b": "love your posts"})
    stats = replies.run_dm_replies(ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools()), now=_clock())
    assert ad.sent == ["thank you!"]
    assert stats.dms == 1 and stats.ignored == 1


def test_a_thread_is_never_answered_more_than_twice():
    threads = [DmThread("fan_a", 100, True)]
    ad = FakeDmAdapter(threads, {"fan_a": "hey"})
    stats = replies.run_dm_replies(
        ad, _human(), FakeLedger(), replies.ReplyConfig(pools=_pools()),
        exchanges={"fan_a": replies.MAX_DM_EXCHANGES}, now=_clock(),
    )
    assert ad.sent == [] and stats.ignored == 1


def test_dm_cap_comes_from_the_ledger():
    threads = [DmThread(f"fan_{i}", 100 + 200 * i, True) for i in range(4)]
    ad = FakeDmAdapter(threads, {t.peer: "hey there" for t in threads})
    led = FakeLedger({policy.DM_REPLY: 2})
    stats = replies.run_dm_replies(
        ad, _human(), led, replies.ReplyConfig(pools=_pools(thanks=("a", "b", "c", "d"))), now=_clock()
    )
    assert stats.dms == 2


# ── 4. The real adapters, against XML dumps ───────────────────────────────────


def _adapter(skill_name, cls_path, xml):
    class Dev:
        serial = f"fake-{skill_name}"

        def __init__(self):
            self.calls = []
            self.xml = xml

        def adb(self, *a, timeout=30):
            self.calls.append(a)
            return "Physical size: 1080x2400" if a[:3] == ("shell", "wm", "size") else ""

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

    module, name = cls_path.rsplit(".", 1)
    cls = getattr(importlib.import_module(module), name)
    dev = Dev()
    skill = importlib.import_module(f"gitd.skills.{skill_name}").load()
    human = HumanInput(dev, SessionProfile.generate(3), screen=ScreenSize(1080, 2400), sleep=lambda s: None)
    return dev, cls(dev, skill._elements_for_device(dev), human)


def test_instagram_adapter_reads_the_comment_list():
    xml = _ig_full_screen([("fan_one", "are you real?"), ("fan_two", "love this")])
    _, ad = _adapter("ofmai_instagram", "gitd.skills.ofmai_instagram.actions.replies.InstagramCommentAdapter", xml)
    found = ad.read_comments(xml)
    assert [(c.author, c.text) for c in found] == [("fan_one", "are you real?"), ("fan_two", "love this")]


def test_instagram_adapter_never_unlikes_a_comment_it_already_liked():
    xml = _ig_full_screen([("fan_one", "love this")], liked=("fan_one",))
    dev, ad = _adapter("ofmai_instagram", "gitd.skills.ofmai_instagram.actions.replies.InstagramCommentAdapter", xml)
    comment = ad.read_comments(xml)[0]
    assert ad.like_comment(comment, xml) is False
    assert dev.taps() == []


def test_reddit_never_votes_back():
    """A vote cast in return for one received is vote manipulation (§9).

    The Reddit comment list is read from what the device really exposes: the
    author only lives in the content-desc of `comment_header` ("Level 1 comment
    by <author>, ..."), the body is the text node right under it.
    """
    xml = (
        "<hierarchy>"
        '<node resource-id="comment_layout" bounds="[0,600][720,760]"/>'
        '<node resource-id="comment_header"'
        ' content-desc="Level 1 comment by u_one, 3 hours ago, 2 votes" bounds="[60,600][700,640]"/>'
        '<node text="nice work" bounds="[60,640][700,680]"/>'
        '<node resource-id="fbp_comment_footer" text="2 votes" bounds="[60,690][720,750]"/>'
        "</hierarchy>"
    )
    dev, ad = _adapter("ofmai_reddit", "gitd.skills.ofmai_reddit.actions.replies.RedditCommentAdapter", xml)
    assert ad.likes_back is False
    comment = ad.read_comments(xml)[0]
    assert (comment.author, comment.text) == ("u_one", "nice work")
    assert ad.like_comment(comment, xml) is False
    assert dev.taps() == []


def test_x_and_instagram_do_like_back():
    for skill, path in [
        ("ofmai_instagram", "gitd.skills.ofmai_instagram.actions.replies.InstagramCommentAdapter"),
        ("ofmai_x", "gitd.skills.ofmai_x.actions.replies.XCommentAdapter"),
    ]:
        _, ad = _adapter(skill, path, "<hierarchy/>")
        assert ad.likes_back is True, skill


def test_instagram_dm_adapter_reads_only_an_incoming_last_bubble():
    xml = _ig_dm_screen()
    _, ad = _adapter("ofmai_instagram", "gitd.skills.ofmai_instagram.actions.replies.InstagramDmAdapter", xml)
    assert ad.last_incoming(xml) == "hey how do you make these"
    threads = ad.read_threads(xml)
    assert [(t.peer, t.unread) for t in threads] == [("fan_one", True)]

    out = _ig_dm_screen(outgoing_last=True)
    _, ad2 = _adapter("ofmai_instagram", "gitd.skills.ofmai_instagram.actions.replies.InstagramDmAdapter", out)
    assert ad2.last_incoming(out) is None  # we spoke last: nothing to answer

    read = _ig_dm_screen(unread=False)
    _, ad3 = _adapter("ofmai_instagram", "gitd.skills.ofmai_instagram.actions.replies.InstagramDmAdapter", read)
    assert ad3.read_threads(read)[0].unread is False


# ── 5. End to end, through the real ledger ────────────────────────────────────


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


def _account_with_budget(db, platform, serial, prefix, action, days, *, want=True):
    """An account whose today is not its rest day and has budget for ``action``.

    The rest day is seeded from the account key, which carries the row id, so
    the only way to land on a non-resting account is to insert another row —
    one per fake device, since a device carries one account per platform (R8).
    """
    created = date.today() - timedelta(days=days)
    for i in range(40):
        acc = ledger.add_account(
            db, platform=platform, handle=f"{prefix}{i}", device_serial=f"{serial}-{i}", created_on=created
        )
        budget = ledger.budget_for(acc)
        if not budget.rest_day and bool(budget.caps.get(action)) is want:
            return acc
    raise AssertionError("could not build an account with the wanted budget")  # pragma: no cover


class StaticDevice:
    """A phone showing one screen, which is enough to drive a whole pass."""

    def __init__(self, serial, xml):
        self.serial = serial
        self.xml = xml
        self.calls = []

    def adb(self, *a, timeout=30):
        self.calls.append(a)
        return "Physical size: 1080x2400" if a[:3] == ("shell", "wm", "size") else ""

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

    def typed(self):
        return typed_text(self.calls)


def test_comment_reply_end_to_end_records_one_line_per_answer(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    xml = _ig_full_screen([("fan_one", "are you real?"), ("fan_two", "this is gorgeous")])
    dev = StaticDevice("fake-ig-reply", xml)
    acc = _account_with_budget(db, "instagram", dev.serial, "ig_reply_", policy.COMMENT_REPLY, days=20)

    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    wf = skill.get_workflow(
        "comment_reply",
        dev,
        handle=acc.handle,
        replies_ai="100 percent ai and proud of it",
        replies_thanks="thank you!",
        seed=11,  # the typing profile is drawn per session: pin it
    )
    result = wf.run()
    assert result.success, result.error
    data = result.data["step_results"][0]["data"]
    assert data["replies"] == 2
    assert sorted(data["replies_used"]) == ["100 percent ai and proud of it", "thank you!"]
    assert data["phase"] == "cruise"
    spent = ledger.spent_on(db, acc, ledger.local_today(acc))
    assert spent.get(policy.COMMENT_REPLY) == 2
    # the replies really went through the keyboard, verbatim, ASCII, no link
    field = dev.typed()
    assert "100 percent ai and proud of it" in field
    assert "thank you!" in field
    assert field.isascii()
    assert "http" not in field and "ofmai.ai" not in field
    # humanised gestures only
    assert [c for c in dev.calls if c[:3] == ("shell", "input", "tap")] == []


def test_a_second_pass_never_answers_the_same_person_twice(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    xml = _ig_full_screen([("fan_one", "this is gorgeous")])
    dev = StaticDevice("fake-ig-twice", xml)
    acc = _account_with_budget(db, "instagram", dev.serial, "ig_twice_", policy.COMMENT_REPLY, days=20)
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()

    first = skill.get_workflow("comment_reply", dev, handle=acc.handle, replies_thanks="thank you!\nappreciate it")
    assert first.run().data["step_results"][0]["data"]["replies"] == 1

    second = skill.get_workflow("comment_reply", dev, handle=acc.handle, replies_thanks="thank you!\nappreciate it")
    data = second.run().data["step_results"][0]["data"]
    assert data["replies"] == 0
    assert data["ignored"] == 1
    assert ledger.spent_on(db, acc, ledger.local_today(acc)).get(policy.COMMENT_REPLY) == 1


def test_the_like_back_waits_for_the_view_ratio(monkeypatch, db):
    """A like is a like: 15 % of the views of the day, warming session included."""
    monkeypatch.setenv("FARM_FAST", "1")
    xml = _ig_full_screen([("fan_one", "this is gorgeous")])
    dev = StaticDevice("fake-ig-ratio", xml)
    acc = _account_with_budget(db, "instagram", dev.serial, "ig_ratio_", policy.COMMENT_REPLY, days=20)
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()

    # no views yet today → the reply happens, the like cannot
    step = skill.get_workflow("comment_reply", dev, handle=acc.handle, replies_thanks="thank you!").run().data
    step = step["step_results"][0]["data"]
    assert step["replies"] == 1 and step["likes"] == 0

    session = ledger.open_session("instagram", acc.handle, db)
    for _ in range(40):
        session.record(policy.VIEW)

    xml2 = _ig_full_screen([("fan_two", "this is gorgeous")])
    dev2 = StaticDevice("fake-ig-ratio", xml2)
    data2 = skill.get_workflow("comment_reply", dev2, handle=acc.handle, replies_thanks="thank you!").run().data
    step = data2["step_results"][0]["data"]
    assert step["replies"] == 1 and step["likes"] == 1


def test_comment_reply_is_refused_before_the_network_phase(monkeypatch, db):
    monkeypatch.setenv("FARM_FAST", "1")
    dev = StaticDevice("fake-ig-young", _ig_full_screen([("fan_one", "gorgeous")]))
    acc = ledger.add_account(
        db, platform="instagram", handle="ig_young", device_serial=dev.serial, created_on=date.today() - timedelta(days=1)
    )
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    result = skill.get_workflow("comment_reply", dev, handle=acc.handle, replies_thanks="thank you!").run()
    assert result.success  # nothing to do is not a failure
    assert result.data["step_results"][0]["data"]["skipped"] == f"no {policy.COMMENT_REPLY} budget"
    assert ledger.spent_on(db, acc, ledger.local_today(acc)) == {}


def test_dm_reply_cruise_only(monkeypatch, db):
    """DM_REPLY is 20 in cruise and 0 before — the cap is the ledger's, not ours."""
    monkeypatch.setenv("FARM_FAST", "1")
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()
    xml = _ig_dm_screen()

    # day 10 → network: comments may be answered, DMs may not
    dev = StaticDevice("fake-ig-dm-young", xml)
    young = _account_with_budget(db, "instagram", dev.serial, "ig_dm_young_", policy.DM_REPLY, days=9, want=False)
    assert ledger.budget_for(young).phase == policy.Phase.NETWORK
    assert ledger.budget_for(young).caps[policy.COMMENT_REPLY] > 0  # comments yes, DMs no
    result = skill.get_workflow("dm_reply", dev, handle=young.handle, replies_ai="100 percent ai").run()
    assert result.success
    assert result.data["step_results"][0]["data"]["skipped"] == f"no {policy.DM_REPLY} budget"

    # cruise → the same screen is answered once
    dev2 = StaticDevice("fake-ig-dm-cruise", xml)
    acc = _account_with_budget(db, "instagram", dev2.serial, "ig_dm_", policy.DM_REPLY, days=40)
    assert ledger.budget_for(acc).phase == policy.Phase.CRUISE
    data = skill.get_workflow("dm_reply", dev2, handle=acc.handle, replies_ai="100 percent ai").run().data
    step = data["step_results"][0]["data"]
    assert step["dms"] == 1
    assert step["replies_used"] == ["100 percent ai"]
    assert ledger.spent_on(db, acc, ledger.local_today(acc)).get(policy.DM_REPLY) == 1


def _clock():
    t = [0.0]

    def now():
        t[0] += 0.5
        return t[0]

    return now


def test_a_pass_tells_ofmai_which_texts_it_really_typed(monkeypatch, db):
    """`replies_used` travels in a session_summary, so the pool can be marked used.

    Without it OFMAI would hand the same texts out again once the 24 h
    reservation expires (bridge-ofmai-farm.md §3.4, §4.1).
    """
    import json

    from sqlalchemy import select

    from gitd.farm.models import FarmOutbox

    monkeypatch.setenv("FARM_FAST", "1")
    xml = _ig_full_screen([("fan_one", "are you real?")])
    dev = StaticDevice("fake-ig-summary", xml)
    acc = _account_with_budget(db, "instagram", dev.serial, "ig_summary_", policy.COMMENT_REPLY, days=20)
    skill = importlib.import_module("gitd.skills.ofmai_instagram").load()

    before = db.execute(select(FarmOutbox.id).order_by(FarmOutbox.id.desc())).first()
    skill.get_workflow("comment_reply", dev, handle=acc.handle, replies_ai="100 percent ai").run()

    rows = db.execute(
        select(FarmOutbox).where(FarmOutbox.id > (before[0] if before else 0)).order_by(FarmOutbox.id)
    ).scalars()
    summaries = [r for r in rows if r.kind == "session_summary"]
    assert len(summaries) == 1
    payload = json.loads(summaries[0].payload_json)
    assert payload["replies_used"] == ["100 percent ai"]
    assert payload["replies"] == 1
    assert payload["handle"] == acc.handle and payload["session_id"]


def _tt_sheet(comments, *, own_caption=None):
    """The TikTok 46.8.2 comments sheet as the explorer dumped it (2026-09-22).

    A comment row is author `title`, body `f41`, time `enj`, then "Reply". The
    sheet of one's own video opens on a caption header — `title`, caption
    `f6u`, "3d ago" in `desc` — with no Reply link under it.
    """
    rid = "com.zhiliaoapp.musically:id/"
    nodes = ['<node text="‎9 comments" resource-id="' + rid + 'wd2" bounds="[247,436][414,507]"/>']
    y = 521
    if own_caption:
        nodes += [
            f'<node text="Jordan Reed" resource-id="{rid}title" bounds="[92,534][210,560]"/>',
            f'<node text="Creator" resource-id="{rid}en2" bounds="[221,534][292,560]"/>',
            f'<node text="{own_caption}" resource-id="{rid}f6u" bounds="[92,565][667,594]"/>',
            f'<node text="‎3d ago" resource-id="{rid}desc" bounds="[92,594][687,638]"/>',
        ]
        y = 653
    for author, body in comments:
        nodes += [
            f'<node text="{author}" resource-id="{rid}title" bounds="[103,{y}][221,{y + 26}]"/>',
            f'<node text="{body}" resource-id="{rid}f41" bounds="[103,{y + 29}][700,{y + 67}]"/>',
            f'<node text="1s ago" resource-id="{rid}enj" bounds="[103,{y + 74}][161,{y + 98}]"/>',
            f'<node text="Reply" resource-id="{rid}emb" bounds="[187,{y + 72}][238,{y + 98}]"/>',
        ]
        y += 132
    nodes.append('<node text="Add comment..." resource-id="' + rid + 'ej0" bounds="[118,1277][497,1328]"/>')
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


def test_tiktok_adapter_reads_the_comment_rows_the_explorer_showed():
    xml = _tt_sheet([("Jordan Reed", "nice one"), ("Isabella", "She looks amazing like always")])
    _, ad = _adapter("ofmai_tiktok", "gitd.skills.ofmai_tiktok.actions.replies.TikTokCommentAdapter", xml)
    assert [(c.author, c.text) for c in ad.read_comments(xml)] == [
        ("Jordan Reed", "nice one"),
        ("Isabella", "She looks amazing like always"),
    ]


def test_tiktok_adapter_never_takes_the_own_caption_header_for_a_comment():
    """Seen on the explorer (2026-09-22): under its own video the pass read one
    "comment" — the caption header "Jordan Reed / 3d ago" — and tried to reply
    to it. A row without a Reply link under it is not a comment."""
    xml = _tt_sheet([], own_caption="golden hour")
    _, ad = _adapter("ofmai_tiktok", "gitd.skills.ofmai_tiktok.actions.replies.TikTokCommentAdapter", xml)
    assert ad.read_comments(xml) == []
    xml = _tt_sheet([("fan_one", "love this")], own_caption="golden hour")
    _, ad = _adapter("ofmai_tiktok", "gitd.skills.ofmai_tiktok.actions.replies.TikTokCommentAdapter", xml)
    assert [(c.author, c.text) for c in ad.read_comments(xml)] == [("fan_one", "love this")]


def test_tiktok_adapter_falls_back_to_the_reply_links_once_the_body_id_is_renamed():
    xml = _tt_sheet([("fan_one", "love this")]).replace("id/f41", "id/zz9")
    _, ad = _adapter("ofmai_tiktok", "gitd.skills.ofmai_tiktok.actions.replies.TikTokCommentAdapter", xml)
    assert [(c.author, c.text) for c in ad.read_comments(xml)] == [("fan_one", "love this")]
