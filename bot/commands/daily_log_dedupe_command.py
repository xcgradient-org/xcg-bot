from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import discord
from discord import app_commands

from backend.services.daily_log_dedupe import DailyLogDedupeService


LOGGER = logging.getLogger("xcg_bot.daily_log_dedupe_command")


def _is_admin(interaction: discord.Interaction) -> bool:
    permissions = getattr(getattr(interaction, "user", None), "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))


def _format_result(result: dict[str, object]) -> str:
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    mode = str(result.get("mode") or "preview")
    if not groups:
        return f"No duplicate Daily Log groups found for `{result.get('from_day') or 'start'}` → `{result.get('to_day') or 'end'}`."

    lines = [f"Duplicate Daily Logs: **{len(groups)}** group(s) found."]
    if result.get("founder"):
        lines.append(f"Founder filter: **{result['founder']}**")
    if result.get("from_day") or result.get("to_day"):
        lines.append(f"Range: **{result.get('from_day') or '...'}** → **{result.get('to_day') or '...'}**")
    lines.append("")

    for group in groups[:10]:
        if not isinstance(group, dict):
            continue
        lines.append(
            f"• **{group.get('founder_name')} · {group.get('logical_day')}**: {group.get('count')} rows, keeper `{group.get('keeper_id')}`"
        )
        if mode == "apply":
            archived_ids = group.get("archived_ids") if isinstance(group.get("archived_ids"), list) else []
            lines.append(
                f"  archived {len(archived_ids)} duplicate(s), merged {group.get('merged_task_count')} task relation(s)"
            )

    if len(groups) > 10:
        lines.append(f"... and {len(groups) - 10} more group(s).")

    synced = result.get("synced_founders") if isinstance(result.get("synced_founders"), list) else []
    if synced:
        founder_names = ", ".join(str(item.get("founder_name")) for item in synced if isinstance(item, dict))
        lines.append("")
        lines.append(f"Streaks resynced: {founder_names}")
    return "\n".join(lines)


def register_daily_log_dedupe_command(bot, tree: app_commands.CommandTree, notion, settings) -> None:
    service = DailyLogDedupeService(SimpleNamespace(notion=notion))
    group = app_commands.Group(
        name="daily-log-dedupe",
        description="Preview or merge duplicate Daily Log rows.",
    )

    @group.command(name="preview", description="Preview duplicate Daily Log groups.")
    @app_commands.describe(
        founder="Optional founder filter, e.g. Adam or COO",
        from_day="Optional inclusive start day in YYYY-MM-DD",
        to_day="Optional inclusive end day in YYYY-MM-DD",
    )
    async def preview(
        interaction: discord.Interaction,
        founder: str | None = None,
        from_day: str | None = None,
        to_day: str | None = None,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("Administrator access is required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await asyncio.to_thread(
                service.preview,
                founder=founder,
                from_day=from_day,
                to_day=to_day,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Daily log dedupe preview failed: %s", exc)
            await interaction.followup.send(f"❌ Preview failed: {exc}", ephemeral=True)
            return
        await interaction.followup.send(_format_result(result), ephemeral=True)

    @group.command(name="apply", description="Merge duplicate Daily Log groups and archive losers.")
    @app_commands.describe(
        founder="Optional founder filter, e.g. Adam or COO",
        from_day="Optional inclusive start day in YYYY-MM-DD",
        to_day="Optional inclusive end day in YYYY-MM-DD",
    )
    async def apply(
        interaction: discord.Interaction,
        founder: str | None = None,
        from_day: str | None = None,
        to_day: str | None = None,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("Administrator access is required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await asyncio.to_thread(
                service.apply,
                founder=founder,
                from_day=from_day,
                to_day=to_day,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Daily log dedupe apply failed: %s", exc)
            await interaction.followup.send(f"❌ Apply failed: {exc}", ephemeral=True)
            return
        await interaction.followup.send(_format_result(result), ephemeral=True)

    tree.add_command(group)
