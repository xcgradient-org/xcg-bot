from __future__ import annotations

from datetime import date
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

    def query_completed_tasks(self, role: str, today_iso: str) -> list[dict[str, Any]]:
        try:
            tasks = self._query_all(self.tasks_db_id)
            return [
                task
                for task in tasks
                if self._property_text(task, "Role") == role
                and self._is_task_done(task)
                and self._property_date(task, "Done date") == today_iso
            ]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to query completed tasks: {exc}") from exc

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

    def create_daily_log(
        self,
        *,
        founder_name: str,
        founder_role: str,
        week_code: str,
        today_iso: str,
        completed_task_ids: list[str],
        raw_notes: str,
        reflection_text: str,
    ) -> dict[str, Any]:
        properties = {
            "Title": {"title": [{"type": "text", "text": {"content": f"{founder_name} · {week_code} · {today_iso}"}}]},
            "Date": {"date": {"start": today_iso}},
            "Founder": {"select": {"name": founder_name}},
            "Role": {"select": {"name": founder_role}},
            "Week": {"select": {"name": week_code}},
            "Tasks completed": {"relation": [{"id": page_id} for page_id in completed_task_ids]},
            "Raw notes": {"rich_text": self._rich_text(raw_notes)},
            "Enhanced notes": {"rich_text": self._rich_text(reflection_text)},
        }
        try:
            return self.client.pages.create(
                parent={"database_id": self.daily_logs_db_id},
                properties=properties,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to create daily log in Notion: {exc}") from exc

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
        descriptions = []
        for task in tasks:
            description = self._property_text(task, "Description") or self._property_text(task, "Display ID")
            if description:
                descriptions.append(description)
        return descriptions

    def page_ids(self, pages: list[dict[str, Any]]) -> list[str]:
        return [page["id"] for page in pages]

    def streak_values(self, row: dict[str, Any]) -> tuple[int, int, str]:
        current = self._property_number(row, "Current Streak")
        best = self._property_number(row, "Best Streak")
        last_log = self._property_date(row, "Last Log")
        return current, best, last_log

    def founder_name(self, row: dict[str, Any]) -> str:
        return self._property_text(row, "Founder")

    def _query_all(self, database_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"page_size": 100}
            if next_cursor:
                payload["start_cursor"] = next_cursor
            response = self.client.databases.query(database_id=database_id, **payload)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")

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

    def _rich_text(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        chunks = [text[index : index + 2000] for index in range(0, len(text), 2000)]
        return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]
