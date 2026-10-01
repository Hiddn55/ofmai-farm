"""A comment written in front of the post, not drawn from a list.

Decision of 2026-10-01 (Nathan): a sentence written in advance cannot fit a
post it has never seen. So when the warm-up decides to comment, the farm sends
what it sees — the screenshot, the author, the caption — to OFMAI
(``POST /api/farm/comments/compose``, bridge-ofmai-farm.md §3.4 bis), which
answers with ONE line in the character's voice, already through its
compliance gate, and journals it. Same for a reply to a comment or a DM.

Nothing is written when OFMAI answers nothing: no pool, no fallback sentence.
A session without the bridge configured simply does not comment.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

COMPOSE_PATH = "/api/farm/comments/compose"
KINDS = ("comment", "reply_ai", "reply_thanks", "reply_question")


class Composer:
    """``composer(ctx) -> text | None`` for one account, over the bridge."""

    def __init__(
        self,
        client: Any = None,
        *,
        character_id: str,
        platform: str,
        handle: str = "",
        timeout: float = 45.0,
        client_factory: Callable[[], Any] | None = None,
    ):
        # The client is built on the first comment, not at session start: a
        # session that never comments never touches the bridge.
        self._client = client
        self._client_factory = client_factory
        self.character_id = character_id
        self.platform = platform
        self.handle = handle
        self.timeout = timeout
        self.calls = 0
        self.last_reason: str | None = None

    def __call__(self, ctx: dict | None = None, *, kind: str = "comment") -> str | None:
        ctx = ctx or {}
        if kind not in KINDS:
            raise ValueError(f"unknown compose kind {kind!r}")
        body: dict[str, Any] = {
            "character_id": self.character_id,
            "platform": self.platform,
            "kind": kind,
            "handle": self.handle,
        }
        if ctx.get("author"):
            body["author"] = str(ctx["author"])[:80]
        if ctx.get("caption"):
            body["caption"] = str(ctx["caption"])[:2000]
        if ctx.get("incoming_text"):
            body["incoming_text"] = str(ctx["incoming_text"])[:1000]
        shot = ctx.get("screenshot")
        if shot:
            body["screenshot_base64"] = base64.b64encode(shot).decode("ascii")
        self.calls += 1
        try:
            if self._client is None:
                if self._client_factory is None:
                    raise RuntimeError("no bridge client")
                self._client = self._client_factory()
            data = self._client.json("POST", COMPOSE_PATH, json=body, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001 — OFMAI down = no comment, never a crash of the session
            log.warning("[composer] %s: compose failed (%s)", self.platform, type(e).__name__)
            self.last_reason = "bridge_error"
            return None
        text = data.get("text")
        self.last_reason = data.get("reason")
        if not text or not isinstance(text, str):
            log.info("[composer] %s: nothing to say (%s)", self.platform, self.last_reason or "no text")
            return None
        if not text.isascii():
            log.warning("[composer] %s: non-ASCII text refused", self.platform)
            self.last_reason = "non_ascii"
            return None
        log.info("[composer] %s %s -> %r", self.platform, kind, text)
        return text.strip()


def from_env(account: Any, *, client_factory: Callable[[], Any] | None = None) -> Composer | None:
    """The composer of an account, or None when the bridge or the character
    is not configured (then the session does not comment)."""
    from gitd.farm import bridge

    character_id = getattr(account, "character_id", None)
    if not character_id:
        log.info("[composer] @%s has no character_id: no comments this session", getattr(account, "handle", "?"))
        return None
    try:
        bridge.resolve_base_url()  # cheap: is there an OFMAI to call at all?
    except bridge.BridgeNotConfigured as e:
        log.info("[composer] bridge not configured (%s): no comments this session", e)
        return None
    return Composer(
        character_id=str(character_id),
        platform=account.platform,
        handle=account.handle,
        client_factory=client_factory or bridge.OfmaiClient.from_env,
    )
