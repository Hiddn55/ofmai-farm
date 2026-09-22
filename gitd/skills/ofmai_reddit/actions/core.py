"""Reddit adapter + core actions.

Same contract as the Instagram and TikTok adapters: the shared warming loop
(:mod:`gitd.farm.warm`) drives it and every gesture goes through
:class:`HumanInput`, never through a raw ``device.tap``.

Everything below was verified on a device — GeeLark ``explorer-us`` (Android
13, 720x1440), Reddit 2026.35.0, 2026-09-16 and 2026-09-19; the survey is in
``docs/social/screens-reddit-actions.md``.

* Reddit is Jetpack Compose. A post card's vote / comments / share buttons
  expose **no id and no content-desc**: they exist only as fixed fractions of
  the ``post_footer`` node's width (:data:`FOOTER_X`). Same for the ⋮ / Reply /
  vote controls of a comment (:data:`COMMENT_FOOTER_X`).
* A gesture is therefore **verified, never assumed**: an upvote by the colour
  of the arrow (a screencap pixel turns orange), a join by ``Join`` →
  ``Joined``, a save by ``Save`` → ``Unsave`` in the reopened menu, a comment
  by the post's "N comments" counter or the typed text showing up. A gesture
  that fires and proves nothing sets ``last_gesture_silent`` and returns
  False: the ledger never records it, and three in a row end the session as
  ``action_blocked`` (:func:`gitd.farm.warm.run_session`).
* What each primitive means (warming-policy.md §7, publishing.md §9): a
  **view** is one card of the Home feed; **like** is the upvote — never the
  downvote, never a toggle; **save** is "Save" in the card's overflow menu;
  **open_author** opens the community the card belongs to (a card exposes no
  author) and returns its name; **follow** joins that community from the
  card, under the ``follows`` cap (R16); the only detour is a search — there
  are no stories on Reddit.
"""

from __future__ import annotations

import logging
import re
import struct
import subprocess
import time

from gitd.farm.human import HumanInput
from gitd.farm.warm import center, nodes_where, parse_karma
from gitd.skills.base import Action, ActionResult, Element

log = logging.getLogger(__name__)

PKG = "com.reddit.frontpage"

# Where the buttons of a post card sit inside `post_footer`, as a fraction of
# the footer's width — measured on a 720 px wide screen (x = 61 / 172 / 247 /
# 586 / 663 for a footer spanning the width). They have no id and no
# content-desc, so this is the only handle there is.
FOOTER_X = {
    "upvote": 61 / 720,
    "downvote": 172 / 720,
    "comments": 247 / 720,
    "repost": 586 / 720,
    "share": 663 / 720,
}
# Same for a comment's own row (`fbp_comment_footer`): ⋮ / Reply / up / down.
COMMENT_FOOTER_X = {"menu": 410 / 720, "reply": 512 / 720, "upvote": 603 / 720, "downvote": 662 / 720}

_BOUNDS = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_COMMENT_COUNT = re.compile(r"(\d[\d,.]*)\s*([kKmM])?\s*comments?\b")
_SUB_NAME = re.compile(r"\br/[A-Za-z0-9_]+")


def _is_upvote_orange(r: int, g: int, b: int) -> bool:
    """Reddit's upvote orange (#FF4500 family), with room for anti-aliasing."""
    return r >= 200 and 40 <= g <= 140 and b <= 80


