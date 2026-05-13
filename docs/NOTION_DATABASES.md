# Notion Database Reference

This document describes every Notion database accessible to the XC Gradient internal tooling integration.
It is the authoritative schema reference for all agents working on this repository.

**Last verified:** 2026-05-08

---

## Database Index

| Database | Notion ID | `.env` variable |
|----------|-----------|-----------------|
| [Team](#team) | `c7ed3e34702c4d26b310cc7d91b16a97` | `NOTION_TEAM_DB_ID` _(not yet in .env)_ |
| [Departments](#departments) | `e7539dd680f34c9abc1b4e1159167c8a` | `NOTION_DEPARTMENTS_DB_ID` _(not yet in .env)_ |
| [Tasks](#tasks) | `85e42f01c75647b5a9ecb2ca6ae26dbc` | `NOTION_TASKS_DB` |
| [Daily Logs](#daily-logs) | `9c40e6920dd6468190a050035f9a98b7` | `NOTION_DAILY_LOGS_DB` |
| [Meetings](#meetings) | `e654a7418d7e410c8072db8f7706ca3d` | `NOTION_MEETINGS_DB_ID` |
| [Projects](#projects) | `307784e81ddc41469f2466de0af51036` | `NOTION_PROJECTS_DB` _(not yet in .env)_ |
| [KRs](#krs) | `2b3c5815dd4943bb8c4dff005901fb1d` | `NOTION_KRS_DB` _(not yet in .env)_ |
| [Objectives](#objectives) | `1e4e9d72f9f5473abd43c1e0ecc53e49` | `NOTION_OBJECTIVES_DB` _(not yet in .env)_ |

> **Removed:** The old dedicated `Streaks` database no longer exists.
> Streak data (`Current Streak`, `Best Streak`, `Last Log`) now lives directly on the **Team** table.

---

## Relationship Map

```
Departments ──── Members ────┐
                             ▼
                           Team ◄──── Owner/Attendees/Founders ──── Tasks
                             │                                       Daily Logs
                             │                                       Meetings
                             │                                       KRs
                             │                                       Objectives
                             │                                       Projects
                             └──── Department ────► Departments
```

**Team is the central identity table.** Every other database links to Team for ownership,
authorship, and attendance. Never use plain text names for people — always resolve to a Team page.

---

## Team

**ID:** `c7ed3e34702c4d26b310cc7d91b16a97`

The single source of truth for team members. Replaces the old Streaks database — streak
counters are properties here now.

| Property | Type | Notes |
|----------|------|-------|
| `Name` | title | Display name, e.g. `Oriol`, `Arnau`, `Adam` |
| `Role` | select | `CEO`, `CTO`, `COO` |
| `Status` | select | `Active`, `Departed` |
| `User` | people | Linked Notion workspace user |
| `Department` | relation → Departments | Primary department |
| `Current Streak` | number | Days logged in a row |
| `Best Streak` | number | All-time best streak |
| `Last Log` | date | ISO date of most recent daily log |
| `Tasks` | relation → Tasks | All tasks owned by this member |
| `Daily Logs` | relation → Daily Logs | All EOD log entries |
| `Meetings` | relation → Meetings | Meetings attended |
| `KRs` | relation → KRs | Key Results owned |
| `Objectives` | relation → Objectives | Objectives owned |
| `Projects` | relation → Projects | Projects this member owns |

**Current members:** Oriol (CEO), Arnau (CTO), Adam (COO)

---

## Departments

**ID:** `e7539dd680f34c9abc1b4e1159167c8a`

Org chart. Tracks all departments, their status (active vs. planned), and their lead.

| Property | Type | Notes |
|----------|------|-------|
| `Name` | title | Department name, e.g. `Marketing`, `Legal`, `AI Research` |
| `C-Role` | select | C-suite role for this dept: `CEO`, `COO`, `CTO`, `CPO`, `CFO`, `CRO`, `CMO`, `CLO`, `CAIO` |
| `Status` | select | `Active`, `Embryonic`, `Future` |
| `Description` | rich_text | One-line department mandate |
| `Lead` | relation → Team | Department lead |
| `Members` | relation → Team | All members in this department |
| `Website` | url | External or internal website |
| `Headcount` | rollup | Computed count of Members |

---

## Tasks

**ID:** `85e42f01c75647b5a9ecb2ca6ae26dbc`

All work items. Scoped by week and owner. Each task belongs to one Project and one Owner.

| Property | Type | Notes |
|----------|------|-------|
| `Display ID` | title | Auto-generated ID, e.g. `ALPHA-CEO-45` |
| `Description` | rich_text | Full task description |
| `Status` | select | `Todo`, `Done`, `Archived` |
| `Done` | checkbox | Whether the task is complete |
| `Done date` | date | Datetime when marked done |
| `Week` | select | ISO week string, e.g. `26-W19` (year-week) |
| `Project` | relation → Projects | The project this task belongs to |
| `Owner` | relation → Team | The team member responsible |

**Week format:** `YY-WNN` — two-digit year, then `W` + zero-padded week number (e.g. `26-W05`).

---

## Daily Logs

**ID:** `9c40e6920dd6468190a050035f9a98b7`

One entry per founder per day. Created either when the founder clicks the manual end-of-day log button in the internal site, or automatically at the daily 05:00 Europe/Madrid finalization if they completed at least one task and still have no log.

| Property | Type | Notes |
|----------|------|-------|
| `Title` | title | Auto-formatted: `{Name} · {Week} · {YYYY-MM-DD}`, e.g. `Arnau · 26-W19 · 2026-05-06` |
| `Date` | date | Business-day datetime of the log. It stores the real clock time, but between `00:00` and `04:59` Madrid it still uses the previous business day. Example: a log created at `2026-05-08 01:12` can be stored as `2026-05-07 01:12`. |
| `Created on` | date | Exact datetime when the founder logged or when the automatic finalizer created the row. |
| `Founder` | relation → Team | **Relation**, not text. The team member who logged. |
| `Tasks completed` | relation → Tasks | Tasks marked done in this session |
| `Notes` | rich_text | Free-form EOD notes / reflection |

> **Breaking change from old schema:** `Founder` was previously a plain text/title field.
> It is now a **relation to Team**. Any code reading or writing this field must use relation IDs.

---

## Meetings

**ID:** `e654a7418d7e410c8072db8f7706ca3d`

Scheduled meetings. The background poller in `bot/commands/meetings.py` reads `Announced` and `Reminded`
to decide when to post to Discord.

| Property | Type | Notes |
|----------|------|-------|
| `Title` | title | e.g. `Weekly Meeting · 26-W20` |
| `Date` | date | Full datetime with timezone |
| `Type` | select | `Weekly Sync`, `Client`, `Investor`, `Other`, `Administrative` |
| `Mode` | select | `Online`, `In-person` |
| `Status` | status | `Pending`, `Missed => Contacted`, `Rescheduled`, `Completed`, `Archived` |
| `Attendees` | relation → Team | Who attends |
| `Attendee Roles` | rollup | Computed roles of Attendees (from Team.Role) |
| `Meeting link` | url | Video call URL |
| `Address` | rich_text | Physical address for in-person meetings |
| `Overview` | rich_text | Agenda or description |
| `TL;DR` | rich_text | Post-meeting summary |
| `Announced` | checkbox | Set to `true` once the bot has posted to #announcements |
| `Reminded` | checkbox | Set to `true` once the bot has posted a reminder |

---

## Projects

**ID:** `307784e81ddc41469f2466de0af51036`

Each project ties work (Tasks) to strategy (Objectives, KRs). Projects have a week-range
scope and an exit gate definition.

| Property | Type | Notes |
|----------|------|-------|
| `Name` | title | Project name, e.g. `ALPHA` |
| `Type` | select | `Company`, `Department`, `Client`, `Internal` |
| `Status` | select | `Active`, `Closed` |
| `Week start` | number | Starting week number (e.g. `16`) |
| `Week end` | number | Ending week number |
| `North Star` | rich_text | One-sentence project goal |
| `Exit Gate` | rich_text | Conditions that define project completion |
| `Owners` | relation → Team | Team members owning this project |
| `Objectives` | relation → Objectives | Strategic objectives this project advances |
| `KRs` | relation → KRs | Key results this project contributes to |

---

## KRs

**ID:** `2b3c5815dd4943bb8c4dff005901fb1d`

Key Results — the measurable outcomes under each Objective. Part of the OKR framework.

| Property | Type | Notes |
|----------|------|-------|
| `Title` | title | e.g. `KR3: OEE before/after metrics documented for both` |
| `Status` | status | `To Do`, `In Progress`, `Done` |
| `Period` | select | `2026`, `2027`, `2028`, `26-Q1`, `26-Q2`, `26-Q3`, `26-Q4` |
| `Owner` | relation → Team | Team member(s) accountable |
| `Objective` | relation → Objectives | The parent objective |
| `Projects` | relation → Projects | Projects contributing to this KR |
| `Notes` | rich_text | Supporting context or progress notes |

---

## Objectives

**ID:** `1e4e9d72f9f5473abd43c1e0ecc53e49`

Top-level strategic goals. Can be nested (parent/child). Progress is a formula over linked KRs.

| Property | Type | Notes |
|----------|------|-------|
| `Title` | title | e.g. `O1 · Product — Validate the core product end-to-end` |
| `Period` | select | `2026`, `2027`, `2028`, `26-Q1`, `26-Q2`, `26-Q3`, `26-Q4` |
| `Progress %` | formula | Computed from KR statuses |
| `Owner` | relation → Team | Team member(s) accountable |
| `KRs` | relation → KRs | Key Results under this objective |
| `Parent Objective` | relation → Objectives | Parent in the objective tree |
| `Child Objectives` | relation → Objectives | Children in the objective tree |
| `Notes` | rich_text | Supporting context |

---

## Bot Code vs. Current Schema

Known mismatches between `notion.py` / `.env` and the live schema:

| Area | Old (code) | Current (Notion) | Action needed |
|------|-----------|-------------------|---------------|
| Streaks | Separate `NOTION_STREAKS_DB` database | Fields on **Team** table | Migrate `NotionService` streak methods to read/write Team |
| Daily Logs founder | Text/title field | `Founder` is a **relation** → Team | Update `_daily_log_founder_value()` and `create_daily_log()` |
| Meetings attendees | No attendee tracking | `Attendees` relation → Team | Wire up when building attendee-aware features |
| `.env` | Missing `NOTION_TEAM_DB_ID`, `NOTION_DEPARTMENTS_DB_ID` | Both DBs exist and are accessible | Add env vars |
| `.env` | `NOTION_LOG_DB_ID` concatenated onto `GEMINI_API_KEY` line | That database no longer exists | Remove the broken line |
