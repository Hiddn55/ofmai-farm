"""TikTok reply adapters: under one's own video, and in the inbox.

Same shape as the Instagram ones. What the device confirmed (GeeLark
``explorer-us``, TikTok 46.8.2, 2026-09-18, screens-tiktok-actions.md §3):
``Reply`` under a comment opens the same composer as a new comment, and the
reply is proven by the comment counter (345 -> 346) or by the text showing in
the sheet. The send arrow has NO label: it is the (657, 858) point of
``elements.yaml`` (keyboard open), scaled to the screen. The row ids of the
comment list are obfuscated and were not mined (R34): ``read_comments`` keeps
the mixin's id-based pairing for builds that expose them, and falls back to
the "Reply" links, pairing each with the text right above it. The DM adapter
was NOT exercised (no incoming message on a new account).
"""

from __future__ import annotations

import logging
import re

from gitd.farm.replies import Comment, CommentRowsMixin, DmThread, post_key, rows_by_rid, tap_in_row, text_of
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.ofmai_tiktok.actions.core import PKG, TikTokAdapter

log = logging.getLogger(__name__)


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node or "")
    return m.group(1) if m else ""


class TikTokCommentAdapter(CommentRowsMixin, TikTokAdapter):
    """Profile → newest video → comments → like back and answer."""

    def _launch(self) -> None:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.5))
        self.device.dismiss_popups(self.dump())
        self.human.pause(1.0)

    def open_own_post(self) -> str | None:
        self._launch()
        xml = self.dump()
        if not (self._tap_el("profile_tab", xml) or self._tap_text(xml, "Profile")):
            return None
        self.human.pause(2.5)
        thumb = self._first_grid_item(self.dump())
        if thumb is None:
            return None
        self.human.tap(*thumb)
        self.human.pause(3.0)
        post = self.dump()
        key = post_key(self._post_label(post))
        if not (self._tap_el("comment_button", post) or self._tap_desc(post, "Comment")):
            return None
        self.human.pause(2.0)
        return key

    def _first_grid_item(self, xml: str) -> tuple[int, int] | None:
        rid = self._rid("profile_grid_first_item")
        nodes = list(nodes_where(xml, rid=rid)) if rid else []
        if not nodes:
            nodes = list(nodes_where(xml, desc="video"))
        best = None
        for n in nodes:
            c = center(n)
            if c and (best is None or (c[1], c[0]) < (best[1], best[0])):
                best = c
        return best

    def _post_label(self, xml: str) -> str:
        for n in nodes_where(xml, desc="video"):
            d = desc_of(n)
            if d:
                return d
        return ""

    def read_comments(self, xml: str) -> list[Comment]:
        # A row is a comment only if its author sits right above the body
        # (35 px on 46.8.2, 2026-09-22) and its own "Reply" link right under
        # it (37-77 px). Under one's own video the sheet opens on a caption
        # header — author `title`, caption, "3d ago" — that the mixin's wider
        # pairing took for a comment (and, with a real comment below, for
        # that comment's author): the pass then "replied" to the caption and
        # found no Reply link to tap.
        authors = rows_by_rid(xml, self._rid("comment_author_row"))
        rows: list[Comment] = []
        for bnode, (_, by) in rows_by_rid(xml, self._rid("comment_text_row")):
            above = [(by - ay, anode) for anode, (_, ay) in authors if 0 < by - ay <= 60]
            if not above or not self._reply_link_under(xml, by):
                continue
            author, body = text_of(min(above)[1]).lstrip("@").strip(), text_of(bnode).strip()
            if author and body:
                rows.append(Comment(author=author, text=body, y=by))
        if rows:
            return rows
        # obfuscated ids: each "Reply" link belongs to the comment right above it,
        # whose author is the text node above the body
        out: list[Comment] = []
        texts = []
        for n in nodes_where(xml, text=""):
            t = _text(n).strip()
            c = center(n)
            if t and c and t.lower() not in ("reply", "view replies", "add comment...") and not re.match(r"^\d[\d.,]*[km]?$", t.lower()):
                texts.append((c[1], t))
        texts.sort()
        for link in nodes_where(xml, text="Reply"):
            lc = center(link)
            if not lc:
                continue
            above = [(y, t) for y, t in texts if 0 < lc[1] - y <= 220]
            if len(above) < 2:
                continue
            (_, author), (by, body) = above[-2], above[-1]
            out.append(Comment(author=author.lstrip("@"), text=body, y=by))
        return out

    @staticmethod
    def _reply_link_under(xml: str, body_y: int, band: int = 130) -> bool:
        for link in nodes_where(xml, text="Reply"):
            c = center(link)
            if c and _text(link).strip().lower() == "reply" and 0 < c[1] - body_y <= band:
                return True
        return False

    def reply_to_comment(self, comment: Comment, text: str, xml: str) -> bool:
        if not tap_in_row(self.human, xml, comment.y, text="Reply"):
            return False
        self.human.pause(1.2)
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add comment")):
            return False
        self.human.pause(0.6)
        ok = self._send_comment(text)  # types, sends by the arrow, checks the text is there
        self.device.back()  # close the keyboard
        return ok


class TikTokDmAdapter(TikTokAdapter):
    """Inbox → unread thread → one short answer. Same geometry rule as Instagram."""

    def _rid(self, name: str) -> str | None:
        el = self.elements.get(name)
        return el.resource_id if el else None

    def open_inbox(self) -> bool:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.5))
        self.device.dismiss_popups(self.dump())
        self.human.pause(1.0)
        xml = self.dump()
        if not (self._tap_el("inbox_tab", xml) or self._tap_text(xml, "Inbox")):
            return False
        self.human.pause(2.5)
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
        if not (self._tap_el("dm_input", xml) or self._tap_text(xml, "Send a message")):
            return False
        self.human.pause(0.6)
        self.human.type_text(text)
        out = self.dump()
        ok = self._tap_el("dm_send", out) or self._tap_desc(out, "Send") or self._tap_text(out, "Send")
        self.human.pause(1.2)
        return ok

    def back_to_inbox(self) -> None:
        self.device.back(delay=0.8)
        self.human.pause(0.8)


def _unread_near(xml: str, y: int, band: int = 90) -> bool:
    for probe in ({"desc": "unread"}, {"desc": "new message"}, {"text": "Unread"}):
        for node in nodes_where(xml, **probe):
            c = center(node)
            if c and abs(c[1] - y) <= band:
                return True
    return False