def _text_of(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


def _desc_of(node: str) -> str:
    m = re.search(r'content-desc="([^"]*)"', node)
    return m.group(1) if m else ""


def _bounds_of(node: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS.search(node)
    return tuple(int(v) for v in m.groups()) if m else None  # type: ignore[return-value]


def _count(raw: str, suffix: str | None) -> int | None:
    """"345" -> 345, "1,234" -> 1234, "1.2" + "K" -> 1200 (en-US Reddit)."""
    cleaned = raw.replace(",", "")
    try:
        if suffix:
            return int(float(cleaned) * {"k": 1_000, "m": 1_000_000}[suffix.lower()])
        return int(cleaned.replace(".", ""))  # no suffix: a dot is never a fraction of a comment
    except ValueError:
        return None


def comment_count(xml: str) -> int | None:
    """"345 comments" as shown on the post page (text or content-desc)."""
    for node in re.findall(r"<node[^>]+/?>", xml or ""):
        hay = "".join(ch for ch in f"{_text_of(node)} {_desc_of(node)}" if ord(ch) < 128)
        m = _COMMENT_COUNT.search(hay)
        if m:
            return _count(m.group(1), m.group(2))
    return None


class RedditAdapter:
    platform = "reddit"
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

    def _tap_el(self, name: str, xml: str | None = None) -> bool:
        pos = self._find(name, xml)
        if not pos:
            return False
        self.human.tap(*pos)
        return True

    def _tap_text(self, xml: str, text: str) -> bool:
        for n in nodes_where(xml, text=text):
            if _text_of(n).strip().lower() != text.lower():
                continue
            c = center(n)
            if c:
                self.human.tap(*c)
                return True
        return False

    def _nodes(self, name: str, xml: str) -> list[str]:
        rid = self._rid(name)
        return nodes_where(xml, rid=rid) if rid else []

    def _footer(self, xml: str) -> tuple[int, int, int, int] | None:
        """Bounds of the topmost post footer that is on screen."""
        h = self.human.screen.height
        boxes = [b for n in self._nodes("post_footer", xml) if (b := _bounds_of(n)) and 0 <= b[1] and b[3] <= h]
        boxes.sort(key=lambda b: b[1])
        return boxes[0] if boxes else None

    def _footer_point(self, xml: str, key: str) -> tuple[int, int] | None:
        """Where to tap for `key` (see FOOTER_X) on the current card."""
        box = self._footer(xml)
        if not box:
            return None
        x1, y1, x2, y2 = box
        return int(x1 + FOOTER_X[key] * (x2 - x1)), (y1 + y2) // 2

    def _pixel(self, x: int, y: int) -> tuple[int, int, int] | None:
        """(r, g, b) at (x, y), or None when the screen cannot be read.

        A device may offer ``pixel_at`` (tests do); otherwise a raw screencap —
        12-byte header (width, height, format) then RGBA — the same reading
        ``Device._dismiss_draft_overlay`` does. Never raises: an unreadable
        screen is "not verified", which is the safe answer.
        """
        probe = getattr(self.device, "pixel_at", None)
        if callable(probe):
            try:
                return probe(x, y)
            except Exception:  # noqa: BLE001
                return None
        serial = getattr(self.device, "serial", None)
        if not serial:
            return None
        try:
            raw = subprocess.run(
                ["adb", "-s", serial, "exec-out", "screencap"], capture_output=True, timeout=20
            ).stdout  # ~4 MB over a cloud link: 8 s was sometimes too short
        except Exception:  # noqa: BLE001
            return None
        if len(raw) < 16:
            return None
        w = struct.unpack_from("<I", raw, 0)[0]
        h = struct.unpack_from("<I", raw, 4)[0]
        if not (0 <= x < w and 0 <= y < h):
            return None
        off = 12 + (y * w + x) * 4
        if off + 3 >= len(raw):
            return None
        return raw[off], raw[off + 1], raw[off + 2]

    def _upvoted(self, x: int, y: int) -> bool | None:
        """Is the arrow at (x, y) lit? None when the screen cannot be read."""
        seen = False
        for dx, dy in ((0, 0), (4, 0), (-4, 0), (0, 4), (0, -4)):
            px = self._pixel(x + dx, y + dy)
            if px is None:
                continue
            seen = True
            if _is_upvote_orange(*px):
                return True
        return False if seen else None

    def _settle(self, xml: str) -> bool:
        """Dismiss one verified interstitial, if any. Returns True if it did.

        Three were met on the device: the welcome sheet of a community just
        joined (``got_it_button`` / "Close sheet"), the "Are you enjoying
        Reddit?" survey that lands ON TOP of that sheet and swallows its
        button, and the "Can't create passkey" dialog of a cloud phone.
        """
        if "enjoying Reddit" in xml and self._tap_text(xml, "Not really"):
            return True
        if self._tap_el("welcome_got_it", xml) or self._tap_el("sheet_close", xml):
            return True
        if "create passkey" in xml and self._tap_text(xml, "OK"):
            return True
        return False

    # ── adapter contract ──────────────────────────────────────────────

    def open_feed(self) -> bool:
        self.device.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
        self.human.sleep(self.human.profile.pause_s(4.0))
        for _ in range(3):
            xml = self.dump()
            if not (self.device.dismiss_popups(xml) or self._settle(xml)):
                break
            self.human.pause(0.8)
        xml = self.dump()
        if not self.on_feed(xml):
            self._tap_el("home_tab", xml)
            self.human.pause(2.0)
            xml = self.dump()
        return self.on_feed(xml)

    def on_feed(self, xml: str) -> bool:
        """Cards with their footer — and neither the post page's conversation
        bar nor the profile header, which both show the same cards."""
        if not (self._nodes("post_footer", xml) or self._nodes("post_card", xml)):
            return False
        if self._find("comment_input", xml):
            return False  # a post page
        if self._nodes("profile_karma", xml):
            return False  # the account's own profile
        return True

    def next_video(self) -> None:
        """One card further down the feed (the loop's "next item")."""
        self.human.swipe_feed("up")

    def like(self, xml: str) -> bool:
        """Upvote — never un-vote, never downvote — proven by the arrow's colour."""
        self.last_gesture_silent = False
        pt = self._footer_point(xml, "upvote")
        if not pt:
            return False
        if self._upvoted(*pt):
            return False  # already upvoted: a second tap would remove the vote
        self.human.tap(*pt)
        self.human.pause(0.8)
        if self._upvoted(*pt):
            return True
        self.last_gesture_silent = True
        return False

    def save(self, xml: str) -> bool:
        """"Save" in the card's ⋮ menu, proven by "Unsave" when the menu reopens."""
        self.last_gesture_silent = False
        if not self._tap_el("more_button", xml):
            return False
        self.human.pause(1.0)
        sheet = self.dump()
        if nodes_where(sheet, text="Unsave"):
            self.device.back()
            return False  # already saved: never toggle
        if not self._tap_text(sheet, "Save"):
            self.device.back()
            return False
        self.human.pause(1.2)
        again = self.dump()
        if self._tap_el("more_button", again):
            self.human.pause(1.0)
            reopened = self.dump()
            saved = bool(nodes_where(reopened, text="Unsave"))
            self.device.back()
            if saved:
                return True
        self.last_gesture_silent = True
        return False

    def open_author(self, xml: str) -> str | None:
        """Open the post page and name its community.

        A card exposes no author (no id, no label), but its post page carries
        the community in the title bar ("r/zelda"). That page is the visit,
        and the community is what ``follow`` may join.
        """
        pt = self._footer_point(xml, "comments")
        if not pt:
            return None
        self.human.tap(*pt)
        self.human.pause(2.0)
        page = self.dump()
        for n in self._nodes("page_title", page):
            m = _SUB_NAME.search(_text_of(n))
            if m:
                return m.group(0)
        for n in nodes_where(page, desc=" has ") + nodes_where(page, desc=" members"):
            m = _SUB_NAME.search(_desc_of(n))
            if m:
                return m.group(0)
        self.device.back()
        return None

    def follow(self, xml: str) -> bool:
        """Join the community from the feed card — proven by Join → Joined.

        The loop calls this from the post page, which has no join button we
        surveyed, so we come back to the feed and join from the card. Never
        "Joined": leaving a community is not a warming gesture.
        """
        self.last_gesture_silent = False
        if self._join_here(xml):
            return True
        if self.last_gesture_silent:
            return False
        self.back_to_feed()
        return self._join_here(self.dump())

    def _join_here(self, xml: str) -> bool:
        node = next(iter(self._nodes("join_button", xml)), None)
        if node is None:
            return False
        label = _text_of(node).strip().lower()
        if label != "join":
            return False  # "Joined" (never leave) or something else entirely
        c = center(node)
        if not c:
            return False
        self.human.tap(*c)
        self.human.pause(1.5)
        after = self.dump()
        if self._settle(after):  # the welcome sheet covers the card
            self.human.pause(1.0)
            after = self.dump()
        node2 = next(iter(self._nodes("join_button", after)), None)
        if node2 is not None and _text_of(node2).strip().lower() == "joined":
            return True
        self.last_gesture_silent = True
        return False

    def comment(self, text: str) -> bool:
        """Comment on the card on screen. ASCII only (R12), never a link (R22).

        Proven by the post page's "N comments" counter going up, or the typed
        text showing up in the thread.
        """
        self.last_gesture_silent = False
        xml = self.dump()
        pt = self._footer_point(xml, "comments")
        if not pt:
            return False
        self.human.tap(*pt)
        self.human.pause(2.0)
        page = self.dump()
        before = comment_count(page)
        if not self._tap_el("comment_input", page):
            self.device.back()
            return False
        self.human.pause(0.8)
        self.human.type_text(text)
        if not self._tap_el("comment_send", self.dump()):
            self.device.back()
            self.device.back()
            return False
        self.human.pause(2.0)
        after = self.dump()
        count = comment_count(after)
        ok = (before is not None and count is not None and count > before) or bool(nodes_where(after, text=text))
        self.device.back()  # keyboard, then the post page
        self.human.pause(0.5)
        self.device.back()
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
        if kind == "search" and query:
            return self._search(query)
        return False  # no stories on Reddit

    def _search(self, query: str) -> bool:
        xml = self.dump()
        if not self._tap_el("search_icon", xml):
            return False
        self.human.pause(1.5)
        sx = self.dump()
        self._tap_el("search_input", sx)  # the field is focused on open; a tap does no harm
        self.human.pause(0.5)
        term = query.lstrip("#")
        self.human.type_text(term if term.startswith("r/") else f"r/{term}")
        self.human.pause(1.2)
        self.device.press_enter()
        self.human.pause(2.5)
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True

    # ── optional hook (gitd.farm.skillkit.read_karma) ─────────────────

    def read_karma(self) -> int | None:
        """The account's own karma: "You" tab → `profile_highlights_karma` ("1 Karma").

        Called at the end of a session, from the feed. Comes back to the feed.
        """
        xml = self.dump()
        if not self._tap_el("profile_tab", xml):
            return None
        self.human.pause(2.5)
        value = parse_karma(self.dump())
        self.back_to_feed()
        return value


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
