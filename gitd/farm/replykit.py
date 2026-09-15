"""Glue between ghost workflows and the reply loops.

Same shape as :mod:`gitd.farm.skillkit`: one :class:`Action` per gesture, each
skill subclasses it with its own adapter, so the skill files stay tiny and the
loop stays in one place (:mod:`gitd.farm.replies`).

Both actions take their texts from ``params`` — ``replies_ai``,
``replies_thanks``, ``replies_question``, newline-separated, 5 each, served by
``GET /api/farm/comments?kind=reply_*`` and copied verbatim by the bridge
(docs/social/bridge-ofmai-farm.md §3.4). The farm writes none of them, and the
quotas come from the ledger, never from here (R13).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from gitd.farm import ledger, policy, replies
from gitd.farm.human import HumanInput, SessionProfile
from gitd.farm.skillkit import _queue_session_summary, clock, parse_list
from gitd.skills.base import Action, ActionResult

log = logging.getLogger(__name__)


def pools_from_params(replies_ai: Any, replies_thanks: Any, replies_question: Any) -> dict[str, list[str]]:
    """The three pools of a persona, in the shape the loops expect.

    An empty ``ai`` pool is normal, not a bug: an undeclared character never
    answers "are you real?" (docs/social/publishing.md §1.1).
    """
    return {
        replies.AI: parse_list(replies_ai, "\n"),
        replies.THANKS: parse_list(replies_thanks, "\n"),
        replies.QUESTION: parse_list(replies_question, "\n"),
    }


class _ReplyAction(Action):
    """Shared plumbing: open the session, refuse early, run one pass."""

    platform: str = ""
    adapter_factory: Callable[..., Any] | None = None
    action_kind: str = ""

    def __init__(
        self,
        device,
        elements,
        *,
        handle: str = "",
        replies_ai: Any = "",
        replies_thanks: Any = "",
        replies_question: Any = "",
        seed: int | str | None = None,
        **kwargs,
    ):
        super().__init__(device, elements)
        self.handle = handle.lstrip("@")
        self.pools = pools_from_params(replies_ai, replies_thanks, replies_question)
        self.seed = int(seed) if seed not in (None, "") else None

    def precondition(self) -> bool:
        return bool(self.handle) and bool(self.adapter_factory)

    def _open(self):
        """(session, budget, refusal) — ``refusal`` is a finished ActionResult."""
        ledger.init()
        try:
            session = ledger.open_session(self.platform, self.handle)
        except (LookupError, PermissionError) as e:
            return None, None, ActionResult(success=False, error=str(e))
        budget = session.tracker.budget
        base = {"handle": session.account.handle, "day_of_life": budget.day_of_life, "phase": budget.phase.value}
        if budget.rest_day:
            return session, budget, ActionResult(success=True, data={"skipped": "rest day", **base})
        if budget.caps.get(self.action_kind, 0) <= 0:
            # 0 before `network` for comments, before `cruise` for DMs: the
            # phase simply does not answer yet (warming-policy.md §2).
            return session, budget, ActionResult(success=True, data={"skipped": f"no {self.action_kind} budget", **base})
        if not any(self.pools.values()):
            return session, budget, ActionResult(success=True, data={"skipped": "no reply pool", **base})
        return session, budget, None

    def _finish(self, session, budget, stats, human) -> ActionResult:
        data = stats.as_dict() | {
            "handle": session.account.handle,
            "day_of_life": budget.day_of_life,
            "phase": budget.phase.value,
            "profile_seed": human.profile.seed,
            "session_id": session.session_id,
        }
        # A pass ends like a session does: the `Data:` dict leaves as a
        # `session_summary`, and it is that event — its `replies_used` — that
        # tells OFMAI which pool texts were really typed, so it can stamp
        # `SocialCommentPool.usedAt` instead of serving them again
        # (bridge-ofmai-farm.md §3.4 and §4.1).
        _queue_session_summary(session, data)
        if stats.health:
            return ActionResult(success=False, error=f"health signal: {stats.health}", data=data)
        if stats.error:
            return ActionResult(success=False, error=stats.error, data=data)
        return ActionResult(success=True, data=data)


class CommentReplyAction(_ReplyAction):
    """One pass under the account's newest post: read, like back, answer."""

    name = "comment_reply_action"
    description = "Answer up to 10 comments under the newest post, from the persona pools"
    max_retries = 1
    action_kind = policy.COMMENT_REPLY

    def __init__(self, device, elements, *, max_comments: int | str = replies.MAX_COMMENTS, **kwargs):
        super().__init__(device, elements, **kwargs)
        self.max_comments = max(1, int(max_comments or replies.MAX_COMMENTS))

    def execute(self) -> ActionResult:
        session, budget, refusal = self._open()
        if refusal is not None:
            return refusal
        now, sleep = clock()
        human = HumanInput(self.device, SessionProfile.generate(self.seed), sleep=sleep)
        adapter = self.adapter_factory(self.device, self.elements, human)
        handled = replies.handled_targets(session.db, session.account, policy.COMMENT_REPLY)
        log.info(
            "[replies] @%s %s day %s phase %s — comment pass, %s already answered",
            session.account.handle,
            self.platform,
            budget.day_of_life,
            budget.phase.value,
            len(handled),
        )
        stats = replies.run_comment_replies(
            adapter,
            human,
            session,
            replies.ReplyConfig(pools=self.pools, max_comments=self.max_comments),
            handled=handled,
            now=now,
        )
        return self._finish(session, budget, stats, human)


class DmReplyAction(_ReplyAction):
    """One pass over the unread DM threads. Instagram and TikTok only."""

    name = "dm_reply_action"
    description = "Answer unread DM threads once, from the persona pools"
    max_retries = 1
    action_kind = policy.DM_REPLY

    def execute(self) -> ActionResult:
        session, budget, refusal = self._open()
        if refusal is not None:
            return refusal
        now, sleep = clock()
        human = HumanInput(self.device, SessionProfile.generate(self.seed), sleep=sleep)
        adapter = self.adapter_factory(self.device, self.elements, human)
        exchanges = replies.target_counts(session.db, session.account, policy.DM_REPLY)
        log.info(
            "[replies] @%s %s day %s phase %s — dm pass, %s threads already answered",
            session.account.handle,
            self.platform,
            budget.day_of_life,
            budget.phase.value,
            len(exchanges),
        )
        stats = replies.run_dm_replies(
            adapter,
            human,
            session,
            replies.ReplyConfig(pools=self.pools),
            exchanges=exchanges,
            now=now,
        )
        return self._finish(session, budget, stats, human)
