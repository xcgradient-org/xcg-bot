from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

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
WEEKDAY_LOOKUP = {day.lower(): index for index, day in enumerate(WEEKDAYS)}
TIME_RE = re.compile(r"(?:(?:at)\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?$", re.IGNORECASE)
SYSTEM_PROMPT = (
    "You are a meeting assistant for a B2B SaaS startup. "
    "Given raw meeting details, return a JSON object with these exact keys: "
    "title (polished, concise), "
    "date_iso (ISO 8601 datetime with timezone offset for Europe/Madrid — parse the date string intelligently, "
    "resolving relative expressions like 'tomorrow', 'friday', 'next monday 10:00', or short formats like "
    "'04-17 10:00' using the provided today's date; default time to 10:00 if not specified), "
    "type, attendees (array of strings), location, "
    "notes_enhanced (1-3 sentences, clean and professional, empty string if no notes provided). "
    "Return only valid JSON, no markdown, no preamble."
)

_ROLE_TO_SETTING = {
    "CEO": "discord_user_id_oriol",
    "CTO": "discord_user_id_arnau",
    "COO": "discord_user_id_adam",
}

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
    app_commands.Choice(name="CEO+CTO", value="CEO, CTO"),
    app_commands.Choice(name="CEO+COO", value="CEO, COO"),
    app_commands.Choice(name="CTO+COO", value="CTO, COO"),
    app_commands.Choice(name="CEO+CTO+COO", value="CEO, CTO, COO"),
]
LOCATION_CHOICES = [
    app_commands.Choice(name="Discord War Room", value="Discord War Room"),
    app_commands.Choice(name="Discord Deep Work", value="Discord Deep Work"),
    app_commands.Choice(name="Google Meet", value="Google Meet"),
    app_commands.Choice(name="In Person", value="In Person"),
    app_commands.Choice(name="Other", value="Other"),
]


def _build_mentions(attendees: list[str], settings) -> str:
    seen: set[str] = set()
    parts = []
    for role in attendees:
        attr = _ROLE_TO_SETTING.get(role.upper())
        if attr and attr not in seen:
            seen.add(attr)
            user_id = getattr(settings, attr, None)
            if user_id:
                parts.append(f"<@{user_id}>")
    return " ".join(parts)


def _title_suggestion(meeting_type: str) -> str:
    now = datetime.now(MADRID_TZ)
    iso_year, iso_week, _ = now.isocalendar()
    week_code = f"{iso_year % 100:02d}-W{iso_week:02d}"
    if meeting_type == "Weekly Sync":
        return f"Weekly Sync · {week_code}"
    if meeting_type == "Client":
        return "Client Meeting"
    if meeting_type == "Investor":
        return "Investor Meeting"
    return "Meeting"


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


def _try_parse_relative_datetime(raw_value: str, *, base_now: datetime) -> str | None:
    value = " ".join(raw_value.strip().lower().split())
    if not value:
        return None

    minute = 0
    hour = 10
    matched_time = TIME_RE.search(value)
    if matched_time:
        hour = int(matched_time.group("hour"))
        minute = int(matched_time.group("minute") or "0")
        value = value[: matched_time.start()].strip()
        if value.endswith("at"):
            value = value[:-2].strip()

    target_date = None
    if value in {"today", "tod"}:
        target_date = base_now.date()
    elif value == "tomorrow":
        target_date = base_now.date() + timedelta(days=1)
    else:
        prefix = ""
        weekday_text = value
        if value.startswith("this "):
            prefix = "this"
            weekday_text = value[5:].strip()
        elif value.startswith("next "):
            prefix = "next"
            weekday_text = value[5:].strip()

        target_weekday = WEEKDAY_LOOKUP.get(weekday_text)
        if target_weekday is not None:
            days_ahead = (target_weekday - base_now.weekday()) % 7
            if prefix == "next":
                days_ahead = 7 if days_ahead == 0 else days_ahead + 7
            elif days_ahead == 0:
                days_ahead = 7
            target_date = base_now.date() + timedelta(days=days_ahead)

    if target_date is None:
        return None

    parsed = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
    return MADRID_TZ.localize(parsed).isoformat()


