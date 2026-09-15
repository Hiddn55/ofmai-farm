"""Instagram reply adapters: under one's own post, and in the DM inbox.

Kept apart from :mod:`~gitd.skills.ofmai_instagram.actions.core` so the warming
adapter stays exactly what the warming loop needs. Both classes extend
:class:`InstagramAdapter`, so they inherit ``dump``, ``_tap_el``, ``_tap_text``,
``_tap_desc`` and the popup handling.

Every selector used here comes from the en-US accessibility labels and **none
has been seen on a device** (R34). The unknown resource ids live in
``elements.yaml`` — ``profile_grid_first_item``, ``comment_author_row``,
``comment_text_row``, ``dm_thread_row``, ``dm_message_row``, ``dm_input``,
``dm_send`` — precisely so Skill Miner fixes them in one file.
"""

from __future__ import annotations

import logging
import re

from gitd.farm.replies import Comment, CommentRowsMixin, DmThread, post_key, tap_in_row
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.ofmai_instagram.actions.core import PKG, InstagramAdapter

log = logging.getLogger(__name__)


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node or "")
    return m.group(1) if m else ""


class InstagramCommentAdapter(CommentRowsMixin, InstagramAdapter):
    """Profile → newest post → comments → like back and answer."""

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
        self.human.pause(2.0)
        thumb = self._first_grid_item(self.dump())
        if thumb is None:
            return None
        self.human.tap(*thumb)
        self.human.pause(2.5)
        post = self.dump()
        key = post_key(self._post_label(post))
        # open the comment sheet; without it there is nothing to answer
        if not (self._tap_desc(post, "Comment") or self._tap_el("comment_button", post)):
            return None
        self.human.pause(2.0)
        return key

    def _first_grid_item(self, xml: str) -> tuple[int, int] | None:
        """Centre of the newest tile of the profile grid (top-left of the grid)."""
        rid = self._rid("profile_grid_first_item")
        nodes = list(nodes_where(xml, rid=rid)) if rid else []
        if not nodes:
            # accessibility fallback: "Photo by sierra…", "Reel by sierra…"
            nodes = list(nodes_where(xml, desc=" by "))
        best = None
        for n in nodes:
            c = center(n)
            if c and (best is None or (c[1], c[0]) < (best[1], best[0])):
                best = c
        return best

    def _post_label(self, xml: str) -> str:
        for n in nodes_where(xml, desc=" by "):
            d = desc_of(n)
            if d:
                return d
        rows = nodes_where(xml, rid=self._rid("caption_input"))
        return _text(rows[0]) if rows else ""

    def reply_to_comment(self, comment: Comment, text: str, xml: str) -> bool:
        if not tap_in_row(self.human, xml, comment.y, text="Reply"):
            return False
        self.human.pause(1.2)  # Instagram pre-fills "@author "
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add a comment")):
            return False
        self.human.pause(0.6)
        self.human.type_text(text)
        posted = self.dump()
        ok = self._tap_el("comment_post", posted) or self._tap_desc(posted, "Post")
        self.human.pause(1.5)
        self.device.back()  # close the keyboard
        return ok


class InstagramDmAdapter(InstagramAdapter):
    """Direct inbox → unread thread → one short answer.

    Incoming and outgoing bubbles are told apart by geometry: a message whose
    centre sits on the left half of the screen came from the other person. It is
    the one layout convention every chat app shares, and it is what makes
    "never answer a thread without an incoming message" enforceable.
    """

    def _rid(self, name: str) -> str | None:
        el = self.elements.get(name)
        return el.resource_id if el else None

    def open_inbox(self) -> bool:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))
        self.device.dismiss_popups(self.dump())
        self.human.pause(1.0)
        xml = self.dump()
        self._tap_el("home_tab", xml)
        self.human.pause(1.2)
        xml = self.dump()
        if not (self._tap_el("direct_inbox", xml) or self._tap_desc(xml, "Direct")):
            return False
        self.human.pause(2.5)
        # an empty inbox is a normal outcome, not a failure: only "we are still
        # on the feed" means the tap took us nowhere
        return not self.on_feed(self.dump())

    def read_threads(self, xml: str) -> list[DmThread]:
        out: list[DmThread] = []
        for node in nodes_where(xml, rid=self._rid("dm_thread_row")):
            c = center(node)
            name = _text(node).strip()
            if c and name:
                out.append(DmThread(peer=name, y=c[1], unread=_unread_near(xml, c[1])))
        out.sort(key=lambda t: t.y)
        return out

    def open_thread(self, thread: DmThread) -> str | None:
        xml = self.dump()
        if not tap_in_row(self.human, xml, thread.y, text=thread.peer, band=80):
            return None
        self.human.pause(2.5)
        return self.last_incoming(self.dump())

    def last_incoming(self, xml: str) -> str | None:
        """The last bubble of the thread, only if it came from the other side."""
        rows = []
        for node in nodes_where(xml, rid=self._rid("dm_message_row")):
            c = center(node)
            body = _text(node).strip()
            if c and body:
                rows.append((c[1], c[0], body))
        if not rows:
            return None
        rows.sort()
        _, x, body = rows[-1]
        return body if x < self.human.screen.width // 2 else None

    def send_dm(self, text: str) -> bool:
        xml = self.dump()
        if not (self._tap_el("dm_input", xml) or self._tap_text(xml, "Message")):
            return False
        self.human.pause(0.6)
        self.human.type_text(text)
        out = self.dump()
        ok = self._tap_el("dm_send", out) or self._tap_text(out, "Send") or self._tap_desc(out, "Send")
        self.human.pause(1.2)
        return ok

    def back_to_inbox(self) -> None:
        self.device.back(delay=0.8)
        self.human.pause(0.8)


def _unread_near(xml: str, y: int, band: int = 90) -> bool:
    """An unread thread carries a dot, or a label saying so (matching is case-insensitive)."""
    for probe in ({"desc": "unread"}, {"desc": "new message"}, {"text": "Unread"}):
        for node in nodes_where(xml, **probe):
            c = center(node)
            if c and abs(c[1] - y) <= band:
                return True
    return False
