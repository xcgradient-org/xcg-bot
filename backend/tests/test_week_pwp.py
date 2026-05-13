from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from backend.scripts.latex_pwp import parse_args  # noqa: E402
from backend.services.pwp_reports import WeekPwpReportService  # noqa: E402


class FakeNotion:
    def __init__(self) -> None:
        self.tasks = [
            {"id": "1", "description": "Ship the weekly dashboard", "done": True},
            {"id": "2", "description": "Review the pricing proposal", "done": True},
            {"id": "3", "description": "Fix the onboarding copy", "done": False},
            {"id": "4", "description": "Prepare the investor follow-up", "done": False},
        ]

    def find_team_member(self, query: str) -> dict[str, str] | None:  # noqa: ARG002
        return {"id": "team-1", "name": "Oriol", "role": "CEO", "status": "Active"}

    def find_team_member_by_role(self, role: str) -> dict[str, str] | None:
        return {"id": "team-1", "name": "Oriol", "role": role, "status": "Active"}

    def query_week_tasks(self, role: str, week_code: str, founder_name: str | None = None):
        del role, week_code, founder_name
        all_tasks = list(self.tasks)
        done = [task for task in self.tasks if task["done"]]
        pending = [task for task in self.tasks if not task["done"]]
        return all_tasks, done, pending

    def task_descriptions(self, tasks):
        return [task["description"] for task in tasks]


class FakeReflection:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json_response(self, *, system_prompt: str, user_prompt: str, max_output_tokens: int = 0):  # noqa: ARG002
        self.prompts.append(system_prompt)
        prompt = system_prompt.lower()
        if "completed-work section" in prompt:
            return {
                "summary": "Completed work focused on shipping and commercial prep.",
                "headline": "Completed work",
                "chart": {
                    "title": "Completed work balance",
                    "labels": ["Shipping", "Commercial"],
                    "values": [1, 1],
                    "note": "Balanced delivery and review work.",
                },
                "groups": [
                    {
                        "title": "Shipping",
                        "summary": "One delivered item.",
                        "tasks": ["Ship the weekly dashboard."],
                        "impact": "Visible product progress.",
                    },
                    {
                        "title": "Commercial",
                        "summary": "One pricing review task.",
                        "tasks": ["Review the pricing proposal."],
                        "impact": "Keeps the pitch aligned.",
                    },
                ],
                "insights": ["Two concrete wins were completed."],
            }
        if "carry-over section" in prompt:
            return {
                "summary": "A small set of operational items remains open.",
                "headline": "Carry-over work",
                "chart": {
                    "title": "Carry-over balance",
                    "labels": ["Copy", "Investor"],
                    "values": [1, 1],
                    "note": "Needs follow-up next week.",
                },
                "groups": [
                    {
                        "title": "Copy",
                        "summary": "One open copy task.",
                        "tasks": ["Fix the onboarding copy."],
                        "risk": "Needs review.",
                    },
                    {
                        "title": "Investor",
                        "summary": "One open follow-up.",
                        "tasks": ["Prepare the investor follow-up."],
                        "risk": "Stakeholder update pending.",
                    },
                ],
                "next_actions": ["Resolve the copy issue.", "Send the follow-up draft."],
                "blank_pages": 2,
            }
        if "composing the cover" in prompt:
            return {
                "cover": {
                    "headline": "Week 20 report",
                    "subtitle": "CEO · Oriol",
                    "summary": "Completed work landed cleanly and the remaining items are clearly scoped.",
                    "intro": "This deck keeps the story tight and leaves manual space at the end.",
                },
                "next_week": {
                    "headline": "Next week focus",
                    "summary": "Close the open items and continue the product push.",
                    "bullets": ["Fix the onboarding copy.", "Prepare the investor follow-up."],
                },
            }
        raise AssertionError(f"Unexpected prompt: {system_prompt}")


class WeekPwpGeneratorTests(unittest.TestCase):
    def test_parse_args_supports_week_shorthand(self) -> None:
        args = parse_args(["pwp", "-week20", "CEO", "--out", "/tmp"])
        self.assertEqual(args.week, 20)
        self.assertEqual(args.person, "CEO")
        self.assertEqual(args.out, "/tmp")

    def test_generate_project_writes_makefile_and_readme(self) -> None:
        runtime = type("Runtime", (), {"notion": FakeNotion(), "reflection": FakeReflection()})()
        service = WeekPwpReportService(runtime)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = service.generate_project(week_number=20, person="CEO", out_dir=Path(tmpdir))
            project = result.project_dir

            self.assertTrue(project.exists())
            self.assertTrue((project / "Makefile").exists())
            self.assertTrue((project / "build.js").exists())
            self.assertTrue((project / "deck.js").exists())
            self.assertTrue((project / "data.js").exists())
            self.assertTrue((project / "README.md").exists())
            self.assertTrue((project / "update.sh").exists())
            self.assertTrue((project / "assets" / "logo.png").exists())
            self.assertTrue((project / "output" / "slides").is_dir())
            self.assertTrue((project / "update.sh").stat().st_mode & stat.S_IXUSR)

            readme = (project / "README.md").read_text(encoding="utf-8")
            self.assertIn("flux pwp week-report --week 20 --person CEO", readme)
            self.assertIn("make build", readme)
            self.assertIn("make pdf", readme)

            data_js = (project / "data.js").read_text(encoding="utf-8")
            self.assertIn("Week 20 report", data_js)
            self.assertIn('"kind": "cover"', data_js)
            self.assertIn('"kind": "next_week"', data_js)
            self.assertIn('"kind": "blank"', data_js)

            self.assertEqual(result.task_count, 4)
            self.assertEqual(result.done_count, 2)
            self.assertEqual(result.pending_count, 2)
            self.assertRegex(result.week_code, r"^\d{2}-W20$")

    def test_build_project_zip_returns_zip_payload(self) -> None:
        runtime = type("Runtime", (), {"notion": FakeNotion(), "reflection": FakeReflection()})()
        service = WeekPwpReportService(runtime)
        data, filename = service.build_project_zip(week_number=20, person="CEO")
        self.assertTrue(filename.endswith(".zip"))
        self.assertGreater(len(data), 64)
        self.assertEqual(data[:2], b"PK")
    unittest.main()
