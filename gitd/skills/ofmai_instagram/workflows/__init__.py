"""Instagram workflows: warm_session, post_video, post_photo, post_story,
comment_reply, dm_reply."""

from __future__ import annotations

from gitd.farm import ledger, policy
from gitd.farm.human import HumanInput, SessionProfile
from gitd.farm.replykit import CommentReplyAction, DmReplyAction
from gitd.farm.skillkit import WarmSessionAction, clock
from gitd.farm.warm import nodes_where
from gitd.skills.base import Action, ActionResult, EngineConfig, Workflow
from gitd.skills.ofmai_instagram.actions.core import PKG, InstagramAdapter
from gitd.skills.ofmai_instagram.actions.replies import InstagramCommentAdapter, InstagramDmAdapter


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
        _, sleep = clock()  # real time, or virtual under FARM_FAST=1 (dry run)
        human = HumanInput(self.device, SessionProfile.generate(), sleep=sleep)
        adapter = InstagramAdapter(self.device, self.elements, human)
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        sleep(4)
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
        sleep(8)
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


class PostPhotoAction(Action):
    """Publish the most recent gallery image to the feed. Best effort; verify on device.

    Same shape as :class:`PostReelAction`, one tab over: Create → POST instead
    of Create → REEL. It shares the ``POST`` budget with the Reel workflow —
    one post a day on the device, whatever its format (R14) — and, like it,
    takes "the most recent item in the gallery", which is why the bridge pushes
    one media at a time per phone.

    TikTok has no photo-from-device path: a TikTok photo only ever goes out
    through the API in ``api_mode`` (docs/social/publishing.md).
    """

    name = "post_photo_action"
    description = "Create → Post → newest gallery item → Next ×2 → caption → Share"
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
        _, sleep = clock()  # real time, or virtual under FARM_FAST=1 (dry run)
        human = HumanInput(self.device, SessionProfile.generate(), sleep=sleep)
        adapter = InstagramAdapter(self.device, self.elements, human)
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        sleep(4)
        self.device.dismiss_popups(self.device.dump_xml())
        xml = self.device.dump_xml()
        if not adapter._tap_el("create_tab", xml):
            return ActionResult(success=False, error="Create tab not found")
        human.pause(2.0)
        xml = self.device.dump_xml()
        if not (adapter._tap_el("create_post", xml) or adapter._tap_text(xml, "POST")):
            return ActionResult(success=False, error="Post tab not found")
        human.pause(2.0)
        xml = self.device.dump_xml()
        if not adapter._tap_el("gallery_first_item", xml):
            return ActionResult(success=False, error="gallery item not found")
        human.pause(2.0)
        for _ in range(2):  # Next (crop) → Next (filters)
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
        sleep(8)
        session.record(policy.POST, self.caption[:40])
        return ActionResult(success=True, data={"caption": self.caption[:80], "format": "feed"})

    def postcondition(self) -> bool:
        xml = self.device.dump_xml() or ""
        return not nodes_where(xml, text="Share")


class PostPhoto(Workflow):
    name = "post_photo"
    description = "Publish a feed photo from the gallery with a caption"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [PostPhotoAction(self.device, self.elements, **self.params)]


class PostStoryAction(Action):
    """Publish the most recent gallery item as a story.

    A story is **not** a post: it spends ``STORY_POST`` (1 a day from `network`
    on, Instagram only, ``policy.py``), never the ``POST`` budget nor its weekly
    cap, and it is not counted as a publication (warming-policy.md §2). Like the
    Reel and the photo workflows it takes "the most recent item in the gallery",
    which is why the bridge pushes one media at a time per phone.

    There is no caption parameter: a story carries no caption on the device.
    """

    name = "post_story_action"
    description = "Create → Story → newest gallery item → Your story"
    max_retries = 1

    def __init__(self, device, elements, *, handle: str = "", **kwargs):
        super().__init__(device, elements)
        self.handle = handle.lstrip("@")

    def precondition(self) -> bool:
        return bool(self.handle)

    def execute(self) -> ActionResult:
        ledger.init()
        try:
            session = ledger.open_session("instagram", self.handle)
        except (LookupError, PermissionError) as e:
            return ActionResult(success=False, error=str(e))
        if not session.allow(policy.STORY_POST):
            return ActionResult(success=False, error="story budget exhausted for this day")
        _, sleep = clock()  # real time, or virtual under FARM_FAST=1 (dry run)
        human = HumanInput(self.device, SessionProfile.generate(), sleep=sleep)
        adapter = InstagramAdapter(self.device, self.elements, human)
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        sleep(4)
        self.device.dismiss_popups(self.device.dump_xml())
        xml = self.device.dump_xml()
        if not adapter._tap_el("create_tab", xml):
            return ActionResult(success=False, error="Create tab not found")
        human.pause(2.0)
        xml = self.device.dump_xml()
        if not (adapter._tap_el("create_story", xml) or adapter._tap_text(xml, "STORY")):
            return ActionResult(success=False, error="Story tab not found")
        human.pause(2.0)
        xml = self.device.dump_xml()
        if not adapter._tap_el("gallery_first_item", xml):
            return ActionResult(success=False, error="gallery item not found")
        human.pause(2.5)
        xml = self.device.dump_xml()
        if not (adapter._tap_el("your_story", xml) or adapter._tap_text(xml, "Your story")):
            return ActionResult(success=False, error="Your story button not found")
        sleep(6)
        session.record(policy.STORY_POST)
        return ActionResult(success=True, data={"format": "story"})

    def postcondition(self) -> bool:
        # the composer is gone: its share button ("Your story", next to "Share
        # to") is no longer on screen. Matching on `text` and not on
        # `content-desc` is deliberate — the home feed's own story ring carries
        # the same words as a content-desc and would never clear.
        # [to verify on the device] the exact label of the composer's button.
        xml = self.device.dump_xml() or ""
        return not nodes_where(xml, text="Your story") and not nodes_where(xml, text="Share to")


class PostStory(Workflow):
    name = "post_story"
    description = "Publish the newest gallery item as a story"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [PostStoryAction(self.device, self.elements, **self.params)]


class InstagramCommentReplyAction(CommentReplyAction):
    platform = "instagram"
    adapter_factory = staticmethod(InstagramCommentAdapter)


class CommentReply(Workflow):
    name = "comment_reply"
    description = "Answer the comments under the newest post, from the persona pools"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [InstagramCommentReplyAction(self.device, self.elements, **self.params)]


class InstagramDmReplyAction(DmReplyAction):
    platform = "instagram"
    adapter_factory = staticmethod(InstagramDmAdapter)


class DmReply(Workflow):
    name = "dm_reply"
    description = "Answer unread DM threads once, from the persona pools"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [InstagramDmReplyAction(self.device, self.elements, **self.params)]
