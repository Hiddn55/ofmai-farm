from datetime import date

from gitd.farm import policy
from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
from gitd.farm.warm import WarmConfig, center, nodes_where, run_session


class FakeDevice:
    serial = "fake"

    def __init__(self):
        self.calls = []

    def adb(self, *args, timeout=30):
        self.calls.append(args)
        return ""


class FakeLedger:
    def __init__(self, budget: policy.DailyBudget):
        self.tracker = policy.BudgetTracker(budget)
        self.signals = []

    def allow(self, action):
        return self.tracker.allow(action)

    def record(self, action, target=None):
        self.tracker.record(action)

    def signal(self, kind, matched=None):
        self.signals.append((kind, matched))


class FakeAdapter:
    platform = "instagram"

    def __init__(self, screen="<node content-desc='Like'/><node content-desc='Comment'/>", *, author_ok=True):
        self.screen = screen
        self.author_ok = author_ok
        self.events = []

    def dump(self):
        return self.screen

    def open_feed(self):
        self.events.append("open")
        return True

    def on_feed(self, xml):
        return "Like" in xml

    def next_video(self):
        self.events.append("next")

    def like(self, xml):
        self.events.append("like")
        return True

    def save(self, xml):
        self.events.append("save")
        return True

    def open_author(self, xml):
        self.events.append("visit")
        return "someone" if self.author_ok else None

    def follow(self, xml):
        self.events.append("follow")
        return True

    def comment(self, text):
        self.events.append(("comment", text))
        return True

    def back_to_feed(self):
        self.events.append("back")

    def detour(self, kind, query):
        self.events.append(("detour", kind, query))
        return True


def _clock():
    t = [0.0]

    def now():
        return t[0]

    def sleep(s):
        t[0] += s

    return now, sleep


def _run(phase_day: int, *, seed=1, comments=(), niche=("fitness",), minutes=30, adapter=None, platform="instagram"):
    now, sleep = _clock()
    dev = FakeDevice()
    human = HumanInput(dev, SessionProfile.generate(seed), screen=ScreenSize(1080, 2400), sleep=sleep)
    budget = policy.DailyBudget.build("acct", platform, date(2026, 9, 1), date(2026, 9, phase_day))
    ledger = FakeLedger(budget)
    adapter = adapter or FakeAdapter()
    cfg = WarmConfig(minutes=minutes, phase=budget.phase, comments=list(comments), niche=list(niche), detour_kinds=("search", "stories"))
    stats = run_session(adapter, human, ledger, cfg, now=now)
    return stats, ledger, adapter


def test_consume_phase_only_watches():
    stats, ledger, adapter = _run(2)
    assert stats.videos > 20
    assert stats.likes == stats.follows == stats.comments == stats.saves == 0
    assert "like" not in adapter.events and "follow" not in adapter.events
    assert stats.seconds <= 30 * 60 + 90


def test_cruise_phase_stays_within_caps_and_ratios():
    stats, ledger, adapter = _run(25, comments=["nice", "love this", "so good"], minutes=60)
    caps = ledger.tracker.budget.caps
    assert 0 < stats.likes <= caps[policy.LIKE]
    assert stats.likes <= policy.MAX_LIKE_PER_VIEW * stats.videos + 1
    assert stats.follows <= caps[policy.FOLLOW]
    assert stats.follows <= policy.MAX_FOLLOW_PER_PROFILE_VISIT * max(1, stats.visits) + 1
    assert stats.comments <= 3
    assert stats.detours >= 1


def test_health_signal_stops_session_and_is_recorded():
    bad = FakeAdapter(screen="<node content-desc='Like'/><node text='Action Blocked'/>")
    stats, ledger, adapter = _run(25, adapter=bad)
    assert stats.health == "action_blocked"
    assert ledger.signals and ledger.signals[0][0] == "action_blocked"
    assert stats.videos == 0


def test_session_respects_duration():
    stats, _, _ = _run(10, minutes=3)
    assert stats.seconds <= 3 * 60 + 120  # last video + a phone-down pause at most


def test_lost_feed_is_reported_not_crashed():
    class Lost(FakeAdapter):
        def on_feed(self, xml):
            return False

    stats, _, adapter = _run(10, adapter=Lost())
    assert stats.error == "lost the feed"
    assert "back" in adapter.events


def test_xml_helpers_contains_matching():
    xml = (
        '<node content-desc="Like 12.3K" bounds="[900,1500][1000,1600]"/>'
        '<node text="Follow" bounds="[100,200][300,260]"/>'
        '<node content-desc="Your story" bounds="[0,0][10,10]"/>'
    )
    assert center(nodes_where(xml, desc="like")[0]) == (950, 1550)
    assert nodes_where(xml, text="follow")
    assert len(nodes_where(xml, desc="story")) == 1
    assert nodes_where(xml, desc="nope") == []
