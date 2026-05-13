from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import Response

from backend.api.models import (
    CreateMeetingRequest,
    CreateOKRRequest,
    CreateTasksRequest,
    LogNowRequest,
    ParseKeyResultsRequest,
    ParseMeetingRequest,
    ParseTasksRequest,
    PreviewTaskIdsRequest,
    WeekPwpReportRequest,
    WeekRolloverRequest,
)
from backend.services.pwp_reports import WeekPwpReportService


def _service_call(callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return callback()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _verify_internal_api_token(request: Request, authorization: str | None) -> None:
    settings = request.app.state.settings
    expected = getattr(settings, "internal_api_token", None)
    if not expected:
        return
    if not authorization or authorization.strip() != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing internal API token.")


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

    @router.get("/team-usage")
    def team_usage() -> dict[str, Any]:
        return _service_call(services.team_usage.get_team_usage)

    @router.get("/claude-usage")
    def claude_usage_status() -> dict[str, Any]:
        member = services.team_usage.get_member_usage("oriol")
        if not member:
            return {"error": "not_configured"}
        subs = member.get("subscriptions", [])
        sub = next((s for s in subs if s.get("type") == "claude_oauth"), None)
        if not sub or sub.get("status") != "ok":
            return {"error": sub.get("status", "error"), "hint": sub.get("hint", "")} if sub else {"error": "not_configured"}
        return {
            "five_hour": sub.get("five_hour"),
            "seven_day": sub.get("seven_day"),
            "seven_day_sonnet": sub.get("seven_day_sonnet"),
            "subscription_type": sub.get("tier"),
            "profile": "oriol",
            "last_checked": sub.get("last_checked"),
        }

    @router.post("/week/rollover")
    def run_weekly_rollover(payload: WeekRolloverRequest) -> dict[str, Any]:
        return _service_call(lambda: services.week.run_weekly_rollover(payload.model_dump()))

    @router.post("/streaks/sync")
    def sync_streaks() -> dict[str, Any]:
        return _service_call(services.streaks.sync_all)

    @router.get("/reports/week-pwp/team")
    def week_pwp_team_list(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _verify_internal_api_token(request, authorization)
        return {"members": services.runtime.notion.list_team_members()}

    @router.post("/reports/week-pwp")
    def week_pwp_zip(
        request: Request,
        payload: WeekPwpReportRequest,
        authorization: str | None = Header(default=None),
    ) -> Response:
        _verify_internal_api_token(request, authorization)
        service = WeekPwpReportService(services.runtime)
        try:
            data, filename = service.build_project_zip(week_number=int(payload.week), person=payload.person)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
