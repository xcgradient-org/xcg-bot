from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import pytz
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notion import NotionService  # noqa: E402
from reflection import ReflectionService  # noqa: E402
from log_command import build_blocker_message, current_context, rewrite_blocker_message  # noqa: E402
from streaks import sync_founder_streak_from_daily_logs  # noqa: E402


LOGGER = logging.getLogger("xcg_bot.internal_htmls")
MADRID_TZ = pytz.timezone("Europe/Madrid")
FOUNDER_BY_ID = {
    "oriol": {"name": "Oriol", "role": "CEO"},
    "arnau": {"name": "Arnau", "role": "CTO"},
    "adam": {"name": "Adam", "role": "COO"},
}
DEFAULT_TEAM_DB_ID = "c7ed3e34702c4d26b310cc7d91b16a97"
DEFAULT_OBJECTIVES_DB_ID = "1e4e9d72f9f5473abd43c1e0ecc53e49"
DEFAULT_KRS_DB_ID = "2b3c5815dd4943bb8c4dff005901fb1d"
DEFAULT_MEETINGS_DB_ID = "e654a7418d7e410c8072db8f7706ca3d"
TASK_PARSE_PROMPT = (
    "You convert a founder's natural-language task request into structured tasks for an internal Notion task database. "
    "Return valid JSON with exactly one key: tasks. "
    "tasks must be an array of objects, each with exactly one key: description. "
    "Each description must be a short, concrete, imperative task sentence. "
    "Split bundled requests into separate tasks when the user clearly asks for multiple tasks. "
    "Do not invent project names, owners, deadlines, IDs, priorities, status, or metadata. "
    "Do not add markdown or commentary."
)
KR_PARSE_PROMPT = (
    "You convert raw key result notes into structured OKR key results. "
    "Return valid JSON with exactly one key: key_results. "
    "key_results must be an array of objects with description, metric, and target string fields. "
    "Do not invent numbers. Leave metric or target blank when unclear. "
    "Do not add markdown or commentary."
)
MEETING_PARSE_PROMPT = (
    "You are a meeting assistant for a B2B SaaS startup. "
    "Given raw meeting details, return valid JSON with these exact keys: "
    "title, date_iso, type, attendees, location, notes_enhanced. "
    "date_iso must be ISO 8601 with timezone offset for Europe/Madrid. "
    "Resolve relative dates using the provided today's date. Default time to 10:00 if no time is provided. "
    "If the date input contains only a time or time range, use today's date and the start time. "
    "For time ranges such as 18-18:30, 18:00-18:30, or 5-5:30pm, set date_iso to the start datetime. "
    "attendees must be an array of strings. Do not add markdown or commentary."
)
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
WEEKDAY_LOOKUP = {day.lower(): index for index, day in enumerate(WEEKDAYS)}
TIME_RE = re.compile(
    r"(?:(?:at)\s+)?(?P<hour>\d{1,2})(?:(?::|h|\.)(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?$",
    re.IGNORECASE,
)
TIME_FIRST_RE = re.compile(
    r"^(?:at\s+)?(?P<hour>\d{1,2})(?:(?::|h|\.)(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?\s+",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"^(?P<before>.*?)(?<!\d)(?P<start_hour>\d{1,2})(?:(?::|h|\.)(?P<start_minute>\d{2}))?\s*"
    r"(?P<start_ampm>am|pm)?\s*(?:-|–|—|\bto\b|\buntil\b)\s*"
    r"(?P<end_hour>\d{1,2})(?:(?::|h|\.)(?P<end_minute>\d{2}))?\s*(?P<end_ampm>am|pm)?(?P<after>.*)$",
    re.IGNORECASE,
)
ROLE_TO_ENV = {
    "CEO": "DISCORD_USER_ID_ORIOL",
    "CTO": "DISCORD_USER_ID_ARNAU",
    "COO": "DISCORD_USER_ID_ADAM",
}


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _clean_line(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    cleaned = re.sub(r"^([\-\*\u2022\u25E6•▪►]+|\d+[\.\)])\s*", "", cleaned).strip()
    return cleaned.strip(" \t\r\n-•,;")


def _finalize_sentence(text: str) -> str:
    cleaned = _clean_line(text)
    if not cleaned:
        return ""
    cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned[-1] in ".!?" else f"{cleaned}."


def _fallback_task_descriptions(text: str) -> list[str]:
    stripped = re.sub(
        r"^\s*(?:add|create)\s+(?:these\s+)?(?:\d+|two|three|four|five)?\s*tasks?\s*:?\s*",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    )
    chunks = [chunk for chunk in re.split(r"[\n;]+", stripped) if chunk.strip()]
    if len(chunks) == 1 and re.search(r"\b(?:2|two)\s+tasks?\b", text, flags=re.IGNORECASE):
        chunks = [chunk for chunk in re.split(r"\s+\band\s+", chunks[0], maxsplit=1, flags=re.IGNORECASE) if chunk.strip()]

    descriptions: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        description = _finalize_sentence(chunk)
        lowered = description.lower()
        if not description or lowered in seen:
            continue
        seen.add(lowered)
        descriptions.append(description)
    return descriptions


def _guess_kr_metric(line: str) -> tuple[str, str]:
    patterns = (
        (r"(\d+(?:[.,]\d+)?)\s*%", "%", lambda m: f"{m.group(1)}%"),
        (r"€\s*(\d[\d.,]*\s*(?:k|m|M|K)?)", "€", lambda m: "€" + m.group(1).replace(" ", "")),
        (r"\$\s*(\d[\d.,]*\s*(?:k|m|M|K)?)", "$", lambda m: "$" + m.group(1).replace(" ", "")),
        (r"\b(\d+)\s+(deals|hires|engineers|customers|users|signups|RFCs|interviews|calls|testimonials|loops)\b", "", lambda m: m.group(1)),
        (r"\bNPS\s*(\d+)\+?", "NPS", lambda m: m.group(1)),
    )
    for pattern, metric, target_fn in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return metric or match.group(2).lower(), target_fn(match)
    return "", ""


def _fallback_key_results(text: str) -> list[dict[str, str]]:
    key_results: list[dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        description = _clean_line(raw_line)
        if not description:
            continue
        metric, target = _guess_kr_metric(description)
        key_results.append({"description": description[0].upper() + description[1:], "metric": metric, "target": target})
    return key_results


def _period_code(period_type: str, quarter: int | str | None, year: int | str | None) -> str:
    year_int = int(year or datetime.now(MADRID_TZ).year)
    if str(period_type or "").lower() == "annual":
        return str(year_int)
    quarter_int = int(quarter or ((datetime.now(MADRID_TZ).month - 1) // 3 + 1))
    return f"{year_int % 100:02d}-Q{quarter_int}"


def _week_parts(week_code: str) -> tuple[int, int]:
    match = re.match(r"^(\d{2})-W(\d{1,2})$", str(week_code or "").strip(), flags=re.IGNORECASE)
    if not match:
        now = datetime.now(MADRID_TZ)
        iso_year, iso_week, _ = now.isocalendar()
        return iso_year, iso_week
    return 2000 + int(match.group(1)), int(match.group(2))


def _month_name() -> str:
    return datetime.now(MADRID_TZ).strftime("%b")


def _normalize_attendees(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value or "").replace("/", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _mode_for_location(location: str) -> str:
    normalized = str(location or "").strip().lower()
    if normalized in {"in person", "in-person"}:
        return "In-person"
    return "Online"


def _normalize_date_iso(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = MADRID_TZ.localize(parsed)
    else:
        parsed = parsed.astimezone(MADRID_TZ)
    return parsed.isoformat()


def _format_datetime_label(date_iso: str) -> str:
    parsed = datetime.fromisoformat(_normalize_date_iso(date_iso))
    return f"{WEEKDAYS[parsed.weekday()]} {parsed.day} {MONTHS[parsed.month - 1]}, {parsed.strftime('%H:%M')}"


def _parse_time_parts(hour_text: str, minute_text: str | None = None, ampm_text: str | None = None) -> tuple[int, int] | None:
    hour = int(hour_text)
    minute = int(minute_text or "0")
    ampm = str(ampm_text or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _time_from_match(match: re.Match[str]) -> tuple[int, int] | None:
    return _parse_time_parts(match.group("hour"), match.group("minute"), match.group("ampm"))


def _try_parse_time_range_datetime(raw_value: str, *, base_now: datetime) -> str | None:
    match = TIME_RANGE_RE.match(raw_value)
    if not match:
        return None
    start_ampm = match.group("start_ampm") or match.group("end_ampm")
    parsed_time = _parse_time_parts(match.group("start_hour"), match.group("start_minute"), start_ampm)
    if parsed_time is None:
        return None
    hour, minute = parsed_time
    before = str(match.group("before") or "").strip()
    after = str(match.group("after") or "").strip()
    start_text = " ".join(part for part in (before, f"{hour:02d}:{minute:02d}", after) if part)
    return _try_parse_relative_datetime(start_text, base_now=base_now)


def _try_parse_relative_datetime(raw_value: str, *, base_now: datetime) -> str | None:
    value = " ".join(str(raw_value or "").strip().lower().split())
    if not value:
        return None

    minute = 0
    hour = 10
    matched_time = TIME_FIRST_RE.match(value)
    if matched_time:
        parsed_time = _time_from_match(matched_time)
        if parsed_time is None:
            return None
        hour, minute = parsed_time
        value = value[matched_time.end():].strip()
    else:
        matched_time = TIME_RE.search(value)
        if matched_time:
            parsed_time = _time_from_match(matched_time)
            if parsed_time is None:
                return None
            hour, minute = parsed_time
            value = value[: matched_time.start()].strip()
            if value.endswith("at"):
                value = value[:-2].strip()

    if value in {"mon", "monday"}:
        value = "monday"
    elif value in {"tue", "tues", "tuesday"}:
        value = "tuesday"
    elif value in {"wed", "wednesday"}:
        value = "wednesday"
    elif value in {"thu", "thur", "thurs", "thursday"}:
        value = "thursday"
    elif value in {"fri", "friday"}:
        value = "friday"
    elif value in {"sat", "saturday"}:
        value = "saturday"
    elif value in {"sun", "sunday"}:
        value = "sunday"

    target_date = None
    if matched_time and not value:
        target_date = base_now.date()
    elif value in {"today", "tod"}:
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
            elif days_ahead == 0 and prefix != "this" and not matched_time:
                days_ahead = 7
            target_date = base_now.date() + timedelta(days=days_ahead)

    if target_date is None:
        return None
    target = MADRID_TZ.localize(datetime(target_date.year, target_date.month, target_date.day, hour, minute))
    if matched_time and target <= base_now and value in set(WEEKDAY_LOOKUP):
        target += timedelta(days=7)
    return target.isoformat()


def _try_parse_user_datetime(raw_value: str, *, default_year: int, base_now: datetime | None = None) -> str | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return _normalize_date_iso(value)
    except Exception:  # noqa: BLE001
        pass
    current = base_now or datetime.now(MADRID_TZ)
    if current.tzinfo is None:
        current = MADRID_TZ.localize(current)
    else:
        current = current.astimezone(MADRID_TZ)

    if time_range := _try_parse_time_range_datetime(value, base_now=current):
        return time_range

    if relative := _try_parse_relative_datetime(value, base_now=current):
        return relative

    patterns_with_year = (
        "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M",
        "%m-%d-%Y %H:%M", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M",
        "%a %b %d %Y %H:%M", "%A %b %d %Y %H:%M",
        "%a %B %d %Y %H:%M", "%A %B %d %Y %H:%M",
    )
    for pattern in patterns_with_year:
        try:
            return MADRID_TZ.localize(datetime.strptime(value, pattern)).isoformat()
        except ValueError:
            continue

    patterns_without_year = ("%m-%d %H:%M", "%m/%d %H:%M", "%d-%m %H:%M", "%d/%m %H:%M")
    for pattern in patterns_without_year:
        try:
            parsed = datetime.strptime(value, pattern).replace(year=default_year)
            return MADRID_TZ.localize(parsed).isoformat()
        except ValueError:
            continue
    return None


def _normalize_meeting_payload(raw_input: dict[str, Any], ai_payload: dict[str, Any] | None) -> dict[str, Any]:
    now = datetime.now(MADRID_TZ)
    payload = ai_payload if isinstance(ai_payload, dict) else {}
    fallback_date = _try_parse_user_datetime(str(raw_input.get("date_input") or ""), default_year=now.year, base_now=now)
    ai_date_raw = str(payload.get("date_iso") or "").strip()
    date_iso = ""
    try:
        date_iso = _normalize_date_iso(ai_date_raw) if ai_date_raw else ""
    except Exception:  # noqa: BLE001
        date_iso = _try_parse_user_datetime(ai_date_raw, default_year=now.year, base_now=now) or ""
    if not date_iso:
        date_iso = fallback_date or MADRID_TZ.localize(datetime(now.year, now.month, now.day, 10, 0)).isoformat()

    title = str(payload.get("title") or raw_input.get("title") or "").strip()
    meeting_type = str(payload.get("type") or raw_input.get("type") or "Other").strip()
    attendees = _normalize_attendees(payload.get("attendees") if payload.get("attendees") else raw_input.get("attendees"))
    location = str(payload.get("location") or raw_input.get("location") or "").strip()
    notes = str(payload.get("notes_enhanced") or raw_input.get("notes") or "").strip()
    meeting_link = str(raw_input.get("meeting_link") or "").strip()
    address = str(raw_input.get("address") or "").strip()
    if not title:
        raise ValueError("Meeting title is required.")
    if not attendees:
        raise ValueError("At least one attendee is required.")
    if not location:
        raise ValueError("Meeting location is required.")
    return {
        "title": title,
        "date_iso": date_iso,
        "date_label": _format_datetime_label(date_iso),
        "type": meeting_type,
        "attendees": attendees,
        "location": location,
        "mode": _mode_for_location(location),
        "notes_enhanced": notes,
        "meeting_link": meeting_link,
        "address": address,
    }


def _resolve_founder(payload: dict[str, Any]) -> dict[str, str]:
    founder_id = str(payload.get("founder") or "").strip().lower()
    founder = dict(FOUNDER_BY_ID.get(founder_id, {}))
    if not founder:
        name = str(payload.get("founder_name") or founder_id).strip().title()
        role = str(payload.get("role") or "").strip().upper()
        if not name or not role:
            raise ValueError("Unknown founder.")
        founder = {"name": name, "role": role}
    role = str(payload.get("role") or founder["role"]).strip().upper()
    founder["role"] = role
    return founder


class InternalNotionApp:
    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")
        self.objectives_db_id = _env("NOTION_OBJECTIVES_DB_ID", "NOTION_OBJECTIVES_DB", default=DEFAULT_OBJECTIVES_DB_ID)
        self.krs_db_id = _env("NOTION_KRS_DB_ID", "NOTION_KRS_DB", default=DEFAULT_KRS_DB_ID)
        self.meetings_db_id = _env("NOTION_MEETINGS_DB_ID", "NOTION_MEETINGS_DB", default=DEFAULT_MEETINGS_DB_ID)
        self.discord_token = _env("DISCORD_TOKEN")
        self.discord_announcements_channel_id = _env("DISCORD_ANNOUNCEMENTS_CHANNEL_ID")
        self.discord_blockers_channel_id = _env("DISCORD_BLOCKERS_CHANNEL_ID")
        self.discord_user_id_oriol = _env("DISCORD_USER_ID_ORIOL")
        self.discord_user_id_arnau = _env("DISCORD_USER_ID_ARNAU")
        self.discord_user_id_adam = _env("DISCORD_USER_ID_ADAM")
        self.notion = NotionService(
            token=_env("NOTION_TOKEN"),
            tasks_db_id=_env("NOTION_TASKS_DB_ID", "NOTION_TASKS_DB"),
            daily_logs_db_id=_env("NOTION_DAILY_LOGS_DB_ID", "NOTION_DAILY_LOGS_DB"),
            team_db_id=_env("NOTION_TEAM_DB_ID", "NOTION_TEAM_DB", default=DEFAULT_TEAM_DB_ID),
            settings_db_id=_env("NOTION_SETTINGS_DB_ID", "NOTION_SETTINGS_DB") or None,
        )
        self.reflection = ReflectionService(
            model=_env("LLM_MODEL", default="openai/gpt-oss-20b"),
            base_url=_env("LLM_BASE_URL", default="https://api.groq.com/openai/v1"),
            api_keys=tuple(
                key.strip()
                for key in (
                    _env("LLM_API_KEY"),
                    _env("LLM_API_KEY_2"),
                    _env("LLM_API_KEY_3"),
                    *_env("LLM_API_KEYS").replace("\n", ",").split(","),
                )
                if key.strip()
            ),
            api_style=_env("LLM_API_STYLE", default="openai"),
        )

    def list_projects(self) -> dict[str, Any]:
        return {"projects": self.notion.list_projects()}

    def week_status(self) -> dict[str, Any]:
        current_week = self.notion.get_current_week_from_settings()
        next_week = self.notion.get_next_week_code(current_week)
        incomplete_tasks = self.notion.find_incomplete_tasks_for_week(current_week)
        carryover_tasks = self.notion.find_carryover_tasks_in_week(next_week)
        return {
            "current_week": current_week,
            "next_week": next_week,
            "incomplete_count": len(incomplete_tasks),
            "carryover_count": len(carryover_tasks),
            "incomplete_tasks": [
                {
                    "id": self.notion.task_display_id(task),
                    "description": self.notion._property_text(task, "Description"),
                }
                for task in incomplete_tasks[:20]
            ],
        }

    def current_week_status(self) -> dict[str, Any]:
        current_week = self.notion.get_current_week_from_settings()
        return {
            "current_week": current_week,
            "next_week": self.notion.get_next_week_code(current_week),
        }

    def run_weekly_rollover(self, payload: dict[str, Any]) -> dict[str, Any]:
        current_week = self.notion.get_current_week_from_settings()
        requested_week = str(payload.get("current_week") or "").strip()
        if requested_week and requested_week != current_week:
            raise RuntimeError(f"Week changed before rollover. Refresh first: current week is now {current_week}.")
        next_week = self.notion.get_next_week_code(current_week)
        tasks_to_move = self.notion.find_incomplete_tasks_for_week(current_week)
        self.notion.rollover_tasks_batch(tasks_to_move, next_week)
        self.notion.set_is_current_week_flags(current_week, next_week)
        self.notion.set_current_week_in_settings(next_week, status="success", count=len(tasks_to_move))
        return {
            "from_week": current_week,
            "to_week": next_week,
            "moved_count": len(tasks_to_move),
            "moved_tasks": [
                {
                    "id": self.notion.task_display_id(task),
                    "description": self.notion._property_text(task, "Description"),
                }
                for task in tasks_to_move[:20]
            ],
        }

    def log_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        ctx = current_context()
        already_logged = self.notion.has_daily_log(founder["name"], ctx.today_iso)
        candidate_tasks, completed_tasks, active_week = self.notion.query_log_tasks(
            founder["role"],
            ctx.today_iso,
            ctx.week_code,
            founder["name"],
        )
        ctx.week_code = active_week
        completed_ids = {task["id"] for task in completed_tasks}
        return {
            "founder": founder,
            "today_iso": ctx.today_iso,
            "week_code": ctx.week_code,
            "already_logged": already_logged,
            "tasks": [
                self._serialize_log_task(task, selected=task["id"] in completed_ids)
                for task in candidate_tasks
            ],
            "completed_count": len(completed_tasks),
        }

    def create_log(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        ctx = current_context()
        if self.notion.has_daily_log(founder["name"], ctx.today_iso):
            raise RuntimeError(f"{founder['name']} already logged for {ctx.today_iso}.")

        candidate_tasks, completed_tasks, active_week = self.notion.query_log_tasks(
            founder["role"],
            ctx.today_iso,
            ctx.week_code,
            founder["name"],
        )
        ctx.week_code = active_week
        selected_task_ids = {str(task_id) for task_id in payload.get("selected_task_ids", [])}
        original_ids = {task["id"] for task in completed_tasks}
        task_by_id = {task["id"]: task for task in candidate_tasks}
        selected_tasks = [task for task in candidate_tasks if task["id"] in selected_task_ids]

        for task in candidate_tasks:
            was_completed = task["id"] in original_ids
            should_be_completed = task["id"] in selected_task_ids
            if was_completed != should_be_completed:
                self.notion.set_task_completion(task, completed=should_be_completed, today_iso=ctx.today_iso)

        missing_ids = selected_task_ids - set(task_by_id)
        if missing_ids:
            LOGGER.warning("Ignoring selected log task IDs outside candidate set: %s", sorted(missing_ids))

        raw_notes = str(payload.get("notes") or "").strip()
        task_descriptions = self.notion.task_descriptions(selected_tasks)
        try:
            reflection_text = self.reflection.generate_reflection(
                founder_name=founder["name"],
                founder_role=founder["role"],
                today_iso=ctx.today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Reflection generation failed; using fallback note: %s", exc)
            reflection_text = self.reflection.build_fallback_reflection(
                founder_name=founder["name"],
                founder_role=founder["role"],
                today_iso=ctx.today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )

        self.notion.create_daily_log(
            founder_name=founder["name"],
            founder_role=founder["role"],
            week_code=ctx.week_code,
            today_iso=ctx.today_iso,
            completed_task_ids=self.notion.page_ids(selected_tasks),
            notes_text=reflection_text,
        )

        streak = None
        if self.notion.streaks_available():
            try:
                streak, _best, _last = sync_founder_streak_from_daily_logs(
                    self.notion,
                    founder["name"],
                    today=datetime.fromisoformat(ctx.today_iso).date(),
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Streak sync failed after web log save for %s: %s", founder["name"], exc)

        remaining_count = None
        try:
            remaining_count = len(self.notion.query_remaining_tasks(founder["role"], ctx.week_code, founder["name"]))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Remaining-task lookup failed after web log save for %s: %s", founder["name"], exc)

        blocker_posted = False
        blocker = payload.get("blocker") if isinstance(payload.get("blocker"), dict) else {}
        blocker_message = str(blocker.get("message") or "").strip()
        blocker_target_role = str(blocker.get("target_role") or "").strip().upper()
        if blocker_message and blocker_target_role:
            final_message = rewrite_blocker_message(
                self.reflection,
                founder,
                target_role=blocker_target_role,
                task_descriptions=task_descriptions,
                raw_notes=raw_notes,
                raw_blocker=blocker_message,
            )
            self._post_discord_message(
                self.discord_blockers_channel_id,
                build_blocker_message(founder["name"], blocker_target_role, final_message, self),
            )
            blocker_posted = True

        return {
            "created": True,
            "today_iso": ctx.today_iso,
            "week_code": ctx.week_code,
            "completed_count": len(selected_tasks),
            "remaining_count": remaining_count,
            "streak": streak,
            "blocker_posted": blocker_posted,
        }

    def _serialize_log_task(self, task: dict[str, Any], *, selected: bool) -> dict[str, Any]:
        return {
            "id": task.get("id"),
            "display_id": self.notion.task_display_id(task),
            "description": self.notion.task_description(task),
            "selected": selected,
        }

    def _post_discord_message(self, channel_id: str, content: str) -> None:
        if not self.discord_token or not channel_id:
            raise RuntimeError("Discord token or channel ID is missing.")
        body = json.dumps({"content": content}).encode("utf-8")
        token = self.discord_token if self.discord_token.lower().startswith("bot ") else f"Bot {self.discord_token}"
        request = Request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            data=body,
            headers={"Authorization": token, "Content-Type": "application/json", "User-Agent": "xcg-internal-tools"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Discord returned HTTP {response.status}.")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord returned HTTP {exc.code}: {detail}") from exc

    def parse_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        descriptions: list[str] = []
        if self.reflection.api_keys:
            try:
                result = self.reflection.generate_json_response(
                    system_prompt=TASK_PARSE_PROMPT,
                    user_prompt=f"Founder request:\n{text.strip()}",
                    max_output_tokens=300,
                )
                raw_tasks = result.get("tasks")
                if isinstance(raw_tasks, list):
                    descriptions = [
                        _finalize_sentence(item.get("description") if isinstance(item, dict) else item)
                        for item in raw_tasks
                    ]
                    descriptions = [description for description in descriptions if description]
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Task parse LLM failed; using fallback parser: %s", exc)
        return {"descriptions": descriptions or _fallback_task_descriptions(text)}

    def preview_task_ids(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        year, week = _week_parts(str(payload.get("week_code") or ""))
        quarter = ((week - 1) // 13) + 1
        ids = self.notion.preview_task_ids(
            project_id=str(payload["project_id"]),
            project_name=str(payload["project_name"]),
            role=founder["role"],
            year=year,
            quarter_name=f"Q{min(quarter, 4)} {year}",
            count=int(payload.get("count") or 0),
        )
        return {"ids": ids}

    def create_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        descriptions = [_finalize_sentence(item) for item in payload.get("descriptions", [])]
        descriptions = [item for item in descriptions if item]
        display_ids = [str(item).strip() for item in payload.get("display_ids", []) if str(item).strip()]
        if len(display_ids) != len(descriptions):
            display_ids = []
        week_code = str(payload["week_code"]).upper()
        is_current_week = False
        try:
            is_current_week = self.notion._week_matches(week_code, self.notion.get_current_week_from_settings())
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not resolve current week for new tasks; leaving Is Current Week false: %s", exc)
        year, week = _week_parts(str(payload.get("week_code") or ""))
        quarter = min(((week - 1) // 13) + 1, 4)
        pages = self.notion.create_tasks_batch(
            project_id=str(payload["project_id"]),
            project_name=str(payload["project_name"]),
            role=founder["role"],
            founder_name=founder["name"],
            descriptions=descriptions,
            year=year,
            quarter_name=f"Q{quarter} {year}",
            month_name=_month_name(),
            week_code=week_code,
            today_iso=datetime.now(MADRID_TZ).date().isoformat(),
            display_ids=display_ids or None,
            is_current_week=is_current_week,
        )
        return {"created": len(pages), "page_ids": [page.get("id") for page in pages]}

    def parse_key_results(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        key_results: list[dict[str, str]] = []
        if self.reflection.api_keys:
            try:
                result = self.reflection.generate_json_response(
                    system_prompt=KR_PARSE_PROMPT,
                    user_prompt=(
                        f"Objective: {payload.get('objective') or ''}\n"
                        f"Raw key result notes:\n{text.strip()}"
                    ),
                    max_output_tokens=500,
                )
                raw_krs = result.get("key_results")
                if isinstance(raw_krs, list):
                    for item in raw_krs:
                        if not isinstance(item, dict):
                            continue
                        description = _clean_line(str(item.get("description") or ""))
                        if description:
                            key_results.append(
                                {
                                    "description": description,
                                    "metric": str(item.get("metric") or "").strip(),
                                    "target": str(item.get("target") or "").strip(),
                                }
                            )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("KR parse LLM failed; using fallback parser: %s", exc)
        return {"key_results": key_results or _fallback_key_results(text)}

    def create_okr(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        period = _period_code(payload.get("period_type", ""), payload.get("quarter"), payload.get("year"))
        project_id = str(payload.get("project_id") or "").strip()
        owner_id = self.notion.lookup_team_member_id(founder["name"])
        objectives = payload.get("objectives") if isinstance(payload.get("objectives"), list) else []

        objective_count = 0
        kr_count = 0
        for objective in objectives:
            if not isinstance(objective, dict):
                continue
            title = str(objective.get("title") or "").strip()
            if not title:
                continue
            objective_page = self._create_objective(title=title, period=period, owner_id=owner_id, founder=founder)
            objective_count += 1
            objective_id = str(objective_page["id"])
            key_results = objective.get("key_results") if isinstance(objective.get("key_results"), list) else []
            for index, key_result in enumerate(key_results, start=1):
                if not isinstance(key_result, dict):
                    continue
                description = str(key_result.get("description") or "").strip()
                if not description:
                    continue
                self._create_key_result(
                    description=description,
                    index=index,
                    period=period,
                    owner_id=owner_id,
                    objective_id=objective_id,
                    project_id=project_id,
                    metric=str(key_result.get("metric") or "").strip(),
                    target=str(key_result.get("target") or "").strip(),
                )
                kr_count += 1
        return {"objectives_created": objective_count, "key_results_created": kr_count}

    def parse_meeting(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_input = {
            "title": payload.get("title"),
            "date_input": payload.get("date_input"),
            "type": payload.get("type"),
            "attendees": payload.get("attendees"),
            "location": payload.get("location"),
            "notes": payload.get("notes"),
            "meeting_link": payload.get("meeting_link"),
            "address": payload.get("address"),
        }
        ai_payload = None
        if self.reflection.api_keys:
            now = datetime.now(MADRID_TZ)
            try:
                ai_payload = self.reflection.generate_json_response(
                    system_prompt=MEETING_PARSE_PROMPT,
                    user_prompt=(
                        f"Today is: {WEEKDAYS[now.weekday()]} {now.date().isoformat()}\n"
                        f"Title: {raw_input['title'] or ''}\n"
                        f"Date: {raw_input['date_input'] or ''}\n"
                        f"Type: {raw_input['type'] or ''}\n"
                        f"Attendees: {raw_input['attendees'] or ''}\n"
                        f"Location: {raw_input['location'] or ''}\n"
                        f"Notes: {str(raw_input['notes'] or '').strip() or 'none'}"
                    ),
                    max_output_tokens=400,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Meeting parse LLM failed; using fallback parser: %s", exc)
        return {"meeting": _normalize_meeting_payload(raw_input, ai_payload)}

    def create_meeting(self, payload: dict[str, Any]) -> dict[str, Any]:
        _resolve_founder(payload)
        meeting = payload.get("meeting")
        if not isinstance(meeting, dict):
            raise ValueError("Meeting payload is required.")
        meeting = _normalize_meeting_payload(
            {
                "title": meeting.get("title"),
                "date_input": meeting.get("date_iso"),
                "type": meeting.get("type"),
                "attendees": meeting.get("attendees"),
                "location": meeting.get("location"),
                "notes": meeting.get("notes_enhanced"),
                "meeting_link": meeting.get("meeting_link"),
                "address": meeting.get("address"),
            },
            {
                "title": meeting.get("title"),
                "date_iso": meeting.get("date_iso"),
                "type": meeting.get("type"),
                "attendees": meeting.get("attendees"),
                "location": meeting.get("location"),
                "notes_enhanced": meeting.get("notes_enhanced"),
            },
        )
        page = self._create_meeting_page(meeting, announced=False)
        announced = False
        announcement_error = ""
        try:
            self._announce_meeting(meeting)
            self._mark_meeting_announced(page)
            announced = True
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Meeting announcement failed: %s", exc)
            announcement_error = str(exc)
        return {
            "created": True,
            "page_id": page.get("id"),
            "announced": announced,
            "announcement_error": announcement_error,
        }

    def _create_meeting_page(self, meeting: dict[str, Any], *, announced: bool) -> dict[str, Any]:
        schema = self.notion._retrieve_schema(self.meetings_db_id)
        properties: dict[str, Any] = {}

        title_name = self.notion._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": meeting["title"]}}]}

        if prop_name := self.notion._existing_property_name(schema, "Date"):
            properties[prop_name] = {"date": {"start": meeting["date_iso"]}}
        if prop := self.notion._get_schema_property(schema, "Type"):
            prop_name = self.notion._property_name(prop, "Type")
            properties[prop_name] = self._text_or_option(prop, meeting["type"])
        if prop := self.notion._get_schema_property(schema, "Attendees"):
            prop_name = self.notion._property_name(prop, "Attendees")
            properties[prop_name] = self._attendees_property(prop, meeting["attendees"])
        if prop := self.notion._get_schema_property(schema, "Mode"):
            prop_name = self.notion._property_name(prop, "Mode")
            properties[prop_name] = self._text_or_option(prop, meeting["mode"])
        if prop := self.notion._get_schema_property(schema, "Meeting link"):
            prop_name = self.notion._property_name(prop, "Meeting link")
            if meeting.get("meeting_link"):
                properties[prop_name] = {"url": meeting["meeting_link"]} if prop.get("type") == "url" else self.notion._build_text_like_property_value(prop, meeting["meeting_link"])
        if prop := self.notion._get_schema_property(schema, "Address", "Location"):
            prop_name = self.notion._property_name(prop, "Address")
            address = meeting.get("address") or meeting.get("location") or ""
            if address:
                properties[prop_name] = self.notion._build_text_like_property_value(prop, address)
        if prop := self.notion._get_schema_property(schema, "Overview", "Notes"):
            prop_name = self.notion._property_name(prop, "Overview")
            if meeting.get("notes_enhanced"):
                properties[prop_name] = self.notion._build_text_like_property_value(prop, meeting["notes_enhanced"])
        if prop_name := self.notion._existing_property_name(schema, "Announced"):
            if schema[prop_name].get("type") == "checkbox":
                properties[prop_name] = {"checkbox": announced}
        if prop_name := self.notion._existing_property_name(schema, "Reminded"):
            if schema[prop_name].get("type") == "checkbox":
                properties[prop_name] = {"checkbox": False}
        if prop := self.notion._get_schema_property(schema, "Status"):
            prop_name = self.notion._property_name(prop, "Status")
            if prop.get("type") in {"select", "status"}:
                properties[prop_name] = self.notion._build_named_option_value(
                    prop,
                    self.notion._resolve_option_name(prop, preferred_values=["Pending", "To Do", "Todo"]),
                )

        return self.notion.client.pages.create(parent=self.notion._build_parent(self.meetings_db_id), properties=properties)

    def _text_or_option(self, prop: dict[str, Any], value: str) -> dict[str, Any]:
        if prop.get("type") in {"select", "status"}:
            return self.notion._build_named_option_value(prop, self.notion._resolve_option_name(prop, preferred_values=[value]))
        return self.notion._build_text_like_property_value(prop, value)

    def _attendees_property(self, prop: dict[str, Any], attendees: list[str]) -> dict[str, Any]:
        prop_type = prop.get("type")
        if prop_type == "relation":
            relations = []
            for attendee in attendees:
                if team_id := self._lookup_attendee_team_id(attendee):
                    relations.append({"id": team_id})
            return {"relation": relations}
        if prop_type == "multi_select":
            return {"multi_select": [{"name": attendee} for attendee in attendees]}
        return self.notion._build_text_like_property_value(prop, ", ".join(attendees))

    def _lookup_attendee_team_id(self, attendee: str) -> str | None:
        normalized = str(attendee or "").strip()
        if not normalized:
            return None
        role = normalized.upper()
        for founder in FOUNDER_BY_ID.values():
            if role == founder["role"]:
                return self.notion.lookup_team_member_id(founder["name"])
        return self.notion.lookup_team_member_id(normalized)

    def _mark_meeting_announced(self, page: dict[str, Any]) -> None:
        prop_name = self.notion._existing_property_name(page.get("properties", {}), "Announced")
        if not prop_name:
            return
        self.notion.client.pages.update(page_id=page["id"], properties={prop_name: {"checkbox": True}})

    def _announce_meeting(self, meeting: dict[str, Any]) -> None:
        if not self.discord_token or not self.discord_announcements_channel_id:
            raise RuntimeError("Discord token or announcements channel ID is missing.")
        mentions = self._meeting_mentions(meeting["attendees"])
        lines = [
            f"{mentions} New meeting scheduled!".strip(),
            "",
            f"{meeting['type']} - {meeting['date_label']}",
            f"Attendees: {', '.join(meeting['attendees'])}",
            f"Location: {meeting['location']}",
        ]
        if meeting.get("meeting_link"):
            lines.append(f"Link: {meeting['meeting_link']}")
        if meeting.get("address"):
            lines.append(f"Address: {meeting['address']}")
        if meeting.get("notes_enhanced"):
            lines.append(f"Overview: {meeting['notes_enhanced']}")
        body = json.dumps({"content": "\n".join(lines)}).encode("utf-8")
        token = self.discord_token if self.discord_token.lower().startswith("bot ") else f"Bot {self.discord_token}"
        request = Request(
            f"https://discord.com/api/v10/channels/{self.discord_announcements_channel_id}/messages",
            data=body,
            headers={"Authorization": token, "Content-Type": "application/json", "User-Agent": "xcg-internal-tools"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Discord returned HTTP {response.status}.")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord returned HTTP {exc.code}: {detail}") from exc

    def _meeting_mentions(self, attendees: list[str]) -> str:
        parts = []
        seen = set()
        for attendee in attendees:
            attendee_text = str(attendee or "").strip()
            env_name = ROLE_TO_ENV.get(attendee_text.upper())
            if not env_name:
                for founder in FOUNDER_BY_ID.values():
                    if attendee_text.lower() == founder["name"].lower():
                        env_name = ROLE_TO_ENV.get(founder["role"])
                        break
            user_id = _env(env_name) if env_name else ""
            if user_id and user_id not in seen:
                seen.add(user_id)
                parts.append(f"<@{user_id}>")
        return " ".join(parts)

    def _create_objective(self, *, title: str, period: str, owner_id: str | None, founder: dict[str, str]) -> dict[str, Any]:
        schema = self.notion._retrieve_schema(self.objectives_db_id)
        properties: dict[str, Any] = {}
        title_name = self.notion._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": title}}]}
        self._set_period(properties, schema, period)
        self._set_owner(properties, schema, owner_id)
        notes_name = self.notion._existing_property_name(schema, "Notes")
        if notes_name:
            properties[notes_name] = {"rich_text": self.notion._rich_text(f"Created from internal OKR Creator for {founder['name']} ({founder['role']}).")}
        return self.notion.client.pages.create(parent=self.notion._build_parent(self.objectives_db_id), properties=properties)

    def _create_key_result(
        self,
        *,
        description: str,
        index: int,
        period: str,
        owner_id: str | None,
        objective_id: str,
        project_id: str,
        metric: str,
        target: str,
    ) -> dict[str, Any]:
        schema = self.notion._retrieve_schema(self.krs_db_id)
        properties: dict[str, Any] = {}
        title_name = self.notion._title_property_name(schema)
        kr_title = description if re.match(r"^kr\s*\d+[:.)-]", description, flags=re.IGNORECASE) else f"KR{index}: {description}"
        properties[title_name] = {"title": [{"type": "text", "text": {"content": kr_title}}]}
        self._set_period(properties, schema, period)
        self._set_owner(properties, schema, owner_id)
        if prop := self.notion._get_schema_property(schema, "Status"):
            prop_name = self.notion._property_name(prop, "Status")
            status_name = self.notion._resolve_option_name(prop, preferred_values=["To Do", "Todo", "Not Started"])
            properties[prop_name] = self.notion._build_named_option_value(prop, status_name)
        if prop := self.notion._get_schema_property(schema, "Objective", "Objectives"):
            prop_name = self.notion._property_name(prop, "Objective")
            properties[prop_name] = {"relation": [{"id": objective_id}]}
        if project_id and (prop := self.notion._get_schema_property(schema, "Projects", "Project")):
            prop_name = self.notion._property_name(prop, "Projects")
            properties[prop_name] = {"relation": [{"id": project_id}]}
        if prop := self.notion._get_schema_property(schema, "Notes"):
            notes = []
            if metric:
                notes.append(f"Metric: {metric}")
            if target:
                notes.append(f"Target: {target}")
            if notes:
                properties[self.notion._property_name(prop, "Notes")] = {"rich_text": self.notion._rich_text(" | ".join(notes))}
        return self.notion.client.pages.create(parent=self.notion._build_parent(self.krs_db_id), properties=properties)

    def _set_period(self, properties: dict[str, Any], schema: dict[str, Any], period: str) -> None:
        if prop := self.notion._get_schema_property(schema, "Period"):
            prop_name = self.notion._property_name(prop, "Period")
            properties[prop_name] = self.notion._build_scalar_property_value(prop, period)

    def _set_owner(self, properties: dict[str, Any], schema: dict[str, Any], owner_id: str | None) -> None:
        owner_name = self.notion._existing_property_name(schema, "Owner", "Founder")
        if owner_name and schema[owner_name].get("type") == "relation" and owner_id:
            properties[owner_name] = {"relation": [{"id": owner_id}]}


class InternalHtmlHandler(BaseHTTPRequestHandler):
    app = InternalNotionApp()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            self._handle_json(lambda: self.app.list_projects())
            return
        if parsed.path == "/api/week":
            self._handle_json(lambda: self.app.week_status())
            return
        if parsed.path == "/api/current-week":
            self._handle_json(lambda: self.app.current_week_status())
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        routes = {
            "/api/parse": self.app.parse_tasks,
            "/api/preview-ids": self.app.preview_task_ids,
            "/api/tasks": self.app.create_tasks,
            "/api/okr/parse-krs": self.app.parse_key_results,
            "/api/okr/push": self.app.create_okr,
            "/api/meetings/parse": self.app.parse_meeting,
            "/api/meetings": self.app.create_meeting,
            "/api/week/rollover": self.app.run_weekly_rollover,
            "/api/log/preview": self.app.log_preview,
            "/api/log": self.app.create_log,
        }
        parsed = urlparse(self.path)
        route_path = parsed.path.rstrip("/") or parsed.path
        handler = routes.get(route_path)
        if handler is None:
            self._json({"error": "Not found"}, status=404)
            return
        payload = self._read_json()
        self._handle_json(lambda: handler(payload))

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def _handle_json(self, callback) -> None:
        try:
            self._json(callback())
        except ValueError as exc:
            LOGGER.info("Bad request: %s", exc)
            self._json({"error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Request failed: %s", exc)
            self._json({"error": str(exc)}, status=500)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object.")
        return payload

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._headers("application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _headers(self, content_type: str | None = None) -> None:
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _serve_static(self, request_path: str) -> None:
        react_root = STATIC_ROOT / "app" / "dist"
        if react_root.exists():
            self._serve_react_static(request_path, react_root)
            return

        rel = unquote(request_path).lstrip("/")
        if not rel:
            self.send_response(302)
            self.send_header("Location", "/task%20creator/")
            self.end_headers()
            return
        path = (STATIC_ROOT / rel).resolve()
        if path.is_dir():
            path = path / "index.html"
        if not str(path).startswith(str(STATIC_ROOT.resolve())) or not path.exists() or not path.is_file():
            self._json({"error": "Not found"}, status=404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._headers(content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_react_static(self, request_path: str, react_root: Path) -> None:
        decoded_path = unquote(request_path)
        legacy_redirects = {
            "/task creator": "/task-creator",
            "/task creator/": "/task-creator",
            "/okr creator": "/okr-creator",
            "/okr creator/": "/okr-creator",
            "/meeting creator": "/meeting-creator",
            "/meeting creator/": "/meeting-creator",
            "/log creator": "/log-creator",
            "/log creator/": "/log-creator",
            "/weekly rollover": "/weekly-rollover",
            "/weekly rollover/": "/weekly-rollover",
        }
        if decoded_path in legacy_redirects:
            self.send_response(302)
            self.send_header("Location", legacy_redirects[decoded_path])
            self.end_headers()
            return

        rel = decoded_path.lstrip("/")
        path = (react_root / rel).resolve() if rel else (react_root / "index.html").resolve()
        if path.is_dir():
            path = path / "index.html"
        if not str(path).startswith(str(react_root.resolve())):
            self._json({"error": "Not found"}, status=404)
            return
        if not path.exists() or not path.is_file():
            index_path = react_root / "index.html"
            if "." not in Path(rel).name and index_path.exists():
                path = index_path
            else:
                self._json({"error": "Not found"}, status=404)
                return

        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._headers(content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    host = os.getenv("INTERNAL_HTMLS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("INTERNAL_HTMLS_PORT", "8012"))
    server = ThreadingHTTPServer((host, port), InternalHtmlHandler)
    print(f"Internal HTMLs server running at http://{host}:{port}/task%20creator/")
    print(f"Home: http://{host}:{port}/")
    print(f"Task Creator: http://{host}:{port}/task-creator")
    print(f"OKR Creator: http://{host}:{port}/okr-creator")
    print(f"Meeting Creator: http://{host}:{port}/meeting-creator")
    print(f"Log Creator: http://{host}:{port}/log-creator")
    server.serve_forever()


if __name__ == "__main__":
    main()
