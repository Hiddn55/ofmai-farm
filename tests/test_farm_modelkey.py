"""The model key: environment first, then the Keychain, never a file."""

import subprocess

from gitd.farm import advisor, explore_score, modelkey


def test_env_wins_and_keychain_fills_the_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-env")
    assert modelkey.ensure_api_key(run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("not called"))) is True
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    fake = lambda argv, **k: subprocess.CompletedProcess(argv, 0, "k-keychain\n", "")
    assert modelkey.ensure_api_key(run=fake) is True
    assert __import__("os").environ["ANTHROPIC_API_KEY"] == "k-keychain"


def test_no_key_anywhere_means_no_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FARM_ADVISOR", raising=False)
    monkeypatch.setattr(modelkey, "_keychain", lambda run=None: "")
    assert modelkey.ensure_api_key() is False
    assert advisor.configured() is None
    assert explore_score.configured() is None
