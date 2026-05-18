from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

import pytz


MADRID_TZ = pytz.timezone("Europe/Madrid")
LOGICAL_DAY_CUTOFF_HOUR = 5
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


def week_parts(week_code: str) -> tuple[int, int]:
    match = re.match(r"^(\d{2})-W(\d{2})$", str(week_code or "").strip(), flags=re.IGNORECASE)
    if not match:
        raise ValueError("Invalid week code. Use YY-WNN, e.g. 26-W05.")
    year = 2000 + int(match.group(1))
    week = int(match.group(2))
    max_week = date(year, 12, 28).isocalendar()[1]
    if week < 1 or week > max_week:
        raise ValueError(f"Invalid ISO week {week:02d} for {year}.")
    return year, week


def month_name() -> str:
    return datetime.now(MADRID_TZ).strftime("%b")


def month_name_for_date(date_iso: str) -> str:
    parsed = datetime.fromisoformat(normalize_date_iso(date_iso))
    return parsed.strftime("%b")


def week_context_for_date(date_iso: str) -> tuple[int, int, str, str]:
    parsed = datetime.fromisoformat(normalize_date_iso(date_iso))
    iso_year, iso_week, _ = parsed.isocalendar()
    quarter = min(((iso_week - 1) // 13) + 1, 4)
    week_code = f"{iso_year % 100:02d}-W{iso_week:02d}"
    return iso_year, iso_week, week_code, f"Q{quarter} {iso_year}"


def normalize_attendees(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value or "").replace("/", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def mode_for_location(location: str) -> str:
    normalized = str(location or "").strip().lower()
    if normalized in {"in person", "in-person"}:
        return "In-person"
    return "Online"


def normalize_date_iso(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = MADRID_TZ.localize(parsed)
    else:
        parsed = parsed.astimezone(MADRID_TZ)
    return parsed.isoformat()


def madrid_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return MADRID_TZ.localize(parsed)
    return parsed.astimezone(MADRID_TZ)


def logical_day_for_madrid(value: str | datetime) -> date:
    if isinstance(value, str):
        raw = value.strip()
        if len(raw) <= 10:
            return date.fromisoformat(raw[:10])
    parsed = madrid_datetime(value)
    if parsed.hour < LOGICAL_DAY_CUTOFF_HOUR:
        parsed -= timedelta(days=1)
    return parsed.date()


def logical_day_iso_for_madrid(value: str | datetime) -> str:
    return logical_day_for_madrid(value).isoformat()


def format_datetime_label(date_iso: str) -> str:
    parsed = datetime.fromisoformat(normalize_date_iso(date_iso))
    return f"{WEEKDAYS[parsed.weekday()]} {parsed.day} {MONTHS[parsed.month - 1]}, {parsed.strftime('%H:%M')}"


def parse_time_parts(hour_text: str, minute_text: str | None = None, ampm_text: str | None = None) -> tuple[int, int] | None:
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


def time_from_match(match: re.Match[str]) -> tuple[int, int] | None:
    return parse_time_parts(match.group("hour"), match.group("minute"), match.group("ampm"))


def try_parse_time_range_datetime(raw_value: str, *, base_now: datetime) -> str | None:
    match = TIME_RANGE_RE.match(raw_value)
    if not match:
        return None
    start_ampm = match.group("start_ampm") or match.group("end_ampm")
    parsed_time = parse_time_parts(match.group("start_hour"), match.group("start_minute"), start_ampm)
    if parsed_time is None:
        return None
    hour, minute = parsed_time
    before = str(match.group("before") or "").strip()
    after = str(match.group("after") or "").strip()
    start_text = " ".join(part for part in (before, f"{hour:02d}:{minute:02d}", after) if part)
    return try_parse_relative_datetime(start_text, base_now=base_now)


def try_parse_relative_datetime(raw_value: str, *, base_now: datetime) -> str | None:
    value = " ".join(str(raw_value or "").strip().lower().split())
    if not value:
        return None

    minute = 0
    hour = 10
    matched_time = TIME_FIRST_RE.match(value)
    if matched_time:
        parsed_time = time_from_match(matched_time)
        if parsed_time is None:
            return None
        hour, minute = parsed_time
        value = value[matched_time.end():].strip()
    else:
        matched_time = TIME_RE.search(value)
        if matched_time:
            parsed_time = time_from_match(matched_time)
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


def try_parse_user_datetime(raw_value: str, *, default_year: int, base_now: datetime | None = None) -> str | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return normalize_date_iso(value)
    except Exception:  # noqa: BLE001
        pass
    current = base_now or datetime.now(MADRID_TZ)
    if current.tzinfo is None:
        current = MADRID_TZ.localize(current)
    else:
        current = current.astimezone(MADRID_TZ)

    if time_range := try_parse_time_range_datetime(value, base_now=current):
        return time_range

    if relative := try_parse_relative_datetime(value, base_now=current):
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


def normalize_meeting_payload(raw_input: dict[str, Any], ai_payload: dict[str, Any] | None) -> dict[str, Any]:
    now = datetime.now(MADRID_TZ)
    payload = ai_payload if isinstance(ai_payload, dict) else {}
    fallback_date = try_parse_user_datetime(str(raw_input.get("date_input") or ""), default_year=now.year, base_now=now)
    ai_date_raw = str(payload.get("date_iso") or "").strip()
    date_iso = ""
    try:
        date_iso = normalize_date_iso(ai_date_raw) if ai_date_raw else ""
    except Exception:  # noqa: BLE001
        date_iso = try_parse_user_datetime(ai_date_raw, default_year=now.year, base_now=now) or ""
    if not date_iso:
        date_iso = fallback_date or MADRID_TZ.localize(datetime(now.year, now.month, now.day, 10, 0)).isoformat()

    title = str(payload.get("title") or raw_input.get("title") or "").strip()
    meeting_type = str(payload.get("type") or raw_input.get("type") or "Other").strip()
    attendees = normalize_attendees(payload.get("attendees") if payload.get("attendees") else raw_input.get("attendees"))
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
        "date_label": format_datetime_label(date_iso),
        "type": meeting_type,
        "attendees": attendees,
        "location": location,
        "mode": mode_for_location(location),
        "notes_enhanced": notes,
        "meeting_link": meeting_link,
        "address": address,
    }
