#!/usr/bin/env python3
"""Backfill the Logical Day property on Daily Log rows that have it empty.

Background: a previous Notion schema migration auto-renamed the date column
from "Logical Day" to "Logical Day 1". PROPERTY_ALIASES did not include the
new name, so create_daily_log silently skipped writing the property and
daily_log_dates silently returned empty for every row. After extending the
alias map, run this script once to fill in the date on historical rows so
streaks reflect actual logging history.

Logical day is derived in priority order:
1. The trailing date segment of the page title (`Founder · YY-WNN · YYYY-MM-DD`).
2. `logical_day_for_madrid(Logged At)` from backend.domain.dates.
3. `logical_day_for_madrid(created_time)` as a last resort.

Idempotent: rows that already have a Logical Day value are skipped.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parents[2]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from backend.domain.dates import logical_day_iso_for_madrid
from backend.integrations.notion import NotionService


def _logical_day_from_title(title: str) -> str | None:
    parts = [part.strip() for part in str(title or "").split("·")]
    if len(parts) < 2:
        return None
    candidate = parts[-1][:10]
    try:
        from datetime import date as _date

        _date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def _logical_day_from_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return logical_day_iso_for_madrid(value)
    except (ValueError, TypeError):
        return None


def main() -> int:
    load_dotenv()
    token = os.environ.get("NOTION_TOKEN")
    daily_logs_db = os.environ.get("NOTION_DAILY_LOGS_DB")
    tasks_db = os.environ.get("NOTION_TASKS_DB")
    team_db = os.environ.get("NOTION_TEAM_DB")
    if not (token and daily_logs_db and tasks_db and team_db):
        print("Missing required env: NOTION_TOKEN, NOTION_DAILY_LOGS_DB, NOTION_TASKS_DB, NOTION_TEAM_DB", file=sys.stderr)
        return 2

    service = NotionService(
        token=token,
        tasks_db_id=tasks_db,
        daily_logs_db_id=daily_logs_db,
        team_db_id=team_db,
        settings_db_id=os.environ.get("NOTION_SETTINGS_DB_ID"),
    )

    schema = service._retrieve_schema(daily_logs_db)
    logical_day_col = service._existing_property_name(schema, "Logical Day")
    if not logical_day_col:
        print("No 'Logical Day' column resolvable in schema. Extend PROPERTY_ALIASES.", file=sys.stderr)
        return 3

    rows = service._query_all(daily_logs_db)
    print(f"Scanning {len(rows)} Daily Log rows; populating '{logical_day_col}' where empty.")

    updated = 0
    skipped_already = 0
    skipped_no_date = 0
    for row in rows:
        if service._property_date(row, "Logical Day"):
            skipped_already += 1
            continue

        title = service._page_title(row)
        logged_at = service._property_date(row, "Logged At")
        created_time = str(row.get("created_time") or "")

        derived = (
            _logical_day_from_title(title)
            or _logical_day_from_datetime(logged_at)
            or _logical_day_from_datetime(created_time)
        )
        if not derived:
            skipped_no_date += 1
            print(f"  skip (no derivable date): id={row.get('id')} title={title!r}")
            continue

        service.client.pages.update(
            page_id=row["id"],
            properties={logical_day_col: {"date": {"start": derived}}},
        )
        updated += 1
        print(f"  set {logical_day_col}={derived} on id={row.get('id')} title={title!r}")

    print(
        f"\nDone. updated={updated} already_populated={skipped_already} skipped_no_date={skipped_no_date}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
