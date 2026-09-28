"""Dispatch tests for RecordedStepAction new step types (M2).

Device-free: uses a mock Device and asserts the right Device call / service
call is made for locator-tap, long_press, open_url, and launch_intent. The
per-step settle sleep is patched out for speed.
"""

from unittest.mock import MagicMock

import pytest

import gitd.skills.base as base
from gitd.skills.base import RecordedStepAction


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda *a, **k: None)


def _run(step, device):
    return RecordedStepAction(device, step, 0).execute()


def test_locator_tap_uses_element_find():
    dev = MagicMock()
    dev.dump_xml.return_value = "<hierarchy/>"
    dev.find_bounds.return_value = "[0,0][20,20]"
    dev.bounds_center.return_value = (10, 10)
    res = _run({"action": "tap", "text": "Search"}, dev)
    assert res.success
    dev.tap.assert_called_once_with(10, 10)


def test_locator_tap_falls_back_to_coords():
    dev = MagicMock()
    dev.dump_xml.return_value = "<hierarchy/>"
    dev.find_bounds.return_value = None  # locator no longer resolves
    res = _run({"action": "tap", "resource_id": "com.x:id/gone", "x": 111, "y": 222}, dev)
    assert res.success
    dev.tap.assert_called_once_with(111, 222)


def test_locator_tap_fails_when_unresolved_and_no_coords():
    dev = MagicMock()
    dev.dump_xml.return_value = "<hierarchy/>"
    dev.find_bounds.return_value = None
    res = _run({"action": "tap", "text": "Nope"}, dev)
    assert not res.success
    assert "locator not found" in res.error
    dev.tap.assert_not_called()


def test_plain_coordinate_tap_still_works():
    dev = MagicMock()
    res = _run({"action": "tap", "x": 5, "y": 6}, dev)
    assert res.success
    dev.tap.assert_called_once_with(5, 6)


def test_long_press():
    dev = MagicMock()
    res = _run({"action": "long_press", "x": 100, "y": 200, "duration_ms": 1200}, dev)
    assert res.success
    dev.long_press.assert_called_once_with(100, 200, duration_ms=1200)


def test_open_url_routes_through_browser(monkeypatch):
    called = {}
    import gitd.services.browser as browser

    monkeypatch.setattr(browser, "open_url", lambda serial, url, bundle_id=None: called.update(serial=serial, url=url))
    dev = MagicMock()
    dev.serial = "SERIAL1"
    res = _run({"action": "open_url", "url": "https://www.reddit.com/r/LocalLLaMA/"}, dev)
    assert res.success
    assert called == {"serial": "SERIAL1", "url": "https://www.reddit.com/r/LocalLLaMA/"}


def test_launch_intent_routes_through_device_context(monkeypatch):
    captured = {}
    import gitd.services.device_context as dc

    def _fake(serial, action="", data="", package="", component="", extras=None):
        captured.update(serial=serial, action=action, data=data, package=package)

    monkeypatch.setattr(dc, "launch_intent", _fake)
    dev = MagicMock()
    dev.serial = "SERIAL2"
    step = {"action": "launch_intent", "intent_action": "android.intent.action.VIEW", "data": "geo:0,0"}
    res = _run(step, dev)
    assert res.success
    # 'intent_action' step field maps to the intent's 'action' arg (dispatch-key collision avoided)
    assert captured == {"serial": "SERIAL2", "action": "android.intent.action.VIEW", "data": "geo:0,0", "package": ""}


# ── one reading of the screen per step ──────────────────────────────────────


def _tree(*labels):
    return "<hierarchy>" + "".join(f'<node text="{t}" bounds="[0,{i*100}][100,{i*100+50}]" />' for i, t in enumerate(labels)) + "</hierarchy>"


def test_a_locator_found_in_the_prefetched_tree_is_tapped_without_a_dump():
    from gitd.bots.common.adb import Device

    dev = MagicMock()
    dev.find_bounds.side_effect = lambda xml, **kw: Device.find_bounds(dev, xml, **kw)
    dev.bounds_center.side_effect = lambda b: Device.bounds_center(dev, b)
    action = RecordedStepAction(dev, {"action": "tap", "text": "Next"}, 0)
    action.prefetched_xml = _tree("Back", "Next")
    assert action.execute().success
    dev.dump_xml.assert_not_called()
    dev.tap.assert_called_once_with(50, 125)


