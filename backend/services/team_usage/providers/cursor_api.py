from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

_USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"

class CursorApiProvider:
    def get_usage(self, subscription: dict[str, Any], profile_dir: Path) -> dict[str, Any]:
        base: dict[str, Any] = {"type": "cursor", "tier": subscription.get("tier", "unknown")}
        db_path = Path(subscription.get("db_path", "~/.config/Cursor/User/globalStorage/state.vscdb")).expanduser()

        if not db_path.exists():
            return {
                **base,
                "status": "not_configured",
                "hint": f"Missing Cursor SQLite db at {db_path}",
            }

        token = ""
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'").fetchone()
            if row:
                token = row[0]
            conn.close()
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "error", "hint": f"Error reading token: {exc}"}

        if not token:
            return {**base, "status": "no_token", "hint": f"No access token found in {db_path}"}

        try:
            resp = httpx.post(
                _USAGE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={},
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
                "hint": "Cursor token expired. Please login to Cursor again.",
            }
        if not resp.is_success:
            return {**base, "status": f"api_error_{resp.status_code}", "hint": resp.text[:200]}

        try:
            data = resp.json()
        except Exception as exc:
            return {**base, "status": "error", "hint": f"Failed to parse response: {exc}"}

        plan_usage = data.get("planUsage", {})
        
        return {
            **base,
            "status": "ok",
            "plan_usage": {
                "auto_percent": plan_usage.get("autoPercentUsed"),
                "api_percent": plan_usage.get("apiPercentUsed"),
                "total_percent": plan_usage.get("totalPercentUsed"),
            },
            "billing_cycle_end": data.get("billingCycleEnd"),
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
