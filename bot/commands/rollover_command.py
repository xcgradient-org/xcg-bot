from __future__ import annotations

import asyncio
import logging
import re

import re

import discord
from discord import app_commands

from .log_command import founder_mapping


LOGGER = logging.getLogger("xcg_bot.rollover_command")


class _RolloverView(discord.ui.View):
    def __init__(self, notion, from_week: str, to_week: str, carryover_count: int) -> None:
        super().__init__(timeout=120)
        self.notion = notion
        self.from_week = from_week
        self.to_week = to_week

        confirm = discord.ui.Button(label="✅ Confirm rollover", style=discord.ButtonStyle.success)
        confirm.callback = self._confirm
        self.add_item(confirm)

        if carryover_count > 0:
            rollback = discord.ui.Button(
                label=f"↩ Roll back {carryover_count} task(s) to {from_week}",
                style=discord.ButtonStyle.danger,
            )
            rollback.callback = self._rollback
            self.add_item(rollback)

        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _confirm(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            tasks_to_move = await asyncio.to_thread(
                self.notion.find_incomplete_tasks_for_week, self.from_week
            )
            await asyncio.to_thread(self.notion.rollover_tasks_batch, tasks_to_move, self.to_week)
            await asyncio.to_thread(
                self.notion.set_is_current_week_flags, self.from_week, self.to_week
            )
            await asyncio.to_thread(
                self.notion.set_current_week_in_settings,
                self.to_week,
                status="success",
                count=len(tasks_to_move),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Rollover execution failed: %s", exc)
            try:
                await asyncio.to_thread(
                    self.notion.set_current_week_in_settings,
                    self.from_week,
                    status="fail",
                    count=0,
                )
            except Exception:  # noqa: BLE001
                pass
            await interaction.edit_original_response(content=f"❌ Rollover failed: {exc}", view=None)
            return

        lines = [
            "✅ Weekly rollover complete.",
            f"Week advanced: **{self.from_week}** → **{self.to_week}**",
            f"Incomplete tasks carried over: **{len(tasks_to_move)}**",
        ]
        await interaction.edit_original_response(content="\n".join(lines), view=None)

    async def _rollback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            count = await asyncio.to_thread(
                self.notion.rollback_rollover, self.from_week, self.to_week
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Rollback failed: %s", exc)
            await interaction.edit_original_response(content=f"❌ Rollback failed: {exc}", view=None)
            return

        lines = [
            "↩ Rollback complete.",
            f"Moved **{count}** task(s) from **{self.to_week}** back to **{self.from_week}**.",
            "Is Current Week flags and Settings were not touched (already correct).",
        ]
        await interaction.edit_original_response(content="\n".join(lines), view=None)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)


class _RemapConfirmView(discord.ui.View):
    def __init__(self, notion, from_week: str, to_week: str) -> None:
        super().__init__(timeout=120)
        self.notion = notion
        self.from_week = from_week
        self.to_week = to_week

    @discord.ui.button(label="✅ Confirm remap", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True)
        try:
            moved = await asyncio.to_thread(self.notion.remap_tasks_week, self.from_week, self.to_week)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Remap failed: %s", exc)
            await interaction.edit_original_response(content=f"❌ Remap failed: {exc}", view=None)
            return

        await interaction.edit_original_response(
            content=f"✅ Moved **{moved}** task(s) from **{self.from_week}** → **{self.to_week}**.",
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)


def register_rollover_command(tree: app_commands.CommandTree, notion, settings) -> None:
    @tree.command(
        name="rollover",
        description="Roll over incomplete tasks to the next week, or remap tasks between weeks.",
    )
    @app_commands.describe(
        remap_from="Remap mode: move tasks FROM this week (e.g. 26-W21)",
        remap_to="Remap mode: move tasks TO this week (e.g. 26-W19)",
    )
    async def weekly_rollover(
        interaction: discord.Interaction,
        remap_from: str | None = None,
        remap_to: str | None = None,
    ) -> None:
        if founder_mapping(settings).get(interaction.user.id) is None:
            await interaction.response.send_message(
                "Your Discord user ID is not configured.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # --- Remap mode ---
        if remap_from is not None or remap_to is not None:
            if not remap_from or not remap_to:
                await interaction.followup.send(
                    "Provide both `remap_from` and `remap_to` to remap tasks.", ephemeral=True
                )
                return
            remap_from = notion._canonical_week_code(remap_from) or remap_from.strip()  # type: ignore[attr-defined]
            remap_to = notion._canonical_week_code(remap_to) or remap_to.strip()  # type: ignore[attr-defined]
            if not re.match(r"^\d{2}-W\d{1,2}$", remap_from) or not re.match(r"^\d{2}-W\d{1,2}$", remap_to):
                await interaction.followup.send(
                    f"Could not parse week codes: `{remap_from}` / `{remap_to}`. Use formats like `26-W19` or `2026-W19`.",
                    ephemeral=True,
                )
                return

            try:
                count = await asyncio.to_thread(notion.count_tasks_for_week, remap_from)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Remap preview failed: %s", exc)
                await interaction.followup.send(
                    f"❌ Could not load remap preview: {exc}", ephemeral=True
                )
                return

            lines = [
                "**Week remap preview**",
                f"Move **{count}** task(s) from **{remap_from}** → **{remap_to}**",
                "",
                "Moves all tasks (done and incomplete) without touching descriptions or flags.",
                "Confirm to proceed.",
            ]
            await interaction.followup.send(
                "\n".join(lines),
                view=_RemapConfirmView(notion, remap_from, remap_to),
                ephemeral=True,
            )
            return

        # --- Normal rollover mode ---
        try:
            from_week = await asyncio.to_thread(notion.get_current_week_from_settings)
            to_week = await asyncio.to_thread(notion.get_next_week_code, from_week)
            tasks_to_move = await asyncio.to_thread(notion.find_incomplete_tasks_for_week, from_week)
            carryover_tasks = await asyncio.to_thread(notion.find_carryover_tasks_in_week, to_week)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Rollover preview failed: %s", exc)
            await interaction.followup.send(
                f"❌ Could not load rollover preview: {exc}", ephemeral=True
            )
            return

        incomplete_count = len(tasks_to_move)
        carryover_count = len(carryover_tasks)

        lines = ["**Weekly rollover preview**"]
        if carryover_count > 0:
            lines += [
                f"⚠️ **{carryover_count} task(s) in {to_week}** have carryover markers — previous rollover may have been incomplete.",
                "",
            ]

        task_ids = [notion.task_display_id(t) for t in tasks_to_move[:10]]
        lines += [
            f"Current week: **{from_week}** → Next week: **{to_week}**",
            f"Incomplete tasks to carry over: **{incomplete_count}**",
        ]
        if task_ids:
            lines.append("")
            lines.extend(f"• {tid}" for tid in task_ids)
            if incomplete_count > 10:
                lines.append(f"• … and {incomplete_count - 10} more")
        lines += ["", "Choose an action below."]

        await interaction.followup.send(
            "\n".join(lines),
            view=_RolloverView(notion, from_week, to_week, carryover_count),
            ephemeral=True,
        )
