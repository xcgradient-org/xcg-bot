from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_BETA_HEADER = "oauth-2025-04-20"
_REFRESH_BUFFER_MS = 5 * 60 * 1000


class ClaudeOAuthProvider:
    def _refresh_tokens(self, refresh_token: str) -> tuple[str, str | None, int | None] | None:
        token = str(refresh_token or "").strip()
        if not token:
            return None
        try:
            resp = httpx.post(
                _TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "xcg-bot/1.0"},
                data={"grant_type": "refresh_token", "refresh_token": token},
                timeout=10.0,
            )
        except Exception:  # noqa: BLE001
            return None
        if not resp.is_success:
            return None
        try:
            payload = resp.json()
        except ValueError:
            return None
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            return None
        refreshed_token = str(payload.get("refresh_token") or "").strip() or None
        expires_in = payload.get("expires_in")
        expires_at_ms = (
            int(time.time() * 1000) + int(float(expires_in) * 1000)
            if isinstance(expires_in, (int, float)) and float(expires_in) > 0
            else None
        )
        return access_token, refreshed_token, expires_at_ms

    def _persist_tokens(
        self,
        creds_path: Path,
        creds: dict[str, Any],
        *,
        access_token: str,
        refresh_token: str | None,
        expires_at_ms: int | None,
    ) -> None:
        oauth = creds.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            return
        oauth["accessToken"] = access_token
        if refresh_token:
            oauth["refreshToken"] = refresh_token
        if expires_at_ms:
            oauth["expiresAt"] = expires_at_ms
        try:
            creds_path.write_text(json.dumps(creds, indent=2), encoding="utf-8")
        except OSError:
            return

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
        refresh_token: str = oauth.get("refreshToken", "")
        expires_at_ms: int = oauth.get("expiresAt", 0)
        tier: str = oauth.get("subscriptionType", base["tier"])
        base["tier"] = tier

        access_token = str(access_token or "").strip()
        refresh_token = str(refresh_token or "").strip()
        now_ms = int(time.time() * 1000)
        token_stale = bool(expires_at_ms) and expires_at_ms <= (now_ms + _REFRESH_BUFFER_MS)
        if token_stale and refresh_token:
            refreshed = self._refresh_tokens(refresh_token)
            if refreshed:
                access_token, refreshed_token, refreshed_expires_at = refreshed
                refresh_token = refreshed_token or refresh_token
                self._persist_tokens(
                    creds_path,
                    creds,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_at_ms=refreshed_expires_at,
                )
                token_stale = False
            else:
                return {
                    **base,
                    "status": "token_expired",
                    "hint": f"CLAUDE_CONFIG_DIR={profile_dir} claude login",
                }

        if not access_token:
            return {**base, "status": "no_token", "hint": "No access token in credentials file"}

        if token_stale:
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

        if resp.status_code == 401 and refresh_token:
            refreshed = self._refresh_tokens(refresh_token)
            if refreshed:
                access_token, refreshed_token, refreshed_expires_at = refreshed
                refresh_token = refreshed_token or refresh_token
                self._persist_tokens(
                    creds_path,
                    creds,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_at_ms=refreshed_expires_at,
                )
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
