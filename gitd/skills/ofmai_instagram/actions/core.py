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
        self.discovered: list[str] = []  # niche accounts met in "Following" lists (§7 bis, depth 2)

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

    # sheets Instagram opens once and never again, seen on the explorer: the
    # "Saved" sheet after the first save ("Collect the posts you love", 2026-09-22)
    ONE_TIME_SHEETS = ("Collect the posts you love", "Start a collection", "Stories archive")

    def _settle(self, xml: str) -> bool:
        """Dismiss one interstitial, if any. Returns True if it did."""
        if self._tap_el("promo_dismiss", xml):
            return True
        if "Introducing" in xml and self._tap_text(xml, "Not now"):
            return True
        if any(t in xml for t in self.ONE_TIME_SHEETS):
            self.device.back()  # a sheet: Back closes it and nothing else
            self.human.pause(0.8)
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

    @staticmethod
    def _exact(xml: str, *labels: str) -> list[str]:
        """Nodes whose content-desc IS one of `labels` — "8,732 likes" is not a Like button."""
        wanted = {l.lower() for l in labels}
        out = []
        for l in labels:
            out += [n for n in nodes_where(xml, desc=l) if desc_of(n).strip().lower() in wanted]
        return out

    def on_feed(self, xml: str) -> bool:
        """The home feed: its bottom bar with no comment composer open — or, on
        a build without ids, a post with its Like and Comment buttons. A sheet
        on top of it (Saved, promo) is not the feed: back_to_feed settles it.

        A screen of the feed showing only a suggestions carousel or the tail
        of a Reel (seen 2026-09-22) is still the feed: the loop must swipe on,
        not "come back" to it — that round trip cost a 3-minute session all
        but one view.
        """
        if self._nodes("comment_input", xml) or self._nodes("comment_input_legacy", xml):
            return False
        if any(t in xml for t in self.ONE_TIME_SHEETS) or self._nodes("promo_dismiss", xml):
            return False
        home = self._nodes("home_tab", xml)
        elsewhere = self._nodes("follow_button", xml) or self._nodes("dm_thread_row", xml) or self._nodes("dm_input", xml)
        if home and not elsewhere:
            return True
        liked = self._nodes("like_button", xml) or self._exact(xml, "Like", "Liked")
        comment = self._nodes("comment_button", xml) or self._exact(xml, "Comment")
        return bool(liked and comment)

    def next_video(self) -> None:
        self.human.swipe_feed("up")

    def _like_node(self, xml: str) -> str | None:
        node = self._topmost(self._nodes("like_button", xml))
        if node is None:  # no id on this build: the exact label alone
            node = self._topmost(self._exact(xml, "Like", "Liked"))
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
        after_xml = self.dump()
        after = self._in_row("like_button", after_xml, c[1])
        if after is None:
            after = next((n for n in self._exact(after_xml, "Liked") if (cc := center(n)) and abs(cc[1] - c[1]) <= ROW_BAND), None)
        if after is not None and desc_of(after).strip().lower() == "liked":
            return True
        self.last_gesture_silent = True
        return False

    def save(self, xml: str) -> bool:
        """Save the topmost post — proven by ``Add to Saved`` → ``Remove from saved``.

        The first save ever opens the "Saved" sheet: it is closed here, or every
        later gesture would land on it.
        """
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
        if self._settle(after):
            after = self.dump()
            node2 = self._in_row("save_button", after, sc[1]) or node2
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
        """Open one unseen ring of the tray — proven by its label losing "Unseen".

        A ring reads "<handle>'s story, 1 of 3, Unseen." (verified 2026-09-22;
        the survey's "unseen story" wording belongs to an older build). Our own
        ring is the first one, next to "Add to story": never opened.
        """
        xml = self.dump()
        self._tap_el("home_tab", xml)
        self.human.pause(2.0)
        home = self.dump()
        rings = [n for n in nodes_where(home, desc="'s story") if "unseen" in desc_of(n).lower()]
        rings.sort(key=lambda n: (center(n) or (0, 0))[0])
        own = desc_of(rings[0]).split("'s story")[0].lower() if rings and nodes_where(home, desc="Add to story") else None
        for n in rings:
            d = desc_of(n)
            owner = d.split("'s story")[0].strip()
            if not owner or owner.lower() == own:
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
            self.human.pause(1.5)
            after = self.dump()
            if not nodes_where(after, desc="'s story"):  # still inside the viewer
                self.device.back()
                self.human.pause(1.5)
                after = self.dump()
            for m in nodes_where(after, desc=f"{owner}'s story"):
                if "unseen" not in desc_of(m).lower():
                    return True
            return False
        return False

    def _search(self, query: str) -> bool:
        """The search detour. A hashtag browses its results; an ``@handle`` is the
        oriented warm-up (warming-policy.md, "chauffe orientée"): the account's
        profile, its Reels tab, and 5-10 of its Reels watched one after the other
        — the only way, in the first week, to show the algorithm the niche
        without ever touching the untrained Reels feed.
        """
        xml = self.dump()
        if not self._tap_el("search_tab", xml):
            return False
        self.human.pause(1.5)
        sx = self.dump()
        if not (self._tap_el("search_input", sx) or self._tap_text(sx, "Search")):
            return False
        self.human.pause(0.5)
        if query.startswith("@"):
            return self._lose_time_in_reels_of(query.lstrip("@"))
        self.human.type_text(query if query.startswith("#") else f"#{query}")
        self.human.pause(1.5)
        self.device.press_enter()
        self.human.pause(2.5)
        # browse the results a bit
        for _ in range(self.human.profile.rng.randint(1, 3)):
            self.human.swipe_feed("up")
            self.human.sleep(self.human.profile.rng.uniform(1.5, 4.0))
        return True

    def _open_first_reel_of_grid(self, handle: str) -> bool:
        """On a profile's Reels grid: open its first (top-left) tile."""
        grid = self.dump()
        tiles = self._nodes("reels_grid_tile", grid)
        tile = min(tiles, key=lambda n: (center(n) or (9999, 9999))[::-1], default=None)
        tile = tile or next((n for n in nodes_where(grid, desc="Row 1, Column 1") if "reel" in desc_of(n).lower()), None)
        tile = tile or next(iter(nodes_where(grid, desc="Row 1, Column 1")), None)
        gc = center(tile) if tile else None
        if not gc:
            log.info("[instagram] @%s: no first tile in the Reels grid", handle)
            self.device.back()
            return False
        self.human.tap(*gc)
        self.human.pause(2.0)
        return True

    def _watch_reels_run(self, *, reels: tuple[int, int], like_rate: float) -> int:
        """Inside the viewer: watch a run of Reels, like a few, leave with Back. Returns the count."""
        watched = 0
        rng = self.human.profile.rng
        w, h = self.human.screen.width, self.human.screen.height
        for _ in range(rng.randint(*reels)):
            xml = self.dump()
            if not xml:
                # a playing Reel never lets uiautomator settle (verified 2026-09-22):
                # an empty tree here means "still in the viewer, video playing".
                # A tap on the video pauses it — a human does that too — and
                # the paused screen dumps; if it still does not, we watch blind.
                self.human.tap(int(w * 0.5), int(h * 0.45), settle=0.8)
                xml = self.dump()
            elif not (self._exact(xml, "Like", "Liked") or self._nodes("like_button", xml)):
                break  # a readable screen without the viewer's buttons: not in the viewer any more
            self.human.sleep(rng.uniform(5.0, 20.0))
            watched += 1
            if xml and self.human.profile.chance(like_rate):
                node = self._topmost(self._exact(xml, "Like"))
                if node and (lc := center(node)):
                    self.human.tap(*lc)
                    self.human.pause(0.6)
            self.human.swipe_feed("up")
            self.human.pause(0.8)
        self.device.back()  # the viewer
        self.human.pause(0.8)
        return watched

    def _lose_time_in_reels_of(self, handle: str, *, reels: tuple[int, int] = (5, 10), like_rate: float = 0.12, follow_list_rate: float = 0.5) -> bool:
        """Type the handle, open its profile, its Reels tab, and watch a run of its
        Reels (5-20 s each, a like now and then). True when at least one Reel
        was watched. The Reels viewer is left with Back, never by scrolling
        into the untrained feed.
        """
        self.human.type_text(handle)
        self.human.pause(2.0)
        results = self.dump()

        def exact_row(xml: str):
            return next((n for n in self._nodes("search_result_user", xml) if _text(n).strip().lstrip("@").lower() == handle.lower()), None)

        # the typeahead may only show the account as a keyword suggestion
        # ("gymshark • 8.6M followers"): submitting the query lands on the
        # results page, where the account is the first username row (verified 2026-09-22)
        hit = exact_row(results)
        if hit is None:
            self.device.press_enter()
            self.human.pause(2.5)
            results = self.dump()
            hit = exact_row(results) or next(iter(self._nodes("search_result_user", results)), None)
        c = center(hit) if hit else None
        if not c:
            log.info("[instagram] @%s: no result row", handle)
            return False
        self.human.tap(*c)
        self.human.pause(2.5)
        profile = self.dump()
        if self._settle(profile):
            profile = self.dump()
        # a long header (bio, links, highlights) pushes the tab strip below the
        # fold: a short scroll brings it up
        tab = None
        for _ in range(3):
            tab = next((n for n in self._nodes("profile_reels_tab", profile) if desc_of(n).strip().lower() == "reels"), None)
            if tab:
                break
            self.human.swipe_feed("up")
            self.human.pause(1.0)
            profile = self.dump()
        tc = center(tab) if tab else None
        if not tc:
            log.info("[instagram] @%s: no Reels tab on the profile", handle)
            self.device.back()
            return False
        self.human.tap(*tc)
        self.human.pause(2.0)
        if not self._open_first_reel_of_grid(handle):
            return False
        watched = self._watch_reels_run(reels=reels, like_rate=like_rate)
        if watched and self.human.profile.chance(follow_list_rate):
            # depth 2: one account this one follows — the same niche, usually
            self._lose_time_in_a_followed_account(handle, reels=reels, like_rate=like_rate)
        return watched > 0

    def _lose_time_in_a_followed_account(self, handle: str, *, reels: tuple[int, int], like_rate: float) -> str | None:
        """From a profile (back on it after its Reels): its "Following" list, one
        of the first rows, that account's Reels. Returns the account visited.
        The discovered handle is what the ledger records as a niche target."""
        profile = self.dump()
        count = next(iter(self._nodes("profile_following_count", profile)), None)
        cc = center(count) if count else None
        if not cc:
            return None
        self.human.tap(*cc)
        self.human.pause(2.5)
        listing = self.dump()
        rows = [n for n in self._nodes("follow_list_username", listing) if _text(n).strip()]
        rows = [n for n in rows if _text(n).strip().lower() != handle.lower()][:8]
        if not rows:
            self.device.back()
            return None
        pick = self.human.profile.rng.choice(rows)
        who = _text(pick).strip().lstrip("@")
        pc = center(pick)
        if not pc:
            self.device.back()
            return None
        self.human.tap(*pc)
        self.human.pause(2.5)
        prof = self.dump()
        if self._settle(prof):
            prof = self.dump()
        tab = None
        for _ in range(3):
            tab = next((n for n in self._nodes("profile_reels_tab", prof) if desc_of(n).strip().lower() == "reels"), None)
            if tab:
                break
            self.human.swipe_feed("up")
            self.human.pause(1.0)
            prof = self.dump()
        tc = center(tab) if tab else None
        if not tc:
            self.device.back()
            self.device.back()
            return None
        self.human.tap(*tc)
        self.human.pause(2.0)
        if self._open_first_reel_of_grid(who):
            self._watch_reels_run(reels=reels, like_rate=like_rate)
        self.discovered.append(who)
        log.info("[instagram] @%s: followed-account run on @%s", handle, who)
        self.device.back()  # the profile
        self.device.back()  # the list
        return who


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
