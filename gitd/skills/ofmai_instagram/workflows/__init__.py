"""Instagram workflows: warm_session, post_video."""

from __future__ import annotations

import time

from gitd.farm import ledger, policy
from gitd.farm.human import HumanInput, SessionProfile
from gitd.farm.skillkit import WarmSessionAction
from gitd.farm.warm import nodes_where
from gitd.skills.base import Action, ActionResult, EngineConfig, Workflow
from gitd.skills.ofmai_instagram.actions.core import PKG, InstagramAdapter


class InstagramWarmAction(WarmSessionAction):
    platform = "instagram"
    adapter_factory = staticmethod(InstagramAdapter)
    default_detours = ("search", "stories")


class WarmSession(Workflow):
    name = "warm_session"
    description = "One humanised Instagram warming session within today's budget"
    # the adapter launches the app itself, with human pacing
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [InstagramWarmAction(self.device, self.elements, **self.params)]


class PostReelAction(Action):
    """Publish the most recent gallery video as a Reel. Best effort; verify on device."""

    name = "post_reel_action"
    description = "Create → Reel → newest gallery item → Next → caption → Share"
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
            session = ledger.open_session("instagram", self.handle)
        except (LookupError, PermissionError) as e:
            return ActionResult(success=False, error=str(e))
        if not session.allow(policy.POST):
            return ActionResult(success=False, error="post budget exhausted for this day/week")
        human = HumanInput(self.device, SessionProfile.generate())
        adapter = InstagramAdapter(self.device, self.elements, human)
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(4)
        self.device.dismiss_popups(self.device.dump_xml())
        xml = self.device.dump_xml()
        if not adapter._tap_el("create_tab", xml):
            return ActionResult(success=False, error="Create tab not found")
        human.pause(2.0)
        xml = self.device.dump_xml()
        adapter._tap_el("create_reel", xml) or adapter._tap_text(xml, "Reel")
        human.pause(2.0)
        xml = self.device.dump_xml()
        if not adapter._tap_el("gallery_first_item", xml):
            return ActionResult(success=False, error="gallery item not found")
        human.pause(2.0)
        for _ in range(2):  # Next (trim) → Next (edit)
            xml = self.device.dump_xml()
            if not (adapter._tap_el("next_button", xml) or adapter._tap_text(xml, "Next")):
                break
            human.pause(2.5)
        xml = self.device.dump_xml()
        if not (adapter._tap_el("caption_input", xml) or adapter._tap_text(xml, "Write a caption")):
            return ActionResult(success=False, error="caption field not found")
        human.pause(0.8)
        human.type_text(self.caption)
        self.device.back(delay=1.0)  # close keyboard
        xml = self.device.dump_xml()
        if not (adapter._tap_el("share_button_final", xml) or adapter._tap_text(xml, "Share")):
            return ActionResult(success=False, error="Share button not found")
        time.sleep(8)
        session.record(policy.POST, self.caption[:40])
        return ActionResult(success=True, data={"caption": self.caption[:80]})

    def postcondition(self) -> bool:
        xml = self.device.dump_xml() or ""
        return not nodes_where(xml, text="Share")


class PostVideo(Workflow):
    name = "post_video"
    description = "Publish a Reel from the gallery with a caption"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [PostReelAction(self.device, self.elements, **self.params)]
