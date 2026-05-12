from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.domain.dates import (
    MADRID_TZ,
    MONTHS,
    TIME_FIRST_RE,
    TIME_RANGE_RE,
    TIME_RE,
    WEEKDAYS,
    WEEKDAY_LOOKUP,
    format_datetime_label,
    mode_for_location,
    month_name,
    month_name_for_date,
    normalize_attendees,
    normalize_date_iso,
    normalize_meeting_payload,
    parse_time_parts,
    time_from_match,
    try_parse_relative_datetime,
    try_parse_time_range_datetime,
    try_parse_user_datetime,
    week_context_for_date,
    week_parts,
)
from backend.domain.founders import FOUNDER_BY_ID, ROLE_TO_ENV, founder_for_attendee, resolve_founder
from backend.domain.prompts import KR_PARSE_PROMPT, MEETING_PARSE_PROMPT, TASK_PARSE_PROMPT
from backend.domain.text import clean_line, fallback_key_results, fallback_task_descriptions, finalize_sentence, guess_kr_metric
from backend.services.logs import LogsService
from backend.services.meetings import MeetingsService
from backend.services.okrs import OKRsService, period_code
from backend.services.projects import ProjectsService
from backend.services.runtime import (
    DEFAULT_KRS_DB_ID,
    DEFAULT_MEETINGS_DB_ID,
    DEFAULT_OBJECTIVES_DB_ID,
    DEFAULT_TEAM_DB_ID,
    InternalRuntime,
    LOGGER,
    build_runtime,
    env,
)
from backend.services.tasks import TasksService
from backend.services.week import WeekService


ROOT = Path(__file__).resolve().parents[2]

_env = env

_clean_line = clean_line
_finalize_sentence = finalize_sentence
_fallback_task_descriptions = fallback_task_descriptions
_guess_kr_metric = guess_kr_metric
_fallback_key_results = fallback_key_results
_period_code = period_code
_week_parts = week_parts
_month_name = month_name
_month_name_for_date = month_name_for_date
_week_context_for_date = week_context_for_date
_normalize_attendees = normalize_attendees
_mode_for_location = mode_for_location
_normalize_date_iso = normalize_date_iso
_format_datetime_label = format_datetime_label
_parse_time_parts = parse_time_parts
_time_from_match = time_from_match
_try_parse_time_range_datetime = try_parse_time_range_datetime
_try_parse_relative_datetime = try_parse_relative_datetime
_try_parse_user_datetime = try_parse_user_datetime
_normalize_meeting_payload = normalize_meeting_payload
_resolve_founder = resolve_founder
_founder_for_attendee = founder_for_attendee


def _missing_post_discord_message(channel_id: str, content: str) -> None:
    raise RuntimeError("Discord token or channel ID is missing.")


