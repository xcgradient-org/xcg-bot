from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATHS = (
    ROOT / ".env",
    ROOT.parents[0] / ".env",
)


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    notion_token: str
    discord_user_id_oriol: int
    discord_user_id_arnau: int
    discord_user_id_adam: int
    notion_tasks_db_id: str
    notion_daily_logs_db_id: str
    notion_team_db_id: str
    notion_meetings_db_id: str
    notion_settings_db_id: str | None
    notion_objectives_db_id: str | None
    notion_krs_db_id: str | None
    discord_blockers_channel_id: int
    discord_announcements_channel_id: int
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_api_keys: tuple[str, ...]
    llm_api_style: str
    internal_host: str
    internal_port: int
    internal_api_token: str | None
    meeting_task_project_id: str | None
    meeting_task_project_name: str | None


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def load_environment() -> Path | None:
    for env_path in ENV_PATHS:
        if env_path.exists():
            load_dotenv(env_path)
            return env_path
    return None


def _split_api_keys(value: str) -> list[str]:
    keys: list[str] = []
    for chunk in value.replace("\n", ",").split(","):
        key = chunk.strip()
        if key:
            keys.append(key)
    return keys


def _llm_api_keys_from_env() -> tuple[str, ...]:
    keys: list[str] = []
    for env_name in (
        "LLM_API_KEY",
        "LLM_API_KEY_1",
        "LLM_API_KEY_2",
        "LLM_API_KEY_3",
        "GROQ_API_KEY",
        "GROQ_API_KEY_1",
        "GROQ_API_KEY_2",
        "GROQ_API_KEY_3",
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            keys.append(value)

    keys.extend(_split_api_keys(os.getenv("LLM_API_KEYS", "")))
    keys.extend(_split_api_keys(os.getenv("GROQ_API_KEYS", "")))

    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return tuple(deduped)


def default_llm_settings() -> tuple[str, str, tuple[str, ...], str]:
    explicit_base_url = os.getenv("LLM_BASE_URL", "").strip()
    explicit_model = os.getenv("LLM_MODEL", "").strip()
    explicit_api_style = os.getenv("LLM_API_STYLE", "").strip().lower()

    base_url = explicit_base_url or "https://api.groq.com/openai/v1"
    model = explicit_model or "llama-3.3-70b-versatile"
    api_keys = _llm_api_keys_from_env()

    if explicit_api_style in {"", "openai"}:
        api_style = explicit_api_style or "openai"
    else:
        raise RuntimeError("Only LLM_API_STYLE=openai is supported.")

    return base_url, model, api_keys, api_style


def load_settings() -> Settings:
    env_path = load_environment()
    if env_path is None:
        searched_paths = ", ".join(str(path) for path in ENV_PATHS)
        raise RuntimeError(f"No .env file found. Searched: {searched_paths}")

    notion_tasks_db_id = os.getenv("NOTION_TASKS_DB_ID", "").strip() or os.getenv("NOTION_TASKS_DB", "").strip()
    notion_daily_logs_db_id = os.getenv("NOTION_DAILY_LOGS_DB_ID", "").strip() or os.getenv("NOTION_DAILY_LOGS_DB", "").strip()
    notion_team_db_id = os.getenv("NOTION_TEAM_DB_ID", "").strip() or os.getenv("NOTION_TEAM_DB", "").strip()
    notion_meetings_db_id = os.getenv("NOTION_MEETINGS_DB_ID", "").strip() or os.getenv("NOTION_MEETINGS_DB", "").strip()

    required = {
        "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", "").strip(),
        "NOTION_TOKEN": os.getenv("NOTION_TOKEN", "").strip(),
        "DISCORD_USER_ID_ORIOL": os.getenv("DISCORD_USER_ID_ORIOL", "").strip(),
        "DISCORD_USER_ID_ARNAU": os.getenv("DISCORD_USER_ID_ARNAU", "").strip(),
        "DISCORD_USER_ID_ADAM": os.getenv("DISCORD_USER_ID_ADAM", "").strip(),
        "NOTION_TASKS_DB_ID": notion_tasks_db_id,
        "NOTION_DAILY_LOGS_DB_ID": notion_daily_logs_db_id,
        "NOTION_TEAM_DB_ID": notion_team_db_id,
        "NOTION_MEETINGS_DB_ID": notion_meetings_db_id,
        "DISCORD_BLOCKERS_CHANNEL_ID": os.getenv("DISCORD_BLOCKERS_CHANNEL_ID", "").strip(),
        "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": os.getenv("DISCORD_ANNOUNCEMENTS_CHANNEL_ID", "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    llm_base_url, llm_model, llm_api_keys, llm_api_style = default_llm_settings()

    return Settings(
        discord_token=required["DISCORD_TOKEN"],
        notion_token=required["NOTION_TOKEN"],
        discord_user_id_oriol=int(required["DISCORD_USER_ID_ORIOL"]),
        discord_user_id_arnau=int(required["DISCORD_USER_ID_ARNAU"]),
        discord_user_id_adam=int(required["DISCORD_USER_ID_ADAM"]),
        notion_tasks_db_id=required["NOTION_TASKS_DB_ID"],
        notion_daily_logs_db_id=required["NOTION_DAILY_LOGS_DB_ID"],
        notion_team_db_id=required["NOTION_TEAM_DB_ID"],
        notion_meetings_db_id=required["NOTION_MEETINGS_DB_ID"],
        notion_settings_db_id=os.getenv("NOTION_SETTINGS_DB_ID", "").strip() or None,
        notion_objectives_db_id=os.getenv("NOTION_OBJECTIVES_DB_ID", "").strip() or os.getenv("NOTION_OBJECTIVES_DB", "").strip() or None,
        notion_krs_db_id=os.getenv("NOTION_KRS_DB_ID", "").strip() or os.getenv("NOTION_KRS_DB", "").strip() or None,
        discord_blockers_channel_id=int(required["DISCORD_BLOCKERS_CHANNEL_ID"]),
        discord_announcements_channel_id=int(required["DISCORD_ANNOUNCEMENTS_CHANNEL_ID"]),
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_keys[0] if llm_api_keys else "",
        llm_api_keys=llm_api_keys,
        llm_api_style=llm_api_style,
        internal_host=os.getenv("INTERNAL_HTMLS_HOST", "127.0.0.1").strip() or "127.0.0.1",
        internal_port=int(os.getenv("INTERNAL_HTMLS_PORT", "8012")),
        internal_api_token=(
            os.getenv("INTERNAL_API_TOKEN", "").strip()
            or os.getenv("XCG_INTERNAL_API_TOKEN", "").strip()
            or None
        ),
        meeting_task_project_id=os.getenv("NOTION_MEETING_TASK_PROJECT_ID", "").strip() or None,
        meeting_task_project_name=os.getenv("NOTION_MEETING_TASK_PROJECT_NAME", "").strip() or None,
    )
