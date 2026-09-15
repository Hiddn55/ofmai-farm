"""X adapter + core actions.

Same contract as the Instagram and TikTok adapters: the shared warming loop
(:mod:`gitd.farm.warm`) drives it and every gesture goes through
:class:`HumanInput`, never through a raw ``device.tap``.

What each primitive means on X (docs/social/warming-policy.md §7):

* a **view** is one post card of the ``For you`` timeline;
* **like** is the heart, **save** is the bookmark;
* **open_author** opens the post author's profile;
* **follow** only ever happens inside the ``open_author`` branch, under the
  day's ``follows`` cap — never in bulk, never from the API (R16, the
  @potter_society incident);
* the only detour is a niche hashtag search: no stories on X.
"""

from __future__ import annotations

import logging
import re
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.twitter.android"


class XAdapter:
    platform = "x"

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
        # stay on "For you": "Following" is a different, much smaller timeline
        if nodes_where(xml, text="For you"):
            self._tap_el("for_you_tab", xml)
            self.human.pause(1.5)
            xml = self.dump()
        return self.on_feed(xml)

    def on_feed(self, xml: str) -> bool:
        has_like = bool(nodes_where(xml, desc="Like") or nodes_where(xml, desc="Liked"))
        return has_like and bool(nodes_where(xml, desc="Reply"))

    def next_video(self) -> None:
        """One card further down the timeline (the loop's "next item")."""
        self.human.swipe_feed("up")

    def like(self, xml: str) -> bool:
        # never un-like: "Liked" / "Unlike" means the heart is already on
        for n in nodes_where(xml, desc="Like"):
            d = desc_of(n).lower()
            if d.startswith("liked") or "unlike" in d:
                return False
        if nodes_where(xml, desc="Liked"):
            return False
        return self._tap_desc(xml, "Like", exclude="Unlike")

    def save(self, xml: str) -> bool:
        """Bookmark the post. Never the "Remove bookmark" state."""
        if nodes_where(xml, desc="Bookmarked") or nodes_where(xml, desc="Remove bookmark"):
            return False
        return self._tap_desc(xml, "Bookmark", exclude="Remove")

    def open_author(self, xml: str) -> str | None:
        name_pos = self._find("author_name", xml)
        if name_pos:
            self.human.tap(*name_pos)
        elif not self._tap_desc(xml, "Profile image"):
            return None
        self.human.pause(2.0)
        pxml = self.dump()
        if not (nodes_where(pxml, text="Follow") or nodes_where(pxml, text="Following") or nodes_where(pxml, text="Followers")):
            self.device.back()
            return None
        rows = nodes_where(pxml, rid=f"{PKG}:id/screen_name")
        m = re.search(r'\btext="(@?[^"]+)"', rows[0]) if rows else None
        return (m.group(1).lstrip("@") if m else "unknown")

    def follow(self, xml: str) -> bool:
        if nodes_where(xml, text="Following") or nodes_where(xml, text="Pending"):
            return False
        for n in nodes_where(xml, text="Follow"):
            m = re.search(r'\btext="([^"]*)"', n)
            if m and m.group(1).strip().lower() == "follow":
                c = center(n)
                if c:
                    self.human.tap(*c)
                    return True
        return False

    def comment(self, text: str) -> bool:
        """Reply to the post on screen. ASCII only (R12); never before `network`
        — the comment cap is 0 in `consume` and `light` (warming-policy.md §2)."""
        xml = self.dump()
        if not self._tap_desc(xml, "Reply"):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("reply_input", sheet) or self._tap_text(sheet, "Post your reply")):
            self.device.back()
            return False
        self.human.pause(0.8)
        self.human.type_text(text)
        posted = self.dump()
        ok = self._tap_el("reply_send", posted) or self._tap_text(posted, "Reply")
        self.human.pause(1.5)
        self.device.back()  # close keyboard
        self.human.pause(0.5)
        self.device.back()  # back to the timeline
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
        return False  # no stories on X

    def _search(self, query: str) -> bool:
        xml = self.dump()
        if not self._tap_el("search_tab", xml):
            return False
        self.human.pause(1.5)
        sx = self.dump()
        if not (self._tap_el("search_input", sx) or self._tap_text(sx, "Search")):
            return False
        self.human.pause(0.5)
        self.human.type_text(query if query.startswith("#") else f"#{query}")
        self.human.pause(1.2)
        self.device.press_enter()
        self.human.pause(2.5)
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True


# ── Actions ───────────────────────────────────────────────────────────────────


class OpenApp(Action):
    name = "open_app"
    description = "Launch X on the For you timeline"

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
