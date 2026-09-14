"""Instagram adapter + core actions.

The adapter is what the shared warming loop drives. Everything goes through
:class:`HumanInput`, never through raw ``device.tap``.
"""

from __future__ import annotations

import logging
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.instagram.android"


class InstagramAdapter:
    platform = "instagram"

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
            d = desc_of(n)
            if exclude and exclude.lower() in d.lower():
                continue
            c = center(n)
            if c:
                self.human.tap(*c)
                return True
        return False

    # ── adapter contract ──────────────────────────────────────────────

    def open_feed(self) -> bool:
        """Home first (stories are there), then Reels: the warming surface."""
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))
        xml = self.dump()
        self.device.dismiss_popups(xml)
        self.human.pause(1.0)
        xml = self.dump()
        if not self._tap_el("reels_tab", xml):
            return False
        self.human.pause(2.0)
        return self.on_feed(self.dump())

    def on_feed(self, xml: str) -> bool:
        return bool(nodes_where(xml, desc="Like") or nodes_where(xml, desc="Liked")) and bool(
            nodes_where(xml, desc="Comment")
        )

    def next_video(self) -> None:
        self.human.swipe_feed("up")

    def like(self, xml: str) -> bool:
        if nodes_where(xml, desc="Liked"):
            return False  # already liked: never toggle
        # double-tap on the video is the most human way to like a reel
        if self.human.profile.chance(0.6):
            w, h = self.human.screen.width, self.human.screen.height
            x, y = int(w * 0.5), int(h * 0.45)
            self.human.tap(x, y, settle=0.08)
            self.human.tap(x, y, settle=0.6)
            return True
        return self._tap_desc(xml, "Like", exclude="Liked")

    def save(self, xml: str) -> bool:
        # Save lives in the "More options" sheet on Reels
        if not self._tap_desc(xml, "More options"):
            return False
        self.human.pause(1.0)
        sheet = self.dump()
        ok = self._tap_desc(sheet, "Save") or self._tap_text(sheet, "Save")
        if not ok:
            self.device.back()
        return ok

    def _tap_text(self, xml: str, text: str) -> bool:
        for n in nodes_where(xml, text=text):
            c = center(n)
            if c:
                self.human.tap(*c)
                return True
        return False

    def open_author(self, xml: str) -> str | None:
        name_pos = self._find("author_name", xml)
        if name_pos:
            self.human.tap(*name_pos)
        elif not self._tap_desc(xml, "Profile picture"):
            return None
        self.human.pause(2.0)
        pxml = self.dump()
        if not (nodes_where(pxml, text="Follow") or nodes_where(pxml, text="Following") or nodes_where(pxml, text="posts")):
            self.device.back()
            return None
        handles = nodes_where(pxml, rid=f"{PKG}:id/action_bar_title")
        return (handles and _text(handles[0])) or "unknown"

    def follow(self, xml: str) -> bool:
        if nodes_where(xml, text="Following") or nodes_where(xml, text="Requested"):
            return False
        for n in nodes_where(xml, text="Follow"):
            if _text(n).strip().lower() == "follow":
                c = center(n)
                if c:
                    self.human.tap(*c)
                    return True
        return False

    def comment(self, text: str) -> bool:
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
        ok = self._tap_el("comment_post", posted) or self._tap_desc(posted, "Post")
        self.human.pause(1.5)
        self.device.back()  # close keyboard
        self.human.pause(0.5)
        self.device.back()  # close sheet
        return ok

    def back_to_feed(self) -> None:
        for _ in range(4):
            xml = self.dump()
            if self.on_feed(xml):
                return
            self.device.back(delay=0.8)
        xml = self.dump()
        self._tap_el("reels_tab", xml)
        self.human.pause(1.5)

    def detour(self, kind: str, query: str | None) -> bool:
        if kind == "stories":
            return self._watch_stories()
        if kind == "search" and query:
            return self._search(query)
        return False

    def _watch_stories(self) -> bool:
        xml = self.dump()
        self._tap_el("home_tab", xml)
        self.human.pause(2.0)
        home = self.dump()
        for n in nodes_where(home, desc="story"):
            if "your story" in desc_of(n).lower():
                continue
            c = center(n)
            if c:
                self.human.tap(*c)
                # a few stories, tap-through
                for _ in range(self.human.profile.rng.randint(2, 6)):
                    self.human.sleep(self.human.profile.rng.uniform(2.0, 6.0))
                    w, h = self.human.screen.width, self.human.screen.height
                    self.human.tap(int(w * 0.85), int(h * 0.5), settle=0.3)
                self.device.back()
                return True
        return False

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
        self.human.pause(1.5)
        self.device.press_enter()
        self.human.pause(2.5)
        # browse the results a bit
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True


def _text(node: str) -> str:
    import re

    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


# ── Actions ───────────────────────────────────────────────────────────────────


class OpenApp(Action):
    name = "open_app"
    description = "Launch Instagram and land on the home feed"

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


class GoReels(Action):
    name = "go_reels"
    description = "Open the Reels tab"

    def execute(self) -> ActionResult:
        pos = self.find_element("reels_tab")
        if not pos:
            return ActionResult(success=False, error="Reels tab not found")
        HumanInput(self.device).tap(*pos)
        time.sleep(2)
        return ActionResult(success=True, data={"pos": pos})

    def postcondition(self) -> bool:
        xml = self.device.dump_xml()
        return bool(nodes_where(xml, desc="Like") or nodes_where(xml, desc="Liked"))