def test_a_locator_missing_from_the_prefetched_tree_reads_the_screen_again():
    from gitd.bots.common.adb import Device

    dev = MagicMock()
    dev.find_bounds.side_effect = lambda xml, **kw: Device.find_bounds(dev, xml, **kw)
    dev.bounds_center.side_effect = lambda b: Device.bounds_center(dev, b)
    dev.dump_xml.return_value = _tree("Next")
    action = RecordedStepAction(dev, {"action": "tap", "text": "Next"}, 0)
    action.prefetched_xml = _tree("Loading")
    assert action.execute().success
    dev.dump_xml.assert_called_once()
    dev.tap.assert_called_once_with(50, 25)


def test_the_engine_reads_the_screen_once_per_step_and_hands_it_to_the_next():
    from gitd.skills.base import RecordedWorkflow

    dev = MagicMock()
    dev.serial = "d"
    dev.dump_xml.return_value = _tree("A", "B")
    dev.dismiss_popups.return_value = False
    dev.find_bounds.return_value = "[0,0][10,10]"
    dev.bounds_center.return_value = (5, 5)
    wf = RecordedWorkflow(dev, [{"action": "tap", "text": "A"}, {"action": "tap", "text": "B"}])
    wf.engine.auto_launch = False
    assert wf.run().success
    # step 1 reads the screen; one reading after step 1 (popups), reused by
    # step 2's locator; one after step 2 — three, not five
    assert dev.dump_xml.call_count == 3
    assert dev.dismiss_popups.call_count == 2


def test_no_popup_pass_after_a_checkpoint(monkeypatch):
    """The screen a human (or a scripted gate) leaves is not searched for a
    'cancel' to tap: that closed the birthday picker on 2026-09-22."""
    from gitd.skills.base import RecordedWorkflow

    dev = MagicMock()
    dev.serial = "d"
    dev.dump_xml.return_value = _tree("Set date", "Cancel")
    dev.dismiss_popups.return_value = True
    steps = [{"action": "checkpoint", "reason": "generic", "success": {"screen_has": "Set date"}}]
    wf = RecordedWorkflow(dev, steps)
    wf.engine.auto_launch = False
    assert wf.run().success
    dev.dismiss_popups.assert_not_called()


# ── scripted gates ──────────────────────────────────────────────────────────


def test_type_secret_reads_the_keychain_and_never_shows_the_value(monkeypatch, caplog):
    import gitd.farm.bridge as bridge

    monkeypatch.setattr(bridge, "_keychain", lambda service: "s3cr3t/pw+\n" if service == "ofmai-social-instagram-sierra" else "")
    dev = MagicMock()
    dev.serial = "d"
    res = _run({"action": "type_secret", "service": "ofmai-social-instagram-sierra"}, dev)
    assert res.success
    args = dev.adb.call_args[0]
    assert args[:3] == ("shell", "input", "text") and "s3cr3t/pw+" in args[3]
    assert "s3cr3t" not in caplog.text and "s3cr3t" not in str(res.data) and "s3cr3t" not in str(res.error)


def test_type_secret_fails_without_an_entry_and_types_nothing(monkeypatch):
    import gitd.farm.bridge as bridge

    monkeypatch.setattr(bridge, "_keychain", lambda service: "")
    dev = MagicMock()
    res = _run({"action": "type_secret", "service": "ofmai-social-instagram-nobody"}, dev)
    assert not res.success and "ofmai-social-instagram-nobody" in res.error
    dev.adb.assert_not_called()


def _set_date_dialog(month="Sep", day="22", year="2026", with_set=True):
    nodes = (
        f'<node text="{month}" resource-id="android:id/numberpicker_input" bounds="[150,450][290,530]" />'
        f'<node text="{day}" resource-id="android:id/numberpicker_input" bounds="[300,450][400,530]" />'
        f'<node text="{year}" resource-id="android:id/numberpicker_input" bounds="[420,450][560,530]" />'
    )
    if with_set:
        nodes += '<node text="SET" clickable="true" bounds="[440,650][540,700]" />'
    return f"<hierarchy>{nodes}</hierarchy>"


