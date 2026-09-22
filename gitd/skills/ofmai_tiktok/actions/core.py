"""TikTok adapter + core actions. Same contract as the Instagram adapter.

Verified on a device — GeeLark ``explorer-us`` (Android 13, 720x1440), TikTok
46.8.2, 2026-09-18, account @jordan.reed90; the survey is in
``docs/social/screens-tiktok-actions.md``. Three things are TikTok's own:

* **ids are obfuscated** (``a3d``, ``g5l``…): every selector is a content-desc,
  matched by *contains* because the label carries the count — "Like video.
  75.7K likes", "Read or add comments. 344 comments";
* **``uiautomator`` cannot read a playing video** ("could not get idle
  state"): :meth:`dump` retries once after a pause tap on the feed, and the
  search results — whose thumbnails loop — are never read at all;
* **a gesture is proven only by a counter that moves**: the post's for a like,
  a favourite and a comment, the account's own "Following" for a follow. A
  node that disappears proves nothing (a false positive was measured: the
  "Follow" node vanished, the profile still said Following 0). A gesture
  that moves no counter sets ``last_gesture_silent`` and returns False; the
  ledger never records it, and three in a row end the session as
  ``action_blocked``. One caveat: a rounded count ("75.7K") may not move for
  one like — then the gesture is "unproven", returned False without the
  silent flag.

The follow button sits 35 px under the avatar: it is tapped on its lower
edge, never at its centre.
"""

from __future__ import annotations

import logging
import re
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, desc_of, nodes_where
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.zhiliaoapp.musically"
# the screen the coordinates of elements.yaml were measured on
REF_W, REF_H = 720, 1440
_BOUNDS = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KkMm])?\b")
_SCALE = {"k": 1_000, "m": 1_000_000}


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


