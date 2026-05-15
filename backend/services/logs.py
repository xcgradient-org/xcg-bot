from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.domain.founders import resolve_founder
from backend.domain.founders import FOUNDER_BY_ID
from bot.commands.log_command import build_blocker_message, current_context, rewrite_blocker_message
from backend.services.streaks import MADRID_TZ


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

    def logging_status(self) -> dict[str, Any]:
        ctx = current_context()
        founders: list[dict[str, Any]] = []
        for founder_id, founder in FOUNDER_BY_ID.items():
            row = self.runtime.notion.find_daily_log(founder["name"], ctx.today_iso)
            founders.append(
                {
                    "founder": founder_id,
                    "founder_name": founder["name"],
                    "role": founder["role"],
                    "logged": row is not None,
                    "logged_at": self._row_logged_at(row),
                }
            )
        return {
            "today_iso": ctx.today_iso,
            "week_code": ctx.week_code,
            "founders": founders,
        }

    def log_now(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = resolve_founder(payload)
        ctx = current_context()
        logged_at_iso = datetime.now(MADRID_TZ).isoformat()
        result = self.auto_create_log_for_founder(
            founder_name=founder["name"],
            founder_role=founder["role"],
            today_iso=ctx.today_iso,
            week_code=ctx.week_code,
            raw_notes="Manual end-of-day log from the internal site.",
            logged_at_iso=logged_at_iso,
        )
        row = self.runtime.notion.find_daily_log(founder["name"], ctx.today_iso)
        return {
            "founder": founder,
            "today_iso": ctx.today_iso,
            "week_code": result.get("week_code") or ctx.week_code,
            "logged": bool(result.get("created")) or row is not None,
            "logged_at": result.get("logged_at") or self._row_logged_at(row),
            "created": bool(result.get("created")),
            "reason": result.get("reason"),
            "completed_count": result.get("completed_count", 0),
            "streak": result.get("streak"),
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
        done_at_iso = datetime.now(MADRID_TZ).isoformat()

        for task in candidate_tasks:
            was_completed = task["id"] in original_ids
            should_be_completed = task["id"] in selected_task_ids
            if was_completed != should_be_completed:
                self.runtime.notion.set_task_completion(task, completed=should_be_completed, done_at_iso=done_at_iso)

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
            logged_at_iso=datetime.now(MADRID_TZ).isoformat(),
            completed_task_ids=self.runtime.notion.page_ids(selected_tasks),
            notes_text=reflection_text,
        )

        streak = self._sync_streak(founder["name"], ctx.today_iso)

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

    def auto_create_log_for_founder(
        self,
        *,
        founder_name: str,
        founder_role: str,
        today_iso: str,
        week_code: str,
        raw_notes: str = "Automatic log created from completed tasks.",
        logged_at_iso: str | None = None,
    ) -> dict[str, Any]:
        existing_row = self.runtime.notion.find_daily_log(founder_name, today_iso)
        if existing_row is not None:
            return {
                "created": False,
                "reason": "already_logged",
                "today_iso": today_iso,
                "week_code": week_code,
                "logged_at": self._row_logged_at(existing_row),
            }

        _candidate_tasks, completed_tasks, active_week = self.runtime.notion.query_log_tasks(
            founder_role,
            today_iso,
            week_code,
            founder_name,
        )
        if not completed_tasks:
            return {
                "created": False,
                "reason": "no_completed_tasks",
                "today_iso": today_iso,
                "week_code": active_week or week_code,
            }

        task_descriptions = self.runtime.notion.task_descriptions(completed_tasks)
        try:
            reflection_text = self.runtime.reflection.generate_reflection(
                founder_name=founder_name,
                founder_role=founder_role,
                today_iso=today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.warning("Auto-log reflection generation failed; using fallback note for %s: %s", founder_name, exc)
            reflection_text = self.runtime.reflection.build_fallback_reflection(
                founder_name=founder_name,
                founder_role=founder_role,
                today_iso=today_iso,
                completed_tasks=task_descriptions,
                raw_notes=raw_notes,
            )

        self.runtime.notion.create_daily_log(
            founder_name=founder_name,
            founder_role=founder_role,
            week_code=active_week or week_code,
            today_iso=today_iso,
            logged_at_iso=logged_at_iso,
            completed_task_ids=self.runtime.notion.page_ids(completed_tasks),
            notes_text=reflection_text,
        )
        streak = self._sync_streak(founder_name, today_iso)
        return {
            "created": True,
            "today_iso": today_iso,
            "week_code": active_week or week_code,
            "logged_at": self._format_logged_at(logged_at_iso),
            "completed_count": len(completed_tasks),
            "streak": streak,
        }

    def _row_logged_at(self, row: dict[str, Any] | None) -> str | None:
        if not row:
            return None
        created_time = str(
            self.runtime.notion._property_date(row, "Logged At")  # noqa: SLF001
            or row.get("created_time")
            or ""
        ).strip()
        if not created_time:
            return None
        return self._format_logged_at(created_time)

    def _format_logged_at(self, timestamp_text: str | None) -> str | None:
        if not timestamp_text:
            return None
        created_time = str(timestamp_text).strip()
        if not created_time:
            return None
        normalized = created_time.replace("Z", "+00:00")
        try:
            timestamp = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return timestamp.astimezone(MADRID_TZ).strftime("%H:%M")

    def _sync_streak(self, founder_name: str, today_iso: str) -> int | None:
        if not self.runtime.notion.streaks_available():
            return None
        try:
            from backend.services.streaks import sync_founder_streak_from_daily_logs

            streak, _best, _last = sync_founder_streak_from_daily_logs(
                self.runtime.notion,
                founder_name,
                today=datetime.fromisoformat(today_iso).date(),
            )
            return streak
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.warning("Streak sync failed after log save for %s: %s", founder_name, exc)
            return None
