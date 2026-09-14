"""TikTok adapter + core actions. Same contract as the Instagram adapter."""

from __future__ import annotations

import logging
import re
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.zhiliaoapp.musically"


class TikTokAdapter:
    platform = "tiktok"

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
        self.human.sleep(self.human.profile.pause_s(3.5))
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
        return bool(nodes_where(xml, desc="Like")) and bool(nodes_where(xml, desc="Comment"))

    def next_video(self) -> None:
        self.human.swipe_feed("up")

    def like(self, xml: str) -> bool:
        for n in nodes_where(xml, desc="Like"):
            d = desc_of(n).lower()
            if "unlike" in d or "liked" in d or 'selected="true"' in n.lower():
                return False  # already liked: never toggle
        if self.human.profile.chance(0.6):
            w, h = self.human.screen.width, self.human.screen.height
            x, y = int(w * 0.5), int(h * 0.45)
            self.human.tap(x, y, settle=0.08)
            self.human.tap(x, y, settle=0.6)
            return True
        return self._tap_desc(xml, "Like", exclude="Unlike")

    def save(self, xml: str) -> bool:
        return self._tap_desc(xml, "Favorites", exclude="Remove")

    def open_author(self, xml: str) -> str | None:
        if not self._tap_desc(xml, "Profile photo") and not self._tap_desc(xml, "avatar"):
            return None
        self.human.pause(2.0)
        pxml = self.dump()
        if not (nodes_where(pxml, text="Follow") or nodes_where(pxml, text="Following") or nodes_where(pxml, text="Followers")):
            self.device.back()
            return None
        rows = nodes_where(pxml, rid=f"{PKG}:id/zef")
        m = re.search(r'text="(@?[^"]+)"', rows[0]) if rows else None
        return (m.group(1).lstrip("@") if m else "unknown")

    def follow(self, xml: str) -> bool:
        if nodes_where(xml, text="Following") or nodes_where(xml, text="Friends"):
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
        xml = self.dump()
        if not self._tap_desc(xml, "Comment"):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add comment")):
            self.device.back()
            return False
        self.human.pause(0.8)
        self.human.type_text(text)
        posted = self.dump()
        ok = self._tap_desc(posted, "Post") or self._tap_desc(posted, "Send")
        self.human.pause(1.5)
        self.device.back()
        self.human.pause(0.5)
        self.device.back()
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
        return False

    def _search(self, query: str) -> bool:
        xml = self.dump()
        if not self._tap_el("search_icon", xml):
            return False
        self.human.pause(1.5)
        sx = self.dump()
        self._tap_el("search_box", sx)
        self.human.pause(0.5)
        self.human.type_text(query.lstrip("#"))
        self.human.pause(1.0)
        self.device.press_enter()
        self.human.pause(2.5)
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True


class OpenApp(Action):
    name = "open_app"
    description = "Launch TikTok on the For You feed"

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
