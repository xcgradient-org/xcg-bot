from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from backend.api.models import (
    CreateMeetingRequest,
    CreateOKRRequest,
    CreateTasksRequest,
    LogNowRequest,
    ParseKeyResultsRequest,
    ParseMeetingRequest,
    ParseTasksRequest,
    PreviewTaskIdsRequest,
    WeekRolloverRequest,
)


def _service_call(callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return callback()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def build_api_router(services) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/projects")
    def list_projects() -> dict[str, Any]:
        return _service_call(services.projects.list_projects)

    @router.get("/week")
    def week_status() -> dict[str, Any]:
        return _service_call(services.week.week_status)

    @router.get("/current-week")
    def current_week_status() -> dict[str, Any]:
        return _service_call(services.week.current_week_status)

    @router.get("/logging/status")
    def logging_status() -> dict[str, Any]:
        return _service_call(services.logs.logging_status)

    @router.post("/logging/log-now")
    def log_now(payload: LogNowRequest) -> dict[str, Any]:
        return _service_call(lambda: services.logs.log_now(payload.model_dump()))

    @router.post("/parse")
    @router.post("/tasks/parse")
    def parse_tasks(payload: ParseTasksRequest) -> dict[str, Any]:
        return _service_call(lambda: services.tasks.parse_tasks(payload.model_dump()))

    @router.post("/preview-ids")
    @router.post("/tasks/preview-ids")
    def preview_task_ids(payload: PreviewTaskIdsRequest) -> dict[str, Any]:
        return _service_call(lambda: services.tasks.preview_task_ids(payload.model_dump()))

    @router.post("/tasks")
    def create_tasks(payload: CreateTasksRequest) -> dict[str, Any]:
        return _service_call(lambda: services.tasks.create_tasks(payload.model_dump()))

    @router.post("/okr/parse-krs")
    @router.post("/okrs/parse-krs")
    def parse_key_results(payload: ParseKeyResultsRequest) -> dict[str, Any]:
        return _service_call(lambda: services.okrs.parse_key_results(payload.model_dump()))

    @router.post("/okr/push")
    @router.post("/okrs")
    def create_okr(payload: CreateOKRRequest) -> dict[str, Any]:
        return _service_call(lambda: services.okrs.create_okr(payload.model_dump()))

    @router.post("/meetings/parse")
    def parse_meeting(payload: ParseMeetingRequest) -> dict[str, Any]:
        return _service_call(lambda: services.meetings.parse_meeting(payload.model_dump()))

    @router.post("/meetings")
    def create_meeting(payload: CreateMeetingRequest) -> dict[str, Any]:
        return _service_call(lambda: services.meetings.create_meeting(payload.model_dump()))

    @router.get("/claude-usage")
    def claude_usage_status() -> dict[str, Any]:
        return _service_call(services.claude_usage.get_usage)

    @router.post("/week/rollover")
    def run_weekly_rollover(payload: WeekRolloverRequest) -> dict[str, Any]:
        return _service_call(lambda: services.week.run_weekly_rollover(payload.model_dump()))

    @router.post("/streaks/sync")
    def sync_streaks() -> dict[str, Any]:
        return _service_call(services.streaks.sync_all)

    return router
