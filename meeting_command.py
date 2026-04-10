from __future__ import annotations

import logging
from datetime import datetime

import discord
import pytz
from discord import app_commands

from meetings import _format_message, _send_announcement


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
DATE_PARSE_SYSTEM_PROMPT = (
    "You parse meeting date strings for a Discord bot. "
    "Return a JSON object with the exact key `date_iso` containing an ISO 8601 datetime in timezone Europe/Madrid. "
    "Preserve the user's intended numeric month, day, and time. "
    "If the year is omitted, assume the provided default year. "
    "If weekday words conflict with the numeric date, trust the numeric date. "
    "Return only valid JSON."
)
TYPE_CHOICES = [
    app_commands.Choice(name="Weekly Sync", value="Weekly Sync"),
    app_commands.Choice(name="Client", value="Client"),
    app_commands.Choice(name="Investor", value="Investor"),
    app_commands.Choice(name="Other", value="Other"),
]
ATTENDEE_CHOICES = [
    app_commands.Choice(name="All", value="CEO, CTO, COO"),
    app_commands.Choice(name="CEO", value="CEO"),
    app_commands.Choice(name="CTO", value="CTO"),
    app_commands.Choice(name="COO", value="COO"),
    app_commands.Choice(name="CEO + CTO", value="CEO, CTO"),
    app_commands.Choice(name="CEO + COO", value="CEO, COO"),
    app_commands.Choice(name="CTO + COO", value="CTO, COO"),
    app_commands.Choice(name="CEO + CTO + COO", value="CEO, CTO, COO"),
]

def _normalize_attendees(value: str) -> list[str]:
    if not value.strip():
        return []
    normalized = value.replace("/", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _normalize_date_iso(value: str) -> str:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = MADRID_TZ.localize(parsed)
    else:
        parsed = parsed.astimezone(MADRID_TZ)
    return parsed.isoformat()


def _try_parse_user_datetime(raw_value: str, *, default_year: int) -> str | None:
    value = raw_value.strip()
    if not value:
        return None

    patterns_with_year = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y/%m/%d %H:%M",
        "%m-%d-%Y %H:%M",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%a %b %d %Y %H:%M",
        "%A %b %d %Y %H:%M",
        "%a %B %d %Y %H:%M",
        "%A %B %d %Y %H:%M",
    )
    for pattern in patterns_with_year:
        try:
            parsed = datetime.strptime(value, pattern)
            return MADRID_TZ.localize(parsed).isoformat()
        except ValueError:
            continue

    patterns_without_year = (
        "%m-%d %H:%M",
        "%m/%d %H:%M",
    )
    for pattern in patterns_without_year:
        try:
            parsed = datetime.strptime(value, pattern).replace(year=default_year)
            return MADRID_TZ.localize(parsed).isoformat()
        except ValueError:
            continue

    return None


def _parse_user_datetime(raw_value: str, *, reflection=None, default_year: int | None = None) -> str:
    year = default_year or datetime.now(MADRID_TZ).year
    parsed = _try_parse_user_datetime(raw_value, default_year=year)
    if parsed:
        return parsed

    if reflection is not None:
        payload = reflection.generate_json_response(
            system_prompt=DATE_PARSE_SYSTEM_PROMPT,
            user_prompt=(
                f"Default year: {year}\n"
                f"Input: {raw_value.strip()}"
            ),
            max_output_tokens=120,
        )
        date_iso = str(payload.get("date_iso") or "").strip()
        if date_iso:
            try:
                return _normalize_date_iso(date_iso)
            except ValueError:
                pass

    raise ValueError(
        "I couldn't parse that date. Try `2026-04-17 11:00` or `04-17 11:00` in Europe/Madrid."
    )


def _normalize_payload(raw_input: dict, ai_payload: dict | None) -> dict:
    if not ai_payload:
        return {
            "title": raw_input["title"].strip(),
            "date_iso": raw_input["date_iso"].strip(),
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
        "date_iso": raw_input["date_iso"].strip(),
        "type": raw_input["type"].strip(),
        "attendees": _normalize_attendees(raw_input["attendees"]),
        "location": raw_input["location"].strip(),
        "notes_enhanced": str(ai_payload.get("notes_enhanced") or "").strip(),
    }


def _format_datetime(date_iso: str) -> str:
    parsed = datetime.fromisoformat(_normalize_date_iso(date_iso))
    return f"{WEEKDAYS[parsed.weekday()]} {parsed.day} {MONTHS[parsed.month - 1]}, {parsed.strftime('%H:%M')}"


def _build_confirmation(payload: dict) -> str:
    lines = [
        "✅ Meeting created and announced.",
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
            "Posted in #announcements.",
        ]
    )
    return "\n".join(lines)


class MeetingModal(discord.ui.Modal, title="Create Meeting"):
    title_input = discord.ui.TextInput(label="Title", required=True, max_length=200)
    date_input = discord.ui.TextInput(
        label="Date and Time",
        required=True,
        placeholder="2026-04-17 11:00",
        max_length=120,
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

    def __init__(self, notion, reflection, settings, *, meeting_type: str, attendees_value: str) -> None:
        super().__init__(timeout=300)
        self.notion = notion
        self.reflection = reflection
        self.settings = settings
        self.meeting_type = meeting_type
        self.attendees_value = attendees_value

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            date_iso = _parse_user_datetime(
                str(self.date_input.value),
                reflection=self.reflection,
                default_year=datetime.now(MADRID_TZ).year,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Meeting date parsing failed: %s", exc)
            await interaction.followup.send(
                "I couldn't parse that date. Try `2026-04-17 11:00` or `04-17 11:00`.",
                ephemeral=True,
            )
            return

        raw_input = {
            "title": str(self.title_input.value),
            "date_input": str(self.date_input.value),
            "date_iso": date_iso,
            "type": self.meeting_type,
            "attendees": self.attendees_value,
            "location": str(self.location_input.value),
            "notes": str(self.notes_input.value or ""),
        }

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
            parent = {"database_id": self.settings.notion_meetings_db_id}
            if hasattr(self.notion.client, "data_sources"):
                parent = {"data_source_id": self.notion.primary_data_source_id(self.settings.notion_meetings_db_id)}
            created_page = self.notion.client.pages.create(
                parent=parent,
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

        try:
            content = _format_message("📅 @everyone New meeting scheduled!", created_page)
            await _send_announcement(interaction.client, self.settings.discord_announcements_channel_id, content)
            self.notion.client.pages.update(
                page_id=created_page["id"],
                properties={"Announced": {"checkbox": True}},
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Immediate meeting announcement failed: %s", exc)
            await interaction.followup.send(
                "Meeting saved in Notion, but I couldn't post it to #announcements right now. "
                "The poller will pick it up later.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(_build_confirmation(payload), ephemeral=True)


def register_meeting_command(tree: app_commands.CommandTree, notion, reflection, settings) -> None:
    @tree.command(name="meeting", description="Create a meeting and queue it for announcement.")
    @app_commands.describe(
        meeting_type="Meeting type",
        attendees="Who should attend",
    )
    @app_commands.choices(
        meeting_type=TYPE_CHOICES,
        attendees=ATTENDEE_CHOICES,
    )
    async def meeting_command(
        interaction: discord.Interaction,
        meeting_type: app_commands.Choice[str],
        attendees: app_commands.Choice[str],
    ) -> None:
        await interaction.response.send_modal(
            MeetingModal(
                notion=notion,
                reflection=reflection,
                settings=settings,
                meeting_type=meeting_type.value,
                attendees_value=attendees.value,
            )
        )
