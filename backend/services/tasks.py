from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.domain.dates import MADRID_TZ, month_name, week_parts
from backend.domain.founders import resolve_founder
from backend.domain.prompts import TASK_PARSE_PROMPT
from backend.domain.text import fallback_task_descriptions, finalize_sentence


class TasksService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def parse_tasks(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        text = str(payload.get("text") or "")
        descriptions: list[str] = []
        if self.runtime.reflection.api_keys:
            try:
                result = self.runtime.reflection.generate_json_response(
                    system_prompt=TASK_PARSE_PROMPT,
                    user_prompt=f"Founder request:\n{text.strip()}",
                    max_output_tokens=300,
                )
                raw_tasks = result.get("tasks")
                if isinstance(raw_tasks, list):
                    descriptions = [
                        finalize_sentence(item.get("description") if isinstance(item, dict) else item)
                        for item in raw_tasks
                    ]
                    descriptions = [description for description in descriptions if description]
            except Exception as exc:  # noqa: BLE001
                from backend.services.runtime import LOGGER
                LOGGER.warning("Task parse LLM failed; using fallback parser: %s", exc)
        return {"descriptions": descriptions or fallback_task_descriptions(text)}

    def preview_task_ids(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        founder = resolve_founder(payload)
        year, week = week_parts(str(payload.get("week_code") or ""))
        quarter = ((week - 1) // 13) + 1
        ids = self.runtime.notion.preview_task_ids(
            project_id=str(payload["project_id"]),
            project_name=str(payload["project_name"]),
            role=founder["role"],
            year=year,
            quarter_name=f"Q{min(quarter, 4)} {year}",
            count=int(payload.get("count") or 0),
        )
        return {"ids": ids}

    def create_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = resolve_founder(payload)
        descriptions = [finalize_sentence(item) for item in payload.get("descriptions", [])]
        descriptions = [item for item in descriptions if item]
        display_ids = [str(item).strip() for item in payload.get("display_ids", []) if str(item).strip()]
        if len(display_ids) != len(descriptions):
            display_ids = []
        week_code = str(payload["week_code"]).upper()
        is_current_week = False
        try:
            is_current_week = self.runtime.notion._week_matches(week_code, self.runtime.notion.get_current_week_from_settings())
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.warning("Could not resolve current week for new tasks; leaving Is Current Week false: %s", exc)
        year, week = week_parts(str(payload.get("week_code") or ""))
        quarter = min(((week - 1) // 13) + 1, 4)
        pages = self.runtime.notion.create_tasks_batch(
            project_id=str(payload["project_id"]),
            project_name=str(payload["project_name"]),
            role=founder["role"],
            founder_name=founder["name"],
            descriptions=descriptions,
            year=year,
            quarter_name=f"Q{quarter} {year}",
            month_name=month_name(),
            week_code=week_code,
            today_iso=datetime.now(MADRID_TZ).date().isoformat(),
            display_ids=display_ids or None,
            is_current_week=is_current_week,
        )
        return {"created": len(pages), "page_ids": [page.get("id") for page in pages]}
