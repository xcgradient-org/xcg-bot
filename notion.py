from __future__ import annotations

import logging
from typing import Any

from notion_client import Client


LOGGER = logging.getLogger("xcg_bot.notion")
DONE_NAMES = {"done", "complete", "completed"}


class NotionService:
    def __init__(self, *, token: str, tasks_db_id: str, daily_logs_db_id: str, streaks_db_id: str) -> None:
        self.client = Client(auth=token)
        self.tasks_db_id = tasks_db_id
        self.daily_logs_db_id = daily_logs_db_id
        self.streaks_db_id = streaks_db_id

    def verify_startup(self) -> None:
        try:
            self.client.databases.retrieve(database_id=self.tasks_db_id)
            self.client.databases.retrieve(database_id=self.daily_logs_db_id)
            self.client.databases.retrieve(database_id=self.streaks_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Unable to reach required Notion databases: {exc}") from exc

    def query_remaining_tasks(self, role: str, week_code: str) -> list[dict[str, Any]]:
        try:
            tasks = self._query_all(self.tasks_db_id)
            return [
                task
                for task in tasks
                if self._property_text(task, "Role") == role
                and not self._is_task_done(task)
                and self._property_text(task, "Week") == week_code
            ]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query remaining tasks: {exc}") from exc

    def query_log_tasks(self, role: str, today_iso: str, week_code: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        try:
            tasks = self._query_all(self.tasks_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query log tasks: {exc}") from exc

        role_tasks = [task for task in tasks if self._property_text(task, "Role") == role]
        active_week = self._resolve_active_week(role_tasks, preferred_week=week_code)
        if active_week:
            candidates = [task for task in role_tasks if self._property_text(task, "Week") == active_week]
        else:
            candidates = list(role_tasks)

        done_today_ids = {
            task["id"]
            for task in role_tasks
            if self._is_task_done(task) and self._date_matches_day(task, "Done date", today_iso)
        }
        done_other_day_ids = {
            task["id"]
            for task in role_tasks
            if self._is_task_done(task)
            and self._property_date(task, "Done date")
            and task["id"] not in done_today_ids
        }
        candidates = [task for task in candidates if task["id"] not in done_other_day_ids]
        legacy_done_ids: set[str] = set()
        if not done_today_ids:
            legacy_done_ids = {
                task["id"]
                for task in candidates
                if self._is_task_done(task) and not self._property_date(task, "Done date")
            }

        completed_ids = done_today_ids or legacy_done_ids
        extra_selected = [task for task in role_tasks if task["id"] in completed_ids and task not in candidates]
        if extra_selected:
            candidates = candidates + extra_selected

        candidates.sort(
            key=lambda task: (
                task["id"] not in completed_ids,
                self.task_description(task).lower(),
                task["id"],
            )
        )
        completed_tasks = [task for task in candidates if task["id"] in completed_ids]
        return candidates, completed_tasks, active_week or week_code

    def create_daily_log(
        self,
        *,
        founder_name: str,
        founder_role: str,
        week_code: str,
        today_iso: str,
        completed_task_ids: list[str],
        notes_text: str,
    ) -> dict[str, Any]:
        properties = {
            "Title": {"title": [{"type": "text", "text": {"content": f"{founder_name} · {week_code} · {today_iso}"}}]},
            "Date": {"date": {"start": today_iso}},
            "Founder": {"select": {"name": founder_name}},
            "Role": {"select": {"name": founder_role}},
            "Week": {"select": {"name": week_code}},
            "Tasks completed": {"relation": [{"id": page_id} for page_id in completed_task_ids]},
            "Notes": {"rich_text": self._rich_text(notes_text)},
        }
        try:
            return self.client.pages.create(
                parent=self._build_parent(self.daily_logs_db_id),
                properties=properties,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to create daily log in Notion: {exc}") from exc

    def has_daily_log(self, founder_name: str, today_iso: str) -> bool:
        try:
            rows = self._query_all(self.daily_logs_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query daily logs: {exc}") from exc
        return any(
            self._property_text(row, "Founder") == founder_name
            and self._date_matches_day(row, "Date", today_iso)
            for row in rows
        )

    def get_streak_row(self, founder_name: str) -> dict[str, Any]:
        try:
            rows = self._query_all(self.streaks_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query streak rows: {exc}") from exc

        matches = [row for row in rows if self._property_text(row, "Founder") == founder_name]
        if not matches:
            raise RuntimeError(f"No streak row found for founder {founder_name}.")
        if len(matches) > 1:
            raise RuntimeError(f"Multiple streak rows found for founder {founder_name}.")
        return matches[0]

    def get_all_streak_rows(self) -> list[dict[str, Any]]:
        try:
            return self._query_all(self.streaks_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query streak rows: {exc}") from exc

    def update_streak_row(
        self,
        row_id: str,
        *,
        current_streak: int,
        best_streak: int | None,
        last_log_iso: str | None = None,
    ) -> None:
        properties: dict[str, Any] = {
            "Current Streak": {"number": current_streak},
        }
        if last_log_iso is not None:
            properties["Last Log"] = {"date": {"start": last_log_iso}}
        if best_streak is not None:
            properties["Best Streak"] = {"number": best_streak}

        try:
            self.client.pages.update(page_id=row_id, properties=properties)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to update streak row {row_id}: {exc}") from exc

    def task_descriptions(self, tasks: list[dict[str, Any]]) -> list[str]:
        descriptions: list[str] = []
        for task in tasks:
            description = self.task_description(task)
            if description:
                descriptions.append(description)
        return descriptions

    def task_description(self, task: dict[str, Any]) -> str:
        return self._property_text(task, "Description") or self._property_text(task, "Display ID") or "Untitled task"

    def task_display_id(self, task: dict[str, Any]) -> str:
        return self._property_text(task, "Display ID")

    def page_ids(self, pages: list[dict[str, Any]]) -> list[str]:
        return [page["id"] for page in pages]

    def streak_values(self, row: dict[str, Any]) -> tuple[int, int, str]:
        current = self._property_number(row, "Current Streak")
        best = self._property_number(row, "Best Streak")
        last_log = self._property_date(row, "Last Log")
        return current, best, last_log

    def founder_name(self, row: dict[str, Any]) -> str:
        return self._property_text(row, "Founder")

    def set_task_completion(self, task: dict[str, Any], *, completed: bool, today_iso: str) -> None:
        status_prop = task.get("properties", {}).get("Status", {})
        prop_type = status_prop.get("type")
        db_schema = self._retrieve_schema(self.tasks_db_id)
        schema_status = db_schema.get("Status", {})
        if not prop_type:
            prop_type = schema_status.get("type")

        properties: dict[str, Any] = {}
        if prop_type == "checkbox":
            properties["Status"] = {"checkbox": completed}
        elif prop_type == "status":
            properties["Status"] = {"status": {"name": self._resolve_status_name(schema_status, completed=completed)}}
        elif prop_type == "select":
            properties["Status"] = {"select": {"name": self._resolve_status_name(schema_status, completed=completed)}}
        else:
            raise RuntimeError("Tasks database is missing a supported Status property.")

        if completed:
            properties["Done date"] = {"date": {"start": today_iso}}
        else:
            properties["Done date"] = {"date": None}

        try:
            self.client.pages.update(page_id=task["id"], properties=properties)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to update task completion for {task['id']}: {exc}") from exc

    def list_projects(self) -> list[dict[str, str]]:
        schema = self._retrieve_schema(self.tasks_db_id)
        relation_prop = self._get_schema_property(schema, "Project", "Projects")
        if not relation_prop:
            raise RuntimeError("Tasks database is missing a Project relation property.")

        relation_type = relation_prop.get("relation") or {}
        # Prefer the pre-resolved data_source_id from the relation schema so we
        # can query the Projects DB directly without calling databases.retrieve
        # on it (which returns 404 when the DB is only accessible via data sources).
        data_source_id = relation_type.get("data_source_id")
        projects_db_id = data_source_id or relation_type.get("database_id")
        if not projects_db_id:
            raise RuntimeError("Tasks database Project relation does not expose a related projects database.")

        try:
            if data_source_id:
                rows = self._query_all_with_data_source_id(data_source_id)
            else:
                rows = self._query_all(projects_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query projects: {exc}") from exc

        projects = []
        for row in rows:
            name = self._page_title(row)
            if not name:
                continue
            projects.append({"id": row["id"], "name": name})
        projects.sort(key=lambda item: item["name"].lower())
        return projects

    def preview_task_ids(
        self,
        *,
        project_id: str,
        project_name: str,
        role: str,
        year: int,
        quarter_name: str,
        count: int,
    ) -> list[str]:
        sequence = self._count_matching_tasks(
            project_id=project_id,
            role=role,
            year=year,
            quarter_name=quarter_name,
        )
        return [f"{project_name}-{role}-{sequence + index}" for index in range(1, count + 1)]

    def create_tasks_batch(
        self,
        *,
        project_id: str,
        project_name: str,
        role: str,
        descriptions: list[str],
        year: int,
        quarter_name: str,
        month_name: str,
        week_code: str,
        today_iso: str,
    ) -> list[dict[str, Any]]:
        if not descriptions:
            return []

        display_ids = self.preview_task_ids(
            project_id=project_id,
            project_name=project_name,
            role=role,
            year=year,
            quarter_name=quarter_name,
            count=len(descriptions),
        )
        schema = self._retrieve_schema(self.tasks_db_id)
        created_pages = []
        for display_id, description in zip(display_ids, descriptions, strict=False):
            properties = self._build_task_properties(
                schema=schema,
                display_id=display_id,
                description=description,
                role=role,
                project_id=project_id,
                year=year,
                quarter_name=quarter_name,
                month_name=month_name,
                week_code=week_code,
                today_iso=today_iso,
            )
            try:
                created_pages.append(
                    self.client.pages.create(
                        parent=self._build_parent(self.tasks_db_id),
                        properties=properties,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Failed to create task {display_id} in Notion: {exc}") from exc
        return created_pages

    def primary_data_source_id(self, database_id: str) -> str:
        database = self.client.databases.retrieve(database_id=database_id)
        source_list = database.get("data_sources", [])
        if not source_list:
            raise RuntimeError(f"Database {database_id} does not expose any data sources.")
        return source_list[0]["id"]

    def _query_all(self, database_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_cursor: str | None = None
        query_fn = getattr(self.client.databases, "query", None)
        query_kwargs_name = "database_id"

        if query_fn is None:
            data_sources = getattr(self.client, "data_sources", None)
            data_source_query = getattr(data_sources, "query", None) if data_sources is not None else None
            if data_source_query is None:
                raise RuntimeError("Installed notion-client does not support querying databases or data sources.")

            query_fn = data_source_query
            query_kwargs_name = "data_source_id"
            database_id = self.primary_data_source_id(database_id)

        while True:
            payload: dict[str, Any] = {"page_size": 100}
            if next_cursor:
                payload["start_cursor"] = next_cursor
            response = query_fn(**{query_kwargs_name: database_id}, **payload)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")

    def _query_all_with_data_source_id(self, data_source_id: str) -> list[dict[str, Any]]:
        """Query a data source directly by its pre-resolved ID, bypassing databases.retrieve."""
        data_sources = getattr(self.client, "data_sources", None)
        data_source_query = getattr(data_sources, "query", None) if data_sources is not None else None
        if data_source_query is not None:
            results: list[dict[str, Any]] = []
            next_cursor: str | None = None
            while True:
                payload: dict[str, Any] = {"page_size": 100}
                if next_cursor:
                    payload["start_cursor"] = next_cursor
                response = data_source_query(data_source_id=data_source_id, **payload)
                results.extend(response.get("results", []))
                if not response.get("has_more"):
                    return results
                next_cursor = response.get("next_cursor")

        # Fallback: standard databases.query using the data_source_id as if it's a DB id
        return self._query_all(data_source_id)

    def _retrieve_schema(self, database_id: str) -> dict[str, Any]:
        database = self.client.databases.retrieve(database_id=database_id)
        properties = database.get("properties")
        if properties:
            return properties

        source_list = database.get("data_sources", [])
        if not source_list:
            raise RuntimeError(f"Database {database_id} does not expose any properties.")

        source = source_list[0]
        source_properties = source.get("properties")
        if source_properties:
            return source_properties

        data_sources = getattr(self.client, "data_sources", None)
        retrieve_fn = getattr(data_sources, "retrieve", None) if data_sources is not None else None
        if retrieve_fn is None:
            raise RuntimeError(f"Database {database_id} requires data source schema support from notion-client.")

        retrieved_source = retrieve_fn(data_source_id=source["id"])
        properties = retrieved_source.get("properties")
        if not properties:
            raise RuntimeError(f"Database {database_id} data source {source['id']} does not expose properties.")
        return properties

    def _build_parent(self, database_id: str) -> dict[str, str]:
        data_sources = getattr(self.client, "data_sources", None)
        if data_sources is not None:
            try:
                return {"data_source_id": self.primary_data_source_id(database_id)}
            except Exception:  # noqa: BLE001
                LOGGER.debug("Falling back to database_id parent for %s", database_id, exc_info=True)
        return {"database_id": database_id}

    def _is_task_done(self, page: dict[str, Any]) -> bool:
        prop = page.get("properties", {}).get("Status")
        if not prop:
            return False

        prop_type = prop.get("type")
        if prop_type == "checkbox":
            return bool(prop.get("checkbox"))
        if prop_type == "status":
            status = (prop.get("status") or {}).get("name", "").strip().lower()
            return status in DONE_NAMES
        if prop_type == "select":
            status = (prop.get("select") or {}).get("name", "").strip().lower()
            return status in DONE_NAMES
        return False

    def _property_text(self, page: dict[str, Any], property_name: str) -> str:
        prop = page.get("properties", {}).get(property_name, {})
        prop_type = prop.get("type")

        if prop_type == "title":
            return "".join(item.get("plain_text", "") for item in prop.get("title", [])).strip()
        if prop_type == "rich_text":
            return "".join(item.get("plain_text", "") for item in prop.get("rich_text", [])).strip()
        if prop_type == "select":
            return (prop.get("select") or {}).get("name", "").strip()
        if prop_type == "status":
            return (prop.get("status") or {}).get("name", "").strip()
        if prop_type == "relation":
            return ",".join(item.get("id", "") for item in prop.get("relation", []))
        if prop_type == "date":
            return ((prop.get("date") or {}).get("start") or "").strip()
        return ""

    def _property_date(self, page: dict[str, Any], property_name: str) -> str:
        prop = page.get("properties", {}).get(property_name, {})
        value = prop.get("date") or {}
        return (value.get("start") or "").strip()

    def _property_number(self, page: dict[str, Any], property_name: str) -> int:
        prop = page.get("properties", {}).get(property_name, {})
        value = prop.get("number")
        return int(value or 0)

    def _property_relation_ids(self, page: dict[str, Any], property_name: str) -> list[str]:
        prop = page.get("properties", {}).get(property_name, {})
        relation = prop.get("relation") or []
        return [str(item.get("id", "")).strip() for item in relation if str(item.get("id", "")).strip()]

    def _rich_text(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        chunks = [text[index : index + 2000] for index in range(0, len(text), 2000)]
        return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]

    def _page_title(self, page: dict[str, Any]) -> str:
        properties = page.get("properties", {})
        for prop in properties.values():
            if prop.get("type") == "title":
                return "".join(item.get("plain_text", "") for item in prop.get("title", [])).strip()
        for fallback_name in ("Name", "Title"):
            value = self._property_text(page, fallback_name)
            if value:
                return value
        return ""

    def _date_matches_day(self, page: dict[str, Any], property_name: str, day_iso: str) -> bool:
        value = self._property_date(page, property_name)
        return bool(value) and value.startswith(day_iso)

    def _resolve_active_week(self, tasks: list[dict[str, Any]], *, preferred_week: str) -> str:
        week_codes = {
            self._property_text(task, "Week")
            for task in tasks
            if self._property_text(task, "Week")
        }
        if preferred_week in week_codes:
            return preferred_week
        if not week_codes:
            return preferred_week
        return max(week_codes, key=self._week_sort_key)

    def _week_sort_key(self, week_code: str) -> tuple[int, int]:
        try:
            year_text, week_text = week_code.split("-W", 1)
            return int(year_text), int(week_text)
        except Exception:  # noqa: BLE001
            return (-1, -1)

    def _resolve_status_name(self, schema_status: dict[str, Any], *, completed: bool) -> str:
        prop_type = schema_status.get("type")
        option_group = schema_status.get(prop_type or "", {})
        options = option_group.get("options", [])
        normalized_options = {
            str(option.get("name", "")).strip().lower(): str(option.get("name", "")).strip()
            for option in options
            if str(option.get("name", "")).strip()
        }

        if completed:
            for name in DONE_NAMES:
                if name in normalized_options:
                    return normalized_options[name]
            return "Done"

        for preferred in ("to do", "todo", "not started", "backlog", "planned", "in progress"):
            if preferred in normalized_options:
                return normalized_options[preferred]

        for lowered, original in normalized_options.items():
            if lowered not in DONE_NAMES:
                return original

        raise RuntimeError("Tasks database does not expose a non-completed Status option.")

    def _count_matching_tasks(self, *, project_id: str, role: str, year: int, quarter_name: str) -> int:
        """Return the highest existing sequence number for project+role tasks, or 0 if none found.

        We parse Display IDs (e.g. "ALPHA-COO-7") rather than relying on Year/Quarter metadata
        fields being filled, which makes this robust to partially-migrated databases.
        """
        try:
            tasks = self._query_all(self.tasks_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query tasks for ID generation: {exc}") from exc

        schema = self._retrieve_schema(self.tasks_db_id)
        project_property_name = self._existing_property_name(schema, "Project", "Projects")
        norm_project_id = project_id.replace("-", "").lower()

        # Collect the sequence numbers of existing tasks for this project+role.
        max_seq = 0
        prefix = f"-{role}-"
        for task in tasks:
            # Filter by project relation first (cheap check).
            relation_ids = self._property_relation_ids(task, project_property_name) if project_property_name else []
            norm_relation_ids = [r.replace("-", "").lower() for r in relation_ids]
            if norm_project_id not in norm_relation_ids:
                continue
            # Parse the sequence number out of the Display ID.
            display_id = self._property_text(task, "Display ID")
            if prefix in display_id:
                suffix = display_id.split(prefix, 1)[-1]
                if suffix.isdigit():
                    max_seq = max(max_seq, int(suffix))

        if max_seq == 0:
            LOGGER.debug(
                "_count_matching_tasks: no existing Display IDs found for role=%r project=%r; starting at 1.",
                role, project_id,
            )
        return max_seq


    def _build_task_properties(
        self,
        *,
        schema: dict[str, Any],
        display_id: str,
        description: str,
        role: str,
        project_id: str,
        year: int,
        quarter_name: str,
        month_name: str,
        week_code: str,
        today_iso: str,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}

        title_name = self._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": display_id}}]}

        if prop := self._get_schema_property(schema, "Role"):
            prop_name = self._property_name(prop, "Role")
            properties[prop_name] = self._build_named_option_value(prop, role)
        if prop := self._get_schema_property(schema, "Project", "Projects"):
            prop_name = self._property_name(prop, "Project")
            properties[prop_name] = {"relation": [{"id": project_id}]}
        if prop := self._get_schema_property(schema, "Description"):
            prop_name = self._property_name(prop, "Description")
            properties[prop_name] = {"rich_text": self._rich_text(description)}
        if prop := self._get_schema_property(schema, "Year"):
            prop_name = self._property_name(prop, "Year")
            properties[prop_name] = {"number": year}
        if prop := self._get_schema_property(schema, "Quarter"):
            prop_name = self._property_name(prop, "Quarter")
            properties[prop_name] = self._build_named_option_value(
                prop,
                self._resolve_option_name(prop, preferred_values=[quarter_name, quarter_name.split()[0]]),
            )
        if prop := self._get_schema_property(schema, "Month"):
            prop_name = self._property_name(prop, "Month")
            properties[prop_name] = self._build_named_option_value(
                prop,
                self._resolve_option_name(prop, preferred_values=[month_name]),
            )
        if prop := self._get_schema_property(schema, "Week"):
            prop_name = self._property_name(prop, "Week")
            properties[prop_name] = self._build_scalar_property_value(prop, week_code)
        if prop := self._get_schema_property(schema, "Sprint week"):
            prop_name = self._property_name(prop, "Sprint week")
            sprint_week = week_code.split("-")[-1]
            properties[prop_name] = self._build_scalar_property_value(prop, sprint_week)
        if prop := self._get_schema_property(schema, "Status"):
            prop_name = self._property_name(prop, "Status")
            status_type = prop.get("type")
            if status_type == "checkbox":
                properties[prop_name] = {"checkbox": False}
            elif status_type in {"select", "status"}:
                properties[prop_name] = self._build_named_option_value(
                    prop,
                    self._resolve_status_name(prop, completed=False),
                )
        if prop := self._get_schema_property(schema, "Done date"):
            prop_name = self._property_name(prop, "Done date")
            properties[prop_name] = {"date": None}
        if prop := self._get_schema_property(schema, "Created on"):
            prop_name = self._property_name(prop, "Created on")
            properties[prop_name] = {"date": {"start": today_iso}}
        return properties

    def _title_property_name(self, schema: dict[str, Any]) -> str:
        for name, prop in schema.items():
            if prop.get("type") == "title":
                return name
        return "Display ID"

    def _existing_property_name(self, schema: dict[str, Any], *candidate_names: str) -> str | None:
        lowered = {name.lower(): name for name in schema}
        for candidate in candidate_names:
            match = lowered.get(candidate.lower())
            if match:
                return match
        return None

    def _get_schema_property(self, schema: dict[str, Any], *candidate_names: str) -> dict[str, Any] | None:
        property_name = self._existing_property_name(schema, *candidate_names)
        if property_name is None:
            return None
        return schema[property_name]

    def _property_name(self, prop: dict[str, Any], fallback: str) -> str:
        return str(prop.get("name") or fallback)

    def _resolve_option_name(self, schema_prop: dict[str, Any], *, preferred_values: list[str]) -> str:
        prop_type = schema_prop.get("type")
        option_group = schema_prop.get(prop_type or "", {})
        options = option_group.get("options", [])
        normalized = {
            str(option.get("name", "")).strip().lower(): str(option.get("name", "")).strip()
            for option in options
            if str(option.get("name", "")).strip()
        }
        for preferred in preferred_values:
            preferred_text = str(preferred or "").strip()
            if not preferred_text:
                continue
            exact = normalized.get(preferred_text.lower())
            if exact:
                return exact
        for preferred in preferred_values:
            preferred_text = str(preferred or "").strip().lower()
            if not preferred_text:
                continue
            for lowered, original in normalized.items():
                if lowered.startswith(preferred_text):
                    return original
        if preferred_values:
            return str(preferred_values[0])
        raise RuntimeError(f"Property {schema_prop.get('name', 'unknown')} does not expose any options.")

    def _build_named_option_value(self, schema_prop: dict[str, Any], option_name: str) -> dict[str, Any]:
        prop_type = schema_prop.get("type")
        if prop_type == "select":
            return {"select": {"name": option_name}}
        if prop_type == "status":
            return {"status": {"name": option_name}}
        raise RuntimeError(f"Property {schema_prop.get('name', 'unknown')} does not support named options.")

    def _build_scalar_property_value(self, schema_prop: dict[str, Any], value: str) -> dict[str, Any]:
        prop_type = schema_prop.get("type")
        if prop_type == "select":
            option_name = self._resolve_option_name(schema_prop, preferred_values=[value])
            return {"select": {"name": option_name}}
        if prop_type == "status":
            option_name = self._resolve_option_name(schema_prop, preferred_values=[value])
            return {"status": {"name": option_name}}
        if prop_type == "rich_text":
            return {"rich_text": self._rich_text(value)}
        if prop_type == "number":
            digits = "".join(char for char in value if char.isdigit())
            return {"number": int(digits)} if digits else {"number": None}
        raise RuntimeError(f"Property {schema_prop.get('name', 'unknown')} does not support scalar task values.")
