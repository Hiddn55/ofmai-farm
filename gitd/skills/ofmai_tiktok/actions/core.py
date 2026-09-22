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
_NUMBER = re.compile(r"(\d+(?:[.,]\d+)*)\s*([KkMm])?\b")
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+")
_FIRST = re.compile(r"\b(?:add\s+)?1st\b", re.IGNORECASE)
_SHEET_HEADER = re.compile(r"[\d.,]+[KkMm]?\s+comments?", re.IGNORECASE)
_SCALE = {"k": 1_000, "m": 1_000_000}
# the label a rail button takes once toggled — it is not the one of elements.yaml
_TOGGLED = {"like_button": ("like_button_liked",)}
# the sheets TikTok lays over a profile it just opened; Back closes them
_PROFILE_SHEETS = ("Viewer history turned on",)


def _text(node: str) -> str:
    m = re.search(r'\btext="([^"]*)"', node)
    return m.group(1) if m else ""


def _bounds(node: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS.search(node)
    return tuple(int(v) for v in m.groups()) if m else None  # type: ignore[return-value]


def _sheet_count(xml: str) -> int | None:
    """The comments sheet header — "8 comments" (with a leading U+200E on 46.8.2)."""
    for n in nodes_where(xml, text="comment"):
        if _SHEET_HEADER.fullmatch(_text(n).strip("‎‏ ")):
            return parse_count(_text(n))[0]
    return None


def _lower_edge(node: str) -> tuple[int, int] | None:
    """The tap point of the feed's follow button: its lower fifth, clear of the avatar above."""
    b = _bounds(node)
    if not b:
        return None
    return (b[0] + b[2]) // 2, b[3] - max(4, (b[3] - b[1]) // 5)


def parse_count(label: str) -> tuple[int | None, bool]:
    """``("Like video. 75.7K likes")`` -> ``(75700, True)``: the count and whether it is rounded.

    A rounded count (K / M suffix) may not move for a single gesture, which
    is why the caller treats "unchanged and rounded" as unproven rather than
    silent. A post nobody commented on reads "Add 1st comments" (2026-09-22):
    that is a count of zero, not a missing count.
    """
    if _FIRST.search(label or ""):
        return 0, False
    m = _NUMBER.search(label or "")
    if not m:
        return None, False
    raw, suffix = m.group(1), m.group(2)
    # "6,589 likes", "3,514" Likes on a profile: the comma groups thousands
    # (2026-09-22) — read as a decimal it turned 6,589 into 6 and a proven
    # like into a silent one. A comma before fewer than three digits ("1,2K")
    # is a decimal point.
    raw = raw.replace(",", "") if _THOUSANDS.fullmatch(raw) else raw.replace(",", ".")
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
        self._last_sheet = ""  # the comments sheet as it was right after a send

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

    def _rail_node(self, xml: str, name: str) -> str | None:
        """The rail button `name`, whichever state it is in.

        A lit like button is no longer "Like video. 3 likes" but "Video liked"
        — a different label, with no count (measured 2026-09-22): the button
        is looked up under its toggled label too, or the count read after a
        like would be "not found" and a proven like would pass for silent.
        """
        node = self._desc_node(xml, name)
        for alt in _TOGGLED.get(name, ()):
            if node is not None:
                break
            node = self._desc_node(xml, alt)
        return node

    def _count_of(self, xml: str, name: str) -> tuple[int | None, bool]:
        node = self._rail_node(xml, name)
        if node is None:
            return None, False
        n, rounded = parse_count(desc_of(node))
        if n is not None:
            return n, rounded
        # The favourite label carries no count ("Add or remove this video from
        # Favorites."), nor does a lit like ("Video liked"): the number is a
        # text node drawn INSIDE the button's bounds, in its lower part —
        # "27.2K" at y 1002-1016 inside [929, 1027] on 46.8.2 (2026-09-22).
        # The share count sits 62 px under it: only a node inside the button,
        # or hugging its lower edge, is the button's.
        b = _bounds(node)
        if b:
            for t in nodes_where(xml, text=""):
                tb = _bounds(t)
                if tb and abs(tb[0] - b[0]) < 60 and b[1] <= tb[1] < b[3] + 30:
                    n, rounded = parse_count(_text(t))
                    if n is not None:
                        return n, rounded
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
        # the lit state first: its label is "Video liked", and the bare "Like"
        # node inside the button never changes — read alone it would pass an
        # already-liked video for a fresh one and the tap would UNLIKE it
        node = self._rail_node(xml, "like_button") or next(iter(nodes_where(xml, desc="Like")), None)
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
        """Open the author's profile from the avatar ("<handle>'s profile").

        The follow that may come next is proven by the own Following count,
        and a profile has no tab bar to read it from (measured 2026-09-22):
        the baseline is taken here, from the feed, once per session.
        """
        if self._following is None and self._desc_node(xml, "author_avatar") is not None:
            self._following = self.read_own_following()
            xml = self.dump()
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
        pxml = self._profile_screen()
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

    def _profile_screen(self) -> str:
        """The profile just opened, once TikTok's own sheet over it is gone.

        Opening a profile raised the "Viewer history turned on" bottom sheet
        (own profile, 2026-09-22): a Save button and no dismiss word, so the
        popup lists never clear it and the count under it reads as nothing.
        Back closes it without saving anything.
        """
        xml = self.dump()
        for _ in range(2):
            if not any(s in xml for s in _PROFILE_SHEETS):
                break
            self.device.back(delay=1.0)
            xml = self.dump()
        return xml

    def read_own_following(self) -> int | None:
        """The account's own Following count: Profile tab, read, back to the feed."""
        xml = self.dump()
        if not self._tap_el("profile_tab", xml):
            return None
        self.human.pause(2.0)
        value = self._profile_count(self._profile_screen(), "Following")
        self._tap_el("home_tab", self.dump())
        self.human.pause(1.5)
        return value

    def follow(self, xml: str) -> bool:
        """Follow — proven by the account's own Following count going up.

        From the feed: the "Follow <handle>" button under the avatar, tapped on
        its lower edge (35 px separate the two). From a profile: the topmost
        "Follow" button — the "Suggested accounts" strip TikTok unfolds after
        a follow carries three more (2026-09-22). The node vanishing is NOT
        accepted as proof, nor is the button turning into "Message": both
        were seen on the explorer while the own Following count stayed at 0.

        A profile has no tab bar: the baseline was read by :meth:`open_author`
        before leaving the feed, and the count after is read back on it.
        """
        self.last_gesture_silent = False
        node = self._desc_node(xml, "follow_on_feed")
        on_feed = node is not None
        if on_feed:
            target = _lower_edge(node)
        else:
            buttons = sorted(
                (c[1], c) for n in nodes_where(xml, text="Follow") if _text(n).strip().lower() == "follow" and (c := center(n))
            )
            target = buttons[0][1] if buttons else None
        if target is None:
            return False
        if self._following is None:
            if not on_feed:
                return False  # nothing to prove against: open_author could not read the baseline
            self._following = self.read_own_following()
            xml = self.dump()
            node = self._desc_node(xml, "follow_on_feed")
            if node is None:
                return False
            target = _lower_edge(node)
        self.human.tap(*target)
        self.human.pause(1.2)
        if not on_feed:
            self.back_to_feed()
        after = self.read_own_following()
        if self._following is not None and after is not None and after > self._following:
            self._following = after
            return True
        self.last_gesture_silent = True
        return False

    def _send_comment(self, text: str) -> bool:
        """Type, send by the unlabelled arrow, keep the sheet as it is after (``_last_sheet``)."""
        self.human.type_text(text)
        posted = self.dump()
        if not (self._tap_desc(posted, "Post") or self._tap_desc(posted, "Send")):
            self._tap_el("comment_send", posted)  # the unlabelled arrow, by position
        self.human.pause(1.5)
        self._last_sheet = self.dump()
        return bool(nodes_where(self._last_sheet, text=text))

    def comment(self, text: str) -> bool:
        """Comment on the visible video — proven by the text showing in the sheet.

        The fallback proof is the sheet's own header ("8 comments" ->
        "9 comments", 2026-09-22), never the feed's counter: the feed does not
        always come back on the same video once the sheet is closed, and the
        sheet hides the rail, so closing it is :meth:`back_to_feed`.
        """
        self.last_gesture_silent = False
        xml = self.dump()
        if not (self._tap_el("comment_button", xml) or self._tap_desc(xml, "Comment")):
            return False
        self.human.pause(1.5)
        sheet = self.dump()
        if not (self._tap_el("comment_input", sheet) or self._tap_text(sheet, "Add comment")):
            self.device.back()
            return False
        self.human.pause(0.8)
        ok = self._send_comment(text)
        before, after = _sheet_count(sheet), _sheet_count(self._last_sheet)
        self.back_to_feed()
        if ok:
            return True
        if before is not None and after is not None and after > before:
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
        """Magnifier -> field -> Enter. The results play: never dumped, only scrolled.

        The magnifier is the TOPMOST node labelled "Search": the feed's bottom
        "Search · <suggestion>" bar carries the same label and comes first in
        the tree (2026-09-22) — tapped, it runs the suggestion instead.
        """
        xml = self.dump()
        magnifiers = sorted((c[1], c) for n in nodes_where(xml, desc="Search") if (c := center(n)))
        if magnifiers:
            self.human.tap(*magnifiers[0][1])
        elif not self._tap_el("search_icon", xml):
            return False
        self.human.pause(1.5)
        sx = self.dump()
        self._tap_el("search_box", sx)
        self.human.pause(0.5)
        if query.startswith("@"):
            return self._lose_time_in_videos_of(query.lstrip("@"))
        self.human.type_text(query.lstrip("#"))
        self.human.pause(1.0)
        self.device.press_enter()
        self.human.pause(2.5)
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True

    def _lose_time_in_videos_of(self, handle: str, *, videos: tuple[int, int] = (5, 10), like_rate: float = 0.12) -> bool:
        """The oriented warm-up (warming-policy.md §7 bis): the handle typed in
        the search field, the "Users" tab, the account's profile, its first
        video, then a run of its videos (5-20 s each, a like now and then).
        True when at least one video was watched. Left with Back, never by
        swiping into the untrained For You feed.
        """
        before = self.dump()
        self._tap_desc(before, "Clear search field")  # a previous query may still be in the field
        self.human.type_text(handle)
        self.human.pause(1.0)
        # the typeahead's rows are queries (even the one with the account's
        # badge — verified 2026-09-22): submit, then the "Users" tab of the
        # results lists the accounts, and the handle names its row
        self.device.press_enter()
        self.human.pause(2.5)
        results = self.dump()
        if self._tap_text(results, "Users"):
            self.human.pause(2.0)
            results = self.dump()
        # a username is wrapped in bidi isolates ("\u200e\u2068gymshark\u2069",
        # verified 2026-09-22); the search field at the top repeats the query
        def clean(t: str) -> str:
            return "".join(ch for ch in t if ch not in "\u200e\u200f\u2066\u2067\u2068\u2069\u202a\u202b\u202c\u202d\u202e").strip().lstrip("@").lower()

        rows = [n for n in nodes_where(results, text=handle) if (center(n) or (0, 0))[1] > 140]
        row = next((n for n in rows if clean(_text(n)) == handle.lower()), None)
        row = row or next((n for n in rows if clean(_text(n)).startswith(handle.lower())), None)
        c = center(row) if row else None
        if not c:
            log.info("[tiktok] @%s: no account row on the Users tab", handle)
            self.device.back()
            return False
        self.human.tap(*c)
        # the profile loads its header after its video: poll a few seconds
        profile = ""
        for _ in range(4):
            self.human.pause(2.0)
            profile = self.dump()
            if nodes_where(profile, text="Followers") or nodes_where(profile, text="Following"):
                break
        else:
            log.info("[tiktok] @%s: not a profile after the tap", handle)
            self.device.back()
            return False
        el = self.elements.get("profile_grid_first_item")
        tiles = nodes_where(profile, rid=el.resource_id) if el and el.resource_id else []
        tile = min(tiles, key=lambda n: (center(n) or (9999, 9999))[::-1], default=None)
        tc = center(tile) if tile else None
        if not tc:
            log.info("[tiktok] @%s: no video tile on the profile", handle)
            self.device.back()
            return False
        self.human.tap(*tc)
        self.human.pause(2.0)
        watched = 0
        rng = self.human.profile.rng
        for _ in range(rng.randint(*videos)):
            xml = self.dump()
            if not self.on_feed(xml):  # the viewer exposes the same rail as the feed
                break
            self.human.sleep(rng.uniform(5.0, 20.0))
            watched += 1
            if self.human.profile.chance(like_rate):
                self.like(xml)
            self.human.swipe_feed("up")
            self.human.pause(0.8)
        self.device.back()  # the viewer
        self.human.pause(0.8)
        for _ in range(3):  # profile, results, search field — then the tab bar
            if self.on_feed(self.dump()):
                break
            self.device.back()
            self.human.pause(0.6)
        self.back_to_feed()
        return watched > 0


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
