from __future__ import annotations

import logging
from datetime import datetime

import discord
import pytz
from discord import app_commands


LOGGER = logging.getLogger("xcg_bot.meeting_command")
MADRID_TZ = pytz.timezone("Europe/Madrid")
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SYSTEM_PROMPT = (
    "You are a meeting assistant for a B2B SaaS startup. Given raw meeting details, "
    "return a JSON object with these exact keys: title, date_iso (ISO 8601 with timezone Europe/Madrid), "
    "type, attendees (array), location, notes_enhanced (1-3 sentences, clean and professional, empty string if no notes provided). "
    "Return only valid JSON, no markdown, no preamble."
)


def _normalize_attendees(value: str) -> list[str]:
    if not value.strip():
        return []
    normalized = value.replace("/", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _fallback_date_iso(raw_value: str) -> str:
    patterns = (
        "%a %b %d %Y %H:%M",
        "%A %b %d %Y %H:%M",
        "%a %B %d %Y %H:%M",
        "%A %B %d %Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
    )
    for pattern in patterns:
        try:
            parsed = datetime.strptime(raw_value.strip(), pattern)
            return MADRID_TZ.localize(parsed).isoformat()
        except ValueError:
            continue
    return raw_value.strip()


def _normalize_payload(raw_input: dict, ai_payload: dict | None) -> dict:
    if not ai_payload:
        return {
            "title": raw_input["title"].strip(),
            "date_iso": _fallback_date_iso(raw_input["date_input"]),
            "type": raw_input["type"].strip(),
            "attendees": _normalize_attendees(raw_input["attendees"]),
            "location": raw_input["location"].strip(),
            "notes_enhanced": raw_input["notes"].strip(),
        }

    attendees = ai_payload.get("attendees")
    normalized_attendees = []
    if isinstance(attendees, list):
        normalized_attendees = [str(item).strip() for item in attendees if str(item).strip()]

    return {
        "title": str(ai_payload.get("title") or raw_input["title"]).strip(),
        "date_iso": str(ai_payload.get("date_iso") or _fallback_date_iso(raw_input["date_input"])).strip(),
        "type": str(ai_payload.get("type") or raw_input["type"]).strip(),
        "attendees": normalized_attendees or _normalize_attendees(raw_input["attendees"]),
        "location": str(ai_payload.get("location") or raw_input["location"]).strip(),
        "notes_enhanced": str(ai_payload.get("notes_enhanced") or "").strip(),
    }


def _format_datetime(date_iso: str) -> str:
    raw = date_iso.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = MADRID_TZ.localize(parsed)
    else:
        parsed = parsed.astimezone(MADRID_TZ)
    return f"{WEEKDAYS[parsed.weekday()]} {parsed.day} {MONTHS[parsed.month - 1]}, {parsed.strftime('%H:%M')}"


def _build_confirmation(payload: dict) -> str:
    lines = [
        "✅ Meeting created and queued for announcement.",
        "",
        f"🗓 {payload['type']} — {_format_datetime(payload['date_iso'])}",
        f"👥 {', '.join(payload['attendees'])}",
        f"📍 {payload['location']}",
    ]
    if payload["notes_enhanced"]:
        lines.append(f"📝 {payload['notes_enhanced']}")
    lines.extend(
        [
            "",
            "The team will be notified in #announcements within 2 minutes.",
        ]
    )
    return "\n".join(lines)


class MeetingModal(discord.ui.Modal, title="Create Meeting"):
    title_input = discord.ui.TextInput(label="Title", required=True, max_length=200)
    date_input = discord.ui.TextInput(
        label="Date and Time",
        required=True,
        placeholder="Mon Apr 14 2026 10:00",
        max_length=120,
    )
    type_input = discord.ui.TextInput(
        label="Type",
        required=True,
        placeholder="Weekly Sync / Client / Investor / Other",
        max_length=120,
    )
    attendees_input = discord.ui.TextInput(
        label="Attendees",
        required=True,
        placeholder="All / CEO / CTO / COO",
        max_length=200,
    )
    location_input = discord.ui.TextInput(
        label="Location",
        required=True,
        placeholder="URL or physical location",
        max_length=250,
    )
    notes_input = discord.ui.TextInput(
        label="Notes",
        required=False,
        placeholder="Agenda or context",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, notion, reflection, settings) -> None:
        super().__init__(timeout=300)
        self.notion = notion
        self.reflection = reflection
        self.settings = settings

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_input = {
            "title": str(self.title_input.value),
            "date_input": str(self.date_input.value),
            "type": str(self.type_input.value),
            "attendees": str(self.attendees_input.value),
            "location": str(self.location_input.value),
            "notes": str(self.notes_input.value or ""),
        }

        await interaction.response.defer(ephemeral=True, thinking=True)

        ai_payload = None
        try:
            ai_payload = self.reflection.generate_json_response(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=(
                    f"Title: {raw_input['title']}\n"
                    f"Date: {raw_input['date_input']}\n"
                    f"Type: {raw_input['type']}\n"
                    f"Attendees: {raw_input['attendees']}\n"
                    f"Location: {raw_input['location']}\n"
                    f"Notes: {raw_input['notes'].strip() or 'none'}"
                ),
                max_output_tokens=400,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Meeting AI enhancement failed; falling back to raw input: %s", exc)

        payload = _normalize_payload(raw_input, ai_payload)

        try:
            self.notion.client.pages.create(
                parent={"database_id": self.settings.notion_meetings_db_id},
                properties={
                    "Title": {"title": [{"type": "text", "text": {"content": payload["title"]}}]},
                    "Date": {"date": {"start": payload["date_iso"]}},
                    "Type": {"select": {"name": payload["type"]}},
                    "Attendees": {"multi_select": [{"name": attendee} for attendee in payload["attendees"]]},
                    "Location": {"rich_text": [{"type": "text", "text": {"content": payload["location"]}}]},
                    "Notes": {"rich_text": [{"type": "text", "text": {"content": payload["notes_enhanced"]}}]} if payload["notes_enhanced"] else {"rich_text": []},
                    "Announced": {"checkbox": False},
                    "Reminded": {"checkbox": False},
                },
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Meeting creation failed: %s", exc)
            await interaction.followup.send(f"I couldn't create the meeting in Notion: {exc}", ephemeral=True)
            return

        await interaction.followup.send(_build_confirmation(payload), ephemeral=True)


def register_meeting_command(tree: app_commands.CommandTree, notion, reflection, settings) -> None:
    @tree.command(name="meeting", description="Create a meeting and queue it for announcement.")
    async def meeting_command(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MeetingModal(notion=notion, reflection=reflection, settings=settings))