def _bounds(node: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS.search(node)
    return tuple(int(v) for v in m.groups()) if m else None  # type: ignore[return-value]


def parse_count(label: str) -> tuple[int | None, bool]:
    """``("Like video. 75.7K likes")`` -> ``(75700, True)``: the count and whether it is rounded.

    A rounded count (K / M suffix) may not move for a single gesture, which
    is why the caller treats "unchanged and rounded" as unproven rather than
    silent.
    """
    m = _NUMBER.search(label or "")
    if not m:
        return None, False
    raw, suffix = m.group(1).replace(",", "."), m.group(2)
    try:
        value = float(raw)
    except ValueError:
        return None, False
    if suffix:
        return int(value * _SCALE[suffix.lower()]), True
    return int(value), False


class TikTokAdapter:
    platform = "tiktok"
    last_gesture_silent = False

    def __init__(self, device, elements: dict[str, Element], human: HumanInput):
        self.device = device
        self.elements = elements
        self.human = human
        self._following: int | None = None  # the account's own count, read on the profile

    # ── helpers ───────────────────────────────────────────────────────

    def _raw_dump(self) -> str:
        return self.device.dump_xml() or ""

    def dump(self) -> str:
        """The tree — after one pause tap when a playing video blocks uiautomator."""
        xml = self._raw_dump()
        if xml:
            return xml
        w, h = self.human.screen.width, self.human.screen.height
        self.human.tap(int(w * 0.5), int(h * 0.45), settle=0.6)  # pauses the video
        return self._raw_dump()

    def _find(self, name: str, xml: str | None = None) -> tuple[int, int] | None:
        el = self.elements.get(name)
        if el is None:
            return None
        pos = el.find(self.device, xml)
        if pos and el.x is not None and el.y is not None and pos == (el.x, el.y):
            return self._scaled(el.x, el.y)
        return pos

    def _scaled(self, x: int, y: int) -> tuple[int, int]:
        w, h = self.human.screen.width, self.human.screen.height
        return int(x * w / REF_W), int(y * h / REF_H)

    def _tap_el(self, name: str, xml: str | None = None) -> bool:
        pos = self._find(name, xml)
        if not pos:
            return False
        self.human.tap(*pos)
        return True

    def _desc_node(self, xml: str, name: str) -> str | None:
        """The node whose content-desc contains the label of element `name`."""
        el = self.elements.get(name)
        if el is None or not el.content_desc:
            return None
        return next(iter(nodes_where(xml, desc=el.content_desc)), None)

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

    def _count_of(self, xml: str, name: str) -> tuple[int | None, bool]:
        node = self._desc_node(xml, name)
        if node is None:
            return None, False
        n, rounded = parse_count(desc_of(node))
        if n is not None:
            return n, rounded
        # some builds keep the count in the text node right under the button
        b = _bounds(node)
        if b:
            for t in nodes_where(xml, text=""):
                tb = _bounds(t)
                if tb and abs(tb[0] - b[0]) < 60 and 0 <= tb[1] - b[3] < 60:
                    return parse_count(_text(t))
        return None, False

    def _verify_counter(self, before: tuple[int | None, bool], after: tuple[int | None, bool]) -> bool:
        """True when the counter moved up. Silent when it did not and could have."""
        b, rounded = before
        a, _ = after
        if b is not None and a is not None and a > b:
            return True
        if b is not None and a is not None and a == b and rounded:
            log.info("[tiktok] rounded counter %s unchanged — unproven, not silent", b)
            return False
        self.last_gesture_silent = True
        return False

    # ── adapter contract ──────────────────────────────────────────────

    def open_feed(self) -> bool:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(3.5))
        for _ in range(3):
            xml = self.dump()
            if "Swipe up for more" in xml:  # the feed tutorial: a swipe clears it
                self.human.swipe_feed("up")
                self.human.pause(1.0)
                continue
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
        return bool(self._desc_node(xml, "like_button") or nodes_where(xml, desc="Like")) and bool(
            self._desc_node(xml, "comment_button") or nodes_where(xml, desc="Comment")
        )

    def next_video(self) -> None:
        self.human.swipe_feed("up")

    def like(self, xml: str) -> bool:
        """Like the visible video — proven by its like count going up."""
        self.last_gesture_silent = False
        node = self._desc_node(xml, "like_button") or next(iter(nodes_where(xml, desc="Like")), None)
        if node is None:
            return False
        d = desc_of(node).lower()
        if "unlike" in d or "liked" in d or 'selected="true"' in node.lower():
            return False  # already liked: never toggle
        before = self._count_of(xml, "like_button")
        c = center(node)
        if not c:
            return False
        if self.human.profile.chance(0.5):
            w, h = self.human.screen.width, self.human.screen.height
            x, y = int(w * 0.5), int(h * 0.45)
            self.human.tap(x, y, settle=0.08)
            self.human.tap(x, y, settle=0.6)  # a double tap on the video
        else:
            self.human.tap(*c)
        self.human.pause(1.0)
        return self._verify_counter(before, self._count_of(self.dump(), "like_button"))

    def save(self, xml: str) -> bool:
        """Favourite the visible video — proven by its favourites count going up."""
        self.last_gesture_silent = False
        node = self._desc_node(xml, "favorite_button") or next(iter(nodes_where(xml, desc="Favorites")), None)
        if node is None:
            return False
        if "remove" in desc_of(node).lower() and "add or remove" not in desc_of(node).lower():
            return False
        before = self._count_of(xml, "favorite_button")
        c = center(node)
        if not c:
            return False
        self.human.tap(*c)
        self.human.pause(1.0)
        return self._verify_counter(before, self._count_of(self.dump(), "favorite_button"))

    def open_author(self, xml: str) -> str | None:
        """Open the author's profile from the avatar ("<handle>'s profile")."""
        node = self._desc_node(xml, "author_avatar")
        handle = ""
        if node is not None:
            m = re.match(r"(.+?)(?:'s)?\s+profile", desc_of(node), re.IGNORECASE)
            handle = (m.group(1) if m else "").strip().lstrip("@")
            c = center(node)
            if c:
                self.human.tap(*c)
        elif not (self._tap_desc(xml, "Profile photo") or self._tap_desc(xml, "avatar")):
            return None
        self.human.pause(2.0)
        pxml = self.dump()
        if not (nodes_where(pxml, text="Followers") or nodes_where(pxml, text="Following")):
            self.device.back()
            return None
        return handle or "unknown"

    def _profile_count(self, xml: str, label: str) -> int | None:
        """The number next to a profile label ("Following", "Followers", "Likes")."""
        for n in nodes_where(xml, text=label):
            if _text(n).strip().lower() != label.lower():
                continue
            b = _bounds(n)
            if not b:
                continue
            best, best_d = None, None
            for t in nodes_where(xml, text=""):
                tb = _bounds(t)
                value, _ = parse_count(_text(t))
                if tb is None or value is None or _text(t).strip().lower() == label.lower():
                    continue
                d = abs(tb[0] - b[0]) + abs(tb[3] - b[1]) + abs(tb[1] - b[3]) // 2
                if abs(tb[0] - b[0]) < 120 and abs(tb[1] - b[1]) < 120 and (best_d is None or d < best_d):
                    best, best_d = value, d
            return best
        return None

    def read_own_following(self) -> int | None:
        """The account's own Following count: Profile tab, read, back to the feed."""
        xml = self.dump()
        if not self._tap_el("profile_tab", xml):
            return None
        self.human.pause(2.0)
        value = self._profile_count(self.dump(), "Following")
        self._tap_el("home_tab", self.dump())
        self.human.pause(1.5)
        return value

    def follow(self, xml: str) -> bool:
        """Follow — proven by the account's own Following count going up.

        From the feed: the "Follow <handle>" button under the avatar, tapped on
        its lower edge (35 px separate the two). From a profile: the "Follow"
        button. The node vanishing is NOT accepted as proof.
        """
        self.last_gesture_silent = False
        target = None
        node = self._desc_node(xml, "follow_on_feed")
        if node is not None:
            b = _bounds(node)
            if b:
                target = ((b[0] + b[2]) // 2, b[3] - max(4, (b[3] - b[1]) // 5))
        else:
            if nodes_where(xml, text="Following") and not nodes_where(xml, text="Follow"):
                return False
            for n in nodes_where(xml, text="Follow"):
                if _text(n).strip().lower() == "follow":
                    target = center(n)
                    break
        if target is None:
            return False
        if self._following is None:
            self._following = self.read_own_following()
            xml = self.dump()
            node = self._desc_node(xml, "follow_on_feed")
            if node is not None and (b := _bounds(node)):
                target = ((b[0] + b[2]) // 2, b[3] - max(4, (b[3] - b[1]) // 5))
        self.human.tap(*target)
        self.human.pause(1.2)
        after = self.read_own_following()
        if self._following is not None and after is not None and after > self._following:
            self._following = after
            return True
        self.last_gesture_silent = True
        return False

    def _send_comment(self, text: str) -> bool:
        self.human.type_text(text)
        posted = self.dump()
        if not (self._tap_desc(posted, "Post") or self._tap_desc(posted, "Send")):
            self._tap_el("comment_send", posted)  # the unlabelled arrow, by position
        self.human.pause(1.5)
        return bool(nodes_where(self.dump(), text=text))

    def comment(self, text: str) -> bool:
        """Comment on the visible video — proven by the text showing in the sheet."""
        self.last_gesture_silent = False
        xml = self.dump()
        before = self._count_of(xml, "comment_button")
        if not (self._tap_el("comment_button", xml) or self._tap_desc(xml, "Comment")):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add comment")):
            self.device.back()
            return False
        self.human.pause(0.8)
        ok = self._send_comment(text)
        self.device.back()  # keyboard
        self.human.pause(0.5)
        self.device.back()  # sheet
        if ok:
            return True
        after = self._count_of(self.dump(), "comment_button")
        if before[0] is not None and after[0] is not None and after[0] > before[0]:
            return True
        self.last_gesture_silent = True
        return False

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
        """Magnifier -> field -> Enter. The results play: never dumped, only scrolled."""
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
