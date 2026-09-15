"""
Pydantic-settings configuration — reads from .env / environment variables.
Compatible with both pydantic v1 and v2.
"""

from pathlib import Path

try:
    from pydantic_settings import BaseSettings
except ImportError:
    # pydantic v1 fallback — BaseSettings was in pydantic directly
    from pydantic import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env and environment variables."""

    # ── Paths ────────────────────────────────────────────────────────────────
    base_dir: Path = Path(__file__).resolve().parent.parent
    db_path: Path = Path(__file__).resolve().parent.parent / "data" / "gitd.db"

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 5055

    # ── Devices ──────────────────────────────────────────────────────────────
    default_device: str = ""  # ADB serial of primary phone (auto-detected if empty)

    # ── Farm ─────────────────────────────────────────────────────────────────
    # ADB serial of the observer phone: a logged-out profile on its own exit IP
    # used to measure shadowbans from the outside. Never a character's phone,
    # never warmed, never in farm_accounts (docs/social/health-canaries.md §2).
    # Keep DEFAULT_DEVICE on this same serial so dashboard tools that fall back
    # to it can never land on a character.
    farm_observer_device: str = ""

    # Discord webhook the fork posts to for what does NOT travel through OFMAI:
    # a run stopped at a human gate, a dead bridge, a hand-typed kill-switch
    # (docs/social/rules.md R32, health-canaries.md §5). Empty here falls back to
    # the macOS keychain entry `ofmai-discord-webhook`; empty in both makes
    # alerting a silent no-op — the farm keeps running, it just stays quiet.
    farm_discord_webhook_url: str = ""

    # Base URL of the OFMAI node that carries `app/api/farm/*` — the only surface
    # the Mac mini ever calls (docs/social/bridge-ofmai-farm.md §2), e.g.
    # FARM_OFMAI_BASE_URL=https://ofmai.ai
    # The shared secret is deliberately NOT a setting: it lives in the macOS
    # keychain (`ofmai-farm-secret`) or in a real environment variable
    # (FARM_BRIDGE_SECRET), never in a file of the repo (R9).
    farm_ofmai_base_url: str = ""

    # ── iOS (feature-gated) ──────────────────────────────────────────────────
    # iOS support (Appium/WebDriverAgent) ships dev-only for one release cycle:
    # OFF by default, so `ios:` device refs surface "not supported" errors and
    # iOS devices are excluded from discovery. Enable with GITD_ENABLE_IOS=1
    # (or ios_platform_enabled=true in .env). Flip the default once device
    # testing passes.
    ios_platform_enabled: bool = False

    # ── Perception ───────────────────────────────────────────────────────────
    # After a UI action, append a before/after accessibility-tree diff to the
    # tool result so the model sees what its action changed (additive perception
    # aid). ON by default; set A11Y_DIFF_ENABLED=false to disable (kill-switch) —
    # the diff costs one extra UI-tree dump per UI action.
    a11y_diff_enabled: bool = True

    # ── LLM ──────────────────────────────────────────────────────────────────
    # Provider used when a session is created without an explicit one. Defaults
    # to claude-code (Claude subscription, no API key) — `android-agent login`
    # records this in .env.
    default_provider: str = "claude-code"

    # ── API keys (optional, loaded from env) ─────────────────────────────────
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""

    # ── Ollama ──────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"

    # ── vLLM (OpenAI-compatible, remote GPU) ────────────────────────────────────
    # Default assumes a chained tunnel:
    #   phone:8000 → adb reverse → mac:8000 → ssh -L 8000:localhost:8000 <your-gpu-host>
    # On the Mac dev backend, the same URL works directly because the ssh
    # tunnel is already on `localhost`. Override via env GITD_VLLM_BASE_URL.
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_api_key: str = "EMPTY"  # vLLM doesn't enforce auth; placeholder for OpenAI client

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
