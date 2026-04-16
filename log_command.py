from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import discord
from discord import app_commands

from streaks import MADRID_TZ, compute_updated_streak


LOGGER = logging.getLogger("xcg_bot.log_command")
ROLE_TO_SETTING = {
    "CEO": "discord_user_id_oriol",
    "CTO": "discord_user_id_arnau",
    "COO": "discord_user_id_adam",
}
BLOCKER_REWRITE_PROMPT = (
    "You rewrite a founder's blocker note for an internal Discord blockers channel. "
    "Return valid JSON with exactly one key: message. "
    "message must be one concise, direct sentence addressed to the requested role, preserving the founder's intent and concrete need. "
    "Do not invent details. Do not add markdown. Do not add greetings. "
    "Do not include markdown or extra text."
)


# ---------------------------------------------------------------------------
# Helpers (unchanged)
# ---------------------------------------------------------------------------

class LogContext:
    __slots__ = ("today_iso", "week_code")

    def __init__(self, today_iso: str, week_code: str) -> None:
        self.today_iso = today_iso
        self.week_code = week_code


def _effective_log_datetime(now: datetime | None = None) -> datetime:
    current = now or datetime.now(MADRID_TZ)
    if current.tzinfo is None:
        current = MADRID_TZ.localize(current)
    else:
        current = current.astimezone(MADRID_TZ)
    if current.hour < 5:
        current = current - timedelta(days=1)
    return current


def current_context(now: datetime | None = None) -> LogContext:
    effective_now = _effective_log_datetime(now)
    iso_year, iso_week, _ = effective_now.isocalendar()
    return LogContext(
        today_iso=effective_now.date().isoformat(),
        week_code=f"{iso_year % 100:02d}-W{iso_week:02d}",
    )


def _mention_for_role(settings, target_role: str) -> str:
    attr = ROLE_TO_SETTING.get(target_role.upper())
    if not attr:
        return f"@{target_role.upper()}"
    user_id = getattr(settings, attr, None)
    return f"<@{user_id}>" if user_id else f"@{target_role.upper()}"


def build_blocker_message(founder_name: str, target_role: str, description: str, settings=None, *, urgent: bool = False) -> str:
    mention = _mention_for_role(settings, target_role) if settings is not None else f"@{target_role.upper()}"
    urgency = "URGENT " if urgent else ""
    return f"🚨 {urgency}{mention} blocker from **{founder_name}**: {description}"


def founder_mapping(settings) -> dict[int, dict[str, str]]:
    return {
        settings.discord_user_id_oriol: {"name": "Oriol", "role": "CEO"},
        settings.discord_user_id_arnau: {"name": "Arnau", "role": "CTO"},
        settings.discord_user_id_adam: {"name": "Adam", "role": "COO"},
    }


async def post_blocker(bot, channel_id: int, content: str) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        raise RuntimeError(f"Configured blockers channel is not messageable: {channel_id}")
    await channel.send(content)


# ---------------------------------------------------------------------------
# Shared state object (passed between View → Modal)
# ---------------------------------------------------------------------------

class _LogState:
    __slots__ = ("bot", "notion", "reflection", "settings", "founder", "ctx", "candidate_tasks", "completed_tasks", "selected_task_ids", "blocker_target_role")

    def __init__(
        self,
        bot,
        notion,
        reflection,
        settings,
        *,
        founder: dict[str, str],
        ctx: LogContext,
        candidate_tasks: list[dict[str, Any]],
        completed_tasks: list[dict[str, Any]],
    ) -> None:
        self.bot = bot
        self.notion = notion
        self.reflection = reflection
        self.settings = settings
        self.founder = founder
        self.ctx = ctx
        self.candidate_tasks = candidate_tasks
        self.completed_tasks = completed_tasks
        self.selected_task_ids = {task["id"] for task in completed_tasks}
        self.blocker_target_role = ""


def _selected_task_pages(state: _LogState) -> list[dict[str, Any]]:
    return [task for task in state.candidate_tasks if task["id"] in state.selected_task_ids]


