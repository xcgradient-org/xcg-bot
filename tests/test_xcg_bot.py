from __future__ import annotations

import sys
import unittest
from pathlib import Path
import datetime as dt
from unittest.mock import MagicMock, patch


BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

import log_command
import main
import meeting_command
import meetings
import notion
import reflection
import streaks
import task_command


class LoadSettingsTests(unittest.TestCase):
    @patch("main.load_environment")
    def test_load_settings_uses_legacy_notion_env_names(self, load_environment: MagicMock) -> None:
        load_environment.return_value = Path("/tmp/fake.env")
        env = {
            "DISCORD_TOKEN": "discord-token",
            "NOTION_TOKEN": "notion-token",
            "DISCORD_USER_ID_ORIOL": "111",
            "DISCORD_USER_ID_ARNAU": "222",
            "DISCORD_USER_ID_ADAM": "333",
            "NOTION_TASKS_DB": "tasks-db",
            "NOTION_DAILY_LOGS_DB": "daily-db",
            "NOTION_STREAKS_DB": "streaks-db",
            "NOTION_MEETINGS_DB_ID": "meetings-db",
            "DISCORD_BLOCKERS_CHANNEL_ID": "123",
            "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": "456",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = main.load_settings()

        self.assertEqual(settings.notion_tasks_db_id, "tasks-db")
        self.assertEqual(settings.notion_daily_logs_db_id, "daily-db")
        self.assertEqual(settings.notion_streaks_db_id, "streaks-db")
        self.assertEqual(settings.notion_meetings_db_id, "meetings-db")
        self.assertEqual(settings.discord_user_id_oriol, 111)
        self.assertEqual(settings.discord_user_id_arnau, 222)
        self.assertEqual(settings.discord_user_id_adam, 333)
        self.assertEqual(settings.discord_blockers_channel_id, 123)
        self.assertEqual(settings.discord_announcements_channel_id, 456)
        self.assertEqual(settings.ollama_base_url, "http://127.0.0.1:11434")
        self.assertEqual(settings.ollama_model, "qwen2.5:32b")


class ReflectionServiceTests(unittest.TestCase):
    def test_extract_text_returns_first_non_empty_part(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        payload = {"response": "first answer"}
        self.assertEqual(service._extract_text(payload), "first answer")

    def test_verify_startup_accepts_installed_model(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_get_json", return_value={"models": [{"name": "qwen2.5:32b"}]}) as get_json:
            service.verify_startup()
        get_json.assert_called_once_with("/api/tags")

    def test_verify_startup_raises_if_model_missing(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_get_json", return_value={"models": [{"name": "llama3.1:8b"}]}):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                service.verify_startup()

    def test_generate_json_response_parses_json_payload(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_ollama_request", return_value={"response": '{"ok": true, "count": 2}'}):
            payload = service.generate_json_response(system_prompt="s", user_prompt="u")
        self.assertEqual(payload, {"ok": True, "count": 2})

    def test_generate_reflection_raises_on_empty_response(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_ollama_request", return_value={"response": ""}):
            with patch.object(service, "_gemini_text", return_value=""):
                with self.assertRaisesRegex(RuntimeError, "empty reflection"):
                    service.generate_reflection(
                        founder_name="Oriol",
                        founder_role="CEO",
                        today_iso="2026-04-10",
                        completed_tasks=["Task A"],
                        raw_notes="",
                    )

    def test_build_fallback_reflection_includes_tasks_and_notes(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")

        note = service.build_fallback_reflection(
            founder_name="Oriol",
            founder_role="CEO",
            today_iso="2026-04-16",
            completed_tasks=["Task A", "Task B"],
            raw_notes="Need follow-up tomorrow.",
        )

        self.assertIn("2026-04-16", note)
        self.assertIn("Task A; Task B", note)
        self.assertIn("Need follow-up tomorrow.", note)


class StreakTests(unittest.TestCase):
    def test_compute_updated_streak_increments_from_yesterday(self) -> None:
        current, best = streaks.compute_updated_streak("2026-04-09", 3, 4, streaks.date(2026, 4, 10))
        self.assertEqual(current, 4)
        self.assertEqual(best, 4)

    def test_compute_updated_streak_resets_after_gap(self) -> None:
        current, best = streaks.compute_updated_streak("2026-04-01", 8, 10, streaks.date(2026, 4, 10))
        self.assertEqual(current, 1)
        self.assertEqual(best, 10)

    def test_should_reset_streak_only_if_last_log_before_yesterday(self) -> None:
        today = streaks.date(2026, 4, 10)
        self.assertFalse(streaks.should_reset_streak("2026-04-09", today))
        self.assertFalse(streaks.should_reset_streak("2026-04-10", today))
        self.assertTrue(streaks.should_reset_streak("2026-04-08", today))


class LogCommandTests(unittest.TestCase):
    def test_rewrite_blocker_message_uses_llm_response(self) -> None:
        state = MagicMock()
        state.founder = {"name": "Oriol", "role": "CEO"}
        state.notion.task_descriptions.return_value = ["API integration"]
        state.reflection.generate_json_response.return_value = {
            "message": "I need the final schema confirmation to finish the API integration today."
        }

        message = log_command._rewrite_blocker_message(
            state,
            [],
            target_role="CTO",
            raw_notes="Blocked on schema details.",
            raw_blocker="Need schema help from CTO.",
        )

        self.assertEqual(
            message,
            "I need the final schema confirmation to finish the API integration today.",
        )

    def test_build_blocker_message_mentions_configured_user(self) -> None:
        settings = MagicMock()
        settings.discord_user_id_oriol = 111
        settings.discord_user_id_arnau = 222
        settings.discord_user_id_adam = 333

        message = log_command.build_blocker_message(
            "Oriol",
            "CTO",
            "I need the final schema to finish the API integration.",
            settings,
        )

        self.assertIn("<@222>", message)
        self.assertIn("Oriol", message)

    def test_build_blocker_message_marks_urgent_when_requested(self) -> None:
        settings = MagicMock()
        settings.discord_user_id_oriol = 111
        settings.discord_user_id_arnau = 222
        settings.discord_user_id_adam = 333

        message = log_command.build_blocker_message(
            "Oriol",
            "CTO",
            "I need the final schema to finish the API integration.",
            settings,
            urgent=True,
        )

        self.assertIn("URGENT", message)
        self.assertIn("<@222>", message)

    def test_current_context_uses_previous_day_before_5am_madrid(self) -> None:
        now = log_command.MADRID_TZ.localize(dt.datetime(2026, 4, 13, 1, 30))

        ctx = log_command.current_context(now)

        self.assertEqual(ctx.today_iso, "2026-04-12")
        self.assertEqual(ctx.week_code, "26-W15")


class MeetingCommandTests(unittest.TestCase):
    def test_normalize_attendees_splits_slashes_and_commas(self) -> None:
        attendees = meeting_command._normalize_attendees("CEO / CTO, COO")
        self.assertEqual(attendees, ["CEO", "CTO", "COO"])

    def test_attendee_choice_all_maps_to_all_founders(self) -> None:
        self.assertEqual(meeting_command.ATTENDEE_CHOICES[0].value, "CEO, CTO, COO")

    def test_try_parse_user_datetime_uses_strict_madrid_format(self) -> None:
        date_iso = meeting_command._try_parse_user_datetime("2026-04-17 11:00", default_year=2026)
        self.assertEqual(date_iso, "2026-04-17T11:00:00+02:00")

    def test_try_parse_user_datetime_accepts_month_day_without_year(self) -> None:
        date_iso = meeting_command._try_parse_user_datetime("04-17 11:00", default_year=2026)
        self.assertEqual(date_iso, "2026-04-17T11:00:00+02:00")

    def test_try_parse_user_datetime_handles_this_friday_relative_to_today(self) -> None:
        base_now = meeting_command.MADRID_TZ.localize(dt.datetime(2026, 4, 12, 16, 0))
        date_iso = meeting_command._try_parse_user_datetime("this friday", default_year=2026, base_now=base_now)
        self.assertEqual(date_iso, "2026-04-17T10:00:00+02:00")

    def test_normalize_payload_uses_ai_date_when_present(self) -> None:
        raw_input = {
            "title": "Weekly Sync",
            "date_input": "Friday 17 April at 11",
            "type": "Weekly Sync",
            "attendees": "CEO, CTO, COO",
            "location": "Meet room",
            "notes": "Discuss blockers",
        }
        ai_payload = {
            "title": "Weekly Sync",
            "date_iso": "2026-04-17T11:00:00+02:00",
            "attendees": ["CEO", "CTO", "COO"],
            "notes_enhanced": "Discuss blockers clearly.",
        }
        payload = meeting_command._normalize_payload(raw_input, ai_payload)
        self.assertEqual(payload["date_iso"], "2026-04-17T11:00:00+02:00")
        self.assertEqual(payload["notes_enhanced"], "Discuss blockers clearly.")

    def test_normalize_payload_falls_back_to_raw_input(self) -> None:
        raw_input = {
            "title": "Weekly Sync",
            "date_input": "2026-04-14 10:00",
            "date_iso": "2026-04-14T10:00:00+02:00",
            "type": "Weekly Sync",
            "attendees": "CEO, CTO, COO",
            "location": "Meet room",
            "notes": "Discuss blockers",
        }
        payload = meeting_command._normalize_payload(raw_input, None)
        self.assertEqual(payload["title"], "Weekly Sync")
        self.assertEqual(payload["attendees"], ["CEO", "CTO", "COO"])
        self.assertEqual(payload["location"], "Meet room")
        self.assertEqual(payload["notes_enhanced"], "Discuss blockers")

    def test_build_confirmation_omits_notes_when_empty(self) -> None:
        payload = {
            "title": "Client Call",
            "date_iso": "2026-04-14T10:00:00+02:00",
            "type": "Client",
            "attendees": ["CEO", "COO"],
            "location": "Zoom",
            "notes_enhanced": "",
        }
        message = meeting_command._build_confirmation(payload)
        self.assertIn("Client — Tuesday 14 April, 10:00", message)
        self.assertNotIn("📝", message)
        self.assertIn("Posted in #announcements.", message)


class TaskCommandTests(unittest.TestCase):
    def test_normalize_task_descriptions_deduplicates_and_cleans(self) -> None:
        payload = {
            "tasks": [
                {"description": "  Draft investor update  "},
                {"description": "Draft investor update"},
                {"description": "Prepare demo script"},
            ]
        }

        descriptions = task_command._normalize_task_descriptions(payload)

        self.assertEqual(descriptions, ["Draft investor update", "Prepare demo script"])

    def test_fallback_task_descriptions_splits_two_task_request(self) -> None:
        descriptions = task_command._fallback_task_descriptions("add 2 tasks: draft investor update and prepare demo script")

        self.assertEqual(descriptions, ["draft investor update", "prepare demo script"])

    def test_parse_task_descriptions_uses_fallback_when_llm_returns_invalid_payload(self) -> None:
        reflection_service = MagicMock()
        reflection_service.generate_json_response.return_value = {"unexpected": []}

        descriptions = task_command._parse_task_descriptions(
            reflection_service,
            "add 2 tasks: draft investor update and prepare demo script",
        )

        self.assertEqual(descriptions, ["draft investor update", "prepare demo script"])


class NotionTaskCreationTests(unittest.TestCase):
    def test_list_projects_uses_related_database(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks-db", daily_logs_db_id="daily", streaks_db_id="streaks")
        with patch.object(service, "_retrieve_schema", return_value={"Project": {"type": "relation", "relation": {"database_id": "projects-db"}}}):
            with patch.object(
                service,
                "_query_all",
                return_value=[
                    {"id": "proj-1", "properties": {"Name": {"type": "title", "title": [{"plain_text": "ALPHA"}]}}},
                    {"id": "proj-2", "properties": {"Name": {"type": "title", "title": [{"plain_text": "NEON"}]}}},
                ],
            ):
                projects = service.list_projects()

        self.assertEqual(projects, [{"id": "proj-1", "name": "ALPHA"}, {"id": "proj-2", "name": "NEON"}])

    def test_preview_task_ids_counts_matching_project_role_quarter_year(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks-db", daily_logs_db_id="daily", streaks_db_id="streaks")
        tasks = [
            {
                "id": "task-1",
                "properties": {
                    "Display ID": {"type": "title", "title": [{"plain_text": "ALPHA-CEO-1"}]},
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Year": {"type": "number", "number": 2026},
                    "Quarter": {"type": "select", "select": {"name": "Q2 2026"}},
                    "Project": {"type": "relation", "relation": [{"id": "proj-1"}]},
                },
            },
            {
                "id": "task-2",
                "properties": {
                    "Display ID": {"type": "title", "title": [{"plain_text": "ALPHA-CEO-2"}]},
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Year": {"type": "number", "number": 2026},
                    "Quarter": {"type": "select", "select": {"name": "Q2 2026"}},
                    "Project": {"type": "relation", "relation": [{"id": "proj-1"}]},
                },
            },
            {
                "id": "task-3",
                "properties": {
                    "Display ID": {"type": "title", "title": [{"plain_text": "ALPHA-CTO-1"}]},
                    "Role": {"type": "select", "select": {"name": "CTO"}},
                    "Year": {"type": "number", "number": 2026},
                    "Quarter": {"type": "select", "select": {"name": "Q2 2026"}},
                    "Project": {"type": "relation", "relation": [{"id": "proj-1"}]},
                },
            },
        ]
        with patch.object(service, "_retrieve_schema", return_value={"Project": {"type": "relation"}}):
            with patch.object(service, "_query_all", return_value=tasks):
                preview_ids = service.preview_task_ids(
                    project_id="proj-1",
                    project_name="ALPHA",
                    role="CEO",
                    year=2026,
                    quarter_name="Q2 2026",
                    count=2,
                )

        self.assertEqual(preview_ids, ["ALPHA-CEO-3", "ALPHA-CEO-4"])

    def test_create_tasks_batch_builds_expected_properties(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks-db", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.data_sources = None
        schema = {
            "Display ID": {"type": "title"},
            "Role": {"type": "select", "select": {"options": [{"name": "CEO"}]}},
            "Project": {"type": "relation"},
            "Description": {"type": "rich_text"},
            "Year": {"type": "number"},
            "Quarter": {"type": "select", "select": {"options": [{"name": "Q2 2026"}]}},
            "Month": {"type": "select", "select": {"options": [{"name": "Apr"}]}},
            "Week": {"type": "select", "select": {"options": [{"name": "26-W16"}]}},
            "Status": {"type": "checkbox"},
            "Done date": {"type": "date"},
        }
        with patch.object(service, "_retrieve_schema", return_value=schema):
            with patch.object(service, "preview_task_ids", return_value=["ALPHA-CEO-1", "ALPHA-CEO-2"]):
                service.create_tasks_batch(
                    project_id="proj-1",
                    project_name="ALPHA",
                    role="CEO",
                    descriptions=["Draft investor update", "Prepare demo script"],
                    year=2026,
                    quarter_name="Q2 2026",
                    month_name="Apr",
                    week_code="26-W16",
                    today_iso="2026-04-16",
                )

        create_calls = service.client.pages.create.call_args_list
        self.assertEqual(len(create_calls), 2)
        first_kwargs = create_calls[0].kwargs
        self.assertEqual(first_kwargs["parent"], {"database_id": "tasks-db"})
        self.assertEqual(
            first_kwargs["properties"]["Display ID"]["title"][0]["text"]["content"],
            "ALPHA-CEO-1",
        )
        self.assertEqual(first_kwargs["properties"]["Role"]["select"]["name"], "CEO")
        self.assertEqual(first_kwargs["properties"]["Project"]["relation"], [{"id": "proj-1"}])
        self.assertEqual(
            first_kwargs["properties"]["Description"]["rich_text"][0]["text"]["content"],
            "Draft investor update",
        )
        self.assertEqual(first_kwargs["properties"]["Year"]["number"], 2026)
        self.assertEqual(first_kwargs["properties"]["Quarter"]["select"]["name"], "Q2 2026")
        self.assertEqual(first_kwargs["properties"]["Month"]["select"]["name"], "Apr")
        self.assertEqual(first_kwargs["properties"]["Week"]["select"]["name"], "26-W16")
        self.assertFalse(first_kwargs["properties"]["Status"]["checkbox"])
        self.assertIsNone(first_kwargs["properties"]["Done date"]["date"])


class MeetingsFormattingTests(unittest.TestCase):
    def test_format_message_includes_notes_when_present(self) -> None:
        page = {
            "properties": {
                "Type": {"type": "select", "select": {"name": "Weekly Sync"}},
                "Date": {"type": "date", "date": {"start": "2026-04-14T10:00:00+02:00"}},
                "Attendees": {"type": "multi_select", "multi_select": [{"name": "CEO"}, {"name": "CTO"}]},
                "Location": {"type": "rich_text", "rich_text": [{"plain_text": "HQ"}]},
                "Notes": {"type": "rich_text", "rich_text": [{"plain_text": "Agenda ready"}]},
            }
        }
        message = meetings._format_message("📅 @everyone New meeting scheduled!", page)
        self.assertIn("Weekly Sync — Tuesday 14 April, 10:00", message)
        self.assertIn("👥 CEO, CTO", message)
        self.assertIn("📍 HQ", message)
        self.assertIn("📝 Agenda ready", message)


class NotionServiceTests(unittest.TestCase):
    def test_is_task_done_supports_checkbox_and_status(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        checkbox_page = {"properties": {"Status": {"type": "checkbox", "checkbox": True}}}
        status_page = {"properties": {"Status": {"type": "status", "status": {"name": "Done"}}}}
        select_page = {"properties": {"Status": {"type": "select", "select": {"name": "Completed"}}}}
        self.assertTrue(service._is_task_done(checkbox_page))
        self.assertTrue(service._is_task_done(status_page))
        self.assertTrue(service._is_task_done(select_page))

    def test_query_all_uses_data_source_query_when_database_query_missing(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        del service.client.databases.query
        service.client.databases.retrieve.return_value = {
            "data_sources": [{"id": "source-123"}],
        }
        service.client.data_sources.query.return_value = {
            "results": [{"id": "page-1"}],
            "has_more": False,
            "next_cursor": None,
        }

        result = service._query_all("db-123")

        self.assertEqual(result, [{"id": "page-1"}])
        service.client.databases.retrieve.assert_called_once_with(database_id="db-123")
        service.client.data_sources.query.assert_called_once_with(data_source_id="source-123", page_size=100)

    def test_primary_data_source_id_returns_first_source(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.databases.retrieve.return_value = {
            "data_sources": [{"id": "source-123"}, {"id": "source-456"}],
        }

        result = service.primary_data_source_id("db-123")

        self.assertEqual(result, "source-123")
        service.client.databases.retrieve.assert_called_once_with(database_id="db-123")

    def test_query_log_tasks_combines_done_today_and_current_week(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        tasks = [
            {
                "id": "done-today",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-04-10"}},
                    "Week": {"type": "select", "select": {"name": "26-W15"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Done today"}]},
                },
            },
            {
                "id": "todo-this-week",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": False},
                    "Done date": {"type": "date", "date": None},
                    "Week": {"type": "select", "select": {"name": "26-W15"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Todo this week"}]},
                },
            },
            {
                "id": "ignore-other-role",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CTO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-04-10"}},
                    "Week": {"type": "select", "select": {"name": "26-W15"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Other role"}]},
                },
            },
        ]
        with patch.object(service, "_query_all", return_value=tasks):
            candidates, completed, active_week = service.query_log_tasks("CEO", "2026-04-10", "26-W15")

        self.assertEqual([task["id"] for task in candidates], ["done-today", "todo-this-week"])
        self.assertEqual([task["id"] for task in completed], ["done-today"])
        self.assertEqual(active_week, "26-W15")

    def test_query_log_tasks_falls_back_to_latest_week_and_legacy_done_tasks(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        tasks = [
            {
                "id": "done-no-date",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": None},
                    "Week": {"type": "select", "select": {"name": "26-W16"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Legacy done"}]},
                },
            },
            {
                "id": "todo-same-week",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": False},
                    "Done date": {"type": "date", "date": None},
                    "Week": {"type": "select", "select": {"name": "26-W16"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Todo later"}]},
                },
            },
        ]
        with patch.object(service, "_query_all", return_value=tasks):
            candidates, completed, active_week = service.query_log_tasks("CEO", "2026-04-12", "26-W15")

        self.assertEqual([task["id"] for task in candidates], ["done-no-date", "todo-same-week"])
        self.assertEqual([task["id"] for task in completed], ["done-no-date"])
        self.assertEqual(active_week, "26-W16")

    def test_query_log_tasks_excludes_tasks_done_on_other_days(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        tasks = [
            {
                "id": "done-yesterday",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-04-11"}},
                    "Week": {"type": "select", "select": {"name": "26-W16"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Done yesterday"}]},
                },
            },
            {
                "id": "todo-today",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": False},
                    "Done date": {"type": "date", "date": None},
                    "Week": {"type": "select", "select": {"name": "26-W16"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Still open"}]},
                },
            },
        ]
        with patch.object(service, "_query_all", return_value=tasks):
            candidates, completed, active_week = service.query_log_tasks("CEO", "2026-04-12", "26-W16")

        self.assertEqual([task["id"] for task in candidates], ["todo-today"])
        self.assertEqual(completed, [])
        self.assertEqual(active_week, "26-W16")

    def test_set_task_completion_checkbox_clears_done_date(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.databases.retrieve.return_value = {
            "properties": {
                "Status": {"type": "checkbox"},
            }
        }
        task = {
            "id": "page-1",
            "properties": {
                "Status": {"type": "checkbox", "checkbox": True},
            },
        }

        service.set_task_completion(task, completed=False, today_iso="2026-04-10")

        service.client.pages.update.assert_called_once_with(
            page_id="page-1",
            properties={
                "Status": {"checkbox": False},
                "Done date": {"date": None},
            },
        )

    def test_has_daily_log_matches_founder_and_date_prefix(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        rows = [
            {
                "properties": {
                    "Founder": {"type": "select", "select": {"name": "Oriol"}},
                    "Date": {"type": "date", "date": {"start": "2026-04-12T01:20:00+02:00"}},
                }
            }
        ]
        with patch.object(service, "_query_all", return_value=rows):
            result = service.has_daily_log("Oriol", "2026-04-12")

        self.assertTrue(result)

    def test_create_daily_log_builds_expected_properties(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.data_sources = None

        service.create_daily_log(
            founder_name="Oriol",
            founder_role="CEO",
            week_code="26-W15",
            today_iso="2026-04-10",
            completed_task_ids=["page-1", "page-2"],
            notes_text="reflection",
        )

        _, kwargs = service.client.pages.create.call_args
        self.assertEqual(kwargs["parent"], {"database_id": "daily-db"})
        self.assertEqual(kwargs["properties"]["Founder"]["select"]["name"], "Oriol")
        self.assertEqual(kwargs["properties"]["Role"]["select"]["name"], "CEO")
        self.assertEqual(kwargs["properties"]["Week"]["select"]["name"], "26-W15")
        self.assertEqual(kwargs["properties"]["Tasks completed"]["relation"], [{"id": "page-1"}, {"id": "page-2"}])
        self.assertEqual(kwargs["properties"]["Notes"]["rich_text"][0]["text"]["content"], "reflection")


if __name__ == "__main__":
    unittest.main()
