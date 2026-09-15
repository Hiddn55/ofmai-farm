"""TikTok workflows: warm_session, post_video, comment_reply, dm_reply."""

from __future__ import annotations

import re

from gitd.farm import ledger, policy
from gitd.farm.human import HumanInput, SessionProfile
from gitd.farm.replykit import CommentReplyAction, DmReplyAction
from gitd.farm.skillkit import WarmSessionAction, clock
from gitd.farm.warm import nodes_where
from gitd.skills.base import Action, ActionResult, EngineConfig, Workflow
from gitd.skills.ofmai_tiktok.actions.core import TikTokAdapter
from gitd.skills.ofmai_tiktok.actions.replies import TikTokCommentAdapter, TikTokDmAdapter

_AIGC_LABEL = "AI-generated content"
_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def parse_aigc_label(raw) -> bool | None:
    """``params.aigc_label`` as a strict boolean. None = not supplied.

    There is deliberately no default: the flag is frozen on the publication when
    it is queued (``SocialPublication.aigcLabel``) and copied verbatim by the
    bridge. Guessing it would either label a character that does not declare
    itself, or drop the label from one that does (R2, R3).
    """
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


def read_aigc_state(xml: str, elements) -> bool | None:
    """Is the AI-generated-content toggle on? None when the screen does not say."""
    for node in re.findall(r"<node[^>]+/?>", xml or ""):
        if _AIGC_LABEL.lower() not in node.lower():
            continue
        m = re.search(r'\bchecked="(true|false)"', node)
        if m:
            return m.group(1) == "true"
    el = elements.get("aigc_toggle_on") if elements else None
    if el is not None:
        on_desc = (el.content_desc or el.text or "").lower()
        if on_desc and on_desc in (xml or "").lower():
            return True
    return None


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

    The AI-generated-content toggle follows ``params.aigc_label`` — the flag
    frozen on the publication when it was queued — and nothing else: not the
    persona sheet, not ``farm_accounts.disclosed`` (R2, R3). Three of the six
    characters declare themselves AI and three do not, so the label is a
    per-publication decision made upstream.

    The state is re-read after the tap: the post is abandoned rather than
    published with the wrong label, in either direction.
    """

    name = "post_video_action"
    description = "Create → Upload → newest video → Next → caption → AIGC toggle → Post"
    max_retries = 1

    def __init__(self, device, elements, *, handle: str = "", caption: str = "", aigc_label=None, **kwargs):
        super().__init__(device, elements)
        self.handle = handle.lstrip("@")
        self.caption = caption
        self.aigc_label = parse_aigc_label(aigc_label)

    def precondition(self) -> bool:
        return bool(self.handle) and bool(self.caption)

    def execute(self) -> ActionResult:
        if self.aigc_label is None:
            # never a default: an unlabelled publication order is a bug upstream
            return ActionResult(success=False, error="aigc_label is required (no default)")
        ledger.init()
        try:
            session = ledger.open_session("tiktok", self.handle)
        except (LookupError, PermissionError) as e:
            return ActionResult(success=False, error=str(e))
        if not session.allow(policy.POST):
            return ActionResult(success=False, error="post budget exhausted for this day/week")
        _, sleep = clock()  # real time, or virtual under FARM_FAST=1 (dry run)
        human = HumanInput(self.device, SessionProfile.generate(), sleep=sleep)
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
        state = read_aigc_state(xml, self.elements)
        if self.aigc_label and state is not True:
            # declared character: tap the toggle, then insist on seeing it on.
            # Reading first means a toggle TikTok already remembers from the
            # previous post is left alone instead of being switched back off.
            if not (adapter._tap_el("aigc_toggle", xml) or adapter._tap_text(xml, _AIGC_LABEL)):
                return ActionResult(success=False, error="aigc toggle not confirmed", data={"aigc": state})
            human.pause(0.8)
            xml = self.device.dump_xml()
            state = read_aigc_state(xml, self.elements)
        # undeclared character: the toggle is never touched, only checked.
        # An unreadable state (None) is a refusal too — never publish on a guess.
        if state != self.aigc_label:
            return ActionResult(success=False, error="aigc toggle not confirmed", data={"aigc": state})
        human.pause(0.8)
        xml = self.device.dump_xml()
        if not adapter._tap_text(xml, "Post"):
            return ActionResult(success=False, error="Post button not found")
        sleep(8)
        session.record(policy.POST, self.caption[:40])
        return ActionResult(success=True, data={"caption": self.caption[:80], "aigc": self.aigc_label})

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


class TikTokCommentReplyAction(CommentReplyAction):
    platform = "tiktok"
    adapter_factory = staticmethod(TikTokCommentAdapter)


class CommentReply(Workflow):
    name = "comment_reply"
    description = "Answer the comments under the newest video, from the persona pools"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [TikTokCommentReplyAction(self.device, self.elements, **self.params)]


class TikTokDmReplyAction(DmReplyAction):
    platform = "tiktok"
    adapter_factory = staticmethod(TikTokDmAdapter)


class DmReply(Workflow):
    name = "dm_reply"
    description = "Answer unread DM threads once, from the persona pools"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [TikTokDmReplyAction(self.device, self.elements, **self.params)]
