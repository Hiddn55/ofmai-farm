"""X reply adapter: answering the replies under one's own post.

There is no DM adapter: X has **no automatic DM answer in V1** — a human reads
the messages on the phone once a week (docs/social/publishing.md §9). And there
is no posting workflow either: an X publication goes out through the API, over
the character's static exit IP (§4, R21). Only the reply and the like back are
device gestures, because a like is exactly what got @potter_society blocked when
it went through an API (R16).

Selectors come from the en-US accessibility labels and **none has been seen on a
device** (R34); the unknown resource ids live in ``elements.yaml``
(``profile_first_post``, ``comment_author_row``, ``comment_text_row``).
"""

from __future__ import annotations

import logging
import re

from gitd.farm.replies import Comment, CommentRowsMixin, post_key, tap_in_row
from gitd.farm.warm import center, nodes_where
from gitd.skills.ofmai_x.actions.core import PKG, XAdapter

log = logging.getLogger(__name__)


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node or "")
    return m.group(1) if m else ""


class XCommentAdapter(CommentRowsMixin, XAdapter):
    """Profile → newest post → its replies → like back and answer."""

    def _launch(self) -> None:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))
        self.device.dismiss_popups(self.dump())
        self.human.pause(1.0)

    def open_own_post(self) -> str | None:
        self._launch()
        xml = self.dump()
        if not self._tap_el("profile_tab", xml):
            return None
        self.human.pause(2.5)
        timeline = self.dump()
        top = self._first_own_post(timeline)
        if top is None:
            return None
        key, pos = top
        self.human.tap(*pos)
        self.human.pause(2.5)
        # the thread view is the comment list: no sheet to open on X
        return post_key(key)

    def _first_own_post(self, xml: str):
        """(text, centre) of the topmost post of the profile timeline."""
        rid = self._rid("profile_first_post") or self._rid("comment_text_row")
        best = None
        for node in nodes_where(xml, rid=rid):
            c = center(node)
            if c and (best is None or (c[1], c[0]) < (best[1][1], best[1][0])):
                best = (_text(node), c)
        return best

    def reply_to_comment(self, comment: Comment, text: str, xml: str) -> bool:
        if not tap_in_row(self.human, xml, comment.y, desc="Reply"):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("reply_input", sheet) or self._tap_text(sheet, "Post your reply")):
            self.device.back()
            return False
        self.human.pause(0.6)
        self.human.type_text(text)
        posted = self.dump()
        ok = self._tap_el("reply_send", posted) or self._tap_text(posted, "Reply")
        self.human.pause(1.5)
        self.device.back()  # close the keyboard
        return ok
