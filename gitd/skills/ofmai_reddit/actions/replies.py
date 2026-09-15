"""Reddit reply adapter: answering the comments under one's own post.

Two things Reddit does differently, both non-negotiable:

* **no vote in return.** ``likes_back = False``: upvoting the person who just
  commented on you is vote manipulation, the one behaviour Reddit bans on sight
  (docs/social/publishing.md §1 and §9). The like back exists on Instagram,
  TikTok and X; here the answer is the whole gesture.
* **no DM adapter.** No automatic DM answer in V1 — a human reads the inbox
  once a week (§9).

Selectors come from the en-US accessibility labels and **none has been seen on a
device** (R34); the unknown resource ids live in ``elements.yaml``
(``profile_first_post``, ``comment_author_row``, ``comment_text_row``).
"""

from __future__ import annotations

import logging
import re

from gitd.farm.replies import Comment, CommentRowsMixin, post_key, tap_in_row
from gitd.farm.warm import center, nodes_where
from gitd.skills.ofmai_reddit.actions.core import PKG, RedditAdapter

log = logging.getLogger(__name__)


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node or "")
    return m.group(1) if m else ""


class RedditCommentAdapter(CommentRowsMixin, RedditAdapter):
    """Profile → newest post → its comments → answer. Never a vote back."""

    likes_back = False

    def _launch(self) -> None:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))
        self.device.dismiss_popups(self.dump())
        self.human.pause(1.0)

    def open_own_post(self) -> str | None:
        self._launch()
        xml = self.dump()
        if not (self._tap_el("profile_tab", xml) or self._tap_text(xml, "Profile")):
            return None
        self.human.pause(2.5)
        top = self._first_own_post(self.dump())
        if top is None:
            return None
        title, pos = top
        self.human.tap(*pos)
        self.human.pause(2.5)
        # the post page already lists its comments: no sheet to open
        return post_key(title)

    def _first_own_post(self, xml: str):
        """(title, centre) of the topmost post of the profile page."""
        rid = self._rid("profile_first_post") or self._rid("post_title")
        best = None
        for node in nodes_where(xml, rid=rid):
            c = center(node)
            if c and (best is None or (c[1], c[0]) < (best[1][1], best[1][0])):
                best = (_text(node), c)
        return best

    def reply_to_comment(self, comment: Comment, text: str, xml: str) -> bool:
        if not (
            tap_in_row(self.human, xml, comment.y, text="Reply")
            or tap_in_row(self.human, xml, comment.y, desc="Reply")
        ):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add a comment")):
            self.device.back()
            return False
        self.human.pause(0.6)
        self.human.type_text(text)
        posted = self.dump()
        ok = self._tap_el("comment_send", posted) or self._tap_desc(posted, "Post comment")
        self.human.pause(1.5)
        self.device.back()  # close the keyboard
        return ok
