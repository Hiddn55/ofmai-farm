"""Reddit adapter + core actions.

Same contract as the Instagram and TikTok adapters: the shared warming loop
(:mod:`gitd.farm.warm`) drives it and every gesture goes through
:class:`HumanInput`, never through a raw ``device.tap``.

What each primitive means on Reddit (docs/social/warming-policy.md §7 and
publishing.md §9):

* a **view** is one post card of the Home feed;
* **like** is the upvote, counted under the ``likes`` cap. The downvote is
  never tapped, and no vote is ever cast in return for one received — vote
  manipulation is the one thing Reddit bans on sight;
* **save** is "Save" in the post's overflow menu;
* **open_author** opens the author's profile, never the subreddit;
* **follow** is joining the post's subreddit, only inside the ``open_author``
  branch and under the day's ``follows`` cap (R16);
* the only detour is a niche subreddit search: no stories on Reddit.
"""

from __future__ import annotations

import logging
import re
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.reddit.frontpage"


def _text_of(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


class RedditAdapter:
    platform = "reddit"

    def __init__(self, device, elements: dict[str, Element], human: HumanInput):
        self.device = device
        self.elements = elements
        self.human = human

    # ── helpers ───────────────────────────────────────────────────────

    def dump(self) -> str:
        return self.device.dump_xml() or ""

    def _find(self, name: str, xml: str | None = None) -> tuple[int, int] | None:
        el = self.elements.get(name)
        return el.find(self.device, xml) if el else None

    def _tap_el(self, name: str, xml: str | None = None) -> bool:
        pos = self._find(name, xml)
        if not pos:
            return False
        self.human.tap(*pos)
        return True

    def _tap_desc(self, xml: str, contains: str, *, exclude: str | None = None) -> bool:
        for n in nodes_where(xml, desc=contains):
            if exclude and exclude.lower() in desc_of(n).lower():
                continue
            c = center(n)
            if c:
                self.human.tap(*c)
                return True
        return False

    def _tap_text(self, xml: str, text: str) -> bool:
        for n in nodes_where(xml, text=text):
            c = center(n)
            if c:
                self.human.tap(*c)
                return True
        return False

    # ── adapter contract ──────────────────────────────────────────────

    def open_feed(self) -> bool:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))
        for _ in range(3):
            xml = self.dump()
            if not self.device.dismiss_popups(xml):
                break
            self.human.pause(0.8)
        xml = self.dump()
        if not self.on_feed(xml):
            self._tap_el("home_tab", xml)
            self.human.pause(2.0)
            xml = self.dump()
        return self.on_feed(xml)

    def on_feed(self, xml: str) -> bool:
        return bool(nodes_where(xml, desc="Upvote")) and bool(nodes_where(xml, desc="Comment"))

    def next_video(self) -> None:
        """One card further down the feed (the loop's "next item")."""
        self.human.swipe_feed("up")

    def like(self, xml: str) -> bool:
        """Upvote. Never un-vote, never downvote."""
        for n in nodes_where(xml, desc="Upvote"):
            d = desc_of(n).lower()
            if "remove" in d or "upvoted" in d or 'selected="true"' in n.lower():
                return False  # already upvoted: never toggle
        return self._tap_desc(xml, "Upvote", exclude="Remove")

    def save(self, xml: str) -> bool:
        """Save lives in the post's overflow menu."""
        if not self._tap_desc(xml, "More options"):
            return False
        self.human.pause(1.0)
        sheet = self.dump()
        ok = self._tap_el("save_option", sheet) or self._tap_text(sheet, "Save")
        if not ok:
            self.device.back()
        return ok

    def open_author(self, xml: str) -> str | None:
        """The author's profile — never the subreddit (that is not a person)."""
        author = None
        rows = nodes_where(xml, rid=f"{PKG}:id/author")
        if rows:
            author = _text_of(rows[0]).lstrip("u/").strip() or None
            c = center(rows[0])
            if c:
                self.human.tap(*c)
            else:
                return None
        else:
            hit = [n for n in nodes_where(xml, text="u/") if _text_of(n).startswith("u/")]
            if not hit:
                return None
            author = _text_of(hit[0]).lstrip("u/").strip() or None
            c = center(hit[0])
            if not c:
                return None
            self.human.tap(*c)
        self.human.pause(2.0)
        pxml = self.dump()
        if not (nodes_where(pxml, text="Follow") or nodes_where(pxml, text="Following") or nodes_where(pxml, text="karma")):
            self.device.back()
            return None
        return author or "unknown"

    def follow(self, xml: str) -> bool:
        """Join the subreddit the post came from (warming-policy.md §7).

        The loop calls this with the author-profile screen, where there is no
        Join button, so we come back to the feed and join from the post card.
        Never "Joined" — leaving a community is not a warming gesture.
        """
        if self._tap_join(xml):
            return True
        self.back_to_feed()
        return self._tap_join(self.dump())

    def _tap_join(self, xml: str) -> bool:
        if nodes_where(xml, text="Joined"):
            return False
        for n in nodes_where(xml, text="Join"):
            if _text_of(n).strip().lower() == "join":
                c = center(n)
                if c:
                    self.human.tap(*c)
                    return True
        return False

    def comment(self, text: str) -> bool:
        """Comment on the post on screen. ASCII only (R12), never a link (R22)."""
        xml = self.dump()
        if not self._tap_desc(xml, "Comment"):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add a comment")):
            self.device.back()
            return False
        self.human.pause(0.8)
        self.human.type_text(text)
        posted = self.dump()
        ok = self._tap_el("comment_send", posted) or self._tap_desc(posted, "Post comment")
        self.human.pause(1.5)
        self.device.back()  # close keyboard
        self.human.pause(0.5)
        self.device.back()  # back to the feed
        return ok

    def back_to_feed(self) -> None:
        for _ in range(4):
            xml = self.dump()
            if self.on_feed(xml):
                return
            self.device.back(delay=0.8)
        xml = self.dump()
        self._tap_el("home_tab", xml)
        self.human.pause(1.5)

    def detour(self, kind: str, query: str | None) -> bool:
        if kind == "search" and query:
            return self._search(query)
        return False  # no stories on Reddit

    def _search(self, query: str) -> bool:
        xml = self.dump()
        if not self._tap_el("search_icon", xml):
            return False
        self.human.pause(1.5)
        sx = self.dump()
        if not (self._tap_el("search_input", sx) or self._tap_text(sx, "Search")):
            return False
        self.human.pause(0.5)
        term = query.lstrip("#")
        self.human.type_text(term if term.startswith("r/") else f"r/{term}")
        self.human.pause(1.2)
        self.device.press_enter()
        self.human.pause(2.5)
        results = self.dump()
        self._tap_el("hot_tab", results)
        self.human.pause(1.5)
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True


# ── Actions ───────────────────────────────────────────────────────────────────


class OpenApp(Action):
    name = "open_app"
    description = "Launch Reddit on the Home feed"

    def execute(self) -> ActionResult:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(4)
        for _ in range(3):
            xml = self.device.dump_xml()
            if not self.device.dismiss_popups(xml, popups=getattr(self, "_popup_detectors", None)):
                break
            time.sleep(1)
        return ActionResult(success=True)

    def postcondition(self) -> bool:
        return PKG in self.device.adb("shell", "dumpsys", "window", timeout=5)