def _try_parse_user_datetime(raw_value: str, *, default_year: int, base_now: datetime | None = None) -> str | None:
    value = raw_value.strip()
    if not value:
        return None

    current = base_now or datetime.now(MADRID_TZ)
    if current.tzinfo is None:
        current = MADRID_TZ.localize(current)
    else:
        current = current.astimezone(MADRID_TZ)

    relative = _try_parse_relative_datetime(value, base_now=current)
    if relative:
        return relative

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


def _normalize_payload(raw_input: dict, ai_payload: dict | None) -> dict:
    now = datetime.now(MADRID_TZ)
    year = now.year

    if not ai_payload:
        date_iso = _try_parse_user_datetime(raw_input["date_input"], default_year=year, base_now=now) or raw_input["date_input"]
        return {
            "title": raw_input["title"].strip(),
            "date_iso": date_iso,
            "type": raw_input["type"].strip(),
            "attendees": _normalize_attendees(raw_input["attendees"]),
            "location": raw_input["location"].strip(),
            "notes_enhanced": raw_input["notes"].strip(),
        }

    # Use LLM-parsed date_iso; fall back to strptime if invalid
    ai_date_raw = str(ai_payload.get("date_iso") or "").strip()
    if ai_date_raw:
        try:
            date_iso = _normalize_date_iso(ai_date_raw)
        except (ValueError, Exception):  # noqa: BLE001
            date_iso = _try_parse_user_datetime(raw_input["date_input"], default_year=year, base_now=now) or raw_input["date_input"]
    else:
        date_iso = _try_parse_user_datetime(raw_input["date_input"], default_year=year, base_now=now) or raw_input["date_input"]

    ai_attendees = ai_payload.get("attendees")
    if isinstance(ai_attendees, list):
        normalized_attendees = [str(a).strip() for a in ai_attendees if str(a).strip()]
    else:
        normalized_attendees = _normalize_attendees(raw_input["attendees"])

    return {
        "title": str(ai_payload.get("title") or raw_input["title"]).strip(),
        "date_iso": date_iso,
        "type": raw_input["type"].strip(),
        "attendees": normalized_attendees,
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
    lines.extend(["", "Posted in #announcements."])
    return "\n".join(lines)


class MeetingModal(discord.ui.Modal, title="Create Meeting"):
    title_input = discord.ui.TextInput(label="Title", required=True, max_length=200)
    date_input = discord.ui.TextInput(
        label="Date and Time",
        required=True,
        placeholder="e.g. 04-17 10:00 or tomorrow 10:00 or friday 10:00",
        max_length=120,
    )
    notes_input = discord.ui.TextInput(
        label="Notes",
        required=False,
        placeholder="Agenda or context",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(
        self,
        notion,
        reflection,
        settings,
        *,
        meeting_type: str,
        attendees_value: str,
        location: str,
    ) -> None:
        super().__init__(timeout=300)
        self.notion = notion
        self.reflection = reflection
        self.settings = settings
        self.meeting_type = meeting_type
        self.attendees_value = attendees_value
        self.location = location
        self.title_input.default = _title_suggestion(meeting_type)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        now = datetime.now(MADRID_TZ)
        today_iso = now.date().isoformat()
        raw_input = {
            "title": str(self.title_input.value),
            "date_input": str(self.date_input.value),
            "type": self.meeting_type,
            "attendees": self.attendees_value,
            "location": self.location,
            "notes": str(self.notes_input.value or ""),
        }

        ai_payload = None
        try:
            ai_payload = self.reflection.generate_json_response(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=(
                    f"Today is: {WEEKDAYS[now.weekday()]} {today_iso}\n"
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
            mentions = _build_mentions(payload["attendees"], self.settings)
            prefix = f"📅 {mentions} New meeting scheduled!" if mentions else "📅 New meeting scheduled!"
            content = _format_message(prefix, created_page)
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
        location="Meeting location",
    )
    @app_commands.choices(
        meeting_type=TYPE_CHOICES,
        attendees=ATTENDEE_CHOICES,
        location=LOCATION_CHOICES,
    )
    async def meeting_command(
        interaction: discord.Interaction,
        meeting_type: app_commands.Choice[str],
        attendees: app_commands.Choice[str],
        location: app_commands.Choice[str],
    ) -> None:
        await interaction.response.send_modal(
            MeetingModal(
                notion=notion,
                reflection=reflection,
                settings=settings,
                meeting_type=meeting_type.value,
                attendees_value=attendees.value,
                location=location.value,
            )
        )
