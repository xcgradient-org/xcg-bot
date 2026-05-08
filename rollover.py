#!/usr/bin/env python3
"""
Notion Task Rollover Script
Moves incomplete tasks from the current week to the next week.
"""

import argparse
import logging
import sys

from main import load_settings
from notion import NotionService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
LOGGER = logging.getLogger("rollover")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollover incomplete Notion tasks to the next week.")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without modifying Notion.")
    parser.add_argument("--sync-only", action="store_true", help="Only sync 'Is Current Week' flags for from_week without rolling over.")
    parser.add_argument("--force-from-week", help="Override the current week read from Settings (YY-WNN).")
    args = parser.parse_args()

    try:
        settings = load_settings()
        notion = NotionService(
            token=settings.notion_token,
            tasks_db_id=settings.notion_tasks_db_id,
            daily_logs_db_id=settings.notion_daily_logs_db_id,
            streaks_db_id=settings.notion_streaks_db_id,
            settings_db_id=settings.notion_settings_db_id,
        )

        from_week = args.force_from_week or notion.get_current_week_from_settings()
        to_week = notion.get_next_week_code(from_week)

        if args.sync_only:
            LOGGER.info("Starting sync-only mode for week %s (Dry run: %s)", from_week, args.dry_run)
            if not args.dry_run:
                notion.set_is_current_week_flags("", from_week)  # "" ensures it only focuses on setting flags for from_week
                LOGGER.info("Flags synced for week %s.", from_week)
            else:
                LOGGER.info("[DRY RUN] Would sync flags for week %s.", from_week)
            return

        LOGGER.info("Starting rollover from %s to %s (Dry run: %s)", from_week, to_week, args.dry_run)

        tasks_to_move = notion.find_incomplete_tasks_for_week(from_week)
        LOGGER.info("Found %d incomplete tasks to rollover.", len(tasks_to_move))

        if not args.dry_run:
            for task in tasks_to_move:
                display_id = notion.task_display_id(task)
                LOGGER.info("Rolling over task: %s", display_id)
                notion.rollover_task(task, to_week)

            LOGGER.info("Updating 'Is Current Week' flags...")
            notion.set_is_current_week_flags(from_week, to_week)

            LOGGER.info("Updating settings to week %s...", to_week)
            notion.set_current_week_in_settings(to_week, status="success", count=len(tasks_to_move))
        else:
            for task in tasks_to_move:
                display_id = notion.task_display_id(task)
                LOGGER.info("[DRY RUN] Would rollover task: %s", display_id)
            LOGGER.info("[DRY RUN] Would update flags and settings.")

        LOGGER.info("Rollover completed successfully.")

    except Exception as exc:
        LOGGER.error("Rollover failed: %s", exc, exc_info=True)
        if 'notion' in locals() and not args.dry_run:
            try:
                # Attempt to log failure to Notion if possible
                from_week = locals().get('from_week', 'unknown')
                notion.set_current_week_in_settings(from_week, status="fail", count=0)
            except Exception as nested_exc:
                LOGGER.error("Failed to log rollover failure to Notion: %s", nested_exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
