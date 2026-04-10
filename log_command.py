from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import asyncio
import logging
import re

import discord
import pytz
from discord import app_commands

from streaks import MADRID_TZ, compute_updated_streak


LOGGER = logging.getLogger("xcg_bot.log_command")
BLOCKER_RE = re.compile(r"^\s*@(?P<role>CEO|CTO|COO)\s*-\s*(?P<description>.+?)\s*$", re.IGNORECASE | re.DOTALL)

# Replace these placeholders with the founders' real Discord user IDs.
DISCORD_USER_ID_ORIOL = 100000000000000001
DISCORD_USER_ID_ARNAU = 100000000000000002
DISCORD_USER_ID_ADAM = 100000000000000003

FOUNDERS = {
    DISCORD_USER_ID_ORIOL: {"name": "Oriol", "role": "CEO"},
    DISCORD_USER_ID_ARNAU: {"name": "Arnau", "role": "CTO"},
    DISCORD_USER_ID_ADAM: {"name": "Adam", "role": "COO"},
}


@dataclass(frozen=True, slots=True)
class LogContext:
    today_iso: str
    week_code: str


def current_context() -> LogContext:
    now = datetime.now(MADRID_TZ)
    iso_year, iso_week, _ = now.isocalendar()
    return LogContext(
        today_iso=now.date().isoformat(),
        week_code=f"{iso_year % 100:02d}-W{iso_week:02d}",
    )


def build_blocker_message(founder_name: str, target_role: str, description: str) -> str:
    return f"🚨 **{founder_name}** has a blocker for **@{target_role.upper()}**: {description}"


async def wait_for_follow_up(bot: discord.Client, *, channel_id: int, user_id: int, timeout: float = 60.0) -> discord.Message:
    def check(message: discord.Message) -> bool:
        return (
            message.author.id == user_id
            and message.channel.id == channel_id
            and not message.author.bot
        )

    return await bot.wait_for("message", check=check, timeout=timeout)


async def post_blocker(bot: discord.Client, channel_id: int, content: str) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        raise RuntimeError(f"Configured blockers channel is not messageable: {channel_id}")
    await channel.send(content)


async def process_blocker_follow_up(bot: discord.Client, interaction: discord.Interaction, founder_name: str, blockers_channel_id: int) -> None:
    if interaction.channel_id is None:
        return

    try:
        message = await wait_for_follow_up(
            bot,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        LOGGER.info("Blocker follow-up timed out for %s.", founder_name)
        return

    content = message.content.strip()
    if not content or content.lower() == "no":
        return

    match = BLOCKER_RE.match(content)
    if not match:
        await interaction.followup.send(
            "I couldn't parse that blocker. Use `@CEO - description`, `@COO - description`, `@CTO - description`, or `no`.",
            ephemeral=True,
        )
        return

    target_role = match.group("role").upper()
    description = match.group("description").strip()
    await post_blocker(bot, blockers_channel_id, build_blocker_message(founder_name, target_role, description))
    await interaction.followup.send("Blocker posted to the blockers channel.", ephemeral=True)


class LogModal(discord.ui.Modal, title="XC Gradient EOD Log"):
    raw_notes = discord.ui.TextInput(
        label="Raw notes (optional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, bot, notion, reflection, settings) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.notion = notion
        self.reflection = reflection
        self.settings = settings

    async def on_submit(self, interaction: discord.Interaction) -> None:
        founder = FOUNDERS.get(interaction.user.id)
        if founder is None:
            await interaction.response.send_message(
                "Your Discord user ID is not in the FOUNDERS mapping yet.",
                ephemeral=True,
            )
            return

        ctx = current_context()
        founder_name = founder["name"]
        founder_role = founder["role"]
        raw_notes = str(self.raw_notes.value or "").strip()

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            completed_tasks = self.notion.query_completed_tasks(founder_role, ctx.today_iso)
            remaining_tasks = self.notion.query_remaining_tasks(founder_role, ctx.week_code)
            reflection_text = self.reflection.generate_reflection(
                founder_name=founder_name,
                founder_role=founder_role,
                today_iso=ctx.today_iso,
                completed_tasks=self.notion.task_descriptions(completed_tasks),
                raw_notes=raw_notes,
            )
            self.notion.create_daily_log(
                founder_name=founder_name,
                founder_role=founder_role,
                week_code=ctx.week_code,
                today_iso=ctx.today_iso,
                completed_task_ids=self.notion.page_ids(completed_tasks),
                raw_notes=raw_notes,
                reflection_text=reflection_text,
            )

            streak_row = self.notion.get_streak_row(founder_name)
            current_streak, best_streak, last_log_iso = self.notion.streak_values(streak_row)
            new_current, new_best = compute_updated_streak(
                last_log_iso=last_log_iso,
                current_streak=current_streak,
                best_streak=best_streak,
                today=datetime.now(MADRID_TZ).date(),
            )
            self.notion.update_streak_row(
                streak_row["id"],
                current_streak=new_current,
                best_streak=new_best if new_best != best_streak else None,
                last_log_iso=ctx.today_iso,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Log flow failed for %s: %s", founder_name, exc)
            await interaction.followup.send(
                f"I couldn't complete the log flow: {exc}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "✅ Log saved. "
            f"Tasks done today: {len(completed_tasks)}. Remaining this week: {len(remaining_tasks)}.\n\n"
            "Any blockers? Reply with:\n"
            "  @CEO - description\n"
            "  @COO - description\n"
            "  @CTO - description\n"
            "Or type: no",
            ephemeral=True,
        )

        if interaction.channel is not None:
            try:
                await interaction.channel.send(f"✅ {founder_name} logged · 🔥 Streak: {new_current}")
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Failed to post public confirmation: %s", exc)

        try:
            await process_blocker_follow_up(
                self.bot,
                interaction,
                founder_name,
                self.settings.discord_blockers_channel_id,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Blocker follow-up failed for %s: %s", founder_name, exc)
            await interaction.followup.send(
                "Your log was saved, but I couldn't process the blocker follow-up.",
                ephemeral=True,
            )


def register_log_command(bot, tree: app_commands.CommandTree, notion, reflection, settings) -> None:
    @tree.command(name="log", description="Save your XC Gradient end-of-day log.")
    async def log_command(interaction: discord.Interaction) -> None:
        modal = LogModal(bot=bot, notion=notion, reflection=reflection, settings=settings)
        await interaction.response.send_modal(modal)
