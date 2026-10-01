"""The comment is written in front of the post, over the bridge — never drawn
from a list, never a fallback sentence (decision of 2026-10-01)."""

from types import SimpleNamespace

import pytest

from gitd.farm import composer as composer_mod
from gitd.farm.composer import COMPOSE_PATH, Composer, from_env


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def json(self, method, path, **kw):
        self.calls.append((method, path, kw))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def test_a_comment_is_asked_with_what_the_phone_sees():
    client = FakeClient([{"text": "ok the light on this", "reason": None}])
    c = Composer(client, character_id="char-1", platform="instagram", handle="sierra.cole01")
    text = c({"author": "@gymshark", "caption": "leg day", "screenshot": b"\x89PNG..."})
    assert text == "ok the light on this"
    method, path, kw = client.calls[0]
    assert (method, path) == ("POST", COMPOSE_PATH)
    body = kw["json"]
    assert body["character_id"] == "char-1" and body["platform"] == "instagram" and body["kind"] == "comment"
    assert body["author"] == "@gymshark" and body["caption"] == "leg day" and body["handle"] == "sierra.cole01"
    assert body["screenshot_base64"].startswith("iVBOR")  # PNG, base64


def test_nothing_to_say_is_none_never_a_fallback():
    client = FakeClient([{"text": None, "reason": "compliance"}, {"text": "", "reason": "no_text"}])
    c = Composer(client, character_id="char-1", platform="instagram")
    assert c({"caption": "x"}) is None and c.last_reason == "compliance"
    assert c({"caption": "y"}) is None and c.last_reason == "no_text"


def test_a_bridge_failure_is_none_not_a_crash():
    c = Composer(FakeClient([RuntimeError("boom")]), character_id="char-1", platform="tiktok")
    assert c({}) is None
    assert c.last_reason == "bridge_error"


def test_non_ascii_is_refused_locally():
    c = Composer(FakeClient([{"text": "café vibes"}]), character_id="char-1", platform="instagram")
    assert c({}) is None and c.last_reason == "non_ascii"


def test_reply_kinds_are_passed_through_and_unknown_ones_refused():
    client = FakeClient([{"text": "yes, fully AI"}])
    c = Composer(client, character_id="char-1", platform="instagram")
    assert c({"incoming_text": "are you AI?"}, kind="reply_ai") == "yes, fully AI"
    assert client.calls[0][2]["json"]["kind"] == "reply_ai"
    assert client.calls[0][2]["json"]["incoming_text"] == "are you AI?"
    with pytest.raises(ValueError):
        c({}, kind="whatever")


def test_from_env_needs_a_character_and_a_bridge(monkeypatch):
    from gitd.farm import bridge

    acc = SimpleNamespace(character_id=None, platform="instagram", handle="x")
    monkeypatch.setenv("FARM_OFMAI_BASE_URL", "https://ofmai.test")
    assert from_env(acc, client_factory=lambda: FakeClient([])) is None
    acc = SimpleNamespace(character_id="char-1", platform="instagram", handle="x")
    monkeypatch.delenv("FARM_OFMAI_BASE_URL", raising=False)
    monkeypatch.setattr(bridge, "resolve_base_url", lambda: (_ for _ in ()).throw(bridge.BridgeNotConfigured("unset")))
    assert from_env(acc) is None
    monkeypatch.setattr(bridge, "resolve_base_url", lambda: "https://ofmai.test")
    c = from_env(acc, client_factory=lambda: FakeClient([{"text": "hey"}]))
    assert isinstance(c, Composer) and c.character_id == "char-1" and c.handle == "x"
    assert c({}) == "hey"


def test_the_bridge_client_is_built_on_the_first_comment_only():
    built = []

    def factory():
        built.append(1)
        return FakeClient([{"text": "ok"}])

    c = Composer(character_id="char-1", platform="instagram", client_factory=factory)
    assert built == []  # a session that never comments never touches the bridge
    assert c({}) == "ok" and built == [1]
