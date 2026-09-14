"""The two skills load through ghost's Skill machinery and a warm_session
workflow runs end to end against a fake device (FARM_FAST=1, no sleeps)."""

import importlib
from datetime import date, timedelta

import pytest

from gitd.farm import ledger

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


@pytest.mark.parametrize("skill_name,platform", [("ofmai_instagram", "instagram"), ("ofmai_tiktok", "tiktok")])
def test_skill_loads_with_workflows(skill_name, platform):
    mod = importlib.import_module(f"gitd.skills.{skill_name}")
    s = mod.load()
    assert s.name == skill_name
    assert set(s.list_workflows()) == {"warm_session", "post_video"}
    assert "open_app" in s.list_actions()
    assert s.popup_detectors


def test_instagram_warm_session_runs_against_fake_device(monkeypatch):
    monkeypatch.setenv("FARM_FAST", "1")
    ledger.init()
    from gitd.models.base import SessionLocal

    db = SessionLocal()
    for a in ledger.list_accounts(db):
        db.delete(a)
    db.commit()
    acc = ledger.add_account(
        db, platform="instagram", handle="eva_fake", device_serial="fake-skill", created_on=date.today() - timedelta(days=9)
    )
    # the account lives in New York time: its "today" may lag the container's UTC date
    expected_day = (ledger.local_today(acc) - (date.today() - timedelta(days=9))).days + 1
    db.close()

    mod = importlib.import_module("gitd.skills.ofmai_instagram")
    skill = mod.load()
    dev = FakeDevice()
    wf = skill.get_workflow("warm_session", dev, handle="@eva_fake", minutes=10, seed=5, comments="nice\ncool")
    result = wf.run()
    assert result.success, result.error
    step = result.data["step_results"][0]["data"]
    assert step["videos"] > 10
    assert step["phase"] == "network"
    assert step["day_of_life"] == expected_day
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
