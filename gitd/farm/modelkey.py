"""Where the model key comes from, for the two places the farm calls Claude.

``ANTHROPIC_API_KEY`` in the environment wins. Failing that, the macOS login
Keychain, service ``ofmai-anthropic-key`` — the same rule as the Discord
webhook and the bridge secret: a secret lives in the Keychain or in a real
environment variable, never in a file of this repo (R9). The key found is put
in the environment so the SDK's default client picks it up.
"""

from __future__ import annotations

import os
import subprocess

KEYCHAIN_SERVICE = "ofmai-anthropic-key"


def _keychain(run=subprocess.run) -> str:
    try:
        out = run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001 — not macOS, `security` missing, keychain locked…
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def ensure_api_key(run=subprocess.run) -> bool:
    """True when a key is available to the SDK (env, or Keychain copied into the env)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    key = _keychain(run)
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
        return True
    return False
