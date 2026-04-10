from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta

import pytz


LOGGER = logging.getLogger("xcg_bot.streaks")
MADRID_TZ = pytz.timezone("Europe/Madrid")


def compute_updated_streak(last_log_iso: str, current_streak: int, best_streak: int, today: date) -> tuple[int, int]:
    if not last_log_iso:
        new_current = 1
    else:
        last_log_date = date.fromisoformat(last_log_iso)
        yesterday = today - timedelta(days=1)
        if last_log_date == today:
            # Avoid double-incrementing if /log is run twice on the same day.
            new_current = current_streak or 1
        elif last_log_date == yesterday:
            new_current = current_streak + 1
        else:
            new_current = 1

    new_best = max(best_streak, new_current)
    return new_current, new_best


def should_reset_streak(last_log_iso: str, today: date) -> bool:
    if not last_log_iso:
        return True
    last_log_date = date.fromisoformat(last_log_iso)
    yesterday = today - timedelta(days=1)
    return last_log_date < yesterday


async def reset_stale_streaks(notion) -> None:
    today = datetime.now(MADRID_TZ).date()
    rows = notion.get_all_streak_rows()
    for row in rows:
        founder_name = notion.founder_name(row)
        current_streak, best_streak, last_log_iso = notion.streak_values(row)
        if not should_reset_streak(last_log_iso, today):
            continue
        try:
            notion.update_streak_row(
                row["id"],
                current_streak=0,
                best_streak=best_streak,
                last_log_iso=None,
            )
            LOGGER.info("Reset streak for %s to 0.", founder_name or row["id"])
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to reset streak for %s: %s", founder_name or row["id"], exc)


def seconds_until_next_reset(now: datetime) -> float:
    local_now = now.astimezone(MADRID_TZ)
    next_run_date = local_now.date()
    if local_now.time() >= time(5, 0):
        next_run_date += timedelta(days=1)
    next_run = MADRID_TZ.localize(datetime.combine(next_run_date, time(5, 0)))
    return max((next_run - local_now).total_seconds(), 0.0)


async def daily_reset_loop(notion) -> None:
    while True:
        wait_seconds = seconds_until_next_reset(datetime.now(MADRID_TZ))
        LOGGER.info("Next streak reset scheduled in %.0f seconds.", wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await reset_stale_streaks(notion)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Daily streak reset failed: %s", exc)


def start_daily_reset_task(bot, notion):
    return bot.loop.create_task(daily_reset_loop(notion))
