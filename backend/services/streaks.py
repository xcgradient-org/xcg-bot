from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Iterable

import pytz


LOGGER = logging.getLogger("xcg_bot.streaks")
MADRID_TZ = pytz.timezone("Europe/Madrid")
RESET_TIME = time(5, 0)


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


def compute_streak_from_log_dates(log_dates: Iterable[date], today: date, previous_best: int = 0) -> tuple[int, int, str | None]:
    dates = sorted({log_date for log_date in log_dates if log_date <= today})
    if not dates:
        return 0, previous_best, None

    best = 0
    run = 0
    previous: date | None = None
    for log_date in dates:
        if previous is not None and log_date == previous + timedelta(days=1):
            run += 1
        else:
            run = 1
        best = max(best, run)
        previous = log_date

    latest = dates[-1]
    date_set = set(dates)
    if latest < today - timedelta(days=1):
        current = 0
    else:
        current = 1
        cursor = latest
        while cursor - timedelta(days=1) in date_set:
            current += 1
            cursor -= timedelta(days=1)

    return current, max(previous_best, best), latest.isoformat()


def should_reset_streak(last_log_iso: str, today: date) -> bool:
    if not last_log_iso:
        return True
    last_log_date = date.fromisoformat(last_log_iso)
    yesterday = today - timedelta(days=1)
    return last_log_date < yesterday


async def reset_stale_streaks(notion) -> None:
    await sync_streaks_from_daily_logs(notion)


def sync_founder_streak_from_daily_logs(notion, founder_name: str, today: date | None = None) -> tuple[int, int, str | None]:
    today = today or datetime.now(MADRID_TZ).date()
    row = notion.get_streak_row(founder_name)
    current_streak, best_streak, last_log_iso = notion.streak_values(row)
    new_current, new_best, new_last_log_iso = compute_streak_from_log_dates(
        notion.daily_log_dates(founder_name),
        today,
        previous_best=best_streak,
    )
    if (current_streak, best_streak, last_log_iso or None) != (new_current, new_best, new_last_log_iso):
        notion.update_streak_row(
            row["id"],
            current_streak=new_current,
            best_streak=new_best,
            last_log_iso=new_last_log_iso,
        )
        LOGGER.info("Synced streak for %s from Daily Logs: current=%s best=%s.", founder_name, new_current, new_best)
    return new_current, new_best, new_last_log_iso


async def sync_streaks_from_daily_logs(notion) -> None:
    today = datetime.now(MADRID_TZ).date()
    rows = notion.get_all_streak_rows()
    for row in rows:
        founder_name = notion.founder_name(row)
        if not founder_name:
            continue
        try:
            sync_founder_streak_from_daily_logs(notion, founder_name, today)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to sync streak for %s from Daily Logs: %s", founder_name or row["id"], exc)


async def run_daily_maintenance(notion) -> None:
    await sync_streaks_from_daily_logs(notion)


def should_run_startup_reset(now: datetime) -> bool:
    return now.astimezone(MADRID_TZ).time() >= RESET_TIME


def seconds_until_next_reset(now: datetime) -> float:
    local_now = now.astimezone(MADRID_TZ)
    next_run_date = local_now.date()
    if local_now.time() >= RESET_TIME:
        next_run_date += timedelta(days=1)
    next_run = MADRID_TZ.localize(datetime.combine(next_run_date, RESET_TIME))
    return max((next_run - local_now).total_seconds(), 0.0)


async def daily_reset_loop(notion) -> None:
    try:
        LOGGER.info("Running startup Notion maintenance fallback.")
        await run_daily_maintenance(notion)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Startup Notion maintenance failed: %s", exc)

    while True:
        wait_seconds = seconds_until_next_reset(datetime.now(MADRID_TZ))
        LOGGER.info("Next streak reset scheduled in %.0f seconds.", wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await run_daily_maintenance(notion)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Daily Notion maintenance failed: %s", exc)


def start_daily_reset_task(bot, notion):
    return bot.loop.create_task(daily_reset_loop(notion))
