from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"


class ClaudeOAuthProvider:
    def get_usage(self, subscription: dict[str, Any], profile_dir: Path) -> dict[str, Any]:
        base: dict[str, Any] = {"type": "claude_oauth", "tier": subscription.get("tier", "unknown")}
        creds_path = profile_dir / ".credentials.json"

        if not creds_path.exists():
            return {
                **base,
                "status": "not_configured",
                "hint": f"CLAUDE_CONFIG_DIR={profile_dir} claude login",
            }

        try:
            creds = json.loads(creds_path.read_text())
        except Exception as exc:
            return {**base, "status": "error", "hint": str(exc)}

        oauth = creds.get("claudeAiOauth", {})
        access_token: str = oauth.get("accessToken", "")
        expires_at_ms: int = oauth.get("expiresAt", 0)
        tier: str = oauth.get("subscriptionType", base["tier"])
        base["tier"] = tier

        if not access_token:
            return {**base, "status": "no_token", "hint": "No access token in credentials file"}

        if expires_at_ms and expires_at_ms < int(time.time() * 1000):
            return {
                **base,
                "status": "token_expired",
                "hint": f"CLAUDE_CONFIG_DIR={profile_dir} claude login",
            }

        try:
            resp = httpx.get(
                _USAGE_URL,
                headers={"Authorization": f"Bearer {access_token}", "anthropic-beta": _BETA_HEADER},
                timeout=10.0,
            )
        except httpx.TimeoutException:
            return {**base, "status": "timeout"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "error", "hint": str(exc)}

        if resp.status_code == 401:
            return {
                **base,
                "status": "token_expired",
                "hint": f"CLAUDE_CONFIG_DIR={profile_dir} claude login",
            }
        if not resp.is_success:
            return {**base, "status": f"api_error_{resp.status_code}", "hint": resp.text[:200]}

        data = resp.json()
        return {
            **base,
            "status": "ok",
            "five_hour": data.get("five_hour"),
            "seven_day": data.get("seven_day"),
            "seven_day_sonnet": data.get("seven_day_sonnet"),
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
