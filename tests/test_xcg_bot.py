from __future__ import annotations

import sys
import unittest
from pathlib import Path
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
        with patch.object(service, "_post_json", return_value={"models": [{"name": "qwen2.5:32b"}]}) as post_json:
            service.verify_startup()
        post_json.assert_called_once_with("/api/tags", {})

    def test_verify_startup_raises_if_model_missing(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_post_json", return_value={"models": [{"name": "llama3.1:8b"}]}):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                service.verify_startup()

    def test_generate_json_response_parses_json_payload(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_request", return_value={"response": '{"ok": true, "count": 2}'}):
            payload = service.generate_json_response(system_prompt="s", user_prompt="u")
        self.assertEqual(payload, {"ok": True, "count": 2})

    def test_generate_reflection_raises_on_empty_response(self) -> None:
        service = reflection.ReflectionService(model="qwen2.5:32b")
        with patch.object(service, "_request", return_value={"response": ""}):
            with self.assertRaisesRegex(RuntimeError, "empty reflection"):
                service.generate_reflection(
                    founder_name="Oriol",
                    founder_role="CEO",
                    today_iso="2026-04-10",
                    completed_tasks=["Task A"],
                    raw_notes="",
                )


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


class LogCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_blocker_follow_up_posts_blocker(self) -> None:
        bot = MagicMock()
        interaction = MagicMock()
        interaction.channel_id = 999
        interaction.user.id = 123
        interaction.followup.send = AsyncMock()
        fake_message = MagicMock()
        fake_message.content = "@CTO - Need schema review"

        with patch("log_command.wait_for_follow_up", return_value=fake_message), patch("log_command.post_blocker") as post_blocker:
            await log_command.process_blocker_follow_up(bot, interaction, "Oriol", 456)

        post_blocker.assert_awaited_once()
        interaction.followup.send.assert_awaited_once_with("Blocker posted to the blockers channel.", ephemeral=True)

    async def test_process_blocker_follow_up_ignores_no(self) -> None:
        bot = MagicMock()
        interaction = MagicMock()
        interaction.channel_id = 999
        interaction.user.id = 123
        interaction.followup.send = AsyncMock()
        fake_message = MagicMock()
        fake_message.content = "no"

        with patch("log_command.wait_for_follow_up", return_value=fake_message), patch("log_command.post_blocker") as post_blocker:
            await log_command.process_blocker_follow_up(bot, interaction, "Oriol", 456)

        post_blocker.assert_not_called()
        interaction.followup.send.assert_not_called()


class MeetingCommandTests(unittest.TestCase):
    def test_normalize_attendees_splits_slashes_and_commas(self) -> None:
        attendees = meeting_command._normalize_attendees("CEO / CTO, COO")
        self.assertEqual(attendees, ["CEO", "CTO", "COO"])

    def test_normalize_payload_falls_back_to_raw_input(self) -> None:
        raw_input = {
            "title": "Weekly Sync",
            "date_input": "Mon Apr 14 2026 10:00",
            "type": "Weekly Sync",
            "attendees": "CEO / CTO / COO",
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

    def test_create_daily_log_builds_expected_properties(self) -> None:
        service = notion.NotionService(token="token", tasks_db_id="tasks", daily_logs_db_id="daily-db", streaks_db_id="streaks")
        service.client = MagicMock()

        service.create_daily_log(
            founder_name="Oriol",
            founder_role="CEO",
            week_code="26-W15",
            today_iso="2026-04-10",
            completed_task_ids=["page-1", "page-2"],
            raw_notes="note",
            reflection_text="reflection",
        )

        _, kwargs = service.client.pages.create.call_args
        self.assertEqual(kwargs["parent"], {"database_id": "daily-db"})
        self.assertEqual(kwargs["properties"]["Founder"]["select"]["name"], "Oriol")
        self.assertEqual(kwargs["properties"]["Role"]["select"]["name"], "CEO")
        self.assertEqual(kwargs["properties"]["Week"]["select"]["name"], "26-W15")
        self.assertEqual(kwargs["properties"]["Tasks completed"]["relation"], [{"id": "page-1"}, {"id": "page-2"}])


if __name__ == "__main__":
    unittest.main()
