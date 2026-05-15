from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

_ME_URL = "https://api.openai.com/v1/me"
_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
_TOKEN_PATTERN = re.compile(r"(\w+_token_count)=(\d+)")
_CONVO_PATTERN = re.compile(r"conversation\.id=([\w-]+)")


def _aggregate(db_path: Path, since_ts: int) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """SELECT feedback_log_body FROM logs
               WHERE ts >= ?
                 AND feedback_log_body LIKE '%response.completed%'
                 AND feedback_log_body LIKE '%input_token_count%'""",
            (since_ts,),
        ).fetchall()
    finally:
        conn.close()

    inp = out = cached = reasoning = 0
    sessions: set[str] = set()
    for (body,) in rows:
        nums = dict(_TOKEN_PATTERN.findall(body))
        inp += int(nums.get("input_token_count", 0))
        out += int(nums.get("output_token_count", 0))
        cached += int(nums.get("cached_token_count", 0))
        reasoning += int(nums.get("reasoning_token_count", 0))
        m = _CONVO_PATTERN.search(body)
        if m:
            sessions.add(m.group(1))

    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cached_tokens": cached,
        "reasoning_tokens": reasoning,
        "turns": len(rows),
        "sessions": len(sessions),
    }


def _iso_from_epoch(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _map_window(window: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    return {
        "utilization": window.get("used_percent"),
        "resets_at": _iso_from_epoch(window.get("reset_at")),
        "window_seconds": window.get("limit_window_seconds"),
        "reset_after_seconds": window.get("reset_after_seconds"),
    }


class CodexSQLiteProvider:
    def get_usage(self, subscription: dict[str, Any], profile_dir: Path) -> dict[str, Any]:
        db_path = Path(subscription.get("db_path", "~/.codex/logs_2.sqlite")).expanduser()
        auth_path = Path(subscription.get("auth_path", "~/.codex/auth.json")).expanduser()
        base: dict[str, Any] = {"type": "codex", "tier": subscription.get("tier", "chatgpt")}

        if not auth_path.exists() and not db_path.exists():
            return {
                **base,
                "status": "not_configured",
                "hint": f"Missing {auth_path} and {db_path}",
            }

        token = ""
        account_id = ""
        account: dict[str, str] = {}
        if auth_path.exists():
            try:
                auth = json.loads(auth_path.read_text())
                tokens = auth.get("tokens", {})
                token = tokens.get("access_token", "")
                account_id = tokens.get("account_id", "")
            except Exception as exc:  # noqa: BLE001
                return {**base, "status": "error", "hint": str(exc)}

        now = int(time.time())
        today_start = now - (now % 86400)
        today = _aggregate(db_path, today_start) if db_path.exists() else None
        seven_day_stats = _aggregate(db_path, now - 7 * 86400) if db_path.exists() else None

        if not token:
            if not db_path.exists():
                return {**base, "status": "no_token", "hint": f"No access token in {auth_path}"}
            return {
                **base,
                "status": "ok",
                "account": account,
                "today": today,
                "seven_day_stats": seven_day_stats,
                "quota_status": "no_token",
                "quota_hint": f"No access token in {auth_path}",
                "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "xcg-bot/1.0",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        try:
            usage_resp = httpx.get(_USAGE_URL, headers=headers, timeout=10.0, follow_redirects=True)
        except httpx.TimeoutException:
            if not db_path.exists():
                return {**base, "status": "timeout", "hint": "ChatGPT quota request timed out"}
            return {
                **base,
                "status": "ok",
                "account": account,
                "today": today,
                "seven_day_stats": seven_day_stats,
                "quota_status": "timeout",
                "quota_hint": "ChatGPT quota request timed out",
                "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except Exception as exc:  # noqa: BLE001
            if not db_path.exists():
                return {**base, "status": "error", "hint": str(exc)}
            return {
                **base,
                "status": "ok",
                "account": account,
                "today": today,
                "seven_day_stats": seven_day_stats,
                "quota_status": "error",
                "quota_hint": str(exc),
                "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        if usage_resp.status_code == 401:
            return {
                **base,
                "status": "token_expired",
                "hint": f"Refresh ChatGPT auth in {auth_path}",
            }
        if not usage_resp.is_success:
            hint = usage_resp.text[:200]
            if not db_path.exists():
                return {**base, "status": f"api_error_{usage_resp.status_code}", "hint": hint}
            return {
                **base,
                "status": "ok",
                "account": account,
                "today": today,
                "seven_day_stats": seven_day_stats,
                "quota_status": f"api_error_{usage_resp.status_code}",
                "quota_hint": hint,
                "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        data = usage_resp.json()
        rate_limit = data.get("rate_limit") or {}
        account = {
            "email": data.get("email", ""),
            "account_id": data.get("account_id", ""),
            "user_id": data.get("user_id", ""),
        }

        # Fallback profile fetch only when the quota payload did not include an email.
        if not account["email"]:
            try:
                resp = httpx.get(
                    _ME_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5.0,
                )
                if resp.is_success:
                    me = resp.json()
                    account["email"] = me.get("email", "")
                    account["name"] = me.get("name", "")
            except Exception:  # noqa: BLE001
                pass

        return {
            **base,
            "status": "ok",
            "tier": data.get("plan_type") or base["tier"],
            "account": account,
            "five_hour": _map_window(rate_limit.get("primary_window")),
            "seven_day": _map_window(rate_limit.get("secondary_window")),
            "quota_status": "ok",
            "quota_source": "chatgpt_backend",
            "today": today,
            "seven_day_stats": seven_day_stats,
            "credits": data.get("credits"),
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
