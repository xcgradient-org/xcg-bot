from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .providers.claude_oauth import ClaudeOAuthProvider
from .providers.codex_sqlite import CodexSQLiteProvider
from .providers.openai_api import OpenAIApiProvider
from .providers.anthropic_api import AnthropicApiProvider

_ROOT = Path(__file__).resolve().parents[3]
_MEMBERS_FILE = _ROOT / "members.json"

_CLAUDE_OAUTH = ClaudeOAuthProvider()
_CODEX_SQLITE = CodexSQLiteProvider()
_OPENAI_API = OpenAIApiProvider()
_ANTHROPIC_API = AnthropicApiProvider()


def _load_config() -> dict[str, Any]:
    if not _MEMBERS_FILE.exists():
        return {"members": [], "org_apis": []}
    with _MEMBERS_FILE.open() as fh:
        return json.load(fh)


def _fetch_member(member: dict[str, Any]) -> dict[str, Any]:
    profile_dir = Path(member["profile_dir"]).expanduser()
    subscriptions = []
    for sub in member.get("subscriptions", []):
        provider_type = sub.get("type")
        if provider_type == "claude_oauth":
            result = _CLAUDE_OAUTH.get_usage(sub, profile_dir)
        elif provider_type == "codex":
            result = _CODEX_SQLITE.get_usage(sub, profile_dir)
        else:
            result = {"type": provider_type, "status": "unknown_provider"}
        subscriptions.append(result)
    return {
        "id": member["id"],
        "name": member["name"],
        "email": member.get("email", ""),
        "role": member.get("role", ""),
        "subscriptions": subscriptions,
    }


def _fetch_org_api(config: dict[str, Any]) -> dict[str, Any]:
    provider_type = config.get("type")
    if provider_type == "openai_api":
        return _OPENAI_API.get_usage(config)
    if provider_type == "anthropic_api":
        return _ANTHROPIC_API.get_usage(config)
    return {"type": provider_type, "status": "unknown_provider"}


class TeamUsageService:
    def get_team_usage(self) -> dict[str, Any]:
        config = _load_config()
        members_cfg = config.get("members", [])
        org_apis_cfg = config.get("org_apis", [])

        member_results: dict[str, dict[str, Any]] = {}
        org_api_results: list[dict[str, Any]] = []

        tasks: list[tuple[str, Any]] = [("member", m) for m in members_cfg] + [("org", a) for a in org_apis_cfg]

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {}
            for tag, item in tasks:
                if tag == "member":
                    fut = pool.submit(_fetch_member, item)
                    futures[fut] = ("member", item["id"])
                else:
                    fut = pool.submit(_fetch_org_api, item)
                    futures[fut] = ("org", None)

            for fut in as_completed(futures):
                tag, member_id = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:  # noqa: BLE001
                    result = {"status": "error", "hint": str(exc)}
                if tag == "member":
                    member_results[member_id] = result
                else:
                    org_api_results.append(result)

        ordered_members = [member_results.get(m["id"], {"id": m["id"], "name": m["name"], "subscriptions": []}) for m in members_cfg]

        return {
            "members": ordered_members,
            "org_apis": org_api_results,
            "last_refreshed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_member_usage(self, member_id: str) -> dict[str, Any] | None:
        """Returns a single member's data, or None if not found."""
        config = _load_config()
        member = next((m for m in config.get("members", []) if m["id"] == member_id), None)
        if not member:
            return None
        return _fetch_member(member)
