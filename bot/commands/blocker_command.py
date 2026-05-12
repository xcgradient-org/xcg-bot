from __future__ import annotations

import logging

import discord
from discord import app_commands

from .log_command import build_blocker_message, founder_mapping, post_blocker, rewrite_blocker_message


LOGGER = logging.getLogger("xcg_bot.blocker_command")
TARGET_ROLE_CHOICES = [
    app_commands.Choice(name="CEO", value="CEO"),
    app_commands.Choice(name="CTO", value="CTO"),
    app_commands.Choice(name="COO", value="COO"),
]


class UrgentBlockerModal(discord.ui.Modal, title="Urgent Blocker"):
    blocker_input = discord.ui.TextInput(
        label="Urgent blocker",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
        placeholder="Example: I need the final API schema now to unblock the integration deployment.",
    )

    def __init__(self, bot, reflection, settings, *, founder: dict[str, str], target_role: str) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.reflection = reflection
        self.settings = settings
        self.founder = founder
        self.target_role = target_role

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        raw_blocker = str(self.blocker_input.value or "").strip()
        message = rewrite_blocker_message(
            self.reflection,
            self.founder,
            target_role=self.target_role,
            task_descriptions=[],
            raw_notes="",
            raw_blocker=raw_blocker,
        )

        try:
            await post_blocker(
                self.bot,
                self.settings.discord_blockers_channel_id,
                build_blocker_message(
                    self.founder["name"],
                    self.target_role,
                    message,
                    self.settings,
                    urgent=True,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Urgent blocker failed for %s: %s", self.founder["name"], exc)
            await interaction.followup.send(f"I couldn't send the urgent blocker: {exc}", ephemeral=True)
            return

        await interaction.followup.send(
            f"Urgent blocker sent to {self.target_role}.",
            ephemeral=True,
        )


def register_blocker_command(bot, tree: app_commands.CommandTree, reflection, settings) -> None:
    @tree.command(name="blocker", description="Send an urgent blocker to the blockers channel.")
    @app_commands.describe(target_role="Who should handle the urgent blocker")
    @app_commands.choices(target_role=TARGET_ROLE_CHOICES)
    async def blocker_command(interaction: discord.Interaction, target_role: app_commands.Choice[str]) -> None:
        founder = founder_mapping(settings).get(interaction.user.id)
        if founder is None:
            await interaction.response.send_message(
                "Your Discord user ID is not configured in automation/.env yet.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            UrgentBlockerModal(
                bot,
                reflection,
                settings,
                founder=founder,
                target_role=target_role.value,
            )
        )
