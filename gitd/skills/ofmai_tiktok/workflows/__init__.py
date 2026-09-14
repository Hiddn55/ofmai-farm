"""TikTok workflows: warm_session, post_video."""

from __future__ import annotations

import time

from gitd.farm import ledger, policy
from gitd.farm.human import HumanInput, SessionProfile
from gitd.farm.skillkit import WarmSessionAction
from gitd.farm.warm import nodes_where
from gitd.skills.base import Action, ActionResult, EngineConfig, Workflow
from gitd.skills.ofmai_tiktok.actions.core import PKG, TikTokAdapter


class TikTokWarmAction(WarmSessionAction):
    platform = "tiktok"
    adapter_factory = staticmethod(TikTokAdapter)
    default_detours = ("search",)


class WarmSession(Workflow):
    name = "warm_session"
    description = "One humanised TikTok warming session within today's budget"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [TikTokWarmAction(self.device, self.elements, **self.params)]


class PostVideoAction(Action):
    """Publish the newest gallery video. Best effort; verify on device.

    Turns on the AI-generated content toggle when it is visible: mandatory for
    OFMAI characters (TikTok AIGC policy).
    """

    name = "post_video_action"
    description = "Create → Upload → newest video → Next → caption → AIGC toggle → Post"
    max_retries = 1

    def __init__(self, device, elements, *, handle: str = "", caption: str = "", **kwargs):
        super().__init__(device, elements)
        self.handle = handle.lstrip("@")
        self.caption = caption

    def precondition(self) -> bool:
        return bool(self.handle) and bool(self.caption)

    def execute(self) -> ActionResult:
        ledger.init()
        try:
            session = ledger.open_session("tiktok", self.handle)
        except (LookupError, PermissionError) as e:
            return ActionResult(success=False, error=str(e))
        if not session.allow(policy.POST):
            return ActionResult(success=False, error="post budget exhausted for this day/week")
        human = HumanInput(self.device, SessionProfile.generate())
        adapter = TikTokAdapter(self.device, self.elements, human)
        if not adapter.open_feed():
            return ActionResult(success=False, error="feed not reachable")
        xml = self.device.dump_xml()
        if not adapter._tap_el("create_tab", xml):
            return ActionResult(success=False, error="Create tab not found")
        human.pause(2.5)
        xml = self.device.dump_xml()
        if not (adapter._tap_el("upload_button", xml) or adapter._tap_text(xml, "Upload")):
            return ActionResult(success=False, error="Upload button not found")
        human.pause(2.0)
        xml = self.device.dump_xml()
        if not adapter._tap_el("gallery_first_item", xml):
            # first tile of the grid, best effort
            w, h = human.screen.width, human.screen.height
            human.tap(int(w * 0.17), int(h * 0.30))
        human.pause(1.5)
        for _ in range(3):  # Next through select / edit screens
            xml = self.device.dump_xml()
            if not adapter._tap_text(xml, "Next"):
                break
            human.pause(2.5)
        xml = self.device.dump_xml()
        if not (adapter._tap_el("caption_input", xml) or adapter._tap_text(xml, "Describe your video")):
            return ActionResult(success=False, error="caption field not found")
        human.pause(0.8)
        human.type_text(self.caption)
        self.device.back(delay=1.0)
        xml = self.device.dump_xml()
        adapter._tap_text(xml, "AI-generated content")  # toggle if visible
        human.pause(0.8)
        xml = self.device.dump_xml()
        if not adapter._tap_text(xml, "Post"):
            return ActionResult(success=False, error="Post button not found")
        time.sleep(8)
        session.record(policy.POST, self.caption[:40])
        return ActionResult(success=True, data={"caption": self.caption[:80]})

    def postcondition(self) -> bool:
        xml = self.device.dump_xml() or ""
        return not nodes_where(xml, text="Describe your video")


class PostVideo(Workflow):
    name = "post_video"
    description = "Publish the newest gallery video with a caption"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [PostVideoAction(self.device, self.elements, **self.params)]
