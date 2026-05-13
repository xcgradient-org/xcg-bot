from __future__ import annotations

from dataclasses import dataclass

from backend.services.logs import LogsService
from backend.services.meetings import MeetingsService
from backend.services.okrs import OKRsService
from backend.services.projects import ProjectsService
from backend.services.runtime import InternalRuntime, build_runtime
from backend.services.streaks import StreaksService
from backend.services.tasks import TasksService
from backend.services.team_usage.service import TeamUsageService
from backend.services.week import WeekService


@dataclass(slots=True)
class InternalServices:
    runtime: InternalRuntime
    projects: ProjectsService
    week: WeekService
    tasks: TasksService
    logs: LogsService
    okrs: OKRsService
    meetings: MeetingsService
    team_usage: TeamUsageService
    streaks: StreaksService


def build_services(runtime: InternalRuntime | None = None) -> InternalServices:
    active_runtime = runtime or build_runtime()
    return InternalServices(
        runtime=active_runtime,
        projects=ProjectsService(active_runtime),
        week=WeekService(active_runtime),
        tasks=TasksService(active_runtime),
        logs=LogsService(active_runtime),
        okrs=OKRsService(active_runtime),
        meetings=MeetingsService(active_runtime),
        team_usage=TeamUsageService(),
        streaks=StreaksService(active_runtime),
    )
