from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FounderPayload(BaseModel):
    founder: str | None = None
    founder_name: str | None = None
    role: str | None = None


class ParseTasksRequest(FounderPayload):
    text: str = ""


class PreviewTaskIdsRequest(FounderPayload):
    project_id: str
    project_name: str
    week_code: str | None = None
    count: int = 0


class CreateTasksRequest(FounderPayload):
    project_id: str
    project_name: str
    week_code: str
    descriptions: list[str] = Field(default_factory=list)
    display_ids: list[str] = Field(default_factory=list)


class ParseKeyResultsRequest(BaseModel):
    text: str = ""
    objective: str | None = None


class CreateOKRRequest(FounderPayload):
    period_type: str | None = None
    quarter: int | str | None = None
    year: int | str | None = None
    project_id: str | None = None
    objectives: list[dict[str, Any]] = Field(default_factory=list)


class ParseMeetingRequest(FounderPayload):
    title: str | None = None
    date_input: str | None = None
    type: str | None = None
    attendees: list[str] | str | None = None
    location: str | None = None
    notes: str | None = None
    meeting_link: str | None = None
    address: str | None = None


class CreateMeetingRequest(FounderPayload):
    meeting: dict[str, Any]


class LogPreviewRequest(FounderPayload):
    pass


class CreateLogRequest(FounderPayload):
    selected_task_ids: list[str] = Field(default_factory=list)
    notes: str | None = None
    blocker: dict[str, Any] | None = None


class WeekRolloverRequest(BaseModel):
    current_week: str | None = None
