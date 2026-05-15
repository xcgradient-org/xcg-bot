from __future__ import annotations


class WeekService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def week_status(self) -> dict[str, object]:
        current_week = self.runtime.notion.resolve_current_week()
        next_week = self.runtime.notion.get_next_week_code(current_week)
        incomplete_tasks = self.runtime.notion.find_incomplete_tasks_for_week(current_week)
        carryover_tasks = self.runtime.notion.find_carryover_tasks_in_week(next_week)
        return {
            "current_week": current_week,
            "next_week": next_week,
            "incomplete_count": len(incomplete_tasks),
            "carryover_count": len(carryover_tasks),
            "incomplete_tasks": [
                {
                    "id": self.runtime.notion.task_display_id(task),
                    "description": self.runtime.notion._property_text(task, "Description"),
                }
                for task in incomplete_tasks[:20]
            ],
        }

    def current_week_status(self) -> dict[str, str]:
        current_week = self.runtime.notion.resolve_current_week()
        return {
            "current_week": current_week,
            "next_week": self.runtime.notion.get_next_week_code(current_week),
        }

    def run_weekly_rollover(self, payload: dict[str, str]) -> dict[str, object]:
        current_week = self.runtime.notion.resolve_current_week()
        requested_week = str(payload.get("current_week") or "").strip()
        if requested_week and requested_week != current_week:
            raise RuntimeError(f"Week changed before rollover. Refresh first: current week is now {current_week}.")
        next_week = self.runtime.notion.get_next_week_code(current_week)
        tasks_to_move = self.runtime.notion.find_incomplete_tasks_for_week(current_week)
        self.runtime.notion.rollover_tasks_batch(tasks_to_move, next_week)
        self.runtime.notion.set_is_current_week_flags(current_week, next_week)
        self.runtime.notion.set_current_week_in_settings(next_week, status="success", count=len(tasks_to_move))
        return {
            "from_week": current_week,
            "to_week": next_week,
            "moved_count": len(tasks_to_move),
            "moved_tasks": [
                {
                    "id": self.runtime.notion.task_display_id(task),
                    "description": self.runtime.notion._property_text(task, "Description"),
                }
                for task in tasks_to_move[:20]
            ],
        }
