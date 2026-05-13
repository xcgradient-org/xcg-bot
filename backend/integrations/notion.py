from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from notion_client import Client


LOGGER = logging.getLogger("xcg_bot.notion")
DONE_NAMES = {"done", "complete", "completed"}
ARCHIVED_NAMES = {"archived", "archive"}
UNSET = object()
PROPERTY_ALIASES = {
    "Announced": ("Announced", "Posted", "Sent", "Broadcasted"),
    "Attendees": ("Attendees", "People", "Owners", "Founder"),
    "Best Streak": ("Best Streak", "Longest Streak", "Max Streak"),
    "Created on": ("Created on", "Created On", "Created"),
    "Current Streak": ("Current Streak", "Streak"),
    "Current Week": ("Current Week", "Current Sprint"),
    "Date": ("Date", "When", "Log Date", "Meeting Date"),
    "Description": ("Description", "Task", "Details", "Summary"),
    "Display ID": ("Display ID", "Task ID", "ID", "Name", "Title"),
    "Done date": ("Done date", "Completed on", "Completed date", "Done on"),
    "Founder": ("Founder", "Founders", "Owner", "Owners", "Person", "People"),
    "Is Current Week": ("Is Current Week", "In Current Week"),
    "Last Log": ("Last Log", "Last Logged", "Last Activity"),
    "Last Rollover Moved Count": ("Last Rollover Moved Count", "Rollover Moved Count", "Moved Count"),
    "Last Rollover Run": ("Last Rollover Run", "Rollover Run"),
    "Last Rollover Status": ("Last Rollover Status", "Rollover Status"),
    "Location": ("Location", "Place", "Address"),
    "Month": ("Month",),
    "Notes": ("Notes", "Context", "Summary", "Overview", "TL;DR", "TLDR"),
    "Project": ("Project", "Projects"),
    "Projects": ("Projects", "Project"),
    "Quarter": ("Quarter",),
    "Reminded": ("Reminded", "Reminder sent", "Reminder posted"),
    "Role": ("Role", "Function"),
    "Sprint week": ("Sprint week", "Sprint Week"),
    "Status": ("Status", "Done", "Completed", "State"),
    "Tasks completed": ("Tasks completed", "Completed tasks", "Tasks done", "Done tasks", "Tasks"),
    "Title": ("Title", "Name"),
    "Type": ("Type", "Meeting Type", "Category"),
    "Week": ("Week", "Sprint week", "Sprint Week"),
    "Year": ("Year",),
}


