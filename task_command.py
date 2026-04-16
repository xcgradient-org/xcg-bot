from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import discord
from discord import app_commands

from log_command import MADRID_TZ, current_context, founder_mapping


LOGGER = logging.getLogger("xcg_bot.task_command")
MONTH_NAMES = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
TASK_PARSE_PROMPT = (
    "You convert a founder's natural-language task request into structured tasks for an internal Notion task database. "
    "Return valid JSON with exactly one key: tasks. "
    "tasks must be an array of objects, each with exactly one key: description. "
    "Each description must be a short, concrete, imperative task sentence. "
    "Split bundled requests into separate tasks when the user clearly asks for multiple tasks. "
    "Do not invent project names, owners, deadlines, IDs, priorities, status, or metadata. "
    "Do not add markdown or commentary."
)


@dataclass(slots=True)
class _TaskAddState:
    notion: Any
    founder: dict[str, str]
    raw_text: str
    descriptions: list[str]
    projects: list[dict[str, str]]
    year: int
    quarter_name: str
    month_name: str
    week_code: str
    today_iso: str
    selected_project_id: str = ""
    selected_project_name: str = ""
    preview_ids: list[str] = field(default_factory=list)

    def choose_project(self, project_id: str) -> None:
        match = next((project for project in self.projects if project["id"] == project_id), None)
        if match is None:
            raise RuntimeError(f"Unknown project selected: {project_id}")
        self.selected_project_id = match["id"]
        self.selected_project_name = match["name"]
        self.preview_ids = self.notion.preview_task_ids(
            project_id=match["id"],
            project_name=match["name"],
            role=self.founder["role"],
            year=self.year,
            quarter_name=self.quarter_name,
            count=len(self.descriptions),
        )


