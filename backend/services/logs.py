from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.domain.founders import resolve_founder
from backend.services.streaks import sync_founder_streak_from_daily_logs
from bot.commands.log_command import build_blocker_message, current_context, rewrite_blocker_message


class LogsService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def serialize_log_task(self, task: dict[str, Any], *, selected: bool) -> dict[str, Any]:
        return {
            "id": task.get("id"),
            "display_id": self.runtime.notion.task_display_id(task),
            "description": self.runtime.notion.task_description(task),
            "selected": selected,
        }

    def log_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = resolve_founder(payload)
        ctx = current_context()
        already_logged = self.runtime.notion.has_daily_log(founder["name"], ctx.today_iso)
        candidate_tasks, completed_tasks, active_week = self.runtime.notion.query_log_tasks(
            founder["role"],
            ctx.today_iso,
            ctx.week_code,
            founder["name"],
        )
        ctx.week_code = active_week
        completed_ids = {task["id"] for task in completed_tasks}
        return {
            "founder": founder,
            "today_iso": ctx.today_iso,
            "week_code": ctx.week_code,
            "already_logged": already_logged,
            "tasks": [
                self.serialize_log_task(task, selected=task["id"] in completed_ids)
                for task in candidate_tasks
            ],
            "completed_count": len(completed_tasks),
        }

    def create_log(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = resolve_founder(payload)
        ctx = current_context()
        if self.runtime.notion.has_daily_log(founder["name"], ctx.today_iso):
            raise RuntimeError(f"{founder['name']} already logged for {ctx.today_iso}.")

        candidate_tasks, completed_tasks, active_week = self.runtime.notion.query_log_tasks(
            founder["role"],
            ctx.today_iso,
            ctx.week_code,
            founder["name"],
        )
        ctx.week_code = active_week
        selected_task_ids = {str(task_id) for task_id in payload.get("selected_task_ids", [])}
        original_ids = {task["id"] for task in completed_tasks}
        task_by_id = {task["id"]: task for task in candidate_tasks}
        selected_tasks = [task for task in candidate_tasks if task["id"] in selected_task_ids]

        for task in candidate_tasks:
            was_completed = task["id"] in original_ids
            should_be_completed = task["id"] in selected_task_ids
            if was_completed != should_be_completed:
                self.runtime.notion.set_task_completion(task, completed=should_be_completed, today_iso=ctx.today_iso)

        missing_ids = selected_task_ids - set(task_by_id)
        if missing_ids:
            from backend.services.runtime import LOGGER
            LOGGER.warning("Ignoring selected log task IDs outside candidate set: %s", sorted(missing_ids))

        raw_notes = str(payload.get("notes") or "").strip()
        task_descriptions = self.runtime.notion.task_descriptions(selected_tasks)
        try:
            reflection_text = self.runtime.reflection.generate_reflection(
                founder_name=founder["name"],
                founder_role=founder["role"],
                today_iso=ctx.today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.warning("Reflection generation failed; using fallback note: %s", exc)
            reflection_text = self.runtime.reflection.build_fallback_reflection(
                founder_name=founder["name"],
                founder_role=founder["role"],
                today_iso=ctx.today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )

        self.runtime.notion.create_daily_log(
            founder_name=founder["name"],
            founder_role=founder["role"],
            week_code=ctx.week_code,
            today_iso=ctx.today_iso,
            completed_task_ids=self.runtime.notion.page_ids(selected_tasks),
            notes_text=reflection_text,
        )

        streak = None
        if self.runtime.notion.streaks_available():
            try:
                streak, _best, _last = sync_founder_streak_from_daily_logs(
                    self.runtime.notion,
                    founder["name"],
                    today=datetime.fromisoformat(ctx.today_iso).date(),
                )
            except Exception as exc:  # noqa: BLE001
                from backend.services.runtime import LOGGER
                LOGGER.warning("Streak sync failed after web log save for %s: %s", founder["name"], exc)

        remaining_count = None
        try:
            remaining_count = len(self.runtime.notion.query_remaining_tasks(founder["role"], ctx.week_code, founder["name"]))
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.warning("Remaining-task lookup failed after web log save for %s: %s", founder["name"], exc)

        blocker_posted = False
        blocker = payload.get("blocker") if isinstance(payload.get("blocker"), dict) else {}
        blocker_message = str(blocker.get("message") or "").strip()
        blocker_target_role = str(blocker.get("target_role") or "").strip().upper()
        if blocker_message and blocker_target_role:
            final_message = rewrite_blocker_message(
                self.runtime.reflection,
                founder,
                target_role=blocker_target_role,
                task_descriptions=task_descriptions,
                raw_notes=raw_notes,
                raw_blocker=blocker_message,
            )
            self.runtime.post_discord_message(
                self.runtime.discord_blockers_channel_id,
                build_blocker_message(founder["name"], blocker_target_role, final_message, self.runtime),
            )
            blocker_posted = True

        return {
            "created": True,
            "today_iso": ctx.today_iso,
            "week_code": ctx.week_code,
            "completed_count": len(selected_tasks),
            "remaining_count": remaining_count,
            "streak": streak,
            "blocker_posted": blocker_posted,
        }
