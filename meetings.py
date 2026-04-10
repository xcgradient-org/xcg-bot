from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import discord
import pytz


LOGGER = logging.getLogger("xcg_bot.meetings")
MADRID_TZ = pytz.timezone("Europe/Madrid")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
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


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return MADRID_TZ.localize(parsed)
    return parsed.astimezone(MADRID_TZ)


def _property(page: dict[str, Any], name: str) -> dict[str, Any]:
    return page.get("properties", {}).get(name, {})


def _checkbox(page: dict[str, Any], name: str) -> bool:
    prop = _property(page, name)
    return bool(prop.get("checkbox"))


def _date(page: dict[str, Any], name: str) -> str:
    prop = _property(page, name)
    return ((prop.get("date") or {}).get("start") or "").strip()


def _text(page: dict[str, Any], name: str) -> str:
    prop = _property(page, name)
    prop_type = prop.get("type")

    if prop_type == "title":
        return "".join(item.get("plain_text", "") for item in prop.get("title", [])).strip()
    if prop_type == "rich_text":
        return "".join(item.get("plain_text", "") for item in prop.get("rich_text", [])).strip()
    if prop_type == "select":
        return (prop.get("select") or {}).get("name", "").strip()
    if prop_type == "status":
        return (prop.get("status") or {}).get("name", "").strip()
    if prop_type == "multi_select":
        return ", ".join(item.get("name", "").strip() for item in prop.get("multi_select", []) if item.get("name"))
    if prop_type == "people":
        return ", ".join(item.get("name", "").strip() for item in prop.get("people", []) if item.get("name"))
    return ""


def _meeting_datetime(page: dict[str, Any]) -> datetime | None:
    return _parse_iso_datetime(_date(page, "Date"))


def _attendees(page: dict[str, Any]) -> str:
    for field in ("Attendees", "People", "Founder", "Owners"):
        value = _text(page, field)
        if value:
            return value
    return "TBD"


def _location(page: dict[str, Any]) -> str:
    for field in ("Location", "Place"):
        value = _text(page, field)
        if value:
            return value
    return "TBD"


def _notes(page: dict[str, Any]) -> str:
    for field in ("Notes", "Description", "Context"):
        value = _text(page, field)
        if value:
            return value
    return ""


def _meeting_type(page: dict[str, Any]) -> str:
    for field in ("Type", "Title", "Name"):
        value = _text(page, field)
        if value:
            return value
    return "Meeting"


def _format_datetime(dt: datetime) -> str:
    weekday = WEEKDAYS[dt.weekday()]
    month = MONTHS[dt.month - 1]
    return f"{weekday} {dt.day} {month}, {dt.strftime('%H:%M')}"


def _format_message(prefix: str, page: dict[str, Any]) -> str:
    dt = _meeting_datetime(page)
    when_text = _format_datetime(dt) if dt is not None else "Date TBD"
    meeting_type = _meeting_type(page)
    attendees = _attendees(page)
    location = _location(page)
    notes = _notes(page)

    lines = [
        prefix,
        "",
        f"🗓 {meeting_type} — {when_text}",
        f"👥 {attendees}",
        f"📍 {location}",
    ]
    if notes:
        lines.append(f"📝 {notes}")
    return "\n".join(lines)


async def _send_announcement(bot: discord.Client, channel_id: int, content: str) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        raise RuntimeError(f"Announcements channel is not messageable: {channel_id}")
    await channel.send(content)


async def _poll_new_meetings(bot: discord.Client, notion, meetings_db_id: str, announcements_channel_id: int) -> None:
    while True:
        try:
            meetings = notion._query_all(meetings_db_id)  # Reuse the existing NotionService client/session.
            pending = [meeting for meeting in meetings if not _checkbox(meeting, "Announced")]
            for meeting in pending:
                content = _format_message("📅 @everyone New meeting scheduled!", meeting)
                await _send_announcement(bot, announcements_channel_id, content)
                try:
                    notion.client.pages.update(
                        page_id=meeting["id"],
                        properties={"Announced": {"checkbox": True}},
                    )
                    LOGGER.info("Announced meeting %s", meeting["id"])
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Failed to mark meeting %s as announced: %s", meeting["id"], exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("New meeting poller failed: %s", exc)

        await asyncio.sleep(120)


async def _poll_meeting_reminders(bot: discord.Client, notion, meetings_db_id: str, announcements_channel_id: int) -> None:
    while True:
        try:
            now = datetime.now(MADRID_TZ)
            window_end = now + timedelta(hours=25)
            meetings = notion._query_all(meetings_db_id)  # Reuse the existing NotionService client/session.
            candidates = []
            for meeting in meetings:
                if _checkbox(meeting, "Reminded"):
                    continue
                meeting_dt = _meeting_datetime(meeting)
                if meeting_dt is None:
                    continue
                if now <= meeting_dt <= window_end:
                    candidates.append(meeting)

            for meeting in candidates:
                content = _format_message("⏰ @everyone Reminder — meeting tomorrow!", meeting)
                await _send_announcement(bot, announcements_channel_id, content)
                try:
                    notion.client.pages.update(
                        page_id=meeting["id"],
                        properties={"Reminded": {"checkbox": True}},
                    )
                    LOGGER.info("Sent reminder for meeting %s", meeting["id"])
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Failed to mark meeting %s as reminded: %s", meeting["id"], exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Meeting reminder poller failed: %s", exc)

        await asyncio.sleep(1800)


def start_new_meeting_poller(bot: discord.Client, notion, meetings_db_id: str, announcements_channel_id: int):
    return bot.loop.create_task(_poll_new_meetings(bot, notion, meetings_db_id, announcements_channel_id))


def start_meeting_reminder_poller(bot: discord.Client, notion, meetings_db_id: str, announcements_channel_id: int):
    return bot.loop.create_task(_poll_meeting_reminders(bot, notion, meetings_db_id, announcements_channel_id))