def _clean_description(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    cleaned = cleaned.strip(" \t\r\n-•,;")
    return cleaned


def _normalize_task_descriptions(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return []
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        return []

    descriptions: list[str] = []
    seen: set[str] = set()
    for item in raw_tasks:
        if isinstance(item, dict):
            description = _clean_description(item.get("description", ""))
        else:
            description = _clean_description(item)
        if not description:
            continue
        lowered = description.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        descriptions.append(description)
    return descriptions


def _strip_task_prefix(text: str) -> str:
    stripped = str(text or "").strip()
    patterns = [
        r"^\s*(?:add|create)\s+(?:these\s+)?\d+\s+tasks?\s*:?\s*",
        r"^\s*(?:add|create)\s+(?:these\s+)?(?:two|three|four|five)\s+tasks?\s*:?\s*",
        r"^\s*(?:add|create)\s+tasks?\s*:?\s*",
    ]
    for pattern in patterns:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
    return stripped.strip()


def _fallback_task_descriptions(text: str) -> list[str]:
    stripped = _strip_task_prefix(text)
    if not stripped:
        return []

    chunks = [chunk.strip() for chunk in re.split(r"[\n;]+", stripped) if chunk.strip()]
    if len(chunks) == 1:
        single = chunks[0]
        if re.search(r"\b(?:2|two)\s+tasks?\b", text, flags=re.IGNORECASE):
            chunks = [part.strip() for part in re.split(r"\s+\band\b\s+", single, maxsplit=1, flags=re.IGNORECASE) if part.strip()]
        elif "," in single:
            chunks = [part.strip() for part in single.split(",") if part.strip()]

    descriptions: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        description = _clean_description(chunk)
        if not description:
            continue
        lowered = description.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        descriptions.append(description)
    return descriptions


def _parse_task_descriptions(reflection, raw_text: str) -> list[str]:
    payload = None
    try:
        payload = reflection.generate_json_response(
            system_prompt=TASK_PARSE_PROMPT,
            user_prompt=f"Founder request:\n{raw_text.strip()}",
            max_output_tokens=300,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Task parsing via LLM failed; falling back to heuristics: %s", exc)

    descriptions = _normalize_task_descriptions(payload)
    if descriptions:
        return descriptions
    return _fallback_task_descriptions(raw_text)


def _build_state(raw_text: str, descriptions: list[str], projects: list[dict[str, str]], founder: dict[str, str]) -> _TaskAddState:
    now = datetime.now(MADRID_TZ)
    ctx = current_context(now)
    quarter_name = f"Q{((now.month - 1) // 3) + 1} {now.year}"
    month_name = MONTH_NAMES[now.month - 1]
    return _TaskAddState(
        notion=None,  # caller fills this in immediately after creation
        founder=founder,
        raw_text=raw_text,
        descriptions=descriptions,
        projects=projects,
        year=now.year,
        quarter_name=quarter_name,
        month_name=month_name,
        week_code=ctx.week_code,
        today_iso=ctx.today_iso,
    )


def _build_message(state: _TaskAddState) -> str:
    lines = [
        f"**Parsed {len(state.descriptions)} task(s)**",
        *(f"• {description}" for description in state.descriptions),
        "",
    ]
    if state.selected_project_name:
        lines.extend(
            [
                f"Project: **{state.selected_project_name}**",
                f"Role: **{state.founder['role']}**",
                f"Quarter: **{state.quarter_name}**",
                "Will create:",
                *(f"• {display_id} — {description}" for display_id, description in zip(state.preview_ids, state.descriptions, strict=False)),
                "",
                "Confirm to write these tasks to Notion.",
            ]
        )
    else:
        lines.append("Choose the project to preview IDs before writing to Notion.")
    return "\n".join(lines)


class _ProjectSelect(discord.ui.Select):
    def __init__(self, state: _TaskAddState, project_chunk: list[dict[str, str]], index: int) -> None:
        self.state = state
        options = [
            discord.SelectOption(
                label=project["name"][:100],
                value=project["id"],
                default=project["id"] == state.selected_project_id,
            )
            for project in project_chunk
        ]
        super().__init__(
            placeholder=f"Projects {index * 25 + 1}-{index * 25 + len(project_chunk)}",
            min_values=1,
            max_values=1,
            options=options,
            row=index,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.state.choose_project(self.values[0])
        await interaction.response.edit_message(
            content=_build_message(self.state),
            view=_TaskProjectPickerView(self.state),
        )


class _ConfirmCreateButton(discord.ui.Button):
    def __init__(self, state: _TaskAddState) -> None:
        super().__init__(
            label="✅ Create tasks",
            style=discord.ButtonStyle.success,
            row=4,
            disabled=not bool(state.selected_project_id),
        )
        self.state = state

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.state.selected_project_id:
            await interaction.response.send_message("Choose a project first.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            self.state.notion.create_tasks_batch(
                project_id=self.state.selected_project_id,
                project_name=self.state.selected_project_name,
                role=self.state.founder["role"],
                descriptions=self.state.descriptions,
                year=self.state.year,
                quarter_name=self.state.quarter_name,
                month_name=self.state.month_name,
                week_code=self.state.week_code,
                today_iso=self.state.today_iso,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Task creation failed for %s: %s", self.state.founder["name"], exc)
            await interaction.edit_original_response(
                content=f"I couldn't create the tasks in Notion: {exc}",
                view=None,
            )
            return

        lines = [
            f"✅ Created {len(self.state.descriptions)} task(s) in **{self.state.selected_project_name}**.",
            *(f"• {display_id} — {description}" for display_id, description in zip(self.state.preview_ids, self.state.descriptions, strict=False)),
        ]
        await interaction.edit_original_response(content="\n".join(lines), view=None)


class _CancelCreateButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Task creation cancelled.", view=None)


class _TaskProjectPickerView(discord.ui.View):
    def __init__(self, state: _TaskAddState) -> None:
        super().__init__(timeout=300)
        self.state = state
        for index, start in enumerate(range(0, len(state.projects), 25)):
            self.add_item(_ProjectSelect(state, state.projects[start : start + 25], index))
        self.add_item(_ConfirmCreateButton(state))
        self.add_item(_CancelCreateButton())


def register_task_command(bot, tree: app_commands.CommandTree, notion, reflection, settings) -> None:
    group = app_commands.Group(name="tasks", description="Create and manage XC Gradient tasks.")

    @group.command(name="add", description="Parse free text into tasks, pick a project, and create them in Notion.")
    @app_commands.describe(text="Describe the tasks to create")
    async def add_tasks(interaction: discord.Interaction, text: str) -> None:
        founder = founder_mapping(settings).get(interaction.user.id)
        if founder is None:
            await interaction.response.send_message(
                "Your Discord user ID is not configured in automation/.env yet.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        descriptions = _parse_task_descriptions(reflection, text)
        if not descriptions:
            await interaction.followup.send(
                "I couldn't extract any task descriptions from that text.",
                ephemeral=True,
            )
            return

        try:
            projects = notion.list_projects()
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Project lookup failed: %s", exc)
            await interaction.followup.send(
                f"I couldn't fetch the project list from Notion: {exc}",
                ephemeral=True,
            )
            return

        if not projects:
            await interaction.followup.send("No projects were found in Notion.", ephemeral=True)
            return

        state = _build_state(text, descriptions, projects, founder)
        state.notion = notion
        await interaction.followup.send(
            _build_message(state),
            view=_TaskProjectPickerView(state),
            ephemeral=True,
        )

    tree.add_command(group)
