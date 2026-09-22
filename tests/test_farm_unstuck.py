"""The three tiers on an unknown screen (selectors-uiautomator.md §4 bis):
generic closers, then a model's single action, then evidence + alert + stop."""

from pathlib import Path

from gitd.farm import advisor, unstuck
from gitd.farm.human import HumanInput, ScreenSize, SessionProfile
from gitd.farm.unstuck import Step
from gitd.skills.base import Element

FEED = '<hierarchy><node content-desc="Home" bounds="[40,1300][100,1340]"/><node text="feed" bounds="[0,0][10,10]"/></hierarchy>'
SAVED_SHEET = (
    '<hierarchy><node text="Collect the posts you love" bounds="[40,860][680,900]"/>'
    '<node text="Start a collection" bounds="[40,1220][680,1290]"/></hierarchy>'
)
WHY_SHEET = '<hierarchy><node text="Why you\'re seeing this post" bounds="[20,1200][700,1250]"/><node text="View song details" bounds="[20,1280][700,1330]"/></hierarchy>'
PROMO = '<hierarchy><node text="Upgrade your profile" bounds="[60,720][660,780]"/><node text="Not now" bounds="[300,800][420,840]"/></hierarchy>'
CAPTCHA = '<hierarchy><node text="Confirm you\'re human to use your account" bounds="[40,300][680,360]"/><node text="Continue" bounds="[40,600][680,650]"/></hierarchy>'


class FakeDevice:
    serial = "fake-unstuck"

    def __init__(self, screens):
        self.screens = list(screens)  # what each successive dump shows
        self.calls = []

    def adb(self, *a, timeout=30):
        self.calls.append(a)
        return "Physical size: 720x1440" if a[:3] == ("shell", "wm", "size") else ""

    def dump_xml(self):
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def back(self, delay=1.0):
        self.calls.append(("back",))

    def find_bounds(self, xml, **kw):
        from gitd.bots.common.adb import Device

        return Device.find_bounds(self, xml, **kw)

    def bounds_center(self, b):
        from gitd.bots.common.adb import Device

        return Device.bounds_center(self, b)

    def taps(self):
        return [tuple(int(v) for v in c[3:5]) for c in self.calls if c[:3] == ("shell", "input", "swipe")]


class FakeAdapter:
    platform = "instagram"

    def __init__(self, screens):
        self.device = FakeDevice(screens)
        self.human = HumanInput(self.device, SessionProfile.generate(1), screen=ScreenSize(720, 1440), sleep=lambda s: None)
        self.elements = {"home_tab": Element(name="home_tab", content_desc="Home")}

    def dump(self):
        return self.device.dump_xml()

    def on_feed(self, xml):
        return 'text="feed"' in xml


def test_tier_one_closes_a_sheet_with_its_own_button():
    ad = FakeAdapter([PROMO, FEED])
    assert unstuck.generic_recovery(ad) is True
    assert any(abs(x - 360) < 40 and abs(y - 820) < 40 for x, y in ad.device.taps())  # "Not now"


def test_tier_one_presses_back_when_nothing_reads_like_a_closer():
    ad = FakeAdapter([WHY_SHEET, FEED])
    assert unstuck.generic_recovery(ad) is True
    assert ("back",) in ad.device.calls


def test_tier_one_never_touches_an_identity_gate():
    ad = FakeAdapter([CAPTCHA])
    assert unstuck.generic_recovery(ad) is False
    assert ad.device.taps() == [] and ("back",) not in ad.device.calls


def test_tier_two_executes_one_advised_tap_and_refuses_gates():
    ad = FakeAdapter([SAVED_SHEET, FEED])
    asked = []

    def model(platform, summary):
        asked.append(summary)
        return Step(action="tap", text="Start a collection", why="closes the sheet")

    assert unstuck.advised_recovery(ad, "instagram", model) is True
    assert "Collect the posts you love" in asked[0]
    # a model that wants to tap Continue on a captcha is ignored
    ad2 = FakeAdapter([CAPTCHA])
    assert unstuck.advised_recovery(ad2, "instagram", lambda p, s: Step(action="tap", text="Continue")) is False
    assert ad2.device.taps() == []


def test_tier_three_keeps_the_evidence_and_alerts(tmp_path):
    ad = FakeAdapter([WHY_SHEET])
    alerts = []
    base = unstuck.escalate(ad, "instagram", "@jordan", WHY_SHEET, out_dir=tmp_path, notify=lambda level, title, msg: alerts.append((level, title)) or True)
    assert Path(str(base) + ".xml").read_text() == WHY_SHEET
    assert alerts and alerts[0][0] == "warn" and "unknown screen" in alerts[0][1]


def test_recover_runs_the_tiers_in_order_and_stops_cleanly():
    ad = FakeAdapter([CAPTCHA])  # nothing can clear it
    alerts = []
    ok = unstuck.recover(ad, "instagram", "jordan", advisor=lambda p, s: Step(action="give_up"), notify=lambda *a: alerts.append(a) or True)
    assert ok is False and alerts


def test_the_advisor_answer_is_parsed_strictly():
    assert advisor.parse_step('{"action": "tap", "text": "Not now", "why": "promo"}') == Step(action="tap", text="Not now", why="promo")
    assert advisor.parse_step('sure! {"action":"back"}').action == "back"
    assert advisor.parse_step('{"action": "type", "text": "hello"}') is None
    assert advisor.parse_step("I would tap Not now") is None


def test_the_advisor_is_absent_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FARM_ADVISOR", raising=False)
    assert advisor.configured() is None


def test_the_claude_advisor_asks_one_model_call_per_turn():
    class Block:
        type = "text"
        text = '{"action": "back", "why": "a sheet"}'

    class Msgs:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return type("R", (), {"content": [Block()]})()

    class Client:
        messages = Msgs()

    client = Client()
    step = advisor.ClaudeAdvisor(client=client)("instagram", "y=1200 text='Why you are seeing this post'")
    assert step.action == "back"
    assert client.messages.calls[0]["model"] == advisor.MODEL
    assert "Screen" in client.messages.calls[0]["messages"][0]["content"]
