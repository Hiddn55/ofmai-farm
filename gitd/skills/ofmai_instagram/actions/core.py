"""Instagram adapter + core actions.

The adapter is what the shared warming loop drives. Everything goes through
:class:`HumanInput`, never through raw ``device.tap``.

Verified on a device — GeeLark ``explorer-us`` (Android 13, 720x1440),
Instagram 443.0.0.48.82, 2026-09-16, account jordan.reed.97; the survey is in
``docs/social/screens-instagram-actions.md``. The warming surface is the
**home feed**: its posts expose stable ids (``row_feed_button_like`` …) and
content-descs that flip with the state. A gesture is therefore proven by that
flip — ``Like`` → ``Liked``, ``Add to Saved`` → ``Remove from saved``,
``Follow x`` → ``Following x``, ``unseen story`` → ``seen story`` — and a
gesture that flips nothing sets ``last_gesture_silent`` and returns False:
the ledger never records it, and three in a row end the session as
``action_blocked`` (:func:`gitd.farm.warm.run_session`).

Three traps met on the device, all handled here: the promotional
interstitials that land at any moment (one dismiss id, settled before every
gesture); the contact-sync screen that loops (``Next`` and Back do nothing —
the exit is a force-stop and a relaunch, which lands on the feed and never
syncs anything); and the suggestions carousel that follows every follow — the
chain-follow rail, never tapped (R16).
"""

from __future__ import annotations

import logging
import re
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.instagram.android"
_BOUNDS = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
# a post's like / save / comment buttons sit on one row: this is how far apart
# (vertically) two nodes may be and still belong to the same post
ROW_BAND = 60


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


