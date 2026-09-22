"""Reddit reply adapter: answering the comments under one's own post.

Two things Reddit does differently, both non-negotiable:

* **no vote in return.** ``likes_back = False``: upvoting the person who just
  commented on you is vote manipulation, the one behaviour Reddit bans on sight
  (docs/social/publishing.md §1 and §9). The like back exists on Instagram,
  TikTok and X; here the answer is the whole gesture.
* **no DM adapter.** No automatic DM answer in V1 — a human reads the inbox
  once a week (§9).

Verified on GeeLark ``explorer-us`` (Reddit 2026.35.0, 2026-09-19,
docs/social/screens-reddit-actions.md §3): a comment's author only exists in
the content-desc of its ``comment_header`` — "Level 1 comment by <author>,
<age>, <n> votes" — and its Reply button has no id and no label: it sits at a
fixed fraction of the ``fbp_comment_footer`` row (``COMMENT_FOOTER_X``). The
composer that opens is the post's own ("Join the conversation" / "Send
comment"), and a reply is proven by its text showing up in the thread.
"""

from __future__ import annotations

import logging
import re

from gitd.farm.replies import Comment, post_key, text_of
from gitd.farm.warm import center, nodes_where
from gitd.skills.ofmai_reddit.actions.core import COMMENT_FOOTER_X, PKG, RedditAdapter, _bounds_of, _desc_of

log = logging.getLogger(__name__)

# "Level 1 comment by jordan_reed97, 2 hours ago, 3 votes"
_HEADER = re.compile(r"^Level\s+(\d+)\s+comment\s+by\s+([^,]+),", re.IGNORECASE)
# text nodes of a comment row that are chrome, not the comment itself
_CHROME = re.compile(
    r"^(reply|share|award|more options|\d[\d,.]*\s*[km]?\s*(votes?|comments?)|\d+[hmd]|op|·)$", re.IGNORECASE
)
# how far below its header a comment's body may sit
_BODY_TOLERANCE = 260


class RedditCommentAdapter(RedditAdapter):
    """Profile → newest post → its comments → answer. Never a vote back."""

    likes_back = False

    def _launch(self) -> None:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))
        xml = self.dump()
        if not (self.device.dismiss_popups(xml) or self._settle(xml)):
            return
        self.human.pause(1.0)

    # ── reaching the post ─────────────────────────────────────────────

    def open_own_post(self) -> str | None:
        """"You" tab → the topmost card of the Posts tab → its post page.

        The profile lists the account's posts as the same cards as the feed
        (``post_unit`` / ``post_footer``); the post page opens from the card's
        comments button, like everywhere else.
        """
        self._launch()
        xml = self.dump()
        if not self._tap_el("profile_tab", xml):
            return None
        self.human.pause(2.5)
        page = self.dump()
        posts_tab = [n for n in self._nodes("profile_tab_label", page) if text_of(n).strip().lower() == "posts"]
        if posts_tab and (c := center(posts_tab[0])):
            self.human.tap(*c)
            self.human.pause(1.5)
            page = self.dump()
        title = self._card_title(page)
        pt = self._footer_point(page, "comments")
        if not pt:
            return None
        self.human.tap(*pt)
        self.human.pause(2.5)
        return post_key(title or self._page_title(self.dump()))

    def _card_title(self, xml: str) -> str:
        """The first line of text inside the topmost card (the post title)."""
        footer = self._footer(xml)
        cards = sorted((b for n in self._nodes("post_card", xml) if (b := _bounds_of(n))), key=lambda b: b[1])
        if not footer or not cards:
            return ""
        card_top, footer_top = cards[0][1], footer[1]
        best: tuple[int, str] | None = None
        for n in nodes_where(xml, text=""):
            t = text_of(n).strip()
            b = _bounds_of(n)
            if not t or not b or b[1] < card_top or b[3] > footer_top:
                continue
            if len(t) < 8 or _CHROME.match(t) or t.startswith(("u/", "r/")) or t in ("Join", "Joined"):
                continue
            if best is None or b[1] < best[0]:
                best = (b[1], t)
        return best[1] if best else ""

    def _page_title(self, xml: str) -> str:
        for n in self._nodes("page_title", xml):
            return text_of(n)
        return ""

    # ── reading and answering ─────────────────────────────────────────

    def read_comments(self, xml: str) -> list[Comment]:
        """Top-level comments only (Level 1): the people who answered *us*."""
        headers: list[tuple[int, str, tuple[int, int, int, int]]] = []
        for n in self._nodes("comment_header", xml):
            m = _HEADER.match(_desc_of(n).strip())
            b = _bounds_of(n)
            if not m or not b:
                continue
            headers.append((int(m.group(1)), m.group(2).strip(), b))
        bodies: list[tuple[str, tuple[int, int, int, int]]] = []
        for n in nodes_where(xml, text=""):
            t = text_of(n).strip()
            b = _bounds_of(n)
            if not t or not b or _CHROME.match(t) or _HEADER.match(_desc_of(n)):
                continue
            bodies.append((t, b))
        bodies.sort(key=lambda p: p[1][1])
        used: set[int] = set()
        out: list[Comment] = []
        for level, author, hb in sorted(headers, key=lambda h: h[2][1]):
            if level != 1:
                continue
            best, best_d = None, None
            for i, (_, bb) in enumerate(bodies):
                if i in used or bb[1] < hb[3] - 10:
                    continue
                d = bb[1] - hb[3]
                if d <= _BODY_TOLERANCE and (best_d is None or d < best_d):
                    best, best_d = i, d
            if best is None:
                continue
            used.add(best)
            text, bb = bodies[best]
            out.append(Comment(author=re.sub(r"^u/", "", author), text=text, y=(bb[1] + bb[3]) // 2))
        return out

    def like_comment(self, comment: Comment, xml: str) -> bool:
        return False  # vote manipulation — never, whatever the ledger allows

    def _comment_footer(self, xml: str, y: int, band: int = 260) -> tuple[int, int, int, int] | None:
        """The ``fbp_comment_footer`` row that belongs to the comment centred on ``y``."""
        best, best_d = None, None
        for n in self._nodes("comment_footer", xml):
            b = _bounds_of(n)
            if not b or b[1] < y - 40:
                continue
            d = b[1] - y
            if d <= band and (best_d is None or d < best_d):
                best, best_d = b, d
        return best

    def reply_to_comment(self, comment: Comment, text: str, xml: str) -> bool:
        box = self._comment_footer(xml, comment.y)
        if not box:
            return False
        x1, y1, x2, y2 = box
        self.human.tap(int(x1 + COMMENT_FOOTER_X["reply"] * (x2 - x1)), (y1 + y2) // 2)
        self.human.pause(1.5)
        sheet = self.dump()
        if not self._find("comment_send", sheet):
            # the composer did not open on its own: the bar at the bottom does
            if not self._tap_el("comment_input", sheet):
                self.device.back()
                return False
            self.human.pause(0.6)
        self.human.type_text(text)
        if not self._tap_el("comment_send", self.dump()):
            self.device.back()
            return False
        self.human.pause(2.0)
        posted = bool(nodes_where(self.dump(), text=text))
        self.device.back()  # close the keyboard if it is still up
        return posted

    def leave_post(self) -> None:
        self.back_to_feed()