class InternalNotionApp:
    def __init__(self, runtime: InternalRuntime | None = None) -> None:
        self._bind_runtime(runtime or build_runtime())

    def _bind_runtime(self, runtime: InternalRuntime) -> None:
        self._runtime = runtime
        self.notion = runtime.notion
        self.reflection = runtime.reflection
        self.objectives_db_id = runtime.objectives_db_id
        self.krs_db_id = runtime.krs_db_id
        self.meetings_db_id = runtime.meetings_db_id
        self.meeting_task_project_id = runtime.meeting_task_project_id
        self.meeting_task_project_name = runtime.meeting_task_project_name
        self.discord_token = runtime.discord_token
        self.discord_announcements_channel_id = runtime.discord_announcements_channel_id
        self.discord_blockers_channel_id = runtime.discord_blockers_channel_id
        self.discord_user_id_oriol = runtime.discord_user_id_oriol
        self.discord_user_id_arnau = runtime.discord_user_id_arnau
        self.discord_user_id_adam = runtime.discord_user_id_adam
        self._refresh_services()

    def _refresh_services(self) -> None:
        runtime = self._compat_runtime()
        self._projects = ProjectsService(runtime)
        self._week = WeekService(runtime)
        self._tasks = TasksService(runtime)
        self._logs = LogsService(runtime)
        self._okrs = OKRsService(runtime)
        self._meetings = MeetingsService(runtime)

    def _compat_runtime(self):
        runtime = getattr(self, "_runtime", None)
        reflection = getattr(self, "reflection", None) or (runtime.reflection if runtime else None)
        if reflection is None:
            reflection = SimpleNamespace(api_keys=())

        def post_discord_message(channel_id: str, content: str) -> None:
            if runtime is not None:
                return runtime.post_discord_message(channel_id, content)
            return _missing_post_discord_message(channel_id, content)

        return SimpleNamespace(
            notion=getattr(self, "notion", None) or (runtime.notion if runtime else None),
            reflection=reflection,
            objectives_db_id=getattr(self, "objectives_db_id", "") or (runtime.objectives_db_id if runtime else DEFAULT_OBJECTIVES_DB_ID),
            krs_db_id=getattr(self, "krs_db_id", "") or (runtime.krs_db_id if runtime else DEFAULT_KRS_DB_ID),
            meetings_db_id=getattr(self, "meetings_db_id", "") or (runtime.meetings_db_id if runtime else DEFAULT_MEETINGS_DB_ID),
            meeting_task_project_id=getattr(self, "meeting_task_project_id", "") or (runtime.meeting_task_project_id if runtime else ""),
            meeting_task_project_name=getattr(self, "meeting_task_project_name", "") or (runtime.meeting_task_project_name if runtime else "ALPHA"),
            discord_token=getattr(self, "discord_token", "") or (runtime.discord_token if runtime else ""),
            discord_announcements_channel_id=getattr(self, "discord_announcements_channel_id", "") or (runtime.discord_announcements_channel_id if runtime else ""),
            discord_blockers_channel_id=getattr(self, "discord_blockers_channel_id", "") or (runtime.discord_blockers_channel_id if runtime else ""),
            discord_user_id_oriol=getattr(self, "discord_user_id_oriol", "") or (runtime.discord_user_id_oriol if runtime else ""),
            discord_user_id_arnau=getattr(self, "discord_user_id_arnau", "") or (runtime.discord_user_id_arnau if runtime else ""),
            discord_user_id_adam=getattr(self, "discord_user_id_adam", "") or (runtime.discord_user_id_adam if runtime else ""),
            post_discord_message=post_discord_message,
        )

    def _service(self, factory):
        return factory(self._compat_runtime())

    def list_projects(self) -> dict[str, list[dict[str, str]]]:
        return self._service(ProjectsService).list_projects()

    def week_status(self) -> dict[str, object]:
        return self._service(WeekService).week_status()

    def current_week_status(self) -> dict[str, str]:
        return self._service(WeekService).current_week_status()

    def run_weekly_rollover(self, payload: dict[str, str]) -> dict[str, object]:
        return self._service(WeekService).run_weekly_rollover(payload)

    def parse_tasks(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        return self._service(TasksService).parse_tasks(payload)

    def preview_task_ids(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        return self._service(TasksService).preview_task_ids(payload)

    def create_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service(TasksService).create_tasks(payload)

    def log_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service(LogsService).log_preview(payload)

    def create_log(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service(LogsService).create_log(payload)

    def parse_key_results(self, payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        return self._service(OKRsService).parse_key_results(payload)

    def create_okr(self, payload: dict[str, Any]) -> dict[str, int]:
        return self._service(OKRsService).create_okr(payload)

    def parse_meeting(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return self._service(MeetingsService).parse_meeting(payload)

    def create_meeting(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service(MeetingsService).create_meeting(payload)

    def _serialize_log_task(self, task: dict[str, Any], *, selected: bool) -> dict[str, Any]:
        return self._service(LogsService).serialize_log_task(task, selected=selected)

    def _post_discord_message(self, channel_id: str, content: str) -> None:
        runtime = self._compat_runtime()
        return runtime.post_discord_message(channel_id, content)

    def _create_meeting_attendance_tasks(self, meeting: dict[str, Any]) -> list[dict[str, Any]]:
        return self._service(MeetingsService).create_meeting_attendance_tasks(meeting)

    def _meeting_task_project(self) -> dict[str, str]:
        return self._service(MeetingsService).meeting_task_project()

    def _create_meeting_page(self, meeting: dict[str, Any], *, announced: bool) -> dict[str, Any]:
        return self._service(MeetingsService).create_meeting_page(meeting, announced=announced)

    def _text_or_option(self, prop: dict[str, Any], value: str) -> dict[str, Any]:
        return self._service(MeetingsService).text_or_option(prop, value)

    def _attendees_property(self, prop: dict[str, Any], attendees: list[str]) -> dict[str, Any]:
        return self._service(MeetingsService).attendees_property(prop, attendees)

    def _lookup_attendee_team_id(self, attendee: str) -> str | None:
        return self._service(MeetingsService).lookup_attendee_team_id(attendee)

    def _mark_meeting_announced(self, page: dict[str, Any]) -> None:
        return self._service(MeetingsService).mark_meeting_announced(page)

    def _announce_meeting(self, meeting: dict[str, Any]) -> None:
        return self._service(MeetingsService).announce_meeting(meeting)

    def _meeting_mentions(self, attendees: list[str]) -> str:
        return self._service(MeetingsService).meeting_mentions(attendees)

    def _create_objective(self, *, title: str, period: str, owner_id: str | None, founder: dict[str, str]) -> dict[str, Any]:
        return self._service(OKRsService).create_objective(title=title, period=period, owner_id=owner_id, founder=founder)

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
        return self._service(OKRsService).create_key_result(
            description=description,
            index=index,
            period=period,
            owner_id=owner_id,
            objective_id=objective_id,
            project_id=project_id,
            metric=metric,
            target=target,
        )

    def _set_period(self, properties: dict[str, Any], schema: dict[str, Any], period: str) -> None:
        return self._service(OKRsService).set_period(properties, schema, period)

    def _set_owner(self, properties: dict[str, Any], schema: dict[str, Any], owner_id: str | None) -> None:
        return self._service(OKRsService).set_owner(properties, schema, owner_id)


InternalToolsService = InternalNotionApp


def frontend_dist_root() -> Path:
    return ROOT / "frontend" / "dist"


def legacy_redirects() -> dict[str, str]:
    return {
        "/task creator": "/task-creator",
        "/task creator/": "/task-creator",
        "/okr creator": "/okr-creator",
        "/okr creator/": "/okr-creator",
        "/meeting creator": "/meeting-creator",
        "/meeting creator/": "/meeting-creator",
        "/log creator": "/log-creator",
        "/log creator/": "/log-creator",
        "/weekly rollover": "/",
        "/weekly rollover/": "/",
    }


__all__ = [
    "DEFAULT_KRS_DB_ID",
    "DEFAULT_MEETINGS_DB_ID",
    "DEFAULT_OBJECTIVES_DB_ID",
    "DEFAULT_TEAM_DB_ID",
    "FOUNDER_BY_ID",
    "InternalNotionApp",
    "InternalToolsService",
    "KR_PARSE_PROMPT",
    "LOGGER",
    "MADRID_TZ",
    "MEETING_PARSE_PROMPT",
    "MONTHS",
    "ROLE_TO_ENV",
    "TASK_PARSE_PROMPT",
    "TIME_FIRST_RE",
    "TIME_RANGE_RE",
    "TIME_RE",
    "WEEKDAYS",
    "WEEKDAY_LOOKUP",
    "_clean_line",
    "_env",
    "_fallback_key_results",
    "_fallback_task_descriptions",
    "_finalize_sentence",
    "_format_datetime_label",
    "_founder_for_attendee",
    "_guess_kr_metric",
    "_mode_for_location",
    "_month_name",
    "_month_name_for_date",
    "_normalize_attendees",
    "_normalize_date_iso",
    "_normalize_meeting_payload",
    "_parse_time_parts",
    "_period_code",
    "_resolve_founder",
    "_time_from_match",
    "_try_parse_relative_datetime",
    "_try_parse_time_range_datetime",
    "_try_parse_user_datetime",
    "_week_context_for_date",
    "_week_parts",
    "frontend_dist_root",
    "legacy_redirects",
]