def test_date_wheel_types_year_day_and_month_then_sets():
    from gitd.bots.common.adb import Device

    dev = MagicMock()
    for name in ("nodes", "node_text", "node_rid", "node_bounds", "node_center", "find_bounds", "bounds_center"):
        getattr(dev, name).side_effect = lambda *a, _n=name, **kw: getattr(Device, _n)(dev, *a, **kw)
    dev.dump_xml.return_value = _set_date_dialog()
    res = _run({"action": "date_wheel", "date": "2001-08-26"}, dev)
    assert res.success, res.error
    typed = [c[0][3] for c in dev.adb.call_args_list if c[0][:3] == ("shell", "input", "text")]
    assert typed == ["2001", "26", "Aug"]
    taps = [c[0][:2] for c in dev.tap.call_args_list]
    assert taps == [(490, 490), (350, 490), (220, 490), (490, 675)]  # year, day, month, SET


def test_date_wheel_fails_cleanly_when_no_dialog_is_open():
    from gitd.bots.common.adb import Device

    dev = MagicMock()
    for name in ("nodes", "node_text", "node_rid", "node_bounds", "node_center"):
        getattr(dev, name).side_effect = lambda *a, _n=name: getattr(Device, _n)(dev, *a)
    dev.dump_xml.return_value = _tree("What's your name?")
    res = _run({"action": "date_wheel", "date": "2001-08-26"}, dev)
    assert not res.success and "year" in res.error
    dev.tap.assert_not_called()


def test_date_wheel_refuses_a_bad_date():
    res = _run({"action": "date_wheel", "date": "26/08/2001"}, MagicMock())
    assert not res.success and "YYYY-MM-DD" in res.error


def test_a_locator_that_appears_late_is_waited_for(monkeypatch):
    """The screen is re-read for up to wait_s before the step gives up."""
    from gitd.bots.common.adb import Device

    clock = [0.0]
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(base.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    dev = MagicMock()
    dev.find_bounds.side_effect = lambda xml, **kw: Device.find_bounds(dev, xml, **kw)
    dev.bounds_center.side_effect = lambda b: Device.bounds_center(dev, b)
    dev.dump_xml.side_effect = [_tree("Loading"), _tree("Loading"), _tree("Create new account")]
    res = _run({"action": "tap", "text": "Create new account"}, dev)
    assert res.success
    assert dev.dump_xml.call_count == 3
    dev.tap.assert_called_once_with(50, 25)


def test_a_locator_that_never_appears_fails_after_wait_s(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(base.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    dev = MagicMock()
    dev.dump_xml.return_value = "<hierarchy/>"
    dev.find_bounds.return_value = None
    res = _run({"action": "tap", "text": "Nope", "wait_s": 3}, dev)
    assert not res.success and "locator not found" in res.error
    assert 2 <= dev.dump_xml.call_count <= 4


def test_text_any_taps_the_first_label_on_screen():
    from gitd.bots.common.adb import Device

    dev = MagicMock()
    dev.find_bounds.side_effect = lambda xml, **kw: Device.find_bounds(dev, xml, **kw)
    dev.bounds_center.side_effect = lambda b: Device.bounds_center(dev, b)
    dev.dump_xml.return_value = _tree("I already have a profile", "Create new account")
    res = _run({"action": "tap", "text_any": ["Get started", "Create new account"]}, dev)
    assert res.success
    dev.tap.assert_called_once_with(50, 125)


def test_launch_uses_the_launcher_category_through_monkey():
    dev = MagicMock()
    dev.serial = "1.2.3.4:1"
    res = _run({"action": "launch", "package": "com.instagram.android"}, dev)
    assert res.success
    assert dev.adb.call_args[0] == ("shell", "monkey", "-p", "com.instagram.android", "-c", "android.intent.category.LAUNCHER", "1")
