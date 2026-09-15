"""Discord alerts raised by the fork (E2.1, docs/social/rules.md R32).

No network: the HTTP post is injected. What matters here is the contract the
rest of the farm relies on — an alert never raises, never blocks, never carries
a credential, and says the one thing a human needs: which gate, on which phone,
and the command that releases it.
"""

import pytest

from gitd.farm import alerts


@pytest.fixture(autouse=True)
def _no_ambient_webhook(monkeypatch):
    """Neither the operator's env, nor a .env, nor the Mac mini keychain leaks in."""
    monkeypatch.delenv(alerts.ENV_VAR, raising=False)
    monkeypatch.setattr(alerts, "_settings_webhook", lambda: "")
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "")


class Spy:
    """Stands in for the HTTP post."""

    def __init__(self, result=True, boom: Exception | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.result = result
        self.boom = boom

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        if self.boom:
            raise self.boom
        return self.result

    @property
    def content(self) -> str:
        return self.calls[-1][1]["content"]


# ── Where the webhook comes from ──────────────────────────────────────────────


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook-env")
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "https://discord.example/hook-keychain")
    assert alerts.webhook_url() == "https://discord.example/hook-env"


def test_falls_back_to_settings_then_to_the_keychain(monkeypatch):
    """`.env` lands in the settings object, never in os.environ (gitd/config.py)."""
    monkeypatch.setattr(alerts, "_settings_webhook", lambda: "https://discord.example/hook-dotenv")
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "https://discord.example/hook-keychain")
    assert alerts.webhook_url() == "https://discord.example/hook-dotenv"


def test_falls_back_to_the_keychain(monkeypatch):
    monkeypatch.setattr(alerts, "_keychain_webhook", lambda: "https://discord.example/hook-keychain")
    assert alerts.webhook_url() == "https://discord.example/hook-keychain"


def test_settings_field_exists_so_a_dotenv_entry_is_not_silently_ignored():
    from gitd.config import settings

    assert hasattr(settings, "farm_discord_webhook_url")


def test_blank_env_var_is_not_a_webhook(monkeypatch):
    monkeypatch.setenv(alerts.ENV_VAR, "   ")
    assert alerts.webhook_url() == ""


# ── notify() ──────────────────────────────────────────────────────────────────


def test_no_webhook_is_a_silent_no_op():
    """A farm with no webhook configured keeps running; it just stays quiet."""
    spy = Spy()
    assert alerts.notify("error", "title", "message", poster=spy) is False
    assert spy.calls == []  # nothing was even attempted


def test_posts_plain_text_with_title_and_message(monkeypatch):
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    spy = Spy()
    assert alerts.notify("warn", "Santé farm", "un canari muet", poster=spy) is True

    url, payload = spy.calls[0]
    assert url == "https://discord.example/hook"
    assert payload["username"] == alerts.USERNAME
    assert "Santé farm" in payload["content"]
    assert "un canari muet" in payload["content"]
    assert alerts._LEVELS["warn"] in payload["content"]


def test_content_is_truncated_to_the_discord_budget(monkeypatch):
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    spy = Spy()
    alerts.notify("info", "t", "x" * 5000, poster=spy)
    assert len(spy.content) == alerts.MAX_CONTENT


def test_a_broken_webhook_never_raises(monkeypatch):
    """Discord being down must never fail the run that was asking for a human."""
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    spy = Spy(boom=RuntimeError("connection reset"))
    assert alerts.notify("critical", "t", "m", poster=spy) is False


def test_a_non_2xx_answer_is_reported_as_failure(monkeypatch):
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    assert alerts.notify("error", "t", "m", poster=Spy(result=False)) is False


# ── checkpoint_awaiting_human() ───────────────────────────────────────────────


def test_checkpoint_message_says_gate_phone_and_how_to_release_it(monkeypatch):
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    spy = Spy()
    alerts.checkpoint_awaiting_human(
        reason="sms",
        prompt="Read the SMS on the character's own SIM and type it",
        run_id=42,
        device="R58N1234",
        skill="ofmai_signup_instagram",
        poster=spy,
    )
    content = spy.content
    # the shape build-plan.md E2.1 asks for
    assert "AWAITING HUMAN — sms:" in content
    assert "(run 42)" in content
    # …plus what a human in Bangkok needs to act on a phone in Paris
    assert "R58N1234" in content
    assert "ofmai_signup_instagram" in content
    assert "/api/skills/runs/42/resume" in content


def test_checkpoint_without_a_run_has_no_resume_command(monkeypatch):
    """An untracked replay cannot be resumed through the API — don't pretend it can."""
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    spy = Spy()
    alerts.checkpoint_awaiting_human(reason="captcha", prompt="solve it", run_id=None, poster=spy)
    assert "resume" not in spy.content.replace("AWAITING HUMAN", "")
    assert "run " not in spy.content


def test_checkpoint_carries_no_credential(monkeypatch):
    """R9: the prompt says where to read a secret, the alert never carries one."""
    monkeypatch.setenv(alerts.ENV_VAR, "https://discord.example/hook")
    spy = Spy()
    alerts.checkpoint_awaiting_human(
        reason="login",
        prompt="Type the password from the Keychain (ofmai-social-instagram-sierra)",
        run_id=7,
        device="R58N1234",
        poster=spy,
    )
    # the keychain *entry name* is fine; only its value would be a leak, and the
    # alert never reads it.
    assert "ofmai-social-instagram-sierra" in spy.content
    assert spy.content.count("password") == 1  # the word from the prompt, nothing more
