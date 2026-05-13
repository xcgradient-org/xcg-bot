from __future__ import annotations

import os
import time
from typing import Any

import httpx


class AnthropicApiProvider:
    """Org-level Anthropic API usage. Requires an admin API key in .env."""

    def get_usage(self, config: dict[str, Any]) -> dict[str, Any]:
        key_env = config.get("key_env", "ANTHROPIC_API_KEY")
        api_key = os.getenv(key_env, "").strip()
        base: dict[str, Any] = {"type": "anthropic_api", "label": config.get("label", "Anthropic API")}

        if not api_key:
            return {**base, "status": "not_configured", "hint": f"Set {key_env} in .env"}

        try:
            resp = httpx.get(
                "https://api.anthropic.com/v1/usage",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=10.0,
            )
        except httpx.TimeoutException:
            return {**base, "status": "timeout"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "error", "hint": str(exc)}

        if resp.status_code in (401, 403):
            return {**base, "status": "invalid_key"}
        if not resp.is_success:
            return {**base, "status": f"api_error_{resp.status_code}", "hint": resp.text[:200]}

        data = resp.json()
        return {
            **base,
            "status": "ok",
            "data": data,
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
