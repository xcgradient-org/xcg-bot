from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib import error as urlerror
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from backend.domain.founders import ROLE_TO_ENV
from backend.integrations.notion import NotionService
from backend.integrations.reflection import ReflectionService


LOGGER = logging.getLogger("xcg_internal.backend")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEAM_DB_ID = "c7ed3e34702c4d26b310cc7d91b16a97"
DEFAULT_OBJECTIVES_DB_ID = "1e4e9d72f9f5473abd43c1e0ecc53e49"
DEFAULT_KRS_DB_ID = "2b3c5815dd4943bb8c4dff005901fb1d"
DEFAULT_MEETINGS_DB_ID = "e654a7418d7e410c8072db8f7706ca3d"


def env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


@dataclass(slots=True)
class InternalRuntime:
    notion: NotionService
    reflection: ReflectionService
    objectives_db_id: str
    krs_db_id: str
    meetings_db_id: str
    meeting_task_project_id: str
    meeting_task_project_name: str
    discord_token: str
    discord_announcements_channel_id: str
    discord_blockers_channel_id: str
    discord_user_id_oriol: str
    discord_user_id_arnau: str
    discord_user_id_adam: str

    def post_discord_message(self, channel_id: str, content: str) -> None:
        if not self.discord_token or not channel_id:
            raise RuntimeError("Discord token or channel ID is missing.")
        body = json.dumps({"content": content}).encode("utf-8")
        token = self.discord_token if self.discord_token.lower().startswith("bot ") else f"Bot {self.discord_token}"
        request = Request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            data=body,
            headers={"Authorization": token, "Content-Type": "application/json", "User-Agent": "xcg-internal-tools"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Discord returned HTTP {response.status}.")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord returned HTTP {exc.code}: {detail}") from exc

    def mention_user_ids(self, attendees: list[str]) -> str:
        parts: list[str] = []
        seen: set[str] = set()
        for attendee in attendees:
            attendee_text = str(attendee or "").strip()
            env_name = ROLE_TO_ENV.get(attendee_text.upper())
            if not env_name:
                continue
            user_id = env(env_name)
            if user_id and user_id not in seen:
                seen.add(user_id)
                parts.append(f"<@{user_id}>")
        return " ".join(parts)


def build_runtime() -> InternalRuntime:
    load_dotenv(ROOT / ".env")
    return InternalRuntime(
        notion=NotionService(
            token=env("NOTION_TOKEN"),
            tasks_db_id=env("NOTION_TASKS_DB_ID", "NOTION_TASKS_DB"),
            daily_logs_db_id=env("NOTION_DAILY_LOGS_DB_ID", "NOTION_DAILY_LOGS_DB"),
            team_db_id=env("NOTION_TEAM_DB_ID", "NOTION_TEAM_DB", default=DEFAULT_TEAM_DB_ID),
            settings_db_id=env("NOTION_SETTINGS_DB_ID", "NOTION_SETTINGS_DB") or None,
        ),
        reflection=ReflectionService(
            model=env("LLM_MODEL", default="openai/gpt-oss-20b"),
            base_url=env("LLM_BASE_URL", default="https://api.groq.com/openai/v1"),
            api_keys=tuple(
                key.strip()
                for key in (
                    env("LLM_API_KEY"),
                    env("LLM_API_KEY_2"),
                    env("LLM_API_KEY_3"),
                    *env("LLM_API_KEYS").replace("\n", ",").split(","),
                )
                if key.strip()
            ),
            api_style=env("LLM_API_STYLE", default="openai"),
        ),
        objectives_db_id=env("NOTION_OBJECTIVES_DB_ID", "NOTION_OBJECTIVES_DB", default=DEFAULT_OBJECTIVES_DB_ID),
        krs_db_id=env("NOTION_KRS_DB_ID", "NOTION_KRS_DB", default=DEFAULT_KRS_DB_ID),
        meetings_db_id=env("NOTION_MEETINGS_DB_ID", "NOTION_MEETINGS_DB", default=DEFAULT_MEETINGS_DB_ID),
        meeting_task_project_id=env("NOTION_MEETING_TASK_PROJECT_ID"),
        meeting_task_project_name=env("NOTION_MEETING_TASK_PROJECT_NAME", default="ALPHA"),
        discord_token=env("DISCORD_TOKEN"),
        discord_announcements_channel_id=env("DISCORD_ANNOUNCEMENTS_CHANNEL_ID"),
        discord_blockers_channel_id=env("DISCORD_BLOCKERS_CHANNEL_ID"),
        discord_user_id_oriol=env("DISCORD_USER_ID_ORIOL"),
        discord_user_id_arnau=env("DISCORD_USER_ID_ARNAU"),
        discord_user_id_adam=env("DISCORD_USER_ID_ADAM"),
    )