class NotionService:
    def __init__(self, *, token: str, tasks_db_id: str, daily_logs_db_id: str, team_db_id: str, settings_db_id: str | None = None) -> None:
        self.client = Client(auth=token)
        self.tasks_db_id = tasks_db_id
        self.daily_logs_db_id = daily_logs_db_id
        self.team_db_id = team_db_id
        self.settings_db_id = settings_db_id
        self._streaks_available = True
        self._team_member_cache: dict[str, str] = {}

    def verify_startup(self) -> None:
        try:
            self.client.databases.retrieve(database_id=self.tasks_db_id)
            self.client.databases.retrieve(database_id=self.daily_logs_db_id)
            if self.settings_db_id:
                self.client.databases.retrieve(database_id=self.settings_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Unable to reach required Notion databases: {exc}") from exc

        try:
            self.client.databases.retrieve(database_id=self.team_db_id)
        except Exception as exc:  # noqa: BLE001
            self._streaks_available = False
            LOGGER.warning("Team database is unavailable; streak maintenance is disabled: %s", exc)
        else:
            self._streaks_available = True

    def streaks_available(self) -> bool:
        return self._streaks_available

    def query_remaining_tasks(self, role: str, week_code: str, founder_name: str | None = None) -> list[dict[str, Any]]:
        try:
            tasks = self._query_all(self.tasks_db_id)
            return [
                task
                for task in tasks
                if self._task_matches_founder(task, role=role, founder_name=founder_name)
                and not self._is_task_done(task)
                and not self._is_task_archived(task)
                and self._task_matches_week(task, week_code)
            ]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query remaining tasks: {exc}") from exc

    def query_log_tasks(
        self,
        role: str,
        today_iso: str,
        week_code: str,
        founder_name: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        try:
            tasks = self._query_all(self.tasks_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query log tasks: {exc}") from exc

        role_tasks = [
            task
            for task in tasks
            if self._task_matches_founder(task, role=role, founder_name=founder_name)
        ]
        active_week = self._resolve_active_week(role_tasks, preferred_week=week_code)
        if active_week:
            candidates = [task for task in role_tasks if self._task_matches_week(task, active_week)]
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
        candidates = [task for task in candidates if task["id"] not in done_other_day_ids and not self._is_task_archived(task)]
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
        logged_at_iso: str | None = None,
        completed_task_ids: list[str],
        notes_text: str,
    ) -> dict[str, Any]:
        schema = self._retrieve_schema(self.daily_logs_db_id)
        properties: dict[str, Any] = {}
        business_day_timestamp = self._business_day_timestamp(today_iso, logged_at_iso)

        title_name = self._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": f"{founder_name} · {week_code} · {today_iso}"}}]}

        if prop := self._get_schema_property(schema, "Date"):
            properties[self._property_name(prop, "Date")] = {"date": {"start": business_day_timestamp}}

        if prop := self._get_schema_property(schema, "Created on"):
            timestamp = str(logged_at_iso or "").strip() or business_day_timestamp
            properties[self._property_name(prop, "Created on")] = {"date": {"start": timestamp}}

        used_names = {title_name}

        founder_prop_name = self._existing_property_name(schema, "Founder")
        if founder_prop_name:
            used_names.add(founder_prop_name)
            founder_prop = schema[founder_prop_name]
            if founder_prop.get("type") == "relation":
                team_page_id = self.lookup_team_member_id(founder_name)
                if team_page_id:
                    properties[founder_prop_name] = {"relation": [{"id": team_page_id}]}
            else:
                properties[founder_prop_name] = self._build_text_like_property_value(founder_prop, founder_name)

        role_prop_name = self._existing_property_name(schema, "Role")
        if role_prop_name and role_prop_name not in used_names:
            used_names.add(role_prop_name)
            properties[role_prop_name] = self._build_text_like_property_value(schema[role_prop_name], founder_role)

        week_prop_name = self._existing_property_name(schema, "Week")
        if week_prop_name and week_prop_name not in used_names:
            used_names.add(week_prop_name)
            properties[week_prop_name] = self._build_scalar_property_value(schema[week_prop_name], week_code)

        tasks_prop_name = self._existing_property_name(schema, "Tasks completed")
        if tasks_prop_name and tasks_prop_name not in used_names:
            used_names.add(tasks_prop_name)
            properties[tasks_prop_name] = {"relation": [{"id": page_id} for page_id in completed_task_ids]}

        notes_prop_name = self._existing_property_name(schema, "Notes")
        if notes_prop_name and notes_prop_name not in used_names:
            properties[notes_prop_name] = {"rich_text": self._rich_text(notes_text)}

        try:
            return self.client.pages.create(
                parent=self._build_parent(self.daily_logs_db_id),
                properties=properties,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to create daily log in Notion: {exc}") from exc

    def has_daily_log(self, founder_name: str, today_iso: str) -> bool:
        return self.find_daily_log(founder_name, today_iso) is not None

    def find_daily_log(self, founder_name: str, today_iso: str) -> dict[str, Any] | None:
        try:
            rows = self._query_all(self.daily_logs_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query daily logs: {exc}") from exc
        matches = [
            row
            for row in rows
            if self._daily_log_founder_value(row) == founder_name
            and self._date_matches_day(row, "Date", today_iso)
        ]
        if not matches:
            return None
        matches.sort(key=lambda row: str(row.get("created_time") or ""), reverse=True)
        return matches[0]

    def daily_log_dates(self, founder_name: str) -> list[date]:
        try:
            rows = self._query_all(self.daily_logs_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query daily logs: {exc}") from exc

        dates: list[date] = []
        for row in rows:
            if self._daily_log_founder_value(row) != founder_name:
                continue
            value = self._property_date(row, "Date")
            if not value:
                continue
            dates.append(date.fromisoformat(value[:10]))
        return dates

    def get_streak_row(self, founder_name: str) -> dict[str, Any]:
        try:
            rows = self._query_all(self.team_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query team rows: {exc}") from exc

        matches = [row for row in rows if self._founder_matches_row(row, founder_name)]
        if not matches:
            raise RuntimeError(f"No team row found for founder {founder_name}.")
        if len(matches) > 1:
            raise RuntimeError(f"Multiple team rows found for founder {founder_name}.")
        return matches[0]

    def get_all_streak_rows(self) -> list[dict[str, Any]]:
        try:
            return self._query_all(self.team_db_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query team rows: {exc}") from exc

    def update_streak_row(
        self,
        row_id: str,
        *,
        current_streak: int,
        best_streak: int | None,
    ) -> None:
        schema = self._retrieve_schema(self.team_db_id)
        properties: dict[str, Any] = {}

        current_prop_name = self._existing_property_name(schema, "Current Streak") or "Current Streak"
        properties[current_prop_name] = {"number": current_streak}

        if best_streak is not None:
            best_prop_name = self._existing_property_name(schema, "Best Streak") or "Best Streak"
            properties[best_prop_name] = {"number": best_streak}

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
        return self._property_text(task, "Description") or self.task_display_id(task) or "Untitled task"

    def task_display_id(self, task: dict[str, Any]) -> str:
        return self._property_text(task, "Display ID") or self._page_title(task)

    def page_ids(self, pages: list[dict[str, Any]]) -> list[str]:
        return [page["id"] for page in pages]

    def streak_values(self, row: dict[str, Any]) -> tuple[int, int, str]:
        current = self._property_number(row, "Current Streak")
        best = self._property_number(row, "Best Streak")
        last_log = self._property_date(row, "Last Log")
        return current, best, last_log

    def founder_name(self, row: dict[str, Any]) -> str:
        return self._property_text(row, "Founder") or self._page_title(row)

    def lookup_team_member_id(self, founder_name: str) -> str | None:
        key = str(founder_name or "").strip().lower()
        if not key:
            return None
        if key in self._team_member_cache:
            return self._team_member_cache[key]
        try:
            rows = self._query_all(self.team_db_id)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to query Team DB for member lookup: %s", exc)
            return None
        for row in rows:
            name = self._page_title(row)
            if name.strip().lower() == key:
                page_id = str(row.get("id") or "").strip()
                if page_id:
                    self._team_member_cache[key] = page_id
                    return page_id
        return None

    def set_task_completion(self, task: dict[str, Any], *, completed: bool, today_iso: str) -> None:
        db_schema = self._retrieve_schema(self.tasks_db_id)
        properties = self._task_completion_properties(task, db_schema, completed=completed, today_iso=today_iso)
        try:
            self.client.pages.update(page_id=task["id"], properties=properties)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to update task completion for {task['id']}: {exc}") from exc

    def _task_completion_properties(
        self,
        task: dict[str, Any],
        db_schema: dict[str, Any],
        *,
        completed: bool,
        today_iso: str,
    ) -> dict[str, Any]:
        status_prop = self._property(task, "Status")
        prop_type = status_prop.get("type")
        status_prop_name = self._existing_property_name(db_schema, "Status")
        schema_status = db_schema.get(status_prop_name or "", {})
        if not prop_type:
            prop_type = schema_status.get("type")

        properties: dict[str, Any] = {}
        status_target_name = status_prop_name or "Status"
        if prop_type == "checkbox":
            properties[status_target_name] = {"checkbox": completed}
        elif prop_type == "status":
            properties[status_target_name] = {"status": {"name": self._resolve_status_name(schema_status, completed=completed)}}
        elif prop_type == "select":
            properties[status_target_name] = {"select": {"name": self._resolve_status_name(schema_status, completed=completed)}}
        else:
            raise RuntimeError("Tasks database is missing a supported Status property.")

        done_checkbox_name = self._existing_property_name(db_schema, "Done")
        if done_checkbox_name and done_checkbox_name != status_target_name and db_schema[done_checkbox_name].get("type") == "checkbox":
            properties[done_checkbox_name] = {"checkbox": completed}

        done_date_prop_name = self._existing_property_name(db_schema, "Done date") or "Done date"
        if completed:
            properties[done_date_prop_name] = {"date": {"start": today_iso}}
        else:
            properties[done_date_prop_name] = {"date": None}

        return properties

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
        founder_name: str | None = None,
        descriptions: list[str],
        year: int,
        quarter_name: str,
        month_name: str,
        week_code: str,
        today_iso: str,
        display_ids: list[str] | None = None,
        is_current_week: bool = False,
    ) -> list[dict[str, Any]]:
        if not descriptions:
            return []

        owner_team_page_id = self.lookup_team_member_id(founder_name) if founder_name else None
        if display_ids is None or len(display_ids) != len(descriptions):
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
                founder_name=founder_name,
                owner_team_page_id=owner_team_page_id,
                project_id=project_id,
                year=year,
                quarter_name=quarter_name,
                month_name=month_name,
                week_code=week_code,
                today_iso=today_iso,
                is_current_week=is_current_week,
            )
            try:
                created_page = self.client.pages.create(
                    parent=self._build_parent(self.tasks_db_id),
                    properties=properties,
                )
                created_pages.append(created_page)
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
        prop = self._property(page, "Status")
        if not prop:
            return False

        prop_type = prop.get("type")
        if prop_type == "checkbox":
            return bool(prop.get("checkbox"))
        if prop_type == "status":
            status = (prop.get("status") or {}).get("name", "").strip().lower()
            if status in DONE_NAMES:
                return True
        if prop_type == "select":
            status = (prop.get("select") or {}).get("name", "").strip().lower()
            if status in DONE_NAMES:
                return True

        done_prop = self._property(page, "Done")
        if done_prop and done_prop is not prop and done_prop.get("type") == "checkbox":
            return bool(done_prop.get("checkbox"))
        return False

    def _is_task_archived(self, page: dict[str, Any]) -> bool:
        prop = self._property(page, "Status")
        prop_type = prop.get("type")
        if prop_type == "status":
            status = (prop.get("status") or {}).get("name", "").strip().lower()
            return status in ARCHIVED_NAMES
        if prop_type == "select":
            status = (prop.get("select") or {}).get("name", "").strip().lower()
            return status in ARCHIVED_NAMES
        return False

    def _property(self, page: dict[str, Any], *candidate_names: str) -> dict[str, Any]:
        properties = page.get("properties", {})
        if not properties:
            return {}

        property_name = self._existing_property_name(properties, *candidate_names)
        if property_name is None:
            return {}
        return properties.get(property_name, {})

    def _property_text(self, page: dict[str, Any], *candidate_names: str) -> str:
        prop = self._property(page, *candidate_names)
        prop_type = prop.get("type")

        if prop_type == "title":
            return "".join(item.get("plain_text", "") for item in prop.get("title", [])).strip()
        if prop_type == "rich_text":
            return "".join(item.get("plain_text", "") for item in prop.get("rich_text", [])).strip()
        if prop_type == "select":
            return (prop.get("select") or {}).get("name", "").strip()
        if prop_type == "status":
            return (prop.get("status") or {}).get("name", "").strip()
        if prop_type == "multi_select":
            return ", ".join(item.get("name", "").strip() for item in prop.get("multi_select", []) if item.get("name"))
        if prop_type == "people":
            return ", ".join(item.get("name", "").strip() for item in prop.get("people", []) if item.get("name"))
        if prop_type == "relation":
            return ",".join(item.get("id", "") for item in prop.get("relation", []))
        if prop_type == "date":
            return ((prop.get("date") or {}).get("start") or "").strip()
        if prop_type == "number":
            value = prop.get("number")
            return "" if value is None else str(value)
        if prop_type == "checkbox":
            return "true" if prop.get("checkbox") else "false"
        return ""

    def _property_date(self, page: dict[str, Any], *candidate_names: str) -> str:
        prop = self._property(page, *candidate_names)
        value = prop.get("date") or {}
        return (value.get("start") or "").strip()

    def _property_number(self, page: dict[str, Any], *candidate_names: str) -> int:
        prop = self._property(page, *candidate_names)
        value = prop.get("number")
        return int(value or 0)

    def _property_relation_ids(self, page: dict[str, Any], *candidate_names: str) -> list[str]:
        prop = self._property(page, *candidate_names)
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
        week_codes = {self._task_week_value(task) for task in tasks if self._task_week_value(task)}
        if any(self._week_matches(value, preferred_week) for value in week_codes):
            return preferred_week
        if not week_codes:
            return preferred_week
        latest = max(week_codes, key=self._week_sort_key)
        return self._canonical_week_code(latest, fallback=preferred_week) or preferred_week

    def _week_sort_key(self, week_code: str) -> tuple[int, int]:
        parsed = self._parse_week_code(week_code)
        if parsed is None:
            return (-1, -1)
        year, week = parsed
        return (year if year is not None else -1, week)

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
            display_id = self.task_display_id(task)
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
        founder_name: str | None,
        owner_team_page_id: str | None,
        project_id: str,
        year: int,
        quarter_name: str,
        month_name: str,
        week_code: str,
        today_iso: str,
        is_current_week: bool = False,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}

        title_name = self._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": display_id}}]}

        if prop := self._get_schema_property(schema, "Role"):
            prop_name = self._property_name(prop, "Role")
            properties[prop_name] = self._build_named_option_value(prop, role)
        owner_prop_name = self._existing_property_name(schema, "Owner", "Founder")
        if owner_prop_name and owner_prop_name not in properties:
            owner_prop = schema[owner_prop_name]
            if owner_prop.get("type") == "relation" and owner_team_page_id:
                properties[owner_prop_name] = {"relation": [{"id": owner_team_page_id}]}
            elif founder_name and owner_prop.get("type") != "relation":
                try:
                    properties[owner_prop_name] = self._build_text_like_property_value(owner_prop, founder_name)
                except RuntimeError:
                    pass
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
        if prop := self._get_schema_property(schema, "Is Current Week"):
            prop_name = self._property_name(prop, "Is Current Week")
            if prop.get("type") == "checkbox":
                properties[prop_name] = {"checkbox": bool(is_current_week)}
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
        done_prop_name = self._existing_property_name(schema, "Done")
        if done_prop_name and done_prop_name not in properties and schema[done_prop_name].get("type") == "checkbox":
            properties[done_prop_name] = {"checkbox": False}
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
        normalized = {self._normalize_property_name(name): name for name in schema}
        for candidate in self._candidate_property_names(*candidate_names):
            match = normalized.get(self._normalize_property_name(candidate))
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

    def _build_text_like_property_value(self, schema_prop: dict[str, Any], value: str) -> dict[str, Any]:
        prop_type = schema_prop.get("type")
        if prop_type == "title":
            return {"title": [{"type": "text", "text": {"content": value}}]}
        if prop_type == "rich_text":
            return {"rich_text": self._rich_text(value)}
        if prop_type == "select":
            return {"select": {"name": value}}
        if prop_type == "status":
            return {"status": {"name": value}}
        if prop_type == "multi_select":
            if not value:
                return {"multi_select": []}
            return {"multi_select": [{"name": value}]}
        raise RuntimeError(f"Property {schema_prop.get('name', 'unknown')} does not support text-like values.")

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

    def _candidate_property_names(self, *candidate_names: str) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()
        for candidate in candidate_names:
            options = PROPERTY_ALIASES.get(candidate, (candidate,))
            for option in options:
                normalized = self._normalize_property_name(option)
                if normalized in seen:
                    continue
                seen.add(normalized)
                resolved.append(option)
        return resolved

    def _normalize_property_name(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

    def _task_owner_value(self, task: dict[str, Any]) -> str:
        role_value = self._property_text(task, "Role")
        if role_value:
            return role_value

        for candidate_name in ("Founder", "Attendees"):
            prop = self._property(task, candidate_name)
            if prop.get("type") == "relation":
                continue
            explicit_owner = self._property_text(task, candidate_name)
            if explicit_owner:
                return explicit_owner

        display_id = self.task_display_id(task)
        match = re.search(r"-(CEO|CTO|COO)-\d+$", display_id, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return ""

    def _task_matches_founder(self, task: dict[str, Any], *, role: str, founder_name: str | None = None) -> bool:
        owner_value = self._task_owner_value(task)
        if not owner_value:
            return False

        normalized_targets = {role.strip().lower()}
        if founder_name:
            normalized_targets.add(founder_name.strip().lower())

        tokens = {
            token.strip().lower()
            for token in re.split(r"[,/]", owner_value)
            if token.strip()
        }
        if owner_value.strip().lower() in normalized_targets:
            return True
        return bool(tokens & normalized_targets)

    def _task_week_value(self, task: dict[str, Any]) -> str:
        return self._property_text(task, "Week")

    def _parse_week_code(self, week_code: str) -> tuple[int | None, int] | None:
        raw = str(week_code or "").strip()
        if not raw:
            return None

        match = re.search(r"(?:(\d{2,4})\s*[-/]?\s*)?W?(\d{1,2})$", raw, flags=re.IGNORECASE)
        if not match:
            return None

        year_text = match.group(1)
        week_text = match.group(2)
        year: int | None = None
        if year_text:
            year = int(year_text)
            if year < 100:
                year += 2000
        return year, int(week_text)

    def _canonical_week_code(self, week_code: str, *, fallback: str | None = None) -> str | None:
        parsed = self._parse_week_code(week_code)
        if parsed is None:
            return str(week_code or "").strip() or None

        year, week = parsed
        if year is None and fallback:
            fallback_parsed = self._parse_week_code(fallback)
            if fallback_parsed is not None:
                year = fallback_parsed[0]

        if year is None:
            return f"W{week:02d}"
        return f"{year % 100:02d}-W{week:02d}"

    def _week_matches(self, left: str, right: str) -> bool:
        left_parsed = self._parse_week_code(left)
        right_parsed = self._parse_week_code(right)
        if left_parsed and right_parsed:
            left_year, left_week = left_parsed
            right_year, right_week = right_parsed
            if left_week != right_week:
                return False
            if left_year is None or right_year is None:
                return True
            return left_year == right_year
        return str(left or "").strip() == str(right or "").strip()

    def _task_matches_week(self, task: dict[str, Any], week_code: str) -> bool:
        return self._week_matches(self._task_week_value(task), week_code)

    def _founder_matches_row(self, row: dict[str, Any], founder_name: str) -> bool:
        # Check "Founder" alias first; fall back to page title for Team rows (title property is "Name")
        value = self._property_text(row, "Founder") or self._page_title(row)
        if not value:
            return False
        tokens = {
            token.strip().lower()
            for token in re.split(r"[,/]", value)
            if token.strip()
        }
        if value.strip().lower() == founder_name.strip().lower():
            return True
        return founder_name.strip().lower() in tokens

    def _daily_log_founder_value(self, row: dict[str, Any]) -> str:
        prop = self._property(row, "Founder")
        if prop.get("type") != "relation":
            explicit = self._property_text(row, "Founder")
            if explicit:
                return explicit

        title = self._page_title(row)
        if not title:
            return ""
        return title.split("·", 1)[0].strip()

    def _default_current_week(self) -> str:
        now = datetime.now()
        iso_year, iso_week, _ = now.isocalendar()
        return f"{iso_year % 100:02d}-W{iso_week:02d}"

    def _business_day_timestamp(self, business_day_iso: str, logged_at_iso: str | None) -> str:
        raw = str(logged_at_iso or "").strip()
        if not raw:
            return business_day_iso
        normalized = raw.replace("Z", "+00:00")
        try:
            logged_at = datetime.fromisoformat(normalized)
        except ValueError:
            return business_day_iso
        business_day = date.fromisoformat(business_day_iso)
        if logged_at.tzinfo is None:
            return datetime.combine(business_day, logged_at.time()).isoformat(timespec="seconds")
        return datetime.combine(business_day, logged_at.timetz()).isoformat(timespec="seconds")

    def get_current_week_from_settings(self) -> str:
        if not self.settings_db_id:
            return self._default_current_week()
        rows = self._query_all(self.settings_db_id)
        if not rows:
            raise RuntimeError("Settings database is empty.")
        row = rows[0]
        week_code = self._property_text(row, "Current Week")
        if not re.match(r"^\d{2}-W\d{1,2}$", week_code):
            raise RuntimeError(f"Invalid week code in settings: {week_code}")
        return week_code

    def set_current_week_in_settings(self, week_code: str, status: str, count: int) -> None:
        if not self.settings_db_id:
            LOGGER.info("No settings database configured; skipping persisted current-week update to %s (status=%s, count=%s).", week_code, status, count)
            return
        rows = self._query_all(self.settings_db_id)
        if not rows:
            raise RuntimeError("Settings database is empty.")
        row = rows[0]
        now_iso = datetime.now().isoformat()
        schema = self._retrieve_schema(self.settings_db_id)
        properties: dict[str, Any] = {}
        current_week_prop = self._existing_property_name(schema, "Current Week") or "Current Week"
        properties[current_week_prop] = self._build_scalar_property_value(schema.get(current_week_prop, {"type": "rich_text"}), week_code)

        rollover_run_prop = self._existing_property_name(schema, "Last Rollover Run") or "Last Rollover Run"
        properties[rollover_run_prop] = {"date": {"start": now_iso}}

        rollover_status_prop = self._existing_property_name(schema, "Last Rollover Status") or "Last Rollover Status"
        if schema.get(rollover_status_prop, {}).get("type") in {"select", "status"}:
            properties[rollover_status_prop] = self._build_named_option_value(schema[rollover_status_prop], status)
        else:
            properties[rollover_status_prop] = {"rich_text": self._rich_text(status)}

        moved_count_prop = self._existing_property_name(schema, "Last Rollover Moved Count") or "Last Rollover Moved Count"
        properties[moved_count_prop] = {"number": count}
        self.client.pages.update(page_id=row["id"], properties=properties)

    def get_next_week_code(self, current_week: str) -> str:
        year_part, week_part = current_week.split("-W")
        year = 2000 + int(year_part)
        week = int(week_part)
        # Use a safe date within the current week to calculate the next week.
        # ISO week 1 is the week with the first Thursday of the year.
        # We can find a date in the current week and add 7 days.
        current_date = datetime.strptime(f"{year}-W{week}-4", "%G-W%V-%u")
        next_date = current_date + timedelta(days=7)
        iso_year, iso_week, _ = next_date.isocalendar()
        return f"{iso_year % 100:02d}-W{iso_week:02d}"

    def find_incomplete_tasks_for_week(self, week_code: str) -> list[dict[str, Any]]:
        tasks = self._query_all(self.tasks_db_id)
        return [
            task
            for task in tasks
            if self._task_matches_week(task, week_code)
            and not self._is_task_done(task)
            and not self._is_task_archived(task)
        ]

    def _rollover_task_with_schema(self, task: dict[str, Any], to_week: str, db_schema: dict[str, Any]) -> None:
        properties: dict[str, Any] = {}

        if prop := self._get_schema_property(db_schema, "Week"):
            prop_name = self._property_name(prop, "Week")
            properties[prop_name] = self._build_scalar_property_value(prop, to_week)

        desc_prop_name = "Description"
        if prop := self._get_schema_property(db_schema, "Description"):
            desc_prop_name = self._property_name(prop, "Description")

        current_desc_objs = task.get("properties", {}).get(desc_prop_name, {}).get("rich_text", [])
        current_desc_text = "".join(obj.get("plain_text", "") for obj in current_desc_objs)

        carryover_prefix = "↩ carryover | "
        stale_prefix = "⚠ stale | "

        if current_desc_text.startswith(carryover_prefix):
            new_desc_text = stale_prefix + current_desc_text[len(carryover_prefix):]
        elif not current_desc_text.startswith(stale_prefix):
            new_desc_text = carryover_prefix + current_desc_text
        else:
            new_desc_text = current_desc_text

        properties[desc_prop_name] = {"rich_text": self._rich_text(new_desc_text)}
        self.client.pages.update(page_id=task["id"], properties=properties)

    def rollover_task(self, task: dict[str, Any], to_week: str) -> None:
        self._rollover_task_with_schema(task, to_week, self._retrieve_schema(self.tasks_db_id))

    def rollover_tasks_batch(self, tasks: list[dict[str, Any]], to_week: str) -> None:
        """Roll over multiple tasks, fetching the schema only once."""
        db_schema = self._retrieve_schema(self.tasks_db_id)
        for task in tasks:
            self._rollover_task_with_schema(task, to_week, db_schema)

    def count_tasks_for_week(self, week_code: str) -> int:
        """Return the total number of tasks (done and incomplete) assigned to week_code."""
        tasks = self._query_all(self.tasks_db_id)
        return sum(1 for t in tasks if self._task_matches_week(t, week_code))

    def remap_tasks_week(self, from_week: str, to_week: str) -> int:
        """Move ALL tasks from from_week to to_week without touching descriptions or flags."""
        tasks = self._query_all(self.tasks_db_id)
        db_schema = self._retrieve_schema(self.tasks_db_id)
        week_prop_name = "Week"
        if prop := self._get_schema_property(db_schema, "Week"):
            week_prop_name = self._property_name(prop, "Week")
        count = 0
        for task in tasks:
            if not self._task_matches_week(task, from_week):
                continue
            self.client.pages.update(
                page_id=task["id"],
                properties={
                    week_prop_name: self._build_scalar_property_value(
                        db_schema.get(week_prop_name, {"type": "select"}), to_week
                    )
                },
            )
            count += 1
        return count

    def find_carryover_tasks_in_week(self, week_code: str) -> list[dict[str, Any]]:
        """Return tasks in week_code that have a carryover or stale prefix (i.e. were moved by rollover)."""
        tasks = self._query_all(self.tasks_db_id)
        db_schema = self._retrieve_schema(self.tasks_db_id)
        desc_prop_name = "Description"
        if prop := self._get_schema_property(db_schema, "Description"):
            desc_prop_name = self._property_name(prop, "Description")
        result = []
        for task in tasks:
            if not self._task_matches_week(task, week_code):
                continue
            desc_objs = task.get("properties", {}).get(desc_prop_name, {}).get("rich_text", [])
            desc_text = "".join(obj.get("plain_text", "") for obj in desc_objs)
            if desc_text.startswith("↩ carryover | ") or desc_text.startswith("⚠ stale | "):
                result.append(task)
        return result

    def rollback_rollover(self, from_week: str, to_week: str) -> int:
        """Undo a rollover: move tasks from to_week back to from_week, stripping carryover prefixes."""
        tasks = self._query_all(self.tasks_db_id)
        db_schema = self._retrieve_schema(self.tasks_db_id)
        week_prop_name = "Week"
        if prop := self._get_schema_property(db_schema, "Week"):
            week_prop_name = self._property_name(prop, "Week")
        desc_prop_name = "Description"
        if prop := self._get_schema_property(db_schema, "Description"):
            desc_prop_name = self._property_name(prop, "Description")
        carryover_prefix = "↩ carryover | "
        stale_prefix = "⚠ stale | "
        count = 0
        for task in tasks:
            if not self._task_matches_week(task, to_week):
                continue
            desc_objs = task.get("properties", {}).get(desc_prop_name, {}).get("rich_text", [])
            desc_text = "".join(obj.get("plain_text", "") for obj in desc_objs)
            if desc_text.startswith(carryover_prefix):
                restored = desc_text[len(carryover_prefix):]
            elif desc_text.startswith(stale_prefix):
                restored = carryover_prefix + desc_text[len(stale_prefix):]
            else:
                continue
            properties = {
                week_prop_name: self._build_scalar_property_value(
                    db_schema.get(week_prop_name, {"type": "select"}), from_week
                ),
                desc_prop_name: {"rich_text": self._rich_text(restored)},
            }
            self.client.pages.update(page_id=task["id"], properties=properties)
            count += 1
        return count

    def set_is_current_week_flags(self, from_week: str, to_week: str) -> None:
        tasks = self._query_all(self.tasks_db_id)
        db_schema = self._retrieve_schema(self.tasks_db_id)
        current_week_prop_name = self._existing_property_name(db_schema, "Is Current Week")
        if not current_week_prop_name:
            LOGGER.info("Tasks database has no Is Current Week property; skipping flag sync.")
            return
        for task in tasks:
            is_currently_flagged = bool(self._property(task, "Is Current Week").get("checkbox", False))
            task_week = self._task_week_value(task)

            should_be_flagged = self._week_matches(task_week, to_week)
            # If from_week == to_week (unlikely but possible), it stays true.

            if is_currently_flagged != should_be_flagged:
                self.client.pages.update(
                    page_id=task["id"],
                    properties={current_week_prop_name: {"checkbox": should_be_flagged}},
                )

    def _infer_current_week_from_tasks(self) -> str:
        tasks = self._query_all(self.tasks_db_id)
        week_codes = [
            self._task_week_value(task)
            for task in tasks
            if self._task_week_value(task) and not self._is_task_archived(task)
        ]
        if not week_codes:
            raise RuntimeError("Unable to infer current week because no task rows expose a Week value.")
        latest = max(week_codes, key=self._week_sort_key)
        canonical = self._canonical_week_code(latest)
        if not canonical:
            raise RuntimeError(f"Unable to infer current week from task Week value: {latest}")
        return canonical
