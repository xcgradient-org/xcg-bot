from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pytz
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notion import NotionService  # noqa: E402
from reflection import ReflectionService  # noqa: E402


LOGGER = logging.getLogger("xcg_bot.internal_htmls")
MADRID_TZ = pytz.timezone("Europe/Madrid")
FOUNDER_BY_ID = {
    "oriol": {"name": "Oriol", "role": "CEO"},
    "arnau": {"name": "Arnau", "role": "CTO"},
    "adam": {"name": "Adam", "role": "COO"},
}
DEFAULT_TEAM_DB_ID = "c7ed3e34702c4d26b310cc7d91b16a97"
DEFAULT_OBJECTIVES_DB_ID = "1e4e9d72f9f5473abd43c1e0ecc53e49"
DEFAULT_KRS_DB_ID = "2b3c5815dd4943bb8c4dff005901fb1d"
TASK_PARSE_PROMPT = (
    "You convert a founder's natural-language task request into structured tasks for an internal Notion task database. "
    "Return valid JSON with exactly one key: tasks. "
    "tasks must be an array of objects, each with exactly one key: description. "
    "Each description must be a short, concrete, imperative task sentence. "
    "Split bundled requests into separate tasks when the user clearly asks for multiple tasks. "
    "Do not invent project names, owners, deadlines, IDs, priorities, status, or metadata. "
    "Do not add markdown or commentary."
)
KR_PARSE_PROMPT = (
    "You convert raw key result notes into structured OKR key results. "
    "Return valid JSON with exactly one key: key_results. "
    "key_results must be an array of objects with description, metric, and target string fields. "
    "Do not invent numbers. Leave metric or target blank when unclear. "
    "Do not add markdown or commentary."
)


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _clean_line(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    cleaned = re.sub(r"^([\-\*\u2022\u25E6•▪►]+|\d+[\.\)])\s*", "", cleaned).strip()
    return cleaned.strip(" \t\r\n-•,;")


def _finalize_sentence(text: str) -> str:
    cleaned = _clean_line(text)
    if not cleaned:
        return ""
    cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned[-1] in ".!?" else f"{cleaned}."


def _fallback_task_descriptions(text: str) -> list[str]:
    stripped = re.sub(
        r"^\s*(?:add|create)\s+(?:these\s+)?(?:\d+|two|three|four|five)?\s*tasks?\s*:?\s*",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    )
    chunks = [chunk for chunk in re.split(r"[\n;]+", stripped) if chunk.strip()]
    if len(chunks) == 1 and re.search(r"\b(?:2|two)\s+tasks?\b", text, flags=re.IGNORECASE):
        chunks = [chunk for chunk in re.split(r"\s+\band\s+", chunks[0], maxsplit=1, flags=re.IGNORECASE) if chunk.strip()]

    descriptions: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        description = _finalize_sentence(chunk)
        lowered = description.lower()
        if not description or lowered in seen:
            continue
        seen.add(lowered)
        descriptions.append(description)
    return descriptions


def _guess_kr_metric(line: str) -> tuple[str, str]:
    patterns = (
        (r"(\d+(?:[.,]\d+)?)\s*%", "%", lambda m: f"{m.group(1)}%"),
        (r"€\s*(\d[\d.,]*\s*(?:k|m|M|K)?)", "€", lambda m: "€" + m.group(1).replace(" ", "")),
        (r"\$\s*(\d[\d.,]*\s*(?:k|m|M|K)?)", "$", lambda m: "$" + m.group(1).replace(" ", "")),
        (r"\b(\d+)\s+(deals|hires|engineers|customers|users|signups|RFCs|interviews|calls|testimonials|loops)\b", "", lambda m: m.group(1)),
        (r"\bNPS\s*(\d+)\+?", "NPS", lambda m: m.group(1)),
    )
    for pattern, metric, target_fn in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return metric or match.group(2).lower(), target_fn(match)
    return "", ""


def _fallback_key_results(text: str) -> list[dict[str, str]]:
    key_results: list[dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        description = _clean_line(raw_line)
        if not description:
            continue
        metric, target = _guess_kr_metric(description)
        key_results.append({"description": description[0].upper() + description[1:], "metric": metric, "target": target})
    return key_results


def _period_code(period_type: str, quarter: int | str | None, year: int | str | None) -> str:
    year_int = int(year or datetime.now(MADRID_TZ).year)
    if str(period_type or "").lower() == "annual":
        return str(year_int)
    quarter_int = int(quarter or ((datetime.now(MADRID_TZ).month - 1) // 3 + 1))
    return f"{year_int % 100:02d}-Q{quarter_int}"


def _week_parts(week_code: str) -> tuple[int, int]:
    match = re.match(r"^(\d{2})-W(\d{1,2})$", str(week_code or "").strip(), flags=re.IGNORECASE)
    if not match:
        now = datetime.now(MADRID_TZ)
        iso_year, iso_week, _ = now.isocalendar()
        return iso_year, iso_week
    return 2000 + int(match.group(1)), int(match.group(2))


def _month_name() -> str:
    return datetime.now(MADRID_TZ).strftime("%b")


def _resolve_founder(payload: dict[str, Any]) -> dict[str, str]:
    founder_id = str(payload.get("founder") or "").strip().lower()
    founder = dict(FOUNDER_BY_ID.get(founder_id, {}))
    if not founder:
        name = str(payload.get("founder_name") or founder_id).strip().title()
        role = str(payload.get("role") or "").strip().upper()
        if not name or not role:
            raise ValueError("Unknown founder.")
        founder = {"name": name, "role": role}
    role = str(payload.get("role") or founder["role"]).strip().upper()
    founder["role"] = role
    return founder


class InternalNotionApp:
    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")
        self.objectives_db_id = _env("NOTION_OBJECTIVES_DB_ID", "NOTION_OBJECTIVES_DB", default=DEFAULT_OBJECTIVES_DB_ID)
        self.krs_db_id = _env("NOTION_KRS_DB_ID", "NOTION_KRS_DB", default=DEFAULT_KRS_DB_ID)
        self.notion = NotionService(
            token=_env("NOTION_TOKEN"),
            tasks_db_id=_env("NOTION_TASKS_DB_ID", "NOTION_TASKS_DB"),
            daily_logs_db_id=_env("NOTION_DAILY_LOGS_DB_ID", "NOTION_DAILY_LOGS_DB"),
            team_db_id=_env("NOTION_TEAM_DB_ID", "NOTION_TEAM_DB", default=DEFAULT_TEAM_DB_ID),
        )
        self.reflection = ReflectionService(
            model=_env("LLM_MODEL", default="openai/gpt-oss-20b"),
            base_url=_env("LLM_BASE_URL", default="https://api.groq.com/openai/v1"),
            api_keys=tuple(
                key.strip()
                for key in (
                    _env("LLM_API_KEY"),
                    _env("LLM_API_KEY_2"),
                    _env("LLM_API_KEY_3"),
                    *_env("LLM_API_KEYS").replace("\n", ",").split(","),
                )
                if key.strip()
            ),
            api_style=_env("LLM_API_STYLE", default="openai"),
        )

    def list_projects(self) -> dict[str, Any]:
        return {"projects": self.notion.list_projects()}

    def parse_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        descriptions: list[str] = []
        if self.reflection.api_keys:
            try:
                result = self.reflection.generate_json_response(
                    system_prompt=TASK_PARSE_PROMPT,
                    user_prompt=f"Founder request:\n{text.strip()}",
                    max_output_tokens=300,
                )
                raw_tasks = result.get("tasks")
                if isinstance(raw_tasks, list):
                    descriptions = [
                        _finalize_sentence(item.get("description") if isinstance(item, dict) else item)
                        for item in raw_tasks
                    ]
                    descriptions = [description for description in descriptions if description]
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Task parse LLM failed; using fallback parser: %s", exc)
        return {"descriptions": descriptions or _fallback_task_descriptions(text)}

    def preview_task_ids(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        year, week = _week_parts(str(payload.get("week_code") or ""))
        quarter = ((week - 1) // 13) + 1
        ids = self.notion.preview_task_ids(
            project_id=str(payload["project_id"]),
            project_name=str(payload["project_name"]),
            role=founder["role"],
            year=year,
            quarter_name=f"Q{min(quarter, 4)} {year}",
            count=int(payload.get("count") or 0),
        )
        return {"ids": ids}

    def create_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        descriptions = [_finalize_sentence(item) for item in payload.get("descriptions", [])]
        descriptions = [item for item in descriptions if item]
        year, week = _week_parts(str(payload.get("week_code") or ""))
        quarter = min(((week - 1) // 13) + 1, 4)
        pages = self.notion.create_tasks_batch(
            project_id=str(payload["project_id"]),
            project_name=str(payload["project_name"]),
            role=founder["role"],
            founder_name=founder["name"],
            descriptions=descriptions,
            year=year,
            quarter_name=f"Q{quarter} {year}",
            month_name=_month_name(),
            week_code=str(payload["week_code"]).upper(),
            today_iso=datetime.now(MADRID_TZ).date().isoformat(),
        )
        return {"created": len(pages), "page_ids": [page.get("id") for page in pages]}

    def parse_key_results(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        key_results: list[dict[str, str]] = []
        if self.reflection.api_keys:
            try:
                result = self.reflection.generate_json_response(
                    system_prompt=KR_PARSE_PROMPT,
                    user_prompt=(
                        f"Objective: {payload.get('objective') or ''}\n"
                        f"Raw key result notes:\n{text.strip()}"
                    ),
                    max_output_tokens=500,
                )
                raw_krs = result.get("key_results")
                if isinstance(raw_krs, list):
                    for item in raw_krs:
                        if not isinstance(item, dict):
                            continue
                        description = _clean_line(str(item.get("description") or ""))
                        if description:
                            key_results.append(
                                {
                                    "description": description,
                                    "metric": str(item.get("metric") or "").strip(),
                                    "target": str(item.get("target") or "").strip(),
                                }
                            )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("KR parse LLM failed; using fallback parser: %s", exc)
        return {"key_results": key_results or _fallback_key_results(text)}

    def create_okr(self, payload: dict[str, Any]) -> dict[str, Any]:
        founder = _resolve_founder(payload)
        period = _period_code(payload.get("period_type", ""), payload.get("quarter"), payload.get("year"))
        project_id = str(payload.get("project_id") or "").strip()
        owner_id = self.notion.lookup_team_member_id(founder["name"])
        objectives = payload.get("objectives") if isinstance(payload.get("objectives"), list) else []

        objective_count = 0
        kr_count = 0
        for objective in objectives:
            if not isinstance(objective, dict):
                continue
            title = str(objective.get("title") or "").strip()
            if not title:
                continue
            objective_page = self._create_objective(title=title, period=period, owner_id=owner_id, founder=founder)
            objective_count += 1
            objective_id = str(objective_page["id"])
            key_results = objective.get("key_results") if isinstance(objective.get("key_results"), list) else []
            for index, key_result in enumerate(key_results, start=1):
                if not isinstance(key_result, dict):
                    continue
                description = str(key_result.get("description") or "").strip()
                if not description:
                    continue
                self._create_key_result(
                    description=description,
                    index=index,
                    period=period,
                    owner_id=owner_id,
                    objective_id=objective_id,
                    project_id=project_id,
                    metric=str(key_result.get("metric") or "").strip(),
                    target=str(key_result.get("target") or "").strip(),
                )
                kr_count += 1
        return {"objectives_created": objective_count, "key_results_created": kr_count}

    def _create_objective(self, *, title: str, period: str, owner_id: str | None, founder: dict[str, str]) -> dict[str, Any]:
        schema = self.notion._retrieve_schema(self.objectives_db_id)
        properties: dict[str, Any] = {}
        title_name = self.notion._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": title}}]}
        self._set_period(properties, schema, period)
        self._set_owner(properties, schema, owner_id)
        notes_name = self.notion._existing_property_name(schema, "Notes")
        if notes_name:
            properties[notes_name] = {"rich_text": self.notion._rich_text(f"Created from internal OKR Creator for {founder['name']} ({founder['role']}).")}
        return self.notion.client.pages.create(parent=self.notion._build_parent(self.objectives_db_id), properties=properties)

    def _create_key_result(
        self,
        *,
        description: str,
        index: int,
        period: str,
        owner_id: str | None,
        objective_id: str,
        project_id: str,
        metric: str,
        target: str,
    ) -> dict[str, Any]:
        schema = self.notion._retrieve_schema(self.krs_db_id)
        properties: dict[str, Any] = {}
        title_name = self.notion._title_property_name(schema)
        kr_title = description if re.match(r"^kr\s*\d+[:.)-]", description, flags=re.IGNORECASE) else f"KR{index}: {description}"
        properties[title_name] = {"title": [{"type": "text", "text": {"content": kr_title}}]}
        self._set_period(properties, schema, period)
        self._set_owner(properties, schema, owner_id)
        if prop := self.notion._get_schema_property(schema, "Status"):
            prop_name = self.notion._property_name(prop, "Status")
            status_name = self.notion._resolve_option_name(prop, preferred_values=["To Do", "Todo", "Not Started"])
            properties[prop_name] = self.notion._build_named_option_value(prop, status_name)
        if prop := self.notion._get_schema_property(schema, "Objective", "Objectives"):
            prop_name = self.notion._property_name(prop, "Objective")
            properties[prop_name] = {"relation": [{"id": objective_id}]}
        if project_id and (prop := self.notion._get_schema_property(schema, "Projects", "Project")):
            prop_name = self.notion._property_name(prop, "Projects")
            properties[prop_name] = {"relation": [{"id": project_id}]}
        if prop := self.notion._get_schema_property(schema, "Notes"):
            notes = []
            if metric:
                notes.append(f"Metric: {metric}")
            if target:
                notes.append(f"Target: {target}")
            if notes:
                properties[self.notion._property_name(prop, "Notes")] = {"rich_text": self.notion._rich_text(" | ".join(notes))}
        return self.notion.client.pages.create(parent=self.notion._build_parent(self.krs_db_id), properties=properties)

    def _set_period(self, properties: dict[str, Any], schema: dict[str, Any], period: str) -> None:
        if prop := self.notion._get_schema_property(schema, "Period"):
            prop_name = self.notion._property_name(prop, "Period")
            properties[prop_name] = self.notion._build_scalar_property_value(prop, period)

    def _set_owner(self, properties: dict[str, Any], schema: dict[str, Any], owner_id: str | None) -> None:
        owner_name = self.notion._existing_property_name(schema, "Owner", "Founder")
        if owner_name and schema[owner_name].get("type") == "relation" and owner_id:
            properties[owner_name] = {"relation": [{"id": owner_id}]}


class InternalHtmlHandler(BaseHTTPRequestHandler):
    app = InternalNotionApp()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            self._handle_json(lambda: self.app.list_projects())
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        routes = {
            "/api/parse": self.app.parse_tasks,
            "/api/preview-ids": self.app.preview_task_ids,
            "/api/tasks": self.app.create_tasks,
            "/api/okr/parse-krs": self.app.parse_key_results,
            "/api/okr/push": self.app.create_okr,
        }
        parsed = urlparse(self.path)
        route_path = parsed.path.rstrip("/") or parsed.path
        handler = routes.get(route_path)
        if handler is None:
            self._json({"error": "Not found"}, status=404)
            return
        payload = self._read_json()
        self._handle_json(lambda: handler(payload))

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def _handle_json(self, callback) -> None:
        try:
            self._json(callback())
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Request failed: %s", exc)
            self._json({"error": str(exc)}, status=500)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object.")
        return payload

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._headers("application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _headers(self, content_type: str | None = None) -> None:
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _serve_static(self, request_path: str) -> None:
        rel = unquote(request_path).lstrip("/")
        if not rel:
            self.send_response(302)
            self.send_header("Location", "/task%20creator/")
            self.end_headers()
            return
        path = (STATIC_ROOT / rel).resolve()
        if path.is_dir():
            path = path / "index.html"
        if not str(path).startswith(str(STATIC_ROOT.resolve())) or not path.exists() or not path.is_file():
            self._json({"error": "Not found"}, status=404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._headers(content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    host = os.getenv("INTERNAL_HTMLS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("INTERNAL_HTMLS_PORT", "8012"))
    server = ThreadingHTTPServer((host, port), InternalHtmlHandler)
    print(f"Internal HTMLs server running at http://{host}:{port}/task%20creator/")
    print(f"OKR Creator: http://{host}:{port}/okr%20creator/")
    server.serve_forever()


if __name__ == "__main__":
    main()
