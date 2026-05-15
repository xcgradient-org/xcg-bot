from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.domain.dates import madrid_datetime

from .streaks import sync_founder_streak_from_daily_logs


class DailyLogDedupeService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def preview(
        self,
        *,
        founder: str | None = None,
        from_day: str | None = None,
        to_day: str | None = None,
    ) -> dict[str, Any]:
        founder_filter = self._normalize_founder_filter(founder)
        groups = self._duplicate_groups(founder_filter=founder_filter, from_day=from_day, to_day=to_day)
        return {
            "mode": "preview",
            "founder": founder_filter,
            "from_day": from_day,
            "to_day": to_day,
            "group_count": len(groups),
            "groups": [self._serialize_group(group) for group in groups],
        }

    def apply(
        self,
        *,
        founder: str | None = None,
        from_day: str | None = None,
        to_day: str | None = None,
    ) -> dict[str, Any]:
        founder_filter = self._normalize_founder_filter(founder)
        groups = self._duplicate_groups(founder_filter=founder_filter, from_day=from_day, to_day=to_day)
        affected_founders: set[str] = set()
        applied: list[dict[str, Any]] = []
        for group in groups:
            applied.append(self._apply_group(group))
            affected_founders.add(group["founder_name"])

        synced: list[dict[str, Any]] = []
        for founder_name in sorted(affected_founders):
            current, best, last_log_iso = sync_founder_streak_from_daily_logs(
                self.runtime.notion,
                founder_name,
            )
            synced.append(
                {
                    "founder_name": founder_name,
                    "current_streak": current,
                    "best_streak": best,
                    "last_log_iso": last_log_iso,
                }
            )

        return {
            "mode": "apply",
            "founder": founder_filter,
            "from_day": from_day,
            "to_day": to_day,
            "group_count": len(groups),
            "groups": applied,
            "synced_founders": synced,
        }

    def _normalize_founder_filter(self, founder: str | None) -> str | None:
        raw = str(founder or "").strip()
        if not raw:
            return None
        try:
            member = self.runtime.notion.find_team_member(raw)
        except ValueError:
            raise
        except Exception:
            member = None
        if member and member.get("name"):
            return str(member["name"]).strip()
        return raw

    def _duplicate_groups(
        self,
        *,
        founder_filter: str | None,
        from_day: str | None,
        to_day: str | None,
    ) -> list[dict[str, Any]]:
        from_date = date.fromisoformat(from_day) if from_day else None
        to_date = date.fromisoformat(to_day) if to_day else None
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in self.runtime.notion.get_all_daily_logs():
            founder_name = self.runtime.notion.daily_log_founder_name(row).strip()
            logical_day = self.runtime.notion.daily_log_logical_day_iso(row).strip()
            if not founder_name or not logical_day:
                continue
            logical_date = date.fromisoformat(logical_day)
            if founder_filter and founder_name.casefold() != founder_filter.casefold():
                continue
            if from_date and logical_date < from_date:
                continue
            if to_date and logical_date > to_date:
                continue
            grouped.setdefault((founder_name, logical_day), []).append(row)

        groups: list[dict[str, Any]] = []
        for (founder_name, logical_day), rows in grouped.items():
            if len(rows) < 2:
                continue
            keeper = self._select_keeper(rows)
            groups.append(
                {
                    "founder_name": founder_name,
                    "logical_day": logical_day,
                    "keeper": keeper,
                    "rows": sorted(rows, key=self._row_created_at_sort_key),
                }
            )
        groups.sort(key=lambda group: (group["logical_day"], group["founder_name"].casefold()))
        return groups

    def _select_keeper(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return min(
            rows,
            key=lambda row: (
                -len(self.runtime.notion.daily_log_task_ids(row)),
                -len(self.runtime.notion.daily_log_notes_text(row)),
                self._row_created_at_sort_key(row),
            ),
        )

    def _serialize_group(self, group: dict[str, Any]) -> dict[str, Any]:
        keeper_id = str(group["keeper"].get("id") or "").strip()
        return {
            "founder_name": group["founder_name"],
            "logical_day": group["logical_day"],
            "count": len(group["rows"]),
            "keeper_id": keeper_id,
            "rows": [self._row_summary(row, keeper_id=keeper_id) for row in group["rows"]],
        }

    def _row_summary(self, row: dict[str, Any], *, keeper_id: str) -> dict[str, Any]:
        row_id = str(row.get("id") or "").strip()
        return {
            "id": row_id,
            "title": self.runtime.notion.daily_log_title(row),
            "logical_day": self.runtime.notion.daily_log_logical_day_iso(row),
            "logged_at_iso": self.runtime.notion.daily_log_logged_at_iso(row),
            "created_time": str(row.get("created_time") or "").strip(),
            "task_count": len(self.runtime.notion.daily_log_task_ids(row)),
            "notes_length": len(self.runtime.notion.daily_log_notes_text(row)),
            "founder_relation_ids": self.runtime.notion.daily_log_founder_relation_ids(row),
            "is_keeper": row_id == keeper_id,
        }

    def _apply_group(self, group: dict[str, Any]) -> dict[str, Any]:
        rows = group["rows"]
        keeper = group["keeper"]
        keeper_id = str(keeper.get("id") or "").strip()
        losers = [row for row in rows if str(row.get("id") or "").strip() != keeper_id]

        merged_task_ids = list(
            dict.fromkeys(
                task_id
                for row in rows
                for task_id in self.runtime.notion.daily_log_task_ids(row)
            )
        )
        merged_notes = self.runtime.notion.daily_log_notes_text(keeper).strip()
        for loser in losers:
            loser_notes = self.runtime.notion.daily_log_notes_text(loser).strip()
            if loser_notes and loser_notes not in merged_notes:
                merged_notes = (
                    f"{merged_notes}\n\n--- merged from duplicate ---\n{loser_notes}"
                    if merged_notes
                    else loser_notes
                )

        relation_ids = self.runtime.notion.daily_log_founder_relation_ids(keeper)
        if not relation_ids:
            founder_page_id = self.runtime.notion.lookup_team_member_id(group["founder_name"])
            if founder_page_id:
                relation_ids = [founder_page_id]

        earliest_logged_at = self._earliest_logged_at_iso(rows)
        title_text = self.runtime.notion.daily_log_title(keeper)
        canonical_title = self._canonical_title(keeper, founder_name=group["founder_name"], logical_day=group["logical_day"])
        if not self._title_has_logical_day(title_text, group["logical_day"]):
            title_text = canonical_title

        update_kwargs: dict[str, Any] = {
            "title_text": title_text,
            "founder_name": group["founder_name"],
            "logical_day_iso": group["logical_day"],
            "task_ids": merged_task_ids,
            "notes_text": merged_notes,
        }
        if relation_ids:
            update_kwargs["founder_relation_ids"] = relation_ids
        if earliest_logged_at:
            update_kwargs["logged_at_iso"] = earliest_logged_at
        self.runtime.notion.update_daily_log(keeper_id, **update_kwargs)

        archived_ids: list[str] = []
        for loser in losers:
            loser_id = str(loser.get("id") or "").strip()
            self.runtime.notion.archive_page(loser_id)
            archived_ids.append(loser_id)

        result = self._serialize_group(group)
        result["merged_task_count"] = len(merged_task_ids)
        result["archived_ids"] = archived_ids
        result["keeper_updates"] = {
            "title": title_text,
            "logged_at_iso": earliest_logged_at,
            "founder_relation_ids": relation_ids,
        }
        return result

    def _canonical_title(self, row: dict[str, Any], *, founder_name: str, logical_day: str) -> str:
        week_code = self.runtime.notion.daily_log_week_code(row).strip()
        if week_code:
            return f"{founder_name} · {week_code} · {logical_day}"
        title = self.runtime.notion.daily_log_title(row)
        parts = [part.strip() for part in title.split("·")]
        if len(parts) >= 3:
            parts[0] = founder_name
            parts[-1] = logical_day
            return " · ".join(parts)
        return f"{founder_name} · {logical_day}"

    def _title_has_logical_day(self, title: str, logical_day: str) -> bool:
        parts = [part.strip() for part in str(title or "").split("·")]
        return bool(parts) and parts[-1] == logical_day

    def _earliest_logged_at_iso(self, rows: list[dict[str, Any]]) -> str | None:
        candidates: list[tuple[datetime, str]] = []
        for row in rows:
            raw = self.runtime.notion.daily_log_logged_at_iso(row)
            if not raw:
                continue
            try:
                candidates.append((madrid_datetime(raw), raw))
            except ValueError:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _row_created_at_sort_key(self, row: dict[str, Any]) -> tuple[datetime, str]:
        raw = str(row.get("created_time") or "").strip()
        try:
            return madrid_datetime(raw), raw
        except ValueError:
            return madrid_datetime("9999-12-31T23:59:59+00:00"), raw