def _format_task_lines(notion, tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "_No tasks selected._"
    return "\n".join(f"• {notion.task_description(task)}" for task in tasks)


def _build_review_message(state: _LogState, *, selecting: bool = False) -> str:
    selected_tasks = _selected_task_pages(state) if selecting else state.completed_tasks
    headline = f"**Today I found {len(state.completed_tasks)} completed task(s):**"
    if selecting:
        headline = f"**Select the tasks that should count as completed today ({len(selected_tasks)} selected):**"
    return f"{headline}\n{_format_task_lines(state.notion, selected_tasks)}"


def rewrite_blocker_message(
    reflection,
    founder: dict[str, str],
    *,
    target_role: str,
    task_descriptions: list[str],
    raw_notes: str,
    raw_blocker: str,
) -> str:
    if not raw_blocker.strip():
        return ""
    try:
        payload = reflection.generate_json_response(
            system_prompt=BLOCKER_REWRITE_PROMPT,
            user_prompt=(
                f"Founder: {founder['name']}\n"
                f"Role: {founder['role']}\n"
                f"Target role: {target_role}\n"
                f"Tasks completed today: {', '.join(task_descriptions) or 'none'}\n"
                f"Daily notes:\n{raw_notes.strip() or 'none'}\n"
                f"Raw blocker message:\n{raw_blocker.strip()}"
            ),
            max_output_tokens=150,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Blocker rewrite failed: %s", exc)
        return raw_blocker.strip()

    message = str(payload.get("message") or "").strip()
    return message or raw_blocker.strip()


def _rewrite_blocker_message(
    state: _LogState,
    task_pages: list[dict[str, Any]],
    *,
    target_role: str,
    raw_notes: str,
    raw_blocker: str,
) -> str:
    return rewrite_blocker_message(
        state.reflection,
        state.founder,
        target_role=target_role,
        task_descriptions=state.notion.task_descriptions(task_pages),
        raw_notes=raw_notes,
        raw_blocker=raw_blocker,
    )


# ---------------------------------------------------------------------------
# Shared post-submit logic
# ---------------------------------------------------------------------------

async def _finalize_log(
    interaction: discord.Interaction,
    state: _LogState,
    task_pages: list[dict[str, Any]],
    raw_notes: str,
    blocker: dict[str, str] | None = None,
) -> None:
    founder_name = state.founder["name"]
    founder_role = state.founder["role"]
    ctx = state.ctx
    original_ids = {task["id"] for task in state.completed_tasks}
    selected_ids = {task["id"] for task in task_pages}

    try:
        for task in state.candidate_tasks:
            was_completed = task["id"] in original_ids
            should_be_completed = task["id"] in selected_ids
            if was_completed == should_be_completed:
                continue
            state.notion.set_task_completion(
                task,
                completed=should_be_completed,
                today_iso=ctx.today_iso,
            )

        remaining_tasks = state.notion.query_remaining_tasks(founder_role, ctx.week_code)
        task_descriptions = state.notion.task_descriptions(task_pages)
        try:
            reflection_text = state.reflection.generate_reflection(
                founder_name=founder_name,
                founder_role=founder_role,
                today_iso=ctx.today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Reflection generation failed; using fallback note: %s", exc)
            reflection_text = state.reflection.build_fallback_reflection(
                founder_name=founder_name,
                founder_role=founder_role,
                today_iso=ctx.today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )
        state.notion.create_daily_log(
            founder_name=founder_name,
            founder_role=founder_role,
            week_code=ctx.week_code,
            today_iso=ctx.today_iso,
            completed_task_ids=state.notion.page_ids(task_pages),
            notes_text=reflection_text,
        )

        streak_row = state.notion.get_streak_row(founder_name)
        current_streak, best_streak, last_log_iso = state.notion.streak_values(streak_row)
        new_current, new_best = compute_updated_streak(
            last_log_iso=last_log_iso,
            current_streak=current_streak,
            best_streak=best_streak,
            today=datetime.fromisoformat(ctx.today_iso).date(),
        )
        state.notion.update_streak_row(
            streak_row["id"],
            current_streak=new_current,
            best_streak=new_best if new_best != best_streak else None,
            last_log_iso=ctx.today_iso,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Log flow failed for %s: %s", founder_name, exc)
        await interaction.followup.send(f"I couldn't complete the log flow: {exc}", ephemeral=True)
        return

    blockers_posted = 0
    if blocker is not None:
        try:
            final_message = _rewrite_blocker_message(
                state,
                task_pages,
                target_role=blocker["target_role"],
                raw_notes=raw_notes,
                raw_blocker=blocker["message"],
            )
            await post_blocker(
                state.bot,
                state.settings.discord_blockers_channel_id,
                build_blocker_message(founder_name, blocker["target_role"], final_message, state.settings),
            )
            blockers_posted = 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to post blocker for %s: %s", founder_name, exc)

    blocker_suffix = f" Blockers posted: {blockers_posted}." if blockers_posted else ""
    await interaction.followup.send(
        "✅ Log saved. "
        f"Tasks done today: {len(task_pages)}. Remaining this week: {len(remaining_tasks)}.{blocker_suffix}",
        ephemeral=True,
    )

    if interaction.channel is not None:
        try:
            await interaction.channel.send(f"✅ {founder_name} logged · 🔥 Streak: {new_current}")
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to post public confirmation: %s", exc)


class NotesModal(discord.ui.Modal, title="EOD Log Notes"):
    notes_input = discord.ui.TextInput(
        label="Notes",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=2000,
        placeholder="Example: Finished the sync. Needed extra work because the schema was inconsistent.",
    )

    def __init__(self, state: _LogState, task_pages: list[dict[str, Any]]) -> None:
        super().__init__(timeout=300)
        self.state = state
        self.task_pages = task_pages

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_notes = str(self.notes_input.value or "").strip()
        blocker_view = BlockerSelectionView(self.state, self.task_pages, raw_notes)
        await interaction.response.send_message(
            content=blocker_view.message_text(),
            view=blocker_view,
            ephemeral=True,
        )


class BlockerRoleSelect(discord.ui.Select):
    def __init__(self, state: _LogState) -> None:
        self.state = state
        options = [
            discord.SelectOption(label=role, value=role, default=role == state.blocker_target_role)
            for role in ("CEO", "CTO", "COO")
        ]
        super().__init__(
            placeholder="Choose who owns the blocker",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.state.blocker_target_role = self.values[0]
        view = self.view
        if isinstance(view, BlockerSelectionView):
            await interaction.response.edit_message(content=view.message_text(), view=view)


class BlockerModal(discord.ui.Modal, title="Blocker Details"):
    blocker_input = discord.ui.TextInput(
        label="What do you need?",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
        placeholder="Example: I need the final API schema to finish the integration today.",
    )

    def __init__(self, state: _LogState, task_pages: list[dict[str, Any]], raw_notes: str) -> None:
        super().__init__(timeout=300)
        self.state = state
        self.task_pages = task_pages
        self.raw_notes = raw_notes

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _finalize_log(
            interaction,
            self.state,
            self.task_pages,
            self.raw_notes,
            blocker={
                "target_role": self.state.blocker_target_role,
                "message": str(self.blocker_input.value or "").strip(),
            },
        )


class BlockerSelectionView(discord.ui.View):
    def __init__(self, state: _LogState, task_pages: list[dict[str, Any]], raw_notes: str) -> None:
        super().__init__(timeout=300)
        self.state = state
        self.task_pages = task_pages
        self.raw_notes = raw_notes
        self.add_item(BlockerRoleSelect(state))

    def message_text(self) -> str:
        if self.state.blocker_target_role:
            return f"Any blocker to send? Selected owner: **{self.state.blocker_target_role}**"
        return "Any blocker to send?"

    @discord.ui.button(label="🚨 Add blocker", style=discord.ButtonStyle.secondary, row=1)
    async def add_blocker(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.state.blocker_target_role:
            await interaction.response.send_message("Choose CEO, CTO, or COO first.", ephemeral=True)
            return
        await interaction.response.send_modal(BlockerModal(self.state, self.task_pages, self.raw_notes))

    @discord.ui.button(label="✅ No blocker", style=discord.ButtonStyle.success, row=1)
    async def skip_blocker(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Saving your log...", view=None)
        await _finalize_log(interaction, self.state, self.task_pages, self.raw_notes, blocker=None)


# ---------------------------------------------------------------------------
# Review view (buttons shown before the modal)
# ---------------------------------------------------------------------------

class TaskReviewView(discord.ui.View):
    def __init__(self, state: _LogState) -> None:
        super().__init__(timeout=120)
        self.state = state

    @discord.ui.button(label="✅ Correct", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(NotesModal(self.state, self.state.completed_tasks))

    @discord.ui.button(label="✏️ Adjust tasks", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=_build_review_message(self.state, selecting=True),
            view=TaskSelectionView(self.state),
        )


class TaskSelect(discord.ui.Select):
    def __init__(self, state: _LogState, task_chunk: list[dict[str, Any]], index: int) -> None:
        self.state = state
        self.task_ids = [task["id"] for task in task_chunk]
        options = []
        for task in task_chunk:
            label = state.notion.task_description(task)[:100]
            display_id = state.notion.task_display_id(task)
            description = display_id[:100] if display_id and display_id != label else None
            options.append(
                discord.SelectOption(
                    label=label,
                    value=task["id"],
                    description=description,
                    default=task["id"] in state.selected_task_ids,
                )
            )
        super().__init__(
            placeholder=f"Tasks {index * 25 + 1}-{index * 25 + len(task_chunk)}",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.state.selected_task_ids.difference_update(self.task_ids)
        self.state.selected_task_ids.update(self.values)
        await interaction.response.edit_message(
            content=_build_review_message(self.state, selecting=True),
            view=TaskSelectionView(self.state),
        )


class TaskSelectionView(discord.ui.View):
    def __init__(self, state: _LogState) -> None:
        super().__init__(timeout=300)
        self.state = state
        for index, start in enumerate(range(0, len(state.candidate_tasks), 25)):
            self.add_item(TaskSelect(state, state.candidate_tasks[start : start + 25], index))

    @discord.ui.button(label="💾 Finish Logging", style=discord.ButtonStyle.success, row=4)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(NotesModal(self.state, _selected_task_pages(self.state)))

    @discord.ui.button(label="↩ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=_build_review_message(self.state),
            view=TaskReviewView(self.state),
        )


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------

def register_log_command(bot, tree: app_commands.CommandTree, notion, reflection, settings) -> None:
    @tree.command(name="log", description="Save your XC Gradient end-of-day log.")
    async def log_command(interaction: discord.Interaction) -> None:
        founder = founder_mapping(settings).get(interaction.user.id)
        if founder is None:
            await interaction.response.send_message(
                "Your Discord user ID is not configured in automation/.env yet.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        ctx = current_context()
        try:
            if notion.has_daily_log(founder["name"], ctx.today_iso):
                await interaction.followup.send(
                    f"You already logged for {ctx.today_iso}. `/log` is limited to once per business day, with the day rolling over at 05:00 Madrid time.",
                    ephemeral=True,
                )
                return
            candidate_tasks, completed_tasks, active_week = notion.query_log_tasks(founder["role"], ctx.today_iso, ctx.week_code)
            ctx.week_code = active_week
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to fetch completed tasks for %s: %s", founder["name"], exc)
            await interaction.followup.send(
                f"I couldn't fetch your tasks from Notion: {exc}",
                ephemeral=True,
            )
            return

        state = _LogState(
            bot, notion, reflection, settings,
            founder=founder,
            ctx=ctx,
            candidate_tasks=candidate_tasks,
            completed_tasks=completed_tasks,
        )

        await interaction.followup.send(
            _build_review_message(state),
            view=TaskReviewView(state),
            ephemeral=True,
        )
