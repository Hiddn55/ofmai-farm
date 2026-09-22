"""Is this Reel of the character's niche? — answered from the accessibility tree.

warming-policy.md §7 bis, days 8-14: the Reels tab and the Reels of the feed
are allowed, but the account only lingers on a Reel that is of its niche.
Two free, instant tests on what the screen exposes — the author's handle
("Reel by <name>", `clips_username`), the caption and its hashtags — before
the third, paid one (a model on a screenshot, `gitd.farm.advisor`):

1. the author is a known niche account (the radar list, extended by the
   accounts discovered in "following" lists);
2. the caption carries the niche's words or hashtags (the persona sheet's
   `hashtags_niche` / `vocabulary`, i.e. `farm_accounts.niche` entries).

Unknown author and no niche word: not of the niche — the account swipes on.
Not watching teaches the algorithm nothing wrong; watching the wrong thing
does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gitd.farm.warm import desc_of, nodes_where

_REEL_BY = re.compile(r"\b(?:suggested )?reel by ([^,]+?)(?:,|$)", re.IGNORECASE)
_POSTED = re.compile(r"^([A-Za-z0-9._]+) posted a (?:video|reel|photo)", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class ReelVerdict:
    niche: bool
    reason: str  # "author" | "caption" | "unknown"
    author: str = ""


def author_of(xml: str) -> str:
    """The author of the Reel on screen, from the labels Instagram exposes."""
    for n in nodes_where(xml or "", desc="posted a"):
        m = _POSTED.match(desc_of(n).strip())
        if m:
            return m.group(1).lower()
    for n in nodes_where(xml or "", desc="reel by"):
        m = _REEL_BY.search(desc_of(n))
        if m:
            return m.group(1).strip().lower()
    for n in nodes_where(xml or "", rid="com.instagram.android:id/clips_username"):
        t = re.search(r'\btext="([^"]*)"', n)
        if t and t.group(1).strip():
            return t.group(1).strip().lstrip("@").lower()
    return ""


def words_of(xml: str) -> set[str]:
    """Every word and hashtag of the texts on screen (caption, audio, labels)."""
    out: set[str] = set()
    for n in nodes_where(xml or "", text=""):
        t = re.search(r'\btext="([^"]*)"', n)
        if t:
            out.update(_WORD.findall(t.group(1).lower()))
    return out


def niche_terms(niche: list[str]) -> set[str]:
    """`farm_accounts.niche` entries as bare words: "#gymgirl" -> "gymgirl"; "@x" is not a word."""
    return {q.lstrip("#").lower() for q in niche if q and not q.startswith("@")}


def niche_handles(niche: list[str], extra: list[str] = ()) -> set[str]:
    return {h.lstrip("@").lower() for h in list(niche) + list(extra) if h and (h.startswith("@") or h in extra)}


def judge(xml: str, *, handles: set[str], terms: set[str], min_terms: int = 2) -> ReelVerdict:
    """Of the niche when the author is known, or when the caption carries at
    least `min_terms` niche words (one is enough if it is a hashtag of the list)."""
    author = author_of(xml)
    if author and author in handles:
        return ReelVerdict(True, "author", author)
    words = words_of(xml)
    hits = words & terms
    if hits and (len(hits) >= min_terms or any(f"#{h}" in (xml or "").lower() for h in hits)):
        return ReelVerdict(True, "caption", author)
    return ReelVerdict(False, "unknown", author)
