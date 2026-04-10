from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from log_command import register_log_command
from meeting_command import register_meeting_command
from meetings import start_meeting_reminder_poller, start_new_meeting_poller
from notion import NotionService
from reflection import ReflectionService
from streaks import start_daily_reset_task


LOGGER = logging.getLogger("xcg_bot")
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    notion_token: str
    anthropic_api_key: str
    notion_tasks_db_id: str
    notion_daily_logs_db_id: str
    notion_streaks_db_id: str
    notion_meetings_db_id: str
    discord_blockers_channel_id: int
    discord_announcements_channel_id: int


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


def load_environment() -> Path | None:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
        return ENV_PATH
    return None


def load_settings() -> Settings:
    env_path = load_environment()
    if env_path is None:
        raise RuntimeError("No .env file found at automation/.env.")

    required = {
        "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", "").strip(),
        "NOTION_TOKEN": os.getenv("NOTION_TOKEN", "").strip(),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "NOTION_TASKS_DB_ID": os.getenv("NOTION_TASKS_DB_ID", "").strip(),
        "NOTION_DAILY_LOGS_DB_ID": os.getenv("NOTION_DAILY_LOGS_DB_ID", "").strip(),
        "NOTION_STREAKS_DB_ID": os.getenv("NOTION_STREAKS_DB_ID", "").strip(),
        "NOTION_MEETINGS_DB_ID": os.getenv("NOTION_MEETINGS_DB_ID", "").strip(),
        "DISCORD_BLOCKERS_CHANNEL_ID": os.getenv("DISCORD_BLOCKERS_CHANNEL_ID", "").strip(),
        "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": os.getenv("DISCORD_ANNOUNCEMENTS_CHANNEL_ID", "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    LOGGER.info("Loaded environment from %s", env_path)
    LOGGER.info("All required environment variables are present.")

    return Settings(
        discord_token=required["DISCORD_TOKEN"],
        notion_token=required["NOTION_TOKEN"],
        anthropic_api_key=required["ANTHROPIC_API_KEY"],
        notion_tasks_db_id=required["NOTION_TASKS_DB_ID"],
        notion_daily_logs_db_id=required["NOTION_DAILY_LOGS_DB_ID"],
        notion_streaks_db_id=required["NOTION_STREAKS_DB_ID"],
        notion_meetings_db_id=required["NOTION_MEETINGS_DB_ID"],
        discord_blockers_channel_id=int(required["DISCORD_BLOCKERS_CHANNEL_ID"]),
        discord_announcements_channel_id=int(required["DISCORD_ANNOUNCEMENTS_CHANNEL_ID"]),
    )


class XCGradientOSBot(commands.Bot):
    def __init__(self, settings: Settings, notion: NotionService, reflection: ReflectionService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.notion = notion
        self.reflection = reflection
        self.reset_task = None
        self.new_meeting_task = None
        self.meeting_reminder_task = None

    async def setup_hook(self) -> None:
        register_log_command(self, self.tree, self.notion, self.reflection, self.settings)
        register_meeting_command(self.tree, self.notion, self.reflection, self.settings)
        LOGGER.info("✅ /meeting command registered")
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

            if self.reset_task is None or self.reset_task.done():
                self.reset_task = start_daily_reset_task(self, self.notion)
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
        streaks_db_id=settings.notion_streaks_db_id,
    )
    notion.verify_startup()
    notion.client.databases.retrieve(database_id=settings.notion_meetings_db_id)
    LOGGER.info("Startup checks passed: Notion databases are reachable.")

    reflection = ReflectionService(api_key=settings.anthropic_api_key)
    LOGGER.info("Anthropic client initialized.")

    bot = XCGradientOSBot(settings=settings, notion=notion, reflection=reflection)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
