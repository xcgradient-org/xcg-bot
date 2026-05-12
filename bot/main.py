from __future__ import annotations

import logging

import discord
from discord.ext import commands

from backend.config import Settings, configure_logging, load_environment, load_settings, default_llm_settings
from blocker_command import register_blocker_command
from log_command import register_log_command
from meeting_command import register_meeting_command
from meetings import start_meeting_reminder_poller, start_new_meeting_poller
from notion import NotionService
from reflection import ReflectionService
from rollover_command import register_rollover_command
from streaks import start_daily_reset_task
from task_command import register_task_command


LOGGER = logging.getLogger("xcg_internal.bot")


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
        LOGGER.info("/meeting, /log, /blocker, /tasks, and /rollover commands registered")
        synced = await self.tree.sync()
        LOGGER.info("Slash commands synced: %s", len(synced))

    async def on_ready(self) -> None:
        if not self.user:
            return
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
        LOGGER.info("Meetings poller active")

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


__all__ = [
    "Settings",
    "XCGradientOSBot",
    "configure_logging",
    "default_llm_settings",
    "load_environment",
    "load_settings",
    "main",
]


if __name__ == "__main__":
    main()
