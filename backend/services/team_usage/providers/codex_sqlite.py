from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

_ME_URL = "https://api.openai.com/v1/me"
_TOKEN_PATTERN = re.compile(r"(\w+_token_count)=(\d+)")
_CONVO_PATTERN = re.compile(r"conversation\.id=([\w-]+)")
_MODEL_PATTERN = re.compile(r"\bmodel=([\w.\-]+)")


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


class CodexSQLiteProvider:
    def get_usage(self, subscription: dict[str, Any], profile_dir: Path) -> dict[str, Any]:
        db_path = Path(subscription.get("db_path", "~/.codex/logs_2.sqlite")).expanduser()
        auth_path = Path(subscription.get("auth_path", "~/.codex/auth.json")).expanduser()
        base: dict[str, Any] = {"type": "codex", "tier": subscription.get("tier", "chatgpt")}

        if not db_path.exists():
            return {**base, "status": "not_configured", "hint": str(db_path)}

        account: dict[str, str] = {}
        if auth_path.exists():
            try:
                auth = json.loads(auth_path.read_text())
                token = auth.get("tokens", {}).get("access_token", "")
                if token:
                    resp = httpx.get(
                        _ME_URL,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=5.0,
                    )
                    if resp.is_success:
                        me = resp.json()
                        account = {"email": me.get("email", ""), "name": me.get("name", "")}
            except Exception:  # noqa: BLE001
                pass

        now = int(time.time())
        today_start = now - (now % 86400)

        return {
            **base,
            "status": "ok",
            "account": account,
            "today": _aggregate(db_path, today_start),
            "seven_day": _aggregate(db_path, now - 7 * 86400),
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
