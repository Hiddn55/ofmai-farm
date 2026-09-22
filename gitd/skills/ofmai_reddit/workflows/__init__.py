"""Reddit workflows: warm_session, comment_reply.

There is no posting workflow on purpose: a Reddit publication only ever goes
out through the API, over the character's static exit IP, and only once the
account is at least 31 days old with 100+ karma (docs/social/warming-policy.md
§10, publishing.md §5). The device only ever warms the account.
"""

from __future__ import annotations

import math

from gitd.farm.replykit import CommentReplyAction
from gitd.farm.skillkit import WarmSessionAction
from gitd.skills.base import Action, EngineConfig, Workflow
from gitd.skills.ofmai_reddit.actions.core import RedditAdapter
from gitd.skills.ofmai_reddit.actions.replies import RedditCommentAdapter


class RedditWarmAction(WarmSessionAction):
    platform = "reddit"
    adapter_factory = staticmethod(RedditAdapter)
    default_detours = ("search",)  # no stories on Reddit
    # a card of the feed is glanced at in 1-4 s, read in 6-8 s, never stared at
    # for twenty (seen on the explorer, 2026-09-22 — a human would have scrolled)
    profile_overrides = {
        "watch_mu": math.log(2.4),
        "watch_sigma": 0.55,
        "skip_rate": 0.30,
        "linger_rate": 0.05,
        "linger_mu": math.log(9.0),
        "linger_sigma": 0.35,
    }


class WarmSession(Workflow):
    name = "warm_session"
    description = "One humanised Reddit warming session within today's budget"
    # the adapter launches the app itself, with human pacing
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [RedditWarmAction(self.device, self.elements, **self.params)]


class RedditCommentReplyAction(CommentReplyAction):
    platform = "reddit"
    adapter_factory = staticmethod(RedditCommentAdapter)


class CommentReply(Workflow):
    """Answer the comments under one's own post. Never a vote in return.

    The adapter sets ``likes_back = False``: upvoting whoever just commented on
    you is vote manipulation, which Reddit bans on sight
    (docs/social/publishing.md §1 and §9).
    """

    name = "comment_reply"
    description = "Answer the comments under the newest post, from the persona pools"
    engine = EngineConfig(auto_launch=False, skip_popup_detect=True)

    def __init__(self, device, elements, **params):
        super().__init__(device, elements)
        self.params = params

    def steps(self) -> list[Action]:
        return [RedditCommentReplyAction(self.device, self.elements, **self.params)]
