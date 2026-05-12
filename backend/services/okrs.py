from __future__ import annotations

import re
from typing import Any

from backend.domain.dates import month_name
from backend.domain.founders import resolve_founder
from backend.domain.prompts import KR_PARSE_PROMPT
from backend.domain.text import clean_line, fallback_key_results


def period_code(period_type: str, quarter: int | str | None, year: int | str | None) -> str:
    from datetime import datetime
    from backend.domain.dates import MADRID_TZ
    year_int = int(year or datetime.now(MADRID_TZ).year)
    if str(period_type or "").lower() == "annual":
        return str(year_int)
    quarter_int = int(quarter or ((datetime.now(MADRID_TZ).month - 1) // 3 + 1))
    return f"{year_int % 100:02d}-Q{quarter_int}"


class OKRsService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def parse_key_results(self, payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        text = str(payload.get("text") or "")
        key_results: list[dict[str, str]] = []
        if self.runtime.reflection.api_keys:
            try:
                result = self.runtime.reflection.generate_json_response(
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
                        description = clean_line(str(item.get("description") or ""))
                        if description:
                            key_results.append(
                                {
                                    "description": description,
                                    "metric": str(item.get("metric") or "").strip(),
                                    "target": str(item.get("target") or "").strip(),
                                }
                            )
            except Exception as exc:  # noqa: BLE001
                from backend.services.runtime import LOGGER
                LOGGER.warning("KR parse LLM failed; using fallback parser: %s", exc)
        return {"key_results": key_results or fallback_key_results(text)}

    def create_okr(self, payload: dict[str, Any]) -> dict[str, int]:
        founder = resolve_founder(payload)
        period = period_code(payload.get("period_type", ""), payload.get("quarter"), payload.get("year"))
        project_id = str(payload.get("project_id") or "").strip()
        owner_id = self.runtime.notion.lookup_team_member_id(founder["name"])
        objectives = payload.get("objectives") if isinstance(payload.get("objectives"), list) else []

        objective_count = 0
        kr_count = 0
        for objective in objectives:
            if not isinstance(objective, dict):
                continue
            title = str(objective.get("title") or "").strip()
            if not title:
                continue
            objective_page = self.create_objective(title=title, period=period, owner_id=owner_id, founder=founder)
            objective_count += 1
            objective_id = str(objective_page["id"])
            key_results = objective.get("key_results") if isinstance(objective.get("key_results"), list) else []
            for index, key_result in enumerate(key_results, start=1):
                if not isinstance(key_result, dict):
                    continue
                description = str(key_result.get("description") or "").strip()
                if not description:
                    continue
                self.create_key_result(
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

    def create_objective(self, *, title: str, period: str, owner_id: str | None, founder: dict[str, str]) -> dict[str, Any]:
        schema = self.runtime.notion._retrieve_schema(self.runtime.objectives_db_id)
        properties: dict[str, Any] = {}
        title_name = self.runtime.notion._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": title}}]}
        self.set_period(properties, schema, period)
        self.set_owner(properties, schema, owner_id)
        notes_name = self.runtime.notion._existing_property_name(schema, "Notes")
        if notes_name:
            properties[notes_name] = {"rich_text": self.runtime.notion._rich_text(f"Created from internal OKR Creator for {founder['name']} ({founder['role']}).")}
        return self.runtime.notion.client.pages.create(parent=self.runtime.notion._build_parent(self.runtime.objectives_db_id), properties=properties)

    def create_key_result(
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
        schema = self.runtime.notion._retrieve_schema(self.runtime.krs_db_id)
        properties: dict[str, Any] = {}
        title_name = self.runtime.notion._title_property_name(schema)
        kr_title = description if re.match(r"^kr\s*\d+[:.)-]", description, flags=re.IGNORECASE) else f"KR{index}: {description}"
        properties[title_name] = {"title": [{"type": "text", "text": {"content": kr_title}}]}
        self.set_period(properties, schema, period)
        self.set_owner(properties, schema, owner_id)
        if prop := self.runtime.notion._get_schema_property(schema, "Status"):
            prop_name = self.runtime.notion._property_name(prop, "Status")
            status_name = self.runtime.notion._resolve_option_name(prop, preferred_values=["To Do", "Todo", "Not Started"])
            properties[prop_name] = self.runtime.notion._build_named_option_value(prop, status_name)
        if prop := self.runtime.notion._get_schema_property(schema, "Objective", "Objectives"):
            prop_name = self.runtime.notion._property_name(prop, "Objective")
            properties[prop_name] = {"relation": [{"id": objective_id}]}
        if project_id and (prop := self.runtime.notion._get_schema_property(schema, "Projects", "Project")):
            prop_name = self.runtime.notion._property_name(prop, "Projects")
            properties[prop_name] = {"relation": [{"id": project_id}]}
        if prop := self.runtime.notion._get_schema_property(schema, "Notes"):
            notes = []
            if metric:
                notes.append(f"Metric: {metric}")
            if target:
                notes.append(f"Target: {target}")
            if notes:
                properties[self.runtime.notion._property_name(prop, "Notes")] = {"rich_text": self.runtime.notion._rich_text(" | ".join(notes))}
        return self.runtime.notion.client.pages.create(parent=self.runtime.notion._build_parent(self.runtime.krs_db_id), properties=properties)

    def set_period(self, properties: dict[str, Any], schema: dict[str, Any], period: str) -> None:
        if prop := self.runtime.notion._get_schema_property(schema, "Period"):
            prop_name = self.runtime.notion._property_name(prop, "Period")
            properties[prop_name] = self.runtime.notion._build_scalar_property_value(prop, period)

    def set_owner(self, properties: dict[str, Any], schema: dict[str, Any], owner_id: str | None) -> None:
        owner_name = self.runtime.notion._existing_property_name(schema, "Owner", "Founder")
        if owner_name and schema[owner_name].get("type") == "relation" and owner_id:
            properties[owner_name] = {"relation": [{"id": owner_id}]}
