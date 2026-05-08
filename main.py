from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from blocker_command import register_blocker_command
from log_command import register_log_command
from meeting_command import register_meeting_command
from meetings import start_meeting_reminder_poller, start_new_meeting_poller
from notion import NotionService
from reflection import ReflectionService
from rollover_command import register_rollover_command
from streaks import start_daily_reset_task
from task_command import register_task_command


LOGGER = logging.getLogger("xcg_bot")
ENV_PATHS = (
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parents[1] / ".env",
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
    discord_blockers_channel_id: int
    discord_announcements_channel_id: int
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_api_keys: tuple[str, ...]
    llm_api_style: str


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
        api_style = explicit_api_style
    else:
        raise RuntimeError("Only LLM_API_STYLE=openai is supported. Local LLM and Gemini fallbacks are disabled.")
    api_style = api_style or "openai"

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

    LOGGER.info("Loaded environment from %s", env_path)
    LOGGER.info("All required environment variables are present.")
    llm_base_url, llm_model, llm_api_keys, llm_api_style = default_llm_settings()
    notion_settings_db_id = os.getenv("NOTION_SETTINGS_DB_ID", "").strip() or None

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
        notion_settings_db_id=notion_settings_db_id,
        discord_blockers_channel_id=int(required["DISCORD_BLOCKERS_CHANNEL_ID"]),
        discord_announcements_channel_id=int(required["DISCORD_ANNOUNCEMENTS_CHANNEL_ID"]),
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_keys[0] if llm_api_keys else "",
        llm_api_keys=llm_api_keys,
        llm_api_style=llm_api_style,
    )


class XCGradientOSBot(commands.Bot):
    def __init__(self, settings: Settings, notion: NotionService, reflection: ReflectionService) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.notion = notion
        self.reflection = reflection
        self.reset_task = None
        self.new_meeting_task = None
        self.meeting_reminder_task = None

    async def setup_hook(self) -> None:
        register_log_command(self, self.tree, self.notion, self.reflection, self.settings)
        register_blocker_command(self, self.tree, self.reflection, self.settings)
        register_meeting_command(self.tree, self.notion, self.reflection, self.settings)
        register_task_command(self, self.tree, self.notion, self.reflection, self.settings)
        register_rollover_command(self.tree, self.notion, self.settings)
        LOGGER.info("✅ /meeting, /log, /blocker, /tasks, and /rollover commands registered")
        synced = await self.tree.sync()
        LOGGER.info("Slash commands synced: %s", len(synced))

    async def on_ready(self) -> None:
        if self.user:
            LOGGER.info("Bot connected as %s", self.user)
            try:
                channel = self.get_channel(self.settings.discord_blockers_channel_id) or await self.fetch_channel(self.settings.discord_blockers_channel_id)
                LOGGER.info("Blockers channel is live: %s (%s)", getattr(channel, "name", "unknown"), self.settings.discord_blockers_channel_id)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Unable to verify blockers channel %s: %s", self.settings.discord_blockers_channel_id, exc)
            try:
                channel = self.get_channel(self.settings.discord_announcements_channel_id) or await self.fetch_channel(self.settings.discord_announcements_channel_id)
                LOGGER.info("Announcements channel is live: %s (%s)", getattr(channel, "name", "unknown"), self.settings.discord_announcements_channel_id)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Unable to verify announcements channel %s: %s", self.settings.discord_announcements_channel_id, exc)

            if self.notion.streaks_available() and (self.reset_task is None or self.reset_task.done()):
                self.reset_task = start_daily_reset_task(self, self.notion)
            elif not self.notion.streaks_available():
                LOGGER.info("Streak maintenance is disabled because the configured Streaks database is unavailable.")
            if self.new_meeting_task is None or self.new_meeting_task.done():
                self.new_meeting_task = start_new_meeting_poller(
                    self,
                    self.notion,
                    self.settings.notion_meetings_db_id,
                    self.settings.discord_announcements_channel_id,
                )
            if self.meeting_reminder_task is None or self.meeting_reminder_task.done():
                self.meeting_reminder_task = start_meeting_reminder_poller(
                    self,
                    self.notion,
                    self.settings.notion_meetings_db_id,
                    self.settings.discord_announcements_channel_id,
                )
            LOGGER.info("✅ Meetings poller active")

    async def close(self) -> None:
        if self.reset_task is not None:
            self.reset_task.cancel()
        if self.new_meeting_task is not None:
            self.new_meeting_task.cancel()
        if self.meeting_reminder_task is not None:
            self.meeting_reminder_task.cancel()
        await super().close()


def main() -> None:
    configure_logging()
    settings = load_settings()
    notion = NotionService(
        token=settings.notion_token,
        tasks_db_id=settings.notion_tasks_db_id,
        daily_logs_db_id=settings.notion_daily_logs_db_id,
        team_db_id=settings.notion_team_db_id,
        settings_db_id=settings.notion_settings_db_id,
    )
    notion.verify_startup()
    notion.client.databases.retrieve(database_id=settings.notion_meetings_db_id)
    LOGGER.info("Startup checks passed: Notion databases are reachable.")

    reflection = ReflectionService(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_keys=settings.llm_api_keys,
        api_style=settings.llm_api_style,
    )
    try:
        reflection.verify_startup()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Primary LLM backend is unavailable at startup (%s). Bot will continue with degraded AI features.",
            exc,
        )
    else:
        LOGGER.info(
            "LLM client initialized with model %s at %s using %s transport.",
            settings.llm_model,
            settings.llm_base_url,
            settings.llm_api_style,
        )

    bot = XCGradientOSBot(settings=settings, notion=notion, reflection=reflection)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
