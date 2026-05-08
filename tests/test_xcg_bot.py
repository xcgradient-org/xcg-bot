from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch


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
    def test_load_environment_prefers_bot_local_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bot_env = Path(tmpdir) / "xcg-bot.env"
            root_env = Path(tmpdir) / "root.env"
            bot_env.write_text("DISCORD_TOKEN=test\n", encoding="utf-8")
            root_env.write_text("DISCORD_TOKEN=test\n", encoding="utf-8")

            with patch.object(main, "ENV_PATHS", (bot_env, root_env)):
                with patch("main.load_dotenv") as load_dotenv:
                    env_path = main.load_environment()

        self.assertEqual(env_path, bot_env)
        load_dotenv.assert_called_once_with(bot_env)

    def test_load_environment_falls_back_to_parent_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_bot_env = Path(tmpdir) / "missing.env"
            root_env = Path(tmpdir) / "root.env"
            root_env.write_text("DISCORD_TOKEN=test\n", encoding="utf-8")

            with patch.object(main, "ENV_PATHS", (missing_bot_env, root_env)):
                with patch("main.load_dotenv") as load_dotenv:
                    env_path = main.load_environment()

        self.assertEqual(env_path, root_env)
        load_dotenv.assert_called_once_with(root_env)

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
            "NOTION_SETTINGS_DB_ID": "settings-db",
            "DISCORD_BLOCKERS_CHANNEL_ID": "123",
            "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": "456",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("main.default_llm_settings", return_value=("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", ("key-1", "key-2"), "openai")):
                settings = main.load_settings()

        self.assertEqual(settings.notion_tasks_db_id, "tasks-db")
        self.assertEqual(settings.notion_daily_logs_db_id, "daily-db")
        self.assertEqual(settings.notion_streaks_db_id, "streaks-db")
        self.assertEqual(settings.notion_meetings_db_id, "meetings-db")
        self.assertEqual(settings.notion_settings_db_id, "settings-db")
        self.assertEqual(settings.discord_user_id_oriol, 111)
        self.assertEqual(settings.discord_user_id_arnau, 222)
        self.assertEqual(settings.discord_user_id_adam, 333)
        self.assertEqual(settings.discord_blockers_channel_id, 123)
        self.assertEqual(settings.discord_announcements_channel_id, 456)
        self.assertEqual(settings.llm_base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(settings.llm_model, "openai/gpt-oss-20b")
        self.assertEqual(settings.llm_api_key, "key-1")
        self.assertEqual(settings.llm_api_keys, ("key-1", "key-2"))
        self.assertEqual(settings.llm_api_style, "openai")

    @patch("main.load_environment")
    def test_load_settings_allows_missing_settings_db_id(self, load_environment: MagicMock) -> None:
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
            with patch("main.default_llm_settings", return_value=("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", (), "openai")):
                settings = main.load_settings()

        self.assertIsNone(settings.notion_settings_db_id)

    def test_default_llm_settings_uses_groq_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            base_url, model, api_keys, api_style = main.default_llm_settings()

        self.assertEqual(base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(model, "openai/gpt-oss-20b")
        self.assertEqual(api_keys, ())
        self.assertEqual(api_style, "openai")

    def test_default_llm_settings_collects_multiple_api_keys(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_BASE_URL": "https://api.groq.com/openai/v1",
                "LLM_MODEL": "openai/gpt-oss-20b",
                "LLM_API_KEY": "key-1",
                "LLM_API_KEY_2": "key-2",
                "LLM_API_KEYS": "key-2,key-3",
                "GROQ_API_KEY_3": "key-4",
                "LLM_API_STYLE": "openai",
            },
            clear=True,
        ):
            base_url, model, api_keys, api_style = main.default_llm_settings()

        self.assertEqual(base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(model, "openai/gpt-oss-20b")
        self.assertEqual(api_keys, ("key-1", "key-2", "key-4", "key-3"))
        self.assertEqual(api_style, "openai")

    def test_default_llm_settings_rejects_local_api_style(self) -> None:
        with patch.dict("os.environ", {"LLM_API_STYLE": "ollama"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Only LLM_API_STYLE=openai"):
                main.default_llm_settings()


class ReflectionServiceTests(unittest.TestCase):
    def test_extract_text_returns_first_non_empty_part(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        payload = {"response": "first answer"}
        self.assertEqual(service._extract_text(payload), "first answer")

    def test_extract_text_supports_openai_chat_payload(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        payload = {"choices": [{"message": {"content": "chat answer"}}]}
        self.assertEqual(service._extract_text(payload), "chat answer")

    def test_rejects_local_api_style(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Local LLM and Gemini fallbacks are disabled"):
            reflection.ReflectionService(model="openai/gpt-oss-20b", api_style="ollama")

    def test_verify_startup_raises_if_model_missing(self) -> None:
        service = reflection.ReflectionService(model="missing-model")
        with patch.object(service, "_get_json", return_value={"data": [{"id": "openai/gpt-oss-20b"}]}):
            with self.assertRaisesRegex(RuntimeError, "not available"):
                service.verify_startup()

    def test_verify_startup_accepts_openai_compatible_model(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        with patch.object(service, "_get_json", return_value={"data": [{"id": "openai/gpt-oss-20b"}]}) as get_json:
            service.verify_startup()
        get_json.assert_called_once_with("/models")

    def test_generate_json_response_parses_json_payload(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        with patch.object(service, "_model_request", return_value={"response": '{"ok": true, "count": 2}'}):
            payload = service.generate_json_response(system_prompt="s", user_prompt="u")
        self.assertEqual(payload, {"ok": True, "count": 2})

    def test_generate_json_response_extracts_json_from_chatty_model_output(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        with patch.object(
            service,
            "_model_request",
            return_value={"choices": [{"message": {"content": "Sure.\n```json\n{\"ok\": true}\n```"}}]},
        ):
            payload = service.generate_json_response(system_prompt="s", user_prompt="u")
        self.assertEqual(payload, {"ok": True})

    def test_generate_reflection_raises_on_empty_response(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        with patch.object(service, "_model_request", return_value={"response": ""}):
            with self.assertRaisesRegex(RuntimeError, "Configured backend reflection failed"):
                service.generate_reflection(
                    founder_name="Oriol",
                    founder_role="CEO",
                    today_iso="2026-04-10",
                    completed_tasks=["Task A"],
                    raw_notes="",
                )

    def test_generate_reflection_uses_configured_backend(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        with patch.object(service, "_model_request", return_value={"response": "backend note"}):
            reflection_text = service.generate_reflection(
                founder_name="Oriol",
                founder_role="CEO",
                today_iso="2026-04-10",
                completed_tasks=["Task A"],
                raw_notes="",
            )

        self.assertEqual(reflection_text, "backend note")

    def test_request_json_tries_fallback_api_keys(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b", api_keys=("key-1", "key-2"))
        with patch.object(
            service,
            "_request_json_with_key",
            side_effect=[RuntimeError("quota exhausted"), {"data": [{"id": "openai/gpt-oss-20b"}]}],
        ) as request_json:
            payload = service._get_json("/models")

        self.assertEqual(payload, {"data": [{"id": "openai/gpt-oss-20b"}]})
        self.assertEqual([call.kwargs["api_key"] for call in request_json.call_args_list], ["key-1", "key-2"])

    def test_build_fallback_reflection_includes_tasks_and_notes(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")

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

    def test_compute_streak_from_log_dates_uses_daily_logs_as_source(self) -> None:
        current, best, last_log = streaks.compute_streak_from_log_dates(
            [
                streaks.date(2026, 4, 25),
                streaks.date(2026, 4, 27),
                streaks.date(2026, 4, 28),
                streaks.date(2026, 4, 29),
            ],
            streaks.date(2026, 4, 30),
            previous_best=2,
        )

        self.assertEqual(current, 3)
        self.assertEqual(best, 3)
        self.assertEqual(last_log, "2026-04-29")

    def test_compute_streak_from_log_dates_resets_current_after_gap(self) -> None:
        current, best, last_log = streaks.compute_streak_from_log_dates(
            [streaks.date(2026, 4, 24), streaks.date(2026, 4, 25)],
            streaks.date(2026, 4, 30),
            previous_best=4,
        )

        self.assertEqual(current, 0)
        self.assertEqual(best, 4)
        self.assertEqual(last_log, "2026-04-25")

    def test_should_run_startup_reset_after_madrid_cutoff(self) -> None:
        before_cutoff = streaks.MADRID_TZ.localize(dt.datetime(2026, 4, 29, 4, 59))
        after_cutoff = streaks.MADRID_TZ.localize(dt.datetime(2026, 4, 29, 5, 0))

        self.assertFalse(streaks.should_run_startup_reset(before_cutoff))
        self.assertTrue(streaks.should_run_startup_reset(after_cutoff))


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


class LogCommandAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalize_log_runs_sync_work_via_to_thread(self) -> None:
        state = MagicMock()
        state.founder = {"name": "Oriol", "role": "CEO"}
        state.ctx = log_command.LogContext("2026-05-04", "26-W19")
        state.settings = MagicMock(discord_blockers_channel_id=123)
        state.bot = MagicMock()
        interaction = MagicMock()
        interaction.followup.send = AsyncMock()
        interaction.channel = None

        with patch("log_command.asyncio.to_thread", new=AsyncMock(return_value=(3, []))) as to_thread:
            await log_command._finalize_log(
                interaction,
                state,
                task_pages=[],
                raw_notes="",
                blocker=None,
            )

        to_thread.assert_awaited_once_with(log_command._complete_log_sync, state, [], "")
        interaction.followup.send.assert_awaited_once()

    async def test_finalize_log_succeeds_when_streak_refresh_is_unavailable(self) -> None:
        state = MagicMock()
        state.founder = {"name": "Oriol", "role": "CEO"}
        state.ctx = log_command.LogContext("2026-05-04", "26-W19")
        state.settings = MagicMock(discord_blockers_channel_id=123)
        state.bot = MagicMock()
        interaction = MagicMock()
        interaction.followup.send = AsyncMock()
        interaction.channel = MagicMock()
        interaction.channel.send = AsyncMock()

        with patch("log_command.asyncio.to_thread", new=AsyncMock(return_value=(None, None))):
            await log_command._finalize_log(
                interaction,
                state,
                task_pages=[],
                raw_notes="",
                blocker=None,
            )

        interaction.followup.send.assert_awaited_once()
        message = interaction.followup.send.await_args.args[0]
        self.assertIn("Log saved.", message)
        self.assertIn("Remaining this week: unavailable.", message)
        self.assertIn("Streak refresh is temporarily unavailable.", message)
        interaction.channel.send.assert_awaited_once_with("✅ Oriol logged")


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

    def test_fallback_task_descriptions_keeps_single_feature_request_with_metric_list_together(self) -> None:
        descriptions = task_command._fallback_task_descriptions(
            "add a local ai cli which allows you to see the occupied VRAM of a model and the context window available as well as TTFT, TTLT and throughput"
        )

        self.assertEqual(
            descriptions,
            [
                "add a local ai cli which allows you to see the occupied VRAM of a model and the context window available as well as TTFT, TTLT and throughput"
            ],
        )

    def test_parse_task_descriptions_uses_fallback_when_llm_returns_invalid_payload(self) -> None:
        reflection_service = MagicMock()
        reflection_service.generate_json_response.return_value = {"unexpected": []}

        descriptions = task_command._parse_task_descriptions(
            reflection_service,
            "add 2 tasks: draft investor update and prepare demo script",
        )

        self.assertEqual(descriptions, ["Draft investor update.", "Prepare demo script."])

    def test_parse_task_descriptions_limits_over_split_llm_output_without_explicit_multi_task_request(self) -> None:
        reflection_service = MagicMock()
        reflection_service.generate_json_response.return_value = {
            "tasks": [
                {"description": "Build local AI CLI"},
                {"description": "Show occupied VRAM"},
                {"description": "Show available context window"},
                {"description": "Show TTFT"},
                {"description": "Show TTLT"},
                {"description": "Show throughput"},
            ]
        }

        descriptions = task_command._parse_task_descriptions(
            reflection_service,
            "add a local ai cli which allows you to see the occupied VRAM of a model and the context window available as well as TTFT, TTLT and throughput",
        )

        self.assertEqual(
            descriptions,
            [
                "Build local AI CLI.",
                "Show occupied VRAM.",
                "Show available context window.",
                "Show TTFT.",
            ],
        )

    def test_parse_task_descriptions_contextualizes_short_followup_fragments(self) -> None:
        reflection_service = MagicMock()
        reflection_service.generate_json_response.return_value = {
            "tasks": [
                {"description": "set up the joint revolut bank account (group pocket)"},
                {"description": "add adam"},
                {"description": "add arnau"},
            ]
        }

        descriptions = task_command._parse_task_descriptions(
            reflection_service,
            "set up the joint Revolut bank account (group pocket) and add Adam and add Arnau",
        )

        self.assertEqual(
            descriptions,
            [
                "Set up the joint Revolut bank account (group pocket).",
                "Add Adam to the joint Revolut bank account (group pocket).",
                "Add Arnau to the joint Revolut bank account (group pocket).",
            ],
        )

    def test_task_creation_week_code_uses_current_week_before_friday_cutoff(self) -> None:
        before_cutoff = log_command.MADRID_TZ.localize(dt.datetime(2026, 5, 1, 16, 55))
        self.assertEqual(task_command._task_creation_week_code(before_cutoff), "26-W18")

    def test_task_creation_week_code_uses_next_week_at_friday_cutoff(self) -> None:
        at_cutoff = log_command.MADRID_TZ.localize(dt.datetime(2026, 5, 1, 17, 0))
        self.assertEqual(task_command._task_creation_week_code(at_cutoff), "26-W19")

    def test_task_creation_week_code_uses_next_week_on_sunday(self) -> None:
        sunday = log_command.MADRID_TZ.localize(dt.datetime(2026, 5, 3, 12, 0))
        self.assertEqual(task_command._task_creation_week_code(sunday), "26-W19")

    def test_choose_project_only_updates_state_after_preview_succeeds(self) -> None:
        notion_service = MagicMock()
        notion_service.preview_task_ids.side_effect = RuntimeError("preview failed")
        state = task_command._TaskAddState(
            notion=notion_service,
            founder={"name": "Oriol", "role": "CEO"},
            raw_text="draft investor update",
            descriptions=["Draft investor update"],
            projects=[{"id": "proj-1", "name": "ALPHA"}],
            year=2026,
            quarter_name="Q2 2026",
            month_name="May",
            week_code="26-W18",
            today_iso="2026-05-03",
        )

        with self.assertRaisesRegex(RuntimeError, "preview failed"):
            state.choose_project("proj-1")

        self.assertEqual(state.selected_project_id, "")
        self.assertEqual(state.selected_project_name, "")
        self.assertEqual(state.preview_ids, [])

    def test_project_select_defers_before_editing_original_response(self) -> None:
        notion_service = MagicMock()
        notion_service.preview_task_ids.return_value = ["ALPHA-CEO-1"]
        state = task_command._TaskAddState(
            notion=notion_service,
            founder={"name": "Oriol", "role": "CEO"},
            raw_text="draft investor update",
            descriptions=["Draft investor update"],
            projects=[{"id": "proj-1", "name": "ALPHA"}],
            year=2026,
            quarter_name="Q2 2026",
            month_name="May",
            week_code="26-W18",
            today_iso="2026-05-03",
        )
        select = task_command._ProjectSelect(state, state.projects, 0)
        select._values = ["proj-1"]

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        import asyncio

        asyncio.run(select.callback(interaction))

        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        self.assertIn("Project: **ALPHA**", interaction.edit_original_response.await_args.kwargs["content"])
        self.assertIsInstance(
            interaction.edit_original_response.await_args.kwargs["view"],
            task_command._TaskProjectPickerView,
        )


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
            "Done": {"type": "checkbox"},
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
        self.assertFalse(first_kwargs["properties"]["Done"]["checkbox"])
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

    def test_format_message_uses_reshaped_meeting_database_fields(self) -> None:
        page = {
            "properties": {
                "Type": {"type": "select", "select": {"name": "Administrative"}},
                "Date": {"type": "date", "date": {"start": "2026-05-15T11:00:00+02:00"}},
                "Address": {"type": "rich_text", "rich_text": [{"plain_text": "Google Meet"}]},
                "Overview": {"type": "rich_text", "rich_text": [{"plain_text": "Review weekly metrics"}]},
            }
        }

        message = meetings._format_message("📅 New meeting scheduled!", page)

        self.assertIn("Administrative — Friday 15 May, 11:00", message)
        self.assertNotIn("👥 TBD", message)
        self.assertIn("📍 Google Meet", message)
        self.assertIn("📝 Review weekly metrics", message)


class MeetingsPollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_all_async_uses_to_thread(self) -> None:
        notion_service = MagicMock()
        with patch("meetings.asyncio.to_thread", new=AsyncMock(return_value=[{"id": "page-1"}])) as to_thread:
            result = await meetings._query_all_async(notion_service, "meetings-db")

        self.assertEqual(result, [{"id": "page-1"}])
        to_thread.assert_awaited_once_with(notion_service._query_all, "meetings-db")

    async def test_update_page_async_uses_to_thread(self) -> None:
        notion_service = MagicMock()
        notion_service.client.pages.update = MagicMock()
        properties = {"Announced": {"checkbox": True}}

        with patch("meetings.asyncio.to_thread", new=AsyncMock(return_value=None)) as to_thread:
            await meetings._update_page_async(notion_service, "page-1", properties)

        to_thread.assert_awaited_once_with(
            notion_service.client.pages.update,
            page_id="page-1",
            properties=properties,
        )


class NotionServiceTests(unittest.TestCase):
    def test_is_task_done_supports_checkbox_and_status(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        checkbox_page = {"properties": {"Status": {"type": "checkbox", "checkbox": True}}}
        status_page = {"properties": {"Status": {"type": "status", "status": {"name": "Done"}}}}
        select_page = {"properties": {"Status": {"type": "select", "select": {"name": "Completed"}}}}
        paired_page = {
            "properties": {
                "Status": {"type": "select", "select": {"name": "Todo"}},
                "Done": {"type": "checkbox", "checkbox": True},
            }
        }
        self.assertTrue(service._is_task_done(checkbox_page))
        self.assertTrue(service._is_task_done(status_page))
        self.assertTrue(service._is_task_done(select_page))
        self.assertTrue(service._is_task_done(paired_page))

    def test_task_matches_founder_from_display_id_when_owner_fields_are_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        task = {
            "properties": {
                "Display ID": {"type": "title", "title": [{"plain_text": "ALPHA-CEO-45"}]},
            }
        }

        self.assertTrue(service._task_matches_founder(task, role="CEO", founder_name="Oriol"))
        self.assertFalse(service._task_matches_founder(task, role="CTO", founder_name="Arnau"))

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

    def test_verify_startup_disables_streaks_when_query_fails(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.databases.retrieve.return_value = {"properties": {}}
        with patch.object(service, "_query_all", side_effect=RuntimeError("not shared")):
            service.verify_startup()

        self.assertFalse(service.streaks_available())

    def test_get_next_week_code_handles_year_boundaries(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        # Regular rollover
        self.assertEqual(service.get_next_week_code("26-W15"), "26-W16")
        # End of year 2026 (W53 is the last week of 2026)
        self.assertEqual(service.get_next_week_code("26-W53"), "27-W01")

    def test_get_current_week_infers_from_tasks_when_settings_db_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        tasks = [
            {"properties": {"Week": {"type": "select", "select": {"name": "26-W18"}}, "Status": {"type": "select", "select": {"name": "Done"}}}},
            {"properties": {"Week": {"type": "select", "select": {"name": "26-W19"}}, "Status": {"type": "select", "select": {"name": "Todo"}}}},
            {"properties": {"Week": {"type": "select", "select": {"name": "26-W20"}}, "Status": {"type": "select", "select": {"name": "Archived"}}}},
        ]

        with patch.object(service, "_query_all", return_value=tasks):
            self.assertEqual(service.get_current_week_from_settings(), "26-W19")

    def test_set_current_week_in_settings_noops_when_settings_db_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()

        service.set_current_week_in_settings("26-W20", status="success", count=3)

        service.client.pages.update.assert_not_called()

    def test_set_is_current_week_flags_noops_when_property_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        with patch.object(service, "_query_all", return_value=[{"id": "task-1", "properties": {}}]):
            with patch.object(service, "_retrieve_schema", return_value={"Week": {"type": "select"}}):
                service.set_is_current_week_flags("26-W19", "26-W20")

        service.client.pages.update.assert_not_called()

    def test_rollover_task_applies_correct_description_prefixes(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        service._retrieve_schema = MagicMock(return_value={
            "Week": {"type": "select"},
            "Description": {"type": "rich_text"}
        })

        # Test 1: No prefix -> carryover
        task_no_prefix = {
            "id": "task-1",
            "properties": {
                "Description": {"rich_text": [{"plain_text": "Finish report"}]}
            }
        }
        service.rollover_task(task_no_prefix, "26-W17")
        update_call = service.client.pages.update.call_args
        self.assertEqual(
            update_call.kwargs["properties"]["Description"]["rich_text"][0]["text"]["content"],
            "↩ carryover | Finish report"
        )

        # Test 2: Carryover -> stale
        task_carryover = {
            "id": "task-2",
            "properties": {
                "Description": {"rich_text": [{"plain_text": "↩ carryover | Fix bugs"}]}
            }
        }
        service.rollover_task(task_carryover, "26-W17")
        update_call = service.client.pages.update.call_args
        self.assertEqual(
            update_call.kwargs["properties"]["Description"]["rich_text"][0]["text"]["content"],
            "⚠ stale | Fix bugs"
        )

        # Test 3: Stale -> stays stale
        task_stale = {
            "id": "task-3",
            "properties": {
                "Description": {"rich_text": [{"plain_text": "⚠ stale | Long project"}]}
            }
        }
        service.rollover_task(task_stale, "26-W17")
        update_call = service.client.pages.update.call_args
        self.assertEqual(
            update_call.kwargs["properties"]["Description"]["rich_text"][0]["text"]["content"],
            "⚠ stale | Long project"
        )

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

    def test_set_task_completion_updates_status_and_done_checkbox_when_both_exist(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.databases.retrieve.return_value = {
            "properties": {
                "Status": {"type": "select", "select": {"options": [{"name": "Todo"}, {"name": "Done"}]}},
                "Done": {"type": "checkbox"},
                "Done date": {"type": "date"},
            }
        }
        task = {
            "id": "page-1",
            "properties": {
                "Status": {"type": "select", "select": {"name": "Todo"}},
                "Done": {"type": "checkbox", "checkbox": False},
            },
        }

        service.set_task_completion(task, completed=True, today_iso="2026-05-07")

        service.client.pages.update.assert_called_once_with(
            page_id="page-1",
            properties={
                "Status": {"select": {"name": "Done"}},
                "Done": {"checkbox": True},
                "Done date": {"date": {"start": "2026-05-07"}},
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

    def test_has_daily_log_matches_founder_from_title_when_property_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", streaks_db_id="streaks")
        rows = [
            {
                "properties": {
                    "Title": {"type": "title", "title": [{"plain_text": "Oriol · 26-W19 · 2026-05-07"}]},
                    "Date": {"type": "date", "date": {"start": "2026-05-07"}},
                }
            }
        ]
        with patch.object(service, "_query_all", return_value=rows):
            result = service.has_daily_log("Oriol", "2026-05-07")

        self.assertTrue(result)

    def test_create_daily_log_builds_expected_properties(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.data_sources = None

        schema = {
            "Title": {"type": "title"},
            "Date": {"type": "date"},
            "Founder": {"type": "select"},
            "Role": {"type": "select"},
            "Week": {"type": "select", "select": {"options": [{"name": "26-W15"}]}},
            "Tasks completed": {"type": "relation"},
            "Notes": {"type": "rich_text"},
        }
        with patch.object(service, "_retrieve_schema", return_value=schema):
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

    def test_create_daily_log_supports_title_only_founder_schema(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", streaks_db_id="streaks")
        service.client = MagicMock()
        service.client.data_sources = None
        schema = {
            "Title": {"type": "title"},
            "Date": {"type": "date"},
            "Tasks completed": {"type": "relation"},
            "Notes": {"type": "rich_text"},
        }

        with patch.object(service, "_retrieve_schema", return_value=schema):
            service.create_daily_log(
                founder_name="Oriol",
                founder_role="CEO",
                week_code="26-W19",
                today_iso="2026-05-07",
                completed_task_ids=["page-1"],
                notes_text="reflection",
            )

        _, kwargs = service.client.pages.create.call_args
        self.assertEqual(kwargs["properties"]["Title"]["title"][0]["text"]["content"], "Oriol · 26-W19 · 2026-05-07")
        self.assertEqual(kwargs["properties"]["Date"]["date"]["start"], "2026-05-07")
        self.assertNotIn("Founder", kwargs["properties"])
        self.assertNotIn("Role", kwargs["properties"])
        self.assertNotIn("Week", kwargs["properties"])

    def test_daily_log_dates_returns_founder_dates(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", streaks_db_id="streaks")
        rows = [
            {
                "properties": {
                    "Founder": {"type": "select", "select": {"name": "Oriol"}},
                    "Date": {"type": "date", "date": {"start": "2026-04-28T23:00:00+02:00"}},
                }
            },
            {
                "properties": {
                    "Founder": {"type": "select", "select": {"name": "Arnau"}},
                    "Date": {"type": "date", "date": {"start": "2026-04-29"}},
                }
            },
        ]
        with patch.object(service, "_query_all", return_value=rows):
            dates = service.daily_log_dates("Oriol")

        self.assertEqual(dates, [dt.date(2026, 4, 28)])

    def test_update_streak_row_can_clear_last_log(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", streaks_db_id="streaks")
        service.client = MagicMock()

        service.update_streak_row(
            "streak-row",
            current_streak=0,
            best_streak=12,
            last_log_iso=None,
        )

        service.client.pages.update.assert_called_once_with(
            page_id="streak-row",
            properties={
                "Current Streak": {"number": 0},
                "Last Log": {"date": None},
                "Best Streak": {"number": 12},
            },
        )


if __name__ == "__main__":
    unittest.main()
