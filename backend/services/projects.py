from __future__ import annotations


class ProjectsService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def list_projects(self) -> dict[str, list[dict[str, str]]]:
        return {"projects": self.runtime.notion.list_projects()}
