from __future__ import annotations

import logging
from datetime import datetime, timedelta

from backend.domain.dates import MADRID_TZ, logical_day_for_madrid


LOGGER = logging.getLogger("xcg_internal.blockers")

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


class LogContext:
    __slots__ = ("today_iso", "week_code", "calendar_date_iso")

    def __init__(self, today_iso: str, week_code: str, calendar_date_iso: str) -> None:
        self.today_iso = today_iso
        self.week_code = week_code
        self.calendar_date_iso = calendar_date_iso


def _effective_log_datetime(now: datetime | None = None) -> datetime:
    current = now or datetime.now(MADRID_TZ)
    if current.tzinfo is None:
        current = MADRID_TZ.localize(current)
    else:
        current = current.astimezone(MADRID_TZ)
    if logical_day_for_madrid(current) != current.date():
        return current - timedelta(days=1)
    return current


def current_context(now: datetime | None = None) -> LogContext:
    actual = now or datetime.now(MADRID_TZ)
    if actual.tzinfo is None:
        actual = MADRID_TZ.localize(actual)
    else:
        actual = actual.astimezone(MADRID_TZ)
    calendar_date_iso = actual.date().isoformat()
    effective_now = _effective_log_datetime(now)
    iso_year, iso_week, _ = effective_now.isocalendar()
    return LogContext(
        today_iso=effective_now.date().isoformat(),
        week_code=f"{iso_year % 100:02d}-W{iso_week:02d}",
        calendar_date_iso=calendar_date_iso,
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


__all__ = [
    "BLOCKER_REWRITE_PROMPT",
    "LogContext",
    "ROLE_TO_SETTING",
    "build_blocker_message",
    "current_context",
    "rewrite_blocker_message",
]
