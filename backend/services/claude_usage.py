from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_DEFAULT_PROFILE = Path.home() / ".claude-corporate"


def _profile_dir() -> Path:
    env = os.getenv("CLAUDE_PROFILE_DIR", "").strip()
    return Path(env).expanduser() if env else _DEFAULT_PROFILE


def _load_credentials() -> dict[str, Any]:
    path = _profile_dir() / ".credentials.json"
    if not path.exists():
        raise FileNotFoundError(f"Credentials not found: {path}")
    with path.open() as fh:
        return json.load(fh)


class ClaudeUsageService:
    def get_usage(self) -> dict[str, Any]:
        try:
            creds = _load_credentials()
        except FileNotFoundError as exc:
            return {"error": "not_configured", "hint": str(exc)}

        oauth = creds.get("claudeAiOauth", {})
        access_token: str = oauth.get("accessToken", "")
        expires_at_ms: int = oauth.get("expiresAt", 0)
        subscription_type: str = oauth.get("subscriptionType", "unknown")

        if not access_token:
            return {"error": "no_token", "hint": "No access token in credentials file"}

        now_ms = int(time.time() * 1000)
        if expires_at_ms and expires_at_ms < now_ms:
            return {
                "error": "token_expired",
                "hint": "Run claude-corporate in a terminal to re-authenticate",
            }

        try:
            resp = httpx.get(
                _USAGE_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "anthropic-beta": _BETA_HEADER,
                },
                timeout=10.0,
            )
        except httpx.TimeoutException:
            return {"error": "timeout", "hint": "Anthropic API timed out"}
        except Exception as exc:  # noqa: BLE001
            return {"error": "request_failed", "hint": str(exc)}

        if resp.status_code == 401:
            return {
                "error": "token_expired",
                "hint": "Run claude-corporate in a terminal to re-authenticate",
            }
        if not resp.is_success:
            return {"error": f"api_error_{resp.status_code}", "hint": resp.text[:200]}

        data = resp.json()
        return {
            "five_hour": data.get("five_hour"),
            "seven_day": data.get("seven_day"),
            "seven_day_sonnet": data.get("seven_day_sonnet"),
            "subscription_type": subscription_type,
            "profile": _profile_dir().name.lstrip("."),
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