def _bounds(node: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS.search(node)
    return tuple(int(v) for v in m.groups()) if m else None  # type: ignore[return-value]


class InstagramAdapter:
    platform = "instagram"
    # raised by a verifying gesture that fired and proved nothing on screen;
    # read by gitd.farm.warm.run_session after each like / save / follow / comment
    last_gesture_silent = False

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

    def _rid(self, name: str) -> str | None:
        el = self.elements.get(name)
        return el.resource_id if el else None

    def _nodes(self, name: str, xml: str) -> list[str]:
        rid = self._rid(name)
        return nodes_where(xml, rid=rid) if rid else []

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

    def _tap_text(self, xml: str, text: str) -> bool:
        for n in nodes_where(xml, text=text):
            c = center(n)
            if c:
                self.human.tap(*c)
                return True
        return False

    def _topmost(self, nodes: list[str]) -> str | None:
        """The first of these nodes that is fully on screen, top to bottom."""
        h = self.human.screen.height
        best = None
        for n in nodes:
            b = _bounds(n)
            if not b or b[1] < 0 or b[3] > h:
                continue
            if best is None or b[1] < best[0]:
                best = (b[1], n)
        return best[1] if best else None

    def _in_row(self, name: str, xml: str, y: int) -> str | None:
        """The `name` button that belongs to the post whose action bar is at ``y``."""
        for n in self._nodes(name, xml):
            c = center(n)
            if c and abs(c[1] - y) <= ROW_BAND:
                return n
        return None

    def _settle(self, xml: str) -> bool:
        """Dismiss one promotional interstitial, if any. Returns True if it did."""
        if self._tap_el("promo_dismiss", xml):
            return True
        if "Introducing" in xml and self._tap_text(xml, "Not now"):
            return True
        return False

    def _contacts_loop(self, xml: str) -> bool:
        """The contact-sync screen: "Next" does nothing and neither does Back."""
        low = xml.lower()
        return "contacts" in low and not self.on_feed(xml) and bool(nodes_where(xml, text="Next"))

    def _launch(self) -> None:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.0))

    # ── adapter contract ──────────────────────────────────────────────

    def open_feed(self) -> bool:
        """Launch on the Home feed — the surveyed surface, with the story tray."""
        self._launch()
        for _ in range(3):
            xml = self.dump()
            if not (self.device.dismiss_popups(xml) or self._settle(xml)):
                break
            self.human.pause(0.8)
        xml = self.dump()
        if self._contacts_loop(xml):
            # the only exit — and the contacts are never synced, which is what we want
            self.device.adb("shell", "am", "force-stop", PKG)
            self.human.pause(1.0)
            self._launch()
            xml = self.dump()
        if not self.on_feed(xml):
            self._tap_el("home_tab", xml)
            self.human.pause(2.0)
            xml = self.dump()
        return self.on_feed(xml)

    def on_feed(self, xml: str) -> bool:
        """A post with its like and comment buttons, and no comment composer open."""
        liked = nodes_where(xml, desc="Like") or nodes_where(xml, desc="Liked")
        if not (liked and nodes_where(xml, desc="Comment")):
            return False
        return not (self._nodes("comment_input", xml) or self._nodes("comment_input_legacy", xml))

    def next_video(self) -> None:
        self.human.swipe_feed("up")

    def _like_node(self, xml: str) -> str | None:
        node = self._topmost(self._nodes("like_button", xml))
        if node is None:  # no id on this build: the label alone
            node = self._topmost(nodes_where(xml, desc="Like") + nodes_where(xml, desc="Liked"))
        return node

    def like(self, xml: str) -> bool:
        """Like the topmost post — proven by ``Like`` → ``Liked``. Never a toggle."""
        self.last_gesture_silent = False
        node = self._like_node(xml)
        if node is None:
            return False
        if desc_of(node).strip().lower() == "liked":
            return False  # already liked: a second tap would remove it
        c = center(node)
        if not c:
            return False
        if self.human.profile.chance(0.3):
            # a double tap on the photo above the bar is the other human way to like
            photo = self._topmost(self._nodes("post_media", xml))
            pc = center(photo) if photo else None
            if pc and pc[1] < c[1]:
                self.human.tap(*pc, settle=0.08)
                self.human.tap(*pc, settle=0.6)
            else:
                self.human.tap(*c)
        else:
            self.human.tap(*c)
        self.human.pause(0.8)
        after = self._in_row("like_button", self.dump(), c[1])
        if after is None:
            after = next((n for n in nodes_where(self.dump(), desc="Liked") if (cc := center(n)) and abs(cc[1] - c[1]) <= ROW_BAND), None)
        if after is not None and desc_of(after).strip().lower() == "liked":
            return True
        self.last_gesture_silent = True
        return False

    def save(self, xml: str) -> bool:
        """Save the topmost post — proven by ``Add to Saved`` → ``Remove from saved``."""
        self.last_gesture_silent = False
        like = self._like_node(xml)
        if like is None:
            return False
        c = center(like)
        node = self._in_row("save_button", xml, c[1]) if c else None
        if node is None:
            node = next((n for n in nodes_where(xml, desc="Save") if (cc := center(n)) and c and abs(cc[1] - c[1]) <= ROW_BAND), None)
        if node is None:
            return False
        label = desc_of(node).strip().lower()
        if label.startswith("remove") or label == "saved":
            return False  # already saved: never un-save
        sc = center(node)
        if not sc:
            return False
        self.human.tap(*sc)
        self.human.pause(0.8)
        after = self.dump()
        node2 = self._in_row("save_button", after, sc[1])
        if node2 is None:
            node2 = next((n for n in nodes_where(after, desc="Remove from saved") + nodes_where(after, desc="Saved") if (cc := center(n)) and abs(cc[1] - sc[1]) <= ROW_BAND), None)
        if node2 is not None and (desc_of(node2).strip().lower().startswith("remove") or desc_of(node2).strip().lower() == "saved"):
            return True
        self.last_gesture_silent = True
        return False

    def open_author(self, xml: str) -> str | None:
        """Open the author's profile from the topmost post; returns the handle."""
        name = self._topmost(self._nodes("post_author", xml))
        handle = _text(name).strip().lstrip("@") if name else ""
        if name and (c := center(name)):
            self.human.tap(*c)
        elif not self._tap_desc(xml, "Profile picture"):
            return None
        self.human.pause(2.0)
        pxml = self.dump()
        if self._settle(pxml):
            pxml = self.dump()
        on_profile = bool(
            self._nodes("follow_button", pxml)
            or nodes_where(pxml, text="Follow")
            or nodes_where(pxml, text="Following")
            or nodes_where(pxml, text="posts")
        )
        if not on_profile:
            self.device.back()
            return None
        if handle:
            return handle
        titles = nodes_where(pxml, rid=f"{PKG}:id/action_bar_title")
        return (titles and _text(titles[0])) or "unknown"

    def follow(self, xml: str) -> bool:
        """Follow from the profile header — proven by ``Follow x`` → ``Following x``.

        Never the suggestions carousel that appears right after (R16), never
        a second tap on ``Following`` / ``Requested``.
        """
        self.last_gesture_silent = False
        node = next(iter(self._nodes("follow_button", xml)), None)
        if node is not None:
            label = desc_of(node).strip().lower() or _text(node).strip().lower()
            if not label.startswith("follow ") and label != "follow":
                return False  # "Following x", "Requested", or something else
            c = center(node)
            if not c:
                return False
            self.human.tap(*c)
            self.human.pause(1.2)
            after = next(iter(self._nodes("follow_button", self.dump())), None)
            if after is not None:
                l2 = desc_of(after).strip().lower() or _text(after).strip().lower()
                if l2.startswith("following") or l2 == "requested":
                    return True
            self.last_gesture_silent = True
            return False
        # no id on this build: the bare text, exact — never the carousel's buttons
        if nodes_where(xml, text="Following") or nodes_where(xml, text="Requested"):
            return False
        for n in nodes_where(xml, text="Follow"):
            if _text(n).strip().lower() == "follow" and (c := center(n)):
                self.human.tap(*c)
                self.human.pause(1.2)
                if nodes_where(self.dump(), text="Following"):
                    return True
                self.last_gesture_silent = True
                return False
        return False

    def _tap_comment_input(self, sheet: str) -> bool:
        return (
            self._tap_el("comment_input", sheet)
            or self._tap_el("comment_input_legacy", sheet)
            or self._tap_text(sheet, "Add a comment")
            or self._tap_desc(sheet, "Join the conversation")
        )

    def comment(self, text: str) -> bool:
        """Comment on the topmost post — proven by "<handle> said <text>" in the thread."""
        self.last_gesture_silent = False
        xml = self.dump()
        like = self._like_node(xml)
        node = self._in_row("comment_button", xml, center(like)[1]) if like and center(like) else None
        if node is not None and (c := center(node)):
            self.human.tap(*c)
        elif not self._tap_desc(xml, "Comment"):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not self._tap_comment_input(sheet):
            self.device.back()
            return False
        self.human.pause(0.8)
        self.human.type_text(text)
        posted = self.dump()
        if not (self._tap_el("comment_post", posted) or self._tap_desc(posted, "Post")):
            self.device.back()
            self.device.back()
            return False
        self.human.pause(1.5)
        after = self.dump()
        ok = bool(nodes_where(after, desc=text) or nodes_where(after, text=text))
        self.device.back()  # close keyboard
        self.human.pause(0.5)
        self.device.back()  # close sheet
        if ok:
            return True
        self.last_gesture_silent = True
        return False

    def back_to_feed(self) -> None:
        for _ in range(4):
            xml = self.dump()
            if self.on_feed(xml):
                return
            if self._settle(xml):
                continue
            self.device.back(delay=0.8)
        xml = self.dump()
        self._tap_el("home_tab", xml)
        self.human.pause(1.5)

    def detour(self, kind: str, query: str | None) -> bool:
        if kind == "stories":
            return self._watch_stories()
        if kind == "search" and query:
            return self._search(query)
        return False

    def _watch_stories(self) -> bool:
        """Open one unseen ring of the tray — proven by ``unseen story`` → ``seen story``."""
        xml = self.dump()
        self._tap_el("home_tab", xml)
        self.human.pause(2.0)
        home = self.dump()
        rings = self._nodes("story_ring", home) or nodes_where(home, desc="story")
        for n in rings:
            d = desc_of(n)
            low = d.lower()
            if "your story" in low or "unseen" not in low:
                continue
            c = center(n)
            if not c:
                continue
            self.human.tap(*c)
            for _ in range(self.human.profile.rng.randint(2, 6)):  # a few stories, tap-through
                self.human.sleep(self.human.profile.rng.uniform(2.0, 6.0))
                w, h = self.human.screen.width, self.human.screen.height
                self.human.tap(int(w * 0.85), int(h * 0.5), settle=0.3)
            self.device.back()
            self.human.pause(1.0)
            owner = low.split("'s ")[0]
            after = self.dump()
            for m in self._nodes("story_ring", after) or nodes_where(after, desc="story"):
                md = desc_of(m).lower()
                if md.startswith(owner) and "seen story" in md and "unseen" not in md:
                    return True
            return False
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
