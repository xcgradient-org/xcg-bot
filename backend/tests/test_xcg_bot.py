from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, call, patch


BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from backend import config as main
from backend.integrations import notion, reflection
from backend.services.daily_log_dedupe import DailyLogDedupeService
from backend.services import internal_tools as internal_server
from backend.services.meetings import MeetingsService
from backend.services import runtime as runtime_service
from backend.services.tasks import TasksService
from backend.services import streaks
from backend.services.team_usage.providers.claude_oauth import ClaudeOAuthProvider
from backend.services.week import WeekService
from backend.services.logs import LogsService
from backend.domain import blockers
from bot.commands import meetings


class LoadSettingsTests(unittest.TestCase):
    def test_load_environment_prefers_bot_local_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bot_env = Path(tmpdir) / "xcg-bot.env"
            root_env = Path(tmpdir) / "root.env"
            bot_env.write_text("DISCORD_TOKEN=test\n", encoding="utf-8")
            root_env.write_text("DISCORD_TOKEN=test\n", encoding="utf-8")

            with patch.object(main, "ENV_PATHS", (bot_env, root_env)):
                with patch("backend.config.load_dotenv") as load_dotenv:
                    env_path = main.load_environment()

        self.assertEqual(env_path, bot_env)
        load_dotenv.assert_called_once_with(bot_env)

    def test_load_environment_falls_back_to_parent_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_bot_env = Path(tmpdir) / "missing.env"
            root_env = Path(tmpdir) / "root.env"
            root_env.write_text("DISCORD_TOKEN=test\n", encoding="utf-8")

            with patch.object(main, "ENV_PATHS", (missing_bot_env, root_env)):
                with patch("backend.config.load_dotenv") as load_dotenv:
                    env_path = main.load_environment()

        self.assertEqual(env_path, root_env)
        load_dotenv.assert_called_once_with(root_env)

    @patch("backend.config.load_environment")
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
            "NOTION_TEAM_DB": "team-db",
            "NOTION_MEETINGS_DB": "meetings-db",
            "NOTION_SETTINGS_DB_ID": "settings-db",
            "DISCORD_BLOCKERS_CHANNEL_ID": "123",
            "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": "456",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("backend.config.default_llm_settings", return_value=("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", ("key-1", "key-2"), "openai")):
                settings = main.load_settings()

        self.assertEqual(settings.notion_tasks_db_id, "tasks-db")
        self.assertEqual(settings.notion_daily_logs_db_id, "daily-db")
        self.assertEqual(settings.notion_team_db_id, "team-db")
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
        self.assertIsNone(settings.internal_api_token)

    @patch("backend.config.load_environment")
    def test_load_settings_reads_internal_api_token(self, load_environment: MagicMock) -> None:
        load_environment.return_value = Path("/tmp/fake.env")
        env = {
            "DISCORD_TOKEN": "discord-token",
            "NOTION_TOKEN": "notion-token",
            "DISCORD_USER_ID_ORIOL": "111",
            "DISCORD_USER_ID_ARNAU": "222",
            "DISCORD_USER_ID_ADAM": "333",
            "NOTION_TASKS_DB": "tasks-db",
            "NOTION_DAILY_LOGS_DB": "daily-db",
            "NOTION_TEAM_DB": "team-db",
            "NOTION_MEETINGS_DB": "meetings-db",
            "DISCORD_BLOCKERS_CHANNEL_ID": "123",
            "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": "456",
            "INTERNAL_API_TOKEN": "secret-token",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch(
                "backend.config.default_llm_settings",
                return_value=("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", ("key-1",), "openai"),
            ):
                settings = main.load_settings()

        self.assertEqual(settings.internal_api_token, "secret-token")

    @patch("backend.config.load_environment")
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
            "NOTION_TEAM_DB": "team-db",
            "NOTION_MEETINGS_DB": "meetings-db",
            "DISCORD_BLOCKERS_CHANNEL_ID": "123",
            "DISCORD_ANNOUNCEMENTS_CHANNEL_ID": "456",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("backend.config.default_llm_settings", return_value=("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", (), "openai")):
                settings = main.load_settings()

        self.assertIsNone(settings.notion_settings_db_id)
        self.assertIsNone(settings.internal_api_token)

    def test_default_llm_settings_uses_groq_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            base_url, model, api_keys, api_style = main.default_llm_settings()

        self.assertEqual(base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(model, "llama-3.3-70b-versatile")
        self.assertEqual(api_keys, ())
        self.assertEqual(api_style, "openai")

    def test_default_llm_settings_collects_multiple_api_keys(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_BASE_URL": "https://api.groq.com/openai/v1",
                "LLM_MODEL": "llama-3.3-70b-versatile",
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
        self.assertEqual(model, "llama-3.3-70b-versatile")
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

    def test_extract_text_supports_segmented_content_payloads(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "output_text", "text": "first"},
                            {"type": "output_text", "text": {"value": "second"}},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(service._extract_text(payload), "first\nsecond")

    def test_rejects_local_api_style(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Local LLM and Gemini fallbacks are disabled"):
            reflection.ReflectionService(model="openai/gpt-oss-20b", api_style="ollama")

    def test_verify_startup_raises_if_no_preferred_models_available(self) -> None:
        service = reflection.ReflectionService(model="some-model")
        with patch.object(service, "_get_json", return_value={"data": [{"id": "unrelated-model"}]}):
            with self.assertRaisesRegex(RuntimeError, "None of the preferred models"):
                service.verify_startup()

    def test_verify_startup_accepts_partial_preferred_model_set(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b")
        # Only one of the preferred models is available — should not raise
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

    def test_openai_request_uses_json_object_and_disables_reasoning_for_json_mode(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b", api_keys=("key-1",))
        with patch.object(service, "_request_json_with_key", return_value={"choices": []}) as request_json:
            service._openai_request(
                system_prompt="base",
                user_prompt="{}",
                model="openai/gpt-oss-20b",
                api_key="key-1",
                response_mime_type="application/json",
            )
        payload = request_json.call_args.kwargs["payload"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["include_reasoning"])
        self.assertIn("valid JSON only", payload["messages"][0]["content"])

    def test_openai_request_omits_include_reasoning_for_models_without_support(self) -> None:
        service = reflection.ReflectionService(model="llama-3.3-70b-versatile", api_keys=("key-1",))
        with patch.object(service, "_request_json_with_key", return_value={"choices": []}) as request_json:
            service._openai_request(
                system_prompt="base",
                user_prompt="{}",
                model="llama-3.3-70b-versatile",
                api_key="key-1",
                response_mime_type="application/json",
            )
        payload = request_json.call_args.kwargs["payload"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("include_reasoning", payload)

    def test_model_request_json_mode_uses_json_model_priority_per_key(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b", api_keys=("key-1", "key-2"))
        with patch.object(
            service,
            "_openai_request",
            side_effect=[RuntimeError("rate limit"), {"choices": [{"message": {"content": "{\"ok\": true}"}}]}],
        ) as openai_request:
            payload = service._model_request(
                system_prompt="s",
                user_prompt="u",
                response_mime_type="application/json",
            )
        self.assertEqual(payload, {"choices": [{"message": {"content": "{\"ok\": true}"}}]})
        self.assertEqual([call.kwargs["model"] for call in openai_request.call_args_list], ["openai/gpt-oss-20b", "openai/gpt-oss-20b"])
        self.assertEqual([call.kwargs["api_key"] for call in openai_request.call_args_list], ["key-1", "key-2"])

    def test_model_request_skips_remaining_models_for_invalid_api_key(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b", api_keys=("key-1",))
        with patch.object(
            service,
            "_openai_request",
            side_effect=RuntimeError('LLM request failed: 401 {"error":{"code":"invalid_api_key"}}'),
        ) as openai_request:
            with self.assertRaisesRegex(RuntimeError, "All configured LLM key/model combinations failed"):
                service._model_request(system_prompt="s", user_prompt="u")
        openai_request.assert_called_once()

    def test_model_request_fails_fast_on_non_retriable_json_validation_error(self) -> None:
        service = reflection.ReflectionService(model="openai/gpt-oss-20b", api_keys=("key-1", "key-2"))
        with patch.object(
            service,
            "_openai_request",
            side_effect=RuntimeError('LLM request failed: 400 {"error":{"code":"json_validate_failed"}}'),
        ) as openai_request:
            with self.assertRaisesRegex(RuntimeError, "Non-retriable JSON validation failure"):
                service._model_request(
                    system_prompt="s",
                    user_prompt="u",
                    response_mime_type="application/json",
                )
        openai_request.assert_called_once()

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
        current, best = streaks.compute_updated_streak("2026-04-09", 3, 4, date(2026, 4, 10))
        self.assertEqual(current, 4)
        self.assertEqual(best, 4)

    def test_compute_updated_streak_resets_after_gap(self) -> None:
        current, best = streaks.compute_updated_streak("2026-04-01", 8, 10, date(2026, 4, 10))
        self.assertEqual(current, 1)
        self.assertEqual(best, 10)

    def test_should_reset_streak_only_if_last_log_before_yesterday(self) -> None:
        today = date(2026, 4, 10)
        self.assertFalse(streaks.should_reset_streak("2026-04-09", today))
        self.assertFalse(streaks.should_reset_streak("2026-04-10", today))
        self.assertTrue(streaks.should_reset_streak("2026-04-08", today))

    def test_compute_streak_from_log_dates_uses_daily_logs_as_source(self) -> None:
        current, best, last_log = streaks.compute_streak_from_log_dates(
            [
                date(2026, 4, 25),
                date(2026, 4, 27),
                date(2026, 4, 28),
                date(2026, 4, 29),
            ],
            date(2026, 4, 30),
            previous_best=2,
        )

        self.assertEqual(current, 3)
        self.assertEqual(best, 3)
        self.assertEqual(last_log, "2026-04-29")

    def test_compute_streak_from_log_dates_resets_current_after_gap(self) -> None:
        current, best, last_log = streaks.compute_streak_from_log_dates(
            [date(2026, 4, 24), date(2026, 4, 25)],
            date(2026, 4, 30),
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


class DailyResetLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_maintenance_skipped_before_cutoff(self) -> None:
        notion = MagicMock()
        reflection = MagicMock()
        before_cutoff = streaks.MADRID_TZ.localize(dt.datetime(2026, 4, 29, 4, 59))
        with patch("backend.services.streaks.datetime") as mocked_dt:
            mocked_dt.now.return_value = before_cutoff
            mocked_dt.combine = dt.datetime.combine
            with patch("backend.services.streaks.asyncio.sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await streaks.daily_reset_loop(notion, reflection)
        notion.get_all_streak_rows.assert_not_called()

    async def test_startup_maintenance_runs_after_cutoff(self) -> None:
        notion = MagicMock()
        notion.get_all_streak_rows.return_value = []
        reflection = MagicMock()
        after_cutoff = streaks.MADRID_TZ.localize(dt.datetime(2026, 4, 29, 9, 0))
        with patch("backend.services.streaks.datetime") as mocked_dt:
            mocked_dt.now.return_value = after_cutoff
            mocked_dt.combine = dt.datetime.combine
            with patch("backend.services.streaks.asyncio.sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await streaks.daily_reset_loop(notion, reflection)
        self.assertGreater(notion.get_all_streak_rows.call_count, 0)


class RuntimeBuildTests(unittest.TestCase):
    @patch("backend.services.runtime.load_dotenv")
    @patch("backend.services.runtime.default_llm_settings")
    @patch("backend.services.runtime.ReflectionService")
    @patch("backend.services.runtime.NotionService")
    def test_build_runtime_uses_shared_llm_defaults(
        self,
        notion_service_cls: MagicMock,
        reflection_service_cls: MagicMock,
        default_llm_settings: MagicMock,
        _load_dotenv: MagicMock,
    ) -> None:
        notion_service_cls.return_value = MagicMock()
        reflection_service_cls.return_value = MagicMock()
        default_llm_settings.return_value = (
            "https://api.groq.com/openai/v1",
            "llama-3.3-70b-versatile",
            ("key-1", "key-2"),
            "openai",
        )

        runtime_service.build_runtime()

        reflection_service_cls.assert_called_once_with(
            model="llama-3.3-70b-versatile",
            base_url="https://api.groq.com/openai/v1",
            api_keys=("key-1", "key-2"),
            api_style="openai",
        )


class AutomaticLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_create_missing_daily_logs_creates_log_for_completed_tasks(self) -> None:
        notion_service = MagicMock()
        reflection_service = MagicMock()
        row = {"id": "team-oriol", "properties": {}}
        notion_service.get_all_streak_rows.return_value = [row]
        notion_service.founder_name.return_value = "Oriol"
        notion_service._property_text.return_value = "CEO"
        notion_service.find_daily_log.return_value = None
        notion_service.query_log_tasks.return_value = (
            [{"id": "task-1"}],
            [{"id": "task-1"}],
            "26-W20",
        )
        notion_service.task_descriptions.return_value = ["Close enterprise deal."]
        notion_service.page_ids.return_value = ["task-1"]
        notion_service.streaks_available.return_value = False
        reflection_service.generate_reflection.return_value = "Auto-generated reflection"

        now = streaks.MADRID_TZ.localize(dt.datetime(2026, 5, 13, 5, 0))
        results = await streaks.auto_create_missing_daily_logs(notion_service, reflection_service, now=now)

        notion_service.create_daily_log.assert_called_once_with(
            founder_name="Oriol",
            founder_role="CEO",
            week_code="26-W20",
            today_iso="2026-05-12",
            logged_at_iso="2026-05-13T05:00:00+02:00",
            completed_task_ids=["task-1"],
            notes_text="Auto-generated reflection",
        )
        self.assertTrue(results[0]["created"])
        self.assertEqual(results[0]["today_iso"], "2026-05-12")
        notion_service.query_log_tasks.assert_called_once_with("CEO", "2026-05-12", "26-W20", "Oriol")


class WebLoggingTests(unittest.TestCase):
    def test_logging_status_reports_logged_times(self) -> None:
        notion_service = MagicMock()
        reflection_service = MagicMock()
        runtime = MagicMock()
        runtime.notion = notion_service
        runtime.reflection = reflection_service
        service = LogsService(runtime)
        notion_service._property_date.return_value = ""

        notion_service.find_daily_log.side_effect = [
            {"created_time": "2026-05-12T19:03:00.000Z"},
            None,
            None,
        ]

        with patch("backend.services.logs.current_context", return_value=blockers.LogContext("2026-05-12", "26-W20", "2026-05-12")):
            payload = service.logging_status()

        self.assertEqual(payload["today_iso"], "2026-05-12")
        self.assertEqual(payload["founders"][0]["founder"], "oriol")
        self.assertTrue(payload["founders"][0]["logged"])
        self.assertEqual(payload["founders"][0]["logged_at"], "21:03")
        self.assertFalse(payload["founders"][1]["logged"])

    def test_row_logged_at_prefers_logged_at_property(self) -> None:
        notion_service = MagicMock()
        reflection_service = MagicMock()
        runtime = MagicMock()
        runtime.notion = notion_service
        runtime.reflection = reflection_service
        service = LogsService(runtime)
        notion_service._property_date.side_effect = ["2026-05-12T19:03:00.000Z"]

        logged_at = service._row_logged_at({"created_time": "2026-05-12T18:00:00.000Z"})

        self.assertEqual(logged_at, "21:03")

    def test_log_now_creates_manual_log_for_current_context(self) -> None:
        notion_service = MagicMock()
        reflection_service = MagicMock()
        runtime = MagicMock()
        runtime.notion = notion_service
        runtime.reflection = reflection_service
        service = LogsService(runtime)
        notion_service._property_date.return_value = ""

        notion_service.find_daily_log.side_effect = [
            None,
            {"created_time": "2026-05-12T19:03:00.000Z"},
        ]
        notion_service.query_log_tasks.return_value = (
            [{"id": "task-1"}],
            [{"id": "task-1"}],
            "26-W20",
        )
        notion_service.task_descriptions.return_value = ["Close enterprise deal."]
        notion_service.page_ids.return_value = ["task-1"]
        notion_service.streaks_available.return_value = False
        reflection_service.generate_reflection.return_value = "Manual log"

        fake_now = streaks.MADRID_TZ.localize(dt.datetime(2026, 5, 12, 21, 3, 0))
        with patch("backend.services.logs.current_context", return_value=blockers.LogContext("2026-05-12", "26-W20", "2026-05-12")):
            with patch("backend.services.logs.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = fake_now
                mocked_datetime.fromisoformat.side_effect = dt.datetime.fromisoformat
                payload = service.log_now({"founder": "oriol"})

        notion_service.create_daily_log.assert_called_once_with(
            founder_name="Oriol",
            founder_role="CEO",
            week_code="26-W20",
            today_iso="2026-05-12",
            logged_at_iso="2026-05-12T21:03:00+02:00",
            completed_task_ids=["task-1"],
            notes_text="Manual log",
        )
        self.assertTrue(payload["created"])
        self.assertTrue(payload["logged"])
        self.assertEqual(payload["logged_at"], "21:03")

    def test_log_now_reports_missing_completed_tasks(self) -> None:
        notion_service = MagicMock()
        reflection_service = MagicMock()
        runtime = MagicMock()
        runtime.notion = notion_service
        runtime.reflection = reflection_service
        service = LogsService(runtime)
        notion_service._property_date.return_value = ""

        notion_service.find_daily_log.return_value = None
        notion_service.query_log_tasks.return_value = ([], [], "26-W20")

        with patch("backend.services.logs.current_context", return_value=blockers.LogContext("2026-05-12", "26-W20", "2026-05-12")):
            payload = service.log_now({"founder": "oriol"})

        notion_service.create_daily_log.assert_not_called()
        self.assertFalse(payload["created"])
        self.assertFalse(payload["logged"])
        self.assertEqual(payload["reason"], "no_completed_tasks")


class BlockersTests(unittest.TestCase):
    def test_build_blocker_message_mentions_configured_user(self) -> None:
        settings = MagicMock()
        settings.discord_user_id_oriol = 111
        settings.discord_user_id_arnau = 222
        settings.discord_user_id_adam = 333

        message = blockers.build_blocker_message(
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

        message = blockers.build_blocker_message(
            "Oriol",
            "CTO",
            "I need the final schema to finish the API integration.",
            settings,
            urgent=True,
        )

        self.assertIn("URGENT", message)
        self.assertIn("<@222>", message)

    def test_current_context_uses_previous_day_before_5am_madrid(self) -> None:
        now = blockers.MADRID_TZ.localize(dt.datetime(2026, 4, 13, 1, 30))

        ctx = blockers.current_context(now)

        self.assertEqual(ctx.today_iso, "2026-04-12")
        self.assertEqual(ctx.week_code, "26-W15")


class InternalMeetingCreatorTests(unittest.TestCase):
    def test_week_context_for_date_uses_meeting_week(self) -> None:
        year, week, week_code, quarter_name = internal_server._week_context_for_date("2026-05-12T10:00:00+02:00")

        self.assertEqual(year, 2026)
        self.assertEqual(week, 20)
        self.assertEqual(week_code, "26-W20")
        self.assertEqual(quarter_name, "Q2 2026")

    def test_create_meeting_attendance_tasks_creates_one_task_per_attendee(self) -> None:
        app = internal_server.InternalNotionApp.__new__(internal_server.InternalNotionApp)
        app.meeting_task_project_id = ""
        app.meeting_task_project_name = "ALPHA"
        app.notion = MagicMock()
        app.notion.list_projects.return_value = [{"id": "project-alpha", "name": "ALPHA"}]
        app.notion.resolve_current_week.return_value = "26-W20"
        app.notion._week_matches.side_effect = lambda left, right: left == right

        create_calls: list[dict[str, object]] = []

        def create_tasks_batch(**kwargs: object) -> list[dict[str, str]]:
            create_calls.append(kwargs)
            return [{"id": f"task-{kwargs['role']}"}]

        app.notion.create_tasks_batch.side_effect = create_tasks_batch

        created = app._create_meeting_attendance_tasks(
            {
                "title": "Weekly Sync",
                "date_iso": "2026-05-12T10:00:00+02:00",
                "date_label": "Tuesday 12 May, 10:00",
                "attendees": ["CEO", "CTO", "CEO"],
            }
        )

        self.assertEqual(created, [{"id": "task-CEO"}, {"id": "task-CTO"}])
        self.assertEqual([call["role"] for call in create_calls], ["CEO", "CTO"])
        self.assertEqual([call["founder_name"] for call in create_calls], ["Oriol", "Arnau"])
        self.assertEqual({call["project_id"] for call in create_calls}, {"project-alpha"})
        self.assertEqual({call["project_name"] for call in create_calls}, {"ALPHA"})
        self.assertEqual({call["week_code"] for call in create_calls}, {"26-W20"})
        self.assertEqual({call["quarter_name"] for call in create_calls}, {"Q2 2026"})
        self.assertEqual({call["month_name"] for call in create_calls}, {"May"})
        self.assertEqual({call["descriptions"][0] for call in create_calls}, {"Attend Weekly Sync on Tuesday 12 May, 10:00."})
        self.assertEqual({call["is_current_week"] for call in create_calls}, {True})


class InternalWeekServiceTests(unittest.TestCase):
    def test_run_weekly_rollover_uses_resolved_current_week(self) -> None:
        notion_service = MagicMock()
        notion_service.resolve_current_week.return_value = "26-W20"
        notion_service.get_next_week_code.return_value = "26-W21"
        notion_service.find_incomplete_tasks_for_week.return_value = [{"id": "task-1", "properties": {}}]
        notion_service.task_display_id.return_value = "ALPHA-CEO-1"
        notion_service._property_text.return_value = "Finish report"
        runtime = MagicMock(notion=notion_service)

        result = WeekService(runtime).run_weekly_rollover({"current_week": "26-W20"})

        notion_service.resolve_current_week.assert_called_once_with()
        notion_service.find_incomplete_tasks_for_week.assert_called_once_with("26-W20")
        notion_service.rollover_tasks_batch.assert_called_once()
        notion_service.set_is_current_week_flags.assert_called_once_with("26-W20", "26-W21")
        notion_service.set_current_week_in_settings.assert_called_once_with("26-W21", status="success", count=1)
        self.assertEqual(result["from_week"], "26-W20")
        self.assertEqual(result["to_week"], "26-W21")


class InternalTaskServiceTests(unittest.TestCase):
    def test_create_tasks_marks_current_week_from_resolved_week(self) -> None:
        notion_service = MagicMock()
        notion_service.resolve_current_week.return_value = "26-W21"
        notion_service._week_matches.side_effect = lambda left, right: left == right
        notion_service.create_tasks_batch.return_value = [{"id": "task-1"}]
        runtime = MagicMock(notion=notion_service)

        result = TasksService(runtime).create_tasks(
            {
                "founder": "oriol",
                "project_id": "project-alpha",
                "project_name": "ALPHA",
                "week_code": "26-W21",
                "descriptions": ["Finish report"],
            }
        )

        notion_service.resolve_current_week.assert_called_once_with()
        create_call = notion_service.create_tasks_batch.call_args.kwargs
        self.assertTrue(create_call["is_current_week"])
        self.assertEqual(result["created"], 1)


class NotionTaskCreationTests(unittest.TestCase):
    def test_list_projects_uses_related_database(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks-db", daily_logs_db_id="daily", team_db_id="team")
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
        service = notion.NotionService(token="token", tasks_db_id="tasks-db", daily_logs_db_id="daily", team_db_id="team")
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
        service = notion.NotionService(token="token", tasks_db_id="tasks-db", daily_logs_db_id="daily", team_db_id="team")
        service.client = MagicMock()
        service.client.data_sources = None
        schema = {
            "Display ID": {"type": "title"},
            "Owner": {"type": "relation"},
            "Role": {"type": "select", "select": {"options": [{"name": "CEO"}]}},
            "Project": {"type": "relation"},
            "Description": {"type": "rich_text"},
            "Year": {"type": "number"},
            "Quarter": {"type": "select", "select": {"options": [{"name": "Q2 2026"}]}},
            "Month": {"type": "select", "select": {"options": [{"name": "Apr"}]}},
            "Week": {"type": "select", "select": {"options": [{"name": "26-W16"}]}},
            "Is Current Week": {"type": "checkbox"},
            "Status": {"type": "checkbox"},
            "Done": {"type": "checkbox"},
            "Done date": {"type": "date"},
        }
        with patch.object(service, "_retrieve_schema", return_value=schema):
            with patch.object(service, "preview_task_ids", return_value=["ALPHA-CEO-1", "ALPHA-CEO-2"]):
                with patch.object(service, "lookup_team_member_id", return_value="team-member-1"):
                    service.client.pages.create.side_effect = [
                        {"id": "task-1"},
                        {"id": "task-2"},
                    ]
                    service.create_tasks_batch(
                        project_id="proj-1",
                        project_name="ALPHA",
                        role="CEO",
                        founder_name="Oriol",
                        descriptions=["Draft investor update", "Prepare demo script"],
                        year=2026,
                        quarter_name="Q2 2026",
                        month_name="Apr",
                        week_code="26-W16",
                        today_iso="2026-04-16",
                        is_current_week=True,
                    )

        create_calls = service.client.pages.create.call_args_list
        self.assertEqual(len(create_calls), 2)
        # Owner is set inline during create; no separate pages.update calls expected
        service.client.pages.update.assert_not_called()
        first_kwargs = create_calls[0].kwargs
        self.assertEqual(first_kwargs["parent"], {"database_id": "tasks-db"})
        self.assertEqual(
            first_kwargs["properties"]["Display ID"]["title"][0]["text"]["content"],
            "ALPHA-CEO-1",
        )
        self.assertEqual(first_kwargs["properties"]["Owner"]["relation"], [{"id": "team-member-1"}])
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
        self.assertTrue(first_kwargs["properties"]["Is Current Week"]["checkbox"])
        self.assertFalse(first_kwargs["properties"]["Status"]["checkbox"])
        self.assertFalse(first_kwargs["properties"]["Done"]["checkbox"])
        self.assertIsNone(first_kwargs["properties"]["Done date"]["date"])

    def test_task_matches_founder_ignores_owner_relation_and_falls_back_to_display_id(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        task = {
            "properties": {
                "Owner": {"type": "relation", "relation": [{"id": "daily-log-page"}]},
                "Display ID": {"type": "title", "title": [{"plain_text": "ALPHA-CEO-72"}]},
            }
        }

        self.assertTrue(service._task_matches_founder(task, role="CEO", founder_name="Oriol"))
        self.assertFalse(service._task_matches_founder(task, role="COO", founder_name="Adam"))


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
        with patch("bot.commands.meetings.asyncio.to_thread", new=AsyncMock(return_value=[{"id": "page-1"}])) as to_thread:
            result = await meetings._query_all_async(notion_service, "meetings-db")

        self.assertEqual(result, [{"id": "page-1"}])
        to_thread.assert_awaited_once_with(notion_service._query_all, "meetings-db")

    async def test_update_page_async_uses_to_thread(self) -> None:
        notion_service = MagicMock()
        notion_service.client.pages.update = MagicMock()
        properties = {"Announced": {"checkbox": True}}

        with patch("bot.commands.meetings.asyncio.to_thread", new=AsyncMock(return_value=None)) as to_thread:
            await meetings._update_page_async(notion_service, "page-1", properties)

        to_thread.assert_awaited_once_with(
            notion_service.client.pages.update,
            page_id="page-1",
            properties=properties,
        )


class NotionServiceTests(unittest.TestCase):
    def test_is_task_done_supports_checkbox_and_status(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
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
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        task = {
            "properties": {
                "Display ID": {"type": "title", "title": [{"plain_text": "ALPHA-CEO-45"}]},
            }
        }

        self.assertTrue(service._task_matches_founder(task, role="CEO", founder_name="Oriol"))
        self.assertFalse(service._task_matches_founder(task, role="CTO", founder_name="Arnau"))

    def test_query_all_uses_data_source_query_when_database_query_missing(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
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
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        service.client = MagicMock()
        service.client.databases.retrieve.return_value = {
            "data_sources": [{"id": "source-123"}, {"id": "source-456"}],
        }

        result = service.primary_data_source_id("db-123")

        self.assertEqual(result, "source-123")
        service.client.databases.retrieve.assert_called_once_with(database_id="db-123")

    def test_verify_startup_disables_streaks_when_team_db_unreachable(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        service.client = MagicMock()

        def retrieve_side_effect(*, database_id: str):
            if database_id == "team":
                raise RuntimeError("not shared")
            return {"properties": {}}

        service.client.databases.retrieve.side_effect = retrieve_side_effect
        service.verify_startup()

        self.assertFalse(service.streaks_available())

    def test_get_next_week_code_handles_year_boundaries(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        # Regular rollover
        self.assertEqual(service.get_next_week_code("26-W15"), "26-W16")
        # End of year 2026 (W53 is the last week of 2026)
        self.assertEqual(service.get_next_week_code("26-W53"), "27-W01")

    def test_get_current_week_from_settings_raises_when_settings_db_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        with self.assertRaisesRegex(RuntimeError, "No settings database configured"):
            service.get_current_week_from_settings()

    def test_resolve_current_week_prefers_settings_db_over_task_flags(self) -> None:
        service = notion.NotionService(
            token="token",
            tasks_db_id="tasks",
            daily_logs_db_id="daily",
            team_db_id="team",
            settings_db_id="settings",
        )
        tasks = [
            {
                "id": "task-1",
                "properties": {
                    "Week": {"type": "select", "select": {"name": "26-W21"}},
                    "Is Current Week": {"type": "checkbox", "checkbox": True},
                    "Status": {"type": "select", "select": {"name": "Todo"}},
                },
            }
        ]

        with patch.object(service, "_query_all", side_effect=[[{"properties": {"Current Week": {"type": "rich_text", "rich_text": [{"plain_text": "26-W20"}]}}}], tasks]):
            self.assertEqual(service.resolve_current_week(), "26-W20")

    def test_resolve_current_week_uses_task_flags_when_settings_db_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "task-1",
                "properties": {
                    "Week": {"type": "select", "select": {"name": "26-W21"}},
                    "Is Current Week": {"type": "checkbox", "checkbox": True},
                    "Status": {"type": "select", "select": {"name": "Todo"}},
                },
            }
        ]

        with patch.object(service, "_query_all", return_value=tasks):
            self.assertEqual(service.resolve_current_week(), "26-W21")

    def test_resolve_current_week_falls_back_to_task_flags_when_settings_lookup_fails(self) -> None:
        service = notion.NotionService(
            token="token",
            tasks_db_id="tasks",
            daily_logs_db_id="daily",
            team_db_id="team",
            settings_db_id="settings",
        )
        tasks = [
            {
                "id": "task-1",
                "properties": {
                    "Week": {"type": "select", "select": {"name": "2026-W21"}},
                    "Is Current Week": {"type": "checkbox", "checkbox": True},
                    "Status": {"type": "select", "select": {"name": "Todo"}},
                },
            }
        ]

        with patch.object(service, "_query_all", side_effect=[RuntimeError("settings offline"), tasks]):
            self.assertEqual(service.resolve_current_week(), "26-W21")

    def test_resolve_current_week_warns_and_uses_latest_flagged_week(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "task-1",
                "properties": {
                    "Week": {"type": "select", "select": {"name": "26-W20"}},
                    "Is Current Week": {"type": "checkbox", "checkbox": True},
                    "Status": {"type": "select", "select": {"name": "Todo"}},
                },
            },
            {
                "id": "task-2",
                "properties": {
                    "Week": {"type": "select", "select": {"name": "26-W21"}},
                    "Is Current Week": {"type": "checkbox", "checkbox": True},
                    "Status": {"type": "select", "select": {"name": "Todo"}},
                },
            },
        ]

        with patch.object(service, "_query_all", return_value=tasks):
            with self.assertLogs("xcg_bot.notion", level="WARNING") as logs:
                self.assertEqual(service.resolve_current_week(), "26-W21")
        self.assertTrue(any("Multiple task weeks are flagged as current week" in entry for entry in logs.output))

    def test_resolve_current_week_raises_when_no_settings_or_task_flags_exist(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "task-1",
                "properties": {
                    "Week": {"type": "select", "select": {"name": "26-W21"}},
                    "Status": {"type": "select", "select": {"name": "Todo"}},
                },
            }
        ]

        with patch.object(service, "_query_all", return_value=tasks):
            with self.assertRaisesRegex(RuntimeError, "Unable to resolve current week from task flags"):
                service.resolve_current_week()

    def test_set_current_week_in_settings_noops_when_settings_db_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        service.client = MagicMock()

        service.set_current_week_in_settings("26-W20", status="success", count=3)

        service.client.pages.update.assert_not_called()

    def test_set_is_current_week_flags_noops_when_property_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        service.client = MagicMock()
        with patch.object(service, "_query_all", return_value=[{"id": "task-1", "properties": {}}]):
            with patch.object(service, "_retrieve_schema", return_value={"Week": {"type": "select"}}):
                service.set_is_current_week_flags("26-W19", "26-W20")

        service.client.pages.update.assert_not_called()

    def test_rollover_task_applies_correct_description_prefixes(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
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
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "done-today",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-04-10T13:15:00+02:00"}},
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

    def test_query_log_tasks_uses_done_date_logical_day_and_latest_week(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "done-after-midnight",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-04-14T00:57:00+02:00"}},
                    "Week": {"type": "select", "select": {"name": "26-W16"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "Done just after midnight"}]},
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
            candidates, completed, active_week = service.query_log_tasks("CEO", "2026-04-13", "26-W15")

        self.assertEqual([task["id"] for task in candidates], ["done-after-midnight", "todo-same-week"])
        self.assertEqual([task["id"] for task in completed], ["done-after-midnight"])
        self.assertEqual(active_week, "26-W16")

    def test_query_log_tasks_excludes_tasks_done_on_other_days(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "done-yesterday",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "CEO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-04-11T23:40:00+02:00"}},
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

    def test_query_log_tasks_includes_adam_style_after_midnight_tasks_in_previous_logical_day(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        tasks = [
            {
                "id": "task-0029",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "COO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-05-13T00:29:00+02:00"}},
                    "Week": {"type": "select", "select": {"name": "26-W20"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "00:29"}]},
                },
            },
            {
                "id": "task-0057",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "COO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-05-13T00:57:00+02:00"}},
                    "Week": {"type": "select", "select": {"name": "26-W20"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "00:57"}]},
                },
            },
            {
                "id": "task-0139",
                "properties": {
                    "Role": {"type": "select", "select": {"name": "COO"}},
                    "Status": {"type": "checkbox", "checkbox": True},
                    "Done date": {"type": "date", "date": {"start": "2026-05-13T01:39:00+02:00"}},
                    "Week": {"type": "select", "select": {"name": "26-W20"}},
                    "Description": {"type": "rich_text", "rich_text": [{"plain_text": "01:39"}]},
                },
            },
        ]
        with patch.object(service, "_query_all", return_value=tasks):
            candidates, completed, active_week = service.query_log_tasks("COO", "2026-05-12", "26-W20")

        self.assertEqual([task["id"] for task in candidates], ["task-0029", "task-0057", "task-0139"])
        self.assertEqual([task["id"] for task in completed], ["task-0029", "task-0057", "task-0139"])
        self.assertEqual(active_week, "26-W20")

    def test_set_task_completion_checkbox_clears_done_date(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
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

        service.set_task_completion(task, completed=False)

        service.client.pages.update.assert_called_once_with(
            page_id="page-1",
            properties={
                "Status": {"checkbox": False},
                "Done date": {"date": None},
            },
        )

    def test_set_task_completion_updates_status_and_done_checkbox_when_both_exist(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
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

        service.set_task_completion(task, completed=True, done_at_iso="2026-05-07T16:10:00+02:00")

        service.client.pages.update.assert_called_once_with(
            page_id="page-1",
            properties={
                "Status": {"select": {"name": "Done"}},
                "Done": {"checkbox": True},
                "Done date": {"date": {"start": "2026-05-07T16:10:00+02:00"}},
            },
        )

    def test_has_daily_log_matches_founder_and_logical_day(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        rows = [
            {
                "properties": {
                    "Founder": {"type": "select", "select": {"name": "Oriol"}},
                    "Logical Day": {"type": "date", "date": {"start": "2026-04-12"}},
                }
            }
        ]
        with patch.object(service, "_query_all", return_value=rows):
            result = service.has_daily_log("Oriol", "2026-04-12")

        self.assertTrue(result)

    def test_has_daily_log_matches_founder_from_title_when_property_is_absent(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily", team_db_id="team")
        rows = [
            {
                "properties": {
                    "Title": {"type": "title", "title": [{"plain_text": "Oriol · 26-W19 · 2026-05-07"}]},
                    "Logical Day": {"type": "date", "date": {"start": "2026-05-07"}},
                }
            }
        ]
        with patch.object(service, "_query_all", return_value=rows):
            result = service.has_daily_log("Oriol", "2026-05-07")

        self.assertTrue(result)

    def test_create_daily_log_builds_expected_properties(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", team_db_id="team")
        service.client = MagicMock()
        service.client.data_sources = None

        schema = {
            "Title": {"type": "title"},
            "Logged At": {"type": "date"},
            "Logical Day": {"type": "date"},
            "Created on": {"type": "date"},
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
                logged_at_iso="2026-04-10T21:03:00+02:00",
                completed_task_ids=["page-1", "page-2"],
                notes_text="reflection",
            )

        _, kwargs = service.client.pages.create.call_args
        self.assertEqual(kwargs["parent"], {"database_id": "daily-db"})
        self.assertEqual(kwargs["properties"]["Founder"]["select"]["name"], "Oriol")
        self.assertEqual(kwargs["properties"]["Role"]["select"]["name"], "CEO")
        self.assertEqual(kwargs["properties"]["Week"]["select"]["name"], "26-W15")
        self.assertEqual(kwargs["properties"]["Logged At"]["date"]["start"], "2026-04-10T21:03:00+02:00")
        self.assertEqual(kwargs["properties"]["Logical Day"]["date"]["start"], "2026-04-10")
        self.assertEqual(kwargs["properties"]["Created on"]["date"]["start"], "2026-04-10T21:03:00+02:00")
        self.assertEqual(kwargs["properties"]["Tasks completed"]["relation"], [{"id": "page-1"}, {"id": "page-2"}])
        self.assertEqual(kwargs["properties"]["Notes"]["rich_text"][0]["text"]["content"], "reflection")

    def test_create_daily_log_supports_title_only_founder_schema(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", team_db_id="team")
        service.client = MagicMock()
        service.client.data_sources = None
        schema = {
            "Title": {"type": "title"},
            "Logged At": {"type": "date"},
            "Logical Day": {"type": "date"},
            "Created on": {"type": "date"},
            "Tasks completed": {"type": "relation"},
            "Notes": {"type": "rich_text"},
        }

        with patch.object(service, "_retrieve_schema", return_value=schema):
            service.create_daily_log(
                founder_name="Oriol",
                founder_role="CEO",
                week_code="26-W19",
                today_iso="2026-05-07",
                logged_at_iso="2026-05-08T01:12:00+02:00",
                completed_task_ids=["page-1"],
                notes_text="reflection",
            )

        _, kwargs = service.client.pages.create.call_args
        self.assertEqual(kwargs["properties"]["Title"]["title"][0]["text"]["content"], "Oriol · 26-W19 · 2026-05-07")
        self.assertEqual(kwargs["properties"]["Logged At"]["date"]["start"], "2026-05-08T01:12:00+02:00")
        self.assertEqual(kwargs["properties"]["Logical Day"]["date"]["start"], "2026-05-07")
        self.assertEqual(kwargs["properties"]["Created on"]["date"]["start"], "2026-05-08T01:12:00+02:00")
        self.assertNotIn("Founder", kwargs["properties"])
        self.assertNotIn("Role", kwargs["properties"])
        self.assertNotIn("Week", kwargs["properties"])

    def test_daily_log_dates_returns_founder_dates(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", team_db_id="team")
        rows = [
            {
                "properties": {
                    "Founder": {"type": "select", "select": {"name": "Oriol"}},
                    "Logical Day": {"type": "date", "date": {"start": "2026-04-28"}},
                }
            },
            {
                "properties": {
                    "Founder": {"type": "select", "select": {"name": "Arnau"}},
                    "Logical Day": {"type": "date", "date": {"start": "2026-04-29"}},
                }
            },
        ]
        with patch.object(service, "_query_all", return_value=rows):
            dates = service.daily_log_dates("Oriol")

        self.assertEqual(dates, [dt.date(2026, 4, 28)])

    def test_update_streak_row_writes_current_and_best(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", team_db_id="team")
        service.client = MagicMock()
        schema = {"Current Streak": {"type": "number"}, "Best Streak": {"type": "number"}}

        with patch.object(service, "_retrieve_schema", return_value=schema):
            service.update_streak_row(
                "streak-row",
                current_streak=0,
                best_streak=12,
            )

        service.client.pages.update.assert_called_once_with(
            page_id="streak-row",
            properties={
                "Current Streak": {"number": 0},
                "Best Streak": {"number": 12},
            },
        )


class DailyLogDedupeTests(unittest.TestCase):
    def test_preview_surfaces_four_duplicate_groups(self) -> None:
        notion_service = MagicMock()
        runtime = MagicMock(notion=notion_service)
        service = DailyLogDedupeService(runtime)
        rows = [
            self._daily_log_row("adam-1", "Adam · 26-W20 · 2026-05-13", "2026-05-12", created_time="2026-05-13T00:40:00+02:00"),
            self._daily_log_row("adam-2", "Adam · 26-W20 · 2026-05-12", "2026-05-12", created_time="2026-05-13T01:10:00+02:00"),
            self._daily_log_row("oriol-1", "Oriol · 26-W20 · 2026-05-12", "2026-05-12", created_time="2026-05-12T20:00:00+02:00"),
            self._daily_log_row("oriol-2", "Oriol · 26-W20 · 2026-05-12", "2026-05-12", created_time="2026-05-12T21:00:00+02:00"),
            self._daily_log_row("arnau-1", "Arnau · 26-W20 · 2026-05-11", "2026-05-11", created_time="2026-05-11T20:00:00+02:00"),
            self._daily_log_row("arnau-2", "Arnau · 26-W20 · 2026-05-11", "2026-05-11", created_time="2026-05-11T22:00:00+02:00"),
            self._daily_log_row("oriol-3", "Oriol · 26-W19 · 2026-05-07", "2026-05-07", created_time="2026-05-07T20:00:00+02:00"),
            self._daily_log_row("oriol-4", "Oriol · 26-W19 · 2026-05-07", "2026-05-07", created_time="2026-05-07T22:00:00+02:00"),
        ]
        self._stub_daily_log_helpers(notion_service, rows)

        result = service.preview()

        self.assertEqual(result["group_count"], 4)
        self.assertEqual(
            [(group["founder_name"], group["logical_day"]) for group in result["groups"]],
            [
                ("Oriol", "2026-05-07"),
                ("Arnau", "2026-05-11"),
                ("Adam", "2026-05-12"),
                ("Oriol", "2026-05-12"),
            ],
        )

    @patch("backend.services.daily_log_dedupe.sync_founder_streak_from_daily_logs", return_value=(3, 5, "2026-05-12"))
    def test_apply_merges_adam_duplicate_on_logical_day(self, sync_streak: MagicMock) -> None:
        notion_service = MagicMock()
        runtime = MagicMock(notion=notion_service)
        service = DailyLogDedupeService(runtime)
        keeper = self._daily_log_row(
            "adam-keeper",
            "Adam · 26-W20 · 2026-05-13",
            "2026-05-12",
            logged_at="2026-05-13T00:57:00+02:00",
            task_ids=["task-2", "task-1"],
            notes="keeper note",
            relation_ids=[],
            created_time="2026-05-13T00:57:00+02:00",
            week_code="26-W20",
        )
        loser = self._daily_log_row(
            "adam-loser",
            "Adam · 26-W20 · 2026-05-12",
            "2026-05-12",
            logged_at="2026-05-13T00:29:00+02:00",
            task_ids=["task-2"],
            notes="loser note",
            relation_ids=["team-adam"],
            created_time="2026-05-13T00:29:00+02:00",
            week_code="26-W20",
        )
        rows = [keeper, loser]
        self._stub_daily_log_helpers(notion_service, rows)
        notion_service.lookup_team_member_id.return_value = "team-adam"

        result = service.apply(founder="Adam", from_day="2026-05-12", to_day="2026-05-12")

        notion_service.update_daily_log.assert_called_once()
        update_kwargs = notion_service.update_daily_log.call_args.kwargs
        self.assertEqual(notion_service.update_daily_log.call_args.args[0], "adam-keeper")
        self.assertEqual(update_kwargs["title_text"], "Adam · 26-W20 · 2026-05-12")
        self.assertEqual(update_kwargs["logical_day_iso"], "2026-05-12")
        self.assertEqual(update_kwargs["logged_at_iso"], "2026-05-13T00:29:00+02:00")
        self.assertEqual(update_kwargs["founder_relation_ids"], ["team-adam"])
        self.assertEqual(update_kwargs["task_ids"], ["task-2", "task-1"])
        self.assertIn("--- merged from duplicate ---", update_kwargs["notes_text"])
        notion_service.archive_page.assert_called_once_with("adam-loser")
        sync_streak.assert_called_once_with(notion_service, "Adam")
        self.assertEqual(result["group_count"], 1)
        self.assertEqual(result["groups"][0]["archived_ids"], ["adam-loser"])

    def _stub_daily_log_helpers(self, notion_service: MagicMock, rows: list[dict[str, Any]]) -> None:
        notion_service.get_all_daily_logs.return_value = rows
        notion_service.daily_log_founder_name.side_effect = lambda row: row["meta"]["founder_name"]
        notion_service.daily_log_logical_day_iso.side_effect = lambda row: row["meta"]["logical_day"]
        notion_service.daily_log_title.side_effect = lambda row: row["meta"]["title"]
        notion_service.daily_log_logged_at_iso.side_effect = lambda row: row["meta"]["logged_at"]
        notion_service.daily_log_task_ids.side_effect = lambda row: row["meta"]["task_ids"]
        notion_service.daily_log_notes_text.side_effect = lambda row: row["meta"]["notes"]
        notion_service.daily_log_founder_relation_ids.side_effect = lambda row: row["meta"]["relation_ids"]
        notion_service.daily_log_week_code.side_effect = lambda row: row["meta"]["week_code"]
        notion_service.find_team_member.side_effect = lambda founder: {"name": founder}

    def _daily_log_row(
        self,
        row_id: str,
        title: str,
        logical_day: str,
        *,
        logged_at: str | None = None,
        task_ids: list[str] | None = None,
        notes: str = "",
        relation_ids: list[str] | None = None,
        created_time: str,
        week_code: str = "",
    ) -> dict[str, Any]:
        founder_name = title.split("·", 1)[0].strip()
        return {
            "id": row_id,
            "created_time": created_time,
            "meta": {
                "title": title,
                "founder_name": founder_name,
                "logical_day": logical_day,
                "logged_at": logged_at,
                "task_ids": task_ids or [],
                "notes": notes,
                "relation_ids": relation_ids or [],
                "week_code": week_code,
            },
        }


class ClaudeOAuthProviderTests(unittest.TestCase):
    def _write_credentials(
        self,
        profile_dir: Path,
        *,
        access_token: str,
        refresh_token: str,
        expires_at_ms: int,
        subscription_type: str = "team",
    ) -> Path:
        profile_dir.mkdir(parents=True, exist_ok=True)
        creds_path = profile_dir / ".credentials.json"
        creds_path.write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": access_token,
                        "refreshToken": refresh_token,
                        "expiresAt": expires_at_ms,
                        "subscriptionType": subscription_type,
                    }
                }
            ),
            encoding="utf-8",
        )
        return creds_path

    def test_expired_token_refreshes_and_persists_credentials(self) -> None:
        provider = ClaudeOAuthProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir)
            creds_path = self._write_credentials(
                profile_dir,
                access_token="expired-access",
                refresh_token="refresh-1",
                expires_at_ms=1,
            )
            refresh_response = MagicMock(is_success=True)
            refresh_response.json.return_value = {
                "access_token": "fresh-access",
                "refresh_token": "fresh-refresh",
                "expires_in": 3600,
            }
            usage_response = MagicMock(status_code=200, is_success=True)
            usage_response.json.return_value = {
                "five_hour": {"utilization": 42},
                "seven_day": {"utilization": 55},
                "seven_day_sonnet": {"utilization": 60},
            }

            with patch("backend.services.team_usage.providers.claude_oauth.httpx.post", return_value=refresh_response) as http_post:
                with patch("backend.services.team_usage.providers.claude_oauth.httpx.get", return_value=usage_response) as http_get:
                    payload = provider.get_usage({"type": "claude_oauth", "tier": "team_standard"}, profile_dir)
                    saved = json.loads(creds_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["tier"], "team")
        self.assertEqual(http_post.call_count, 1)
        self.assertEqual(http_get.call_count, 1)
        auth_header = http_get.call_args.kwargs["headers"]["Authorization"]
        self.assertEqual(auth_header, "Bearer fresh-access")
        self.assertEqual(saved["claudeAiOauth"]["accessToken"], "fresh-access")
        self.assertEqual(saved["claudeAiOauth"]["refreshToken"], "fresh-refresh")
        self.assertGreater(saved["claudeAiOauth"]["expiresAt"], 1)

    def test_unauthorized_usage_refreshes_and_retries(self) -> None:
        provider = ClaudeOAuthProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir)
            self._write_credentials(
                profile_dir,
                access_token="stale-access",
                refresh_token="refresh-2",
                expires_at_ms=9_999_999_999_999,
            )
            unauthorized = MagicMock(status_code=401, is_success=False, text="unauthorized")
            usage_ok = MagicMock(status_code=200, is_success=True)
            usage_ok.json.return_value = {"five_hour": {"utilization": 10}, "seven_day": {"utilization": 20}}
            refresh_response = MagicMock(is_success=True)
            refresh_response.json.return_value = {"access_token": "fresh-2", "expires_in": 3600}

            with patch(
                "backend.services.team_usage.providers.claude_oauth.httpx.get",
                side_effect=[unauthorized, usage_ok],
            ) as http_get:
                with patch("backend.services.team_usage.providers.claude_oauth.httpx.post", return_value=refresh_response) as http_post:
                    payload = provider.get_usage({"type": "claude_oauth", "tier": "team_standard"}, profile_dir)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(http_post.call_count, 1)
        self.assertEqual(http_get.call_count, 2)
        self.assertEqual(http_get.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer fresh-2")

    def test_expired_token_with_failed_refresh_returns_token_expired(self) -> None:
        provider = ClaudeOAuthProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir)
            self._write_credentials(
                profile_dir,
                access_token="expired-access",
                refresh_token="refresh-3",
                expires_at_ms=1,
            )
            refresh_response = MagicMock(is_success=False, status_code=400, text="bad refresh")
            with patch("backend.services.team_usage.providers.claude_oauth.httpx.post", return_value=refresh_response):
                with patch("backend.services.team_usage.providers.claude_oauth.httpx.get") as http_get:
                    payload = provider.get_usage({"type": "claude_oauth", "tier": "team_standard"}, profile_dir)

        self.assertEqual(payload["status"], "token_expired")
        http_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
