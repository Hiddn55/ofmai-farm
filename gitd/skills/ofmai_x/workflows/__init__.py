"""X workflows: warm_session, comment_reply.

There is no posting workflow on purpose: X publications go out through the
official API from the Mac mini, over the character's static exit IP
(docs/social/publishing.md, R21). The device only ever warms the account.
"""

from __future__ import annotations

from gitd.farm.replykit import CommentReplyAction
from gitd.farm.skillkit import WarmSessionAction
from gitd.skills.base import Action, EngineConfig, Workflow
from gitd.skills.ofmai_x.actions.core import XAdapter
from gitd.skills.ofmai_x.actions.replies import XCommentAdapter


class XWarmAction(WarmSessionAction):
    platform = "x"
    adapter_factory = staticmethod(XAdapter)
    default_detours = ("search",)  # no stories on X


class WarmSession(Workflow):
    name = "warm_session"
    description = "One humanised X warming session within today's budget"
    # the adapter launches the app itself, with human pacing
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [XWarmAction(self.device, self.elements, **self.params)]


class XCommentReplyAction(CommentReplyAction):
    platform = "x"
    adapter_factory = staticmethod(XCommentAdapter)


class CommentReply(Workflow):
    """Answer the replies under one's own post, and like them back.

    The reply itself could go through the API; the like back cannot — a like
    from an API is exactly what cost @potter_society its account (R16). Keeping
    both on the device keeps one gesture, one surface.
    """

    name = "comment_reply"
    description = "Answer the replies under the newest post, from the persona pools"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [XCommentReplyAction(self.device, self.elements, **self.params)]
