from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from backend.services.pwp_reports import WeekPwpReportService
from backend.config import configure_logging
from backend.services.runtime import build_runtime


def _normalize_argv(argv: list[str]) -> list[str]:
    args = list(argv)
    if args and args[0].lower() == "pwp":
        args = args[1:]

    normalized: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if re.fullmatch(r"-?week\d{1,2}", token, flags=re.IGNORECASE):
            normalized.extend(["--week", token.lstrip("-")[4:]])
        elif token in {"-w", "--week"}:
            if index + 1 >= len(args):
                raise SystemExit("error: --week requires a value")
            normalized.extend(["--week", args[index + 1]])
            index += 1
        else:
            normalized.append(token)
        index += 1
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="xcg-bot week-pwp",
        description="Generate a weekly PWP report deck from Notion tasks (writes under --out only).",
    )
    parser.add_argument("--week", "-w", type=int, required=True, help="Week number (0 uses the current week).")
    parser.add_argument(
        "person",
        help="Team member: role title (CEO), full name, or email as stored in the Team database.",
    )
    parser.add_argument("--out", "-o", default=".", help="Parent directory for the generated project.")
    namespace = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))
    if not 0 <= int(namespace.week) <= 52:
        parser.error("week must be between 0 and 52")
    namespace.person = str(namespace.person).strip()
    return namespace


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    runtime = build_runtime()
    service = WeekPwpReportService(runtime)
    result = service.generate_project(
        week_number=int(args.week),
        person=args.person,
        out_dir=Path(args.out),
    )

    print(f"✅ Created {result.project_dir}")
    print()
    print("Next steps:")
    print(f"  cd {result.project_dir}")
    print("  make deps")
    print("  make build")
    print("  make pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
