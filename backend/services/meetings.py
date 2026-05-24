from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.domain.dates import (
    MADRID_TZ,
    month_name_for_date,
    normalize_meeting_payload,
    week_context_for_date,
)
from backend.domain.founders import FOUNDER_BY_ID, ROLE_TO_ENV, founder_for_attendee, resolve_founder
from backend.domain.prompts import MEETING_PARSE_PROMPT
from backend.domain.text import finalize_sentence


class MeetingsService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def list_meeting_types(self) -> dict[str, list[str]]:
        schema = self.runtime.notion._retrieve_schema(self.runtime.meetings_db_id)
        prop = self.runtime.notion._get_schema_property(schema, "Type")
        if not prop:
            raise RuntimeError("Meetings database is missing a Type property.")
        if prop.get("type") != "select":
            raise RuntimeError("Meetings Type property must be a select field.")

        options = [
            str(option.get("name") or "").strip()
            for option in (prop.get("select") or {}).get("options", [])
        ]
        types = [option for option in options if option]
        if not types:
            raise RuntimeError("Meetings Type property does not expose any options.")
        return {"types": types}

    def parse_meeting(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw_input = {
            "title": payload.get("title"),
            "date_input": payload.get("date_input"),
            "type": payload.get("type"),
            "attendees": payload.get("attendees"),
            "location": payload.get("location"),
            "notes": payload.get("notes"),
            "meeting_link": payload.get("meeting_link"),
            "address": payload.get("address"),
        }
        ai_payload = None
        if self.runtime.reflection.api_keys:
            now = datetime.now(MADRID_TZ)
            try:
                from backend.domain.dates import WEEKDAYS
                ai_payload = self.runtime.reflection.generate_json_response(
                    system_prompt=MEETING_PARSE_PROMPT,
                    user_prompt=(
                        f"Today is: {WEEKDAYS[now.weekday()]} {now.date().isoformat()}\n"
                        f"Title: {raw_input['title'] or ''}\n"
                        f"Date: {raw_input['date_input'] or ''}\n"
                        f"Type: {raw_input['type'] or ''}\n"
                        f"Attendees: {raw_input['attendees'] or ''}\n"
                        f"Location: {raw_input['location'] or ''}\n"
                        f"Notes: {str(raw_input['notes'] or '').strip() or 'none'}"
                    ),
                    max_output_tokens=400,
                )
            except Exception as exc:  # noqa: BLE001
                from backend.services.runtime import LOGGER
                LOGGER.warning("Meeting parse LLM failed; using fallback parser: %s", exc)
        return {"meeting": normalize_meeting_payload(raw_input, ai_payload)}

    def create_meeting(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolve_founder(payload)
        meeting = payload.get("meeting")
        if not isinstance(meeting, dict):
            raise ValueError("Meeting payload is required.")
        meeting = normalize_meeting_payload(
            {
                "title": meeting.get("title"),
                "date_input": meeting.get("date_iso"),
                "type": meeting.get("type"),
                "attendees": meeting.get("attendees"),
                "location": meeting.get("location"),
                "notes": meeting.get("notes_enhanced"),
                "meeting_link": meeting.get("meeting_link"),
                "address": meeting.get("address"),
            },
            {
                "title": meeting.get("title"),
                "date_iso": meeting.get("date_iso"),
                "type": meeting.get("type"),
                "attendees": meeting.get("attendees"),
                "location": meeting.get("location"),
                "notes_enhanced": meeting.get("notes_enhanced"),
            },
        )
        page = self.create_meeting_page(meeting, announced=False)
        attendance_pages: list[dict[str, Any]] = []
        attendance_task_error = ""
        try:
            attendance_pages = self.create_meeting_attendance_tasks(meeting)
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.exception("Meeting attendance task creation failed: %s", exc)
            attendance_task_error = str(exc)
        announced = False
        announcement_error = ""
        try:
            self.announce_meeting(meeting)
            self.mark_meeting_announced(page)
            announced = True
        except Exception as exc:  # noqa: BLE001
            from backend.services.runtime import LOGGER
            LOGGER.exception("Meeting announcement failed: %s", exc)
            announcement_error = str(exc)
        return {
            "created": True,
            "page_id": page.get("id"),
            "announced": announced,
            "announcement_error": announcement_error,
            "attendance_tasks_created": len(attendance_pages),
            "attendance_task_page_ids": [task.get("id") for task in attendance_pages],
            "attendance_task_error": attendance_task_error,
        }

    def create_meeting_attendance_tasks(self, meeting: dict[str, Any]) -> list[dict[str, Any]]:
        project = self.meeting_task_project()
        year, _week, week_code, quarter_name = week_context_for_date(meeting["date_iso"])
        month_name = month_name_for_date(meeting["date_iso"])
        today_iso = datetime.now(MADRID_TZ).date().isoformat()
        description = finalize_sentence(f"Attend {meeting['title']} on {meeting['date_label']}")
        _, _, today_week_code, _ = week_context_for_date(datetime.now(MADRID_TZ).isoformat())
        is_current_week = self.runtime.notion._week_matches(week_code, today_week_code)

        created_pages: list[dict[str, Any]] = []
        seen_roles: set[str] = set()
        for attendee in meeting.get("attendees", []):
            founder = founder_for_attendee(str(attendee))
            if not founder:
                from backend.services.runtime import LOGGER
                LOGGER.warning("Skipping attendance task for unknown attendee %r.", attendee)
                continue
            if founder["role"] in seen_roles:
                continue
            seen_roles.add(founder["role"])
            created_pages.extend(
                self.runtime.notion.create_tasks_batch(
                    project_id=project["id"],
                    project_name=project["name"],
                    role=founder["role"],
                    founder_name=founder["name"],
                    descriptions=[description],
                    year=year,
                    quarter_name=quarter_name,
                    month_name=month_name,
                    week_code=week_code,
                    today_iso=today_iso,
                    is_current_week=is_current_week,
                )
            )
        return created_pages

    def meeting_task_project(self) -> dict[str, str]:
        configured_id = str(self.runtime.meeting_task_project_id or "").strip()
        configured_name = str(self.runtime.meeting_task_project_name or "").strip() or "ALPHA"
        if configured_id:
            return {"id": configured_id, "name": configured_name}
        projects = self.runtime.notion.list_projects()
        for project in projects:
            name = str(project.get("name") or "").strip()
            if name.lower() == configured_name.lower():
                return {"id": str(project["id"]), "name": name}
        raise RuntimeError(
            f"Could not find project {configured_name!r} for meeting attendance tasks. "
            "Set NOTION_MEETING_TASK_PROJECT_ID or NOTION_MEETING_TASK_PROJECT_NAME."
        )

    def create_meeting_page(self, meeting: dict[str, Any], *, announced: bool) -> dict[str, Any]:
        schema = self.runtime.notion._retrieve_schema(self.runtime.meetings_db_id)
        properties: dict[str, Any] = {}
        title_name = self.runtime.notion._title_property_name(schema)
        properties[title_name] = {"title": [{"type": "text", "text": {"content": meeting["title"]}}]}
        if prop_name := self.runtime.notion._existing_property_name(schema, "Date"):
            properties[prop_name] = {"date": {"start": meeting["date_iso"]}}
        if prop := self.runtime.notion._get_schema_property(schema, "Type"):
            prop_name = self.runtime.notion._property_name(prop, "Type")
            properties[prop_name] = self.text_or_option(prop, meeting["type"])
        if prop := self.runtime.notion._get_schema_property(schema, "Attendees"):
            prop_name = self.runtime.notion._property_name(prop, "Attendees")
            properties[prop_name] = self.attendees_property(prop, meeting["attendees"])
        if prop := self.runtime.notion._get_schema_property(schema, "Mode"):
            prop_name = self.runtime.notion._property_name(prop, "Mode")
            properties[prop_name] = self.text_or_option(prop, meeting["mode"])
        if prop := self.runtime.notion._get_schema_property(schema, "Meeting link"):
            prop_name = self.runtime.notion._property_name(prop, "Meeting link")
            if meeting.get("meeting_link"):
                properties[prop_name] = {"url": meeting["meeting_link"]} if prop.get("type") == "url" else self.runtime.notion._build_text_like_property_value(prop, meeting["meeting_link"])
        if prop := self.runtime.notion._get_schema_property(schema, "Address", "Location"):
            prop_name = self.runtime.notion._property_name(prop, "Address")
            address = meeting.get("address") or meeting.get("location") or ""
            if address:
                properties[prop_name] = self.runtime.notion._build_text_like_property_value(prop, address)
        if prop := self.runtime.notion._get_schema_property(schema, "Overview", "Notes"):
            prop_name = self.runtime.notion._property_name(prop, "Overview")
            if meeting.get("notes_enhanced"):
                properties[prop_name] = self.runtime.notion._build_text_like_property_value(prop, meeting["notes_enhanced"])
        if prop_name := self.runtime.notion._existing_property_name(schema, "Announced"):
            if schema[prop_name].get("type") == "checkbox":
                properties[prop_name] = {"checkbox": announced}
        if prop_name := self.runtime.notion._existing_property_name(schema, "Reminded"):
            if schema[prop_name].get("type") == "checkbox":
                properties[prop_name] = {"checkbox": False}
        if prop := self.runtime.notion._get_schema_property(schema, "Status"):
            prop_name = self.runtime.notion._property_name(prop, "Status")
            if prop.get("type") in {"select", "status"}:
                properties[prop_name] = self.runtime.notion._build_named_option_value(
                    prop,
                    self.runtime.notion._resolve_option_name(prop, preferred_values=["Pending", "To Do", "Todo"]),
                )
        return self.runtime.notion.client.pages.create(parent=self.runtime.notion._build_parent(self.runtime.meetings_db_id), properties=properties)

    def text_or_option(self, prop: dict[str, Any], value: str) -> dict[str, Any]:
        if prop.get("type") in {"select", "status"}:
            return self.runtime.notion._build_named_option_value(prop, self.runtime.notion._resolve_option_name(prop, preferred_values=[value]))
        return self.runtime.notion._build_text_like_property_value(prop, value)

    def attendees_property(self, prop: dict[str, Any], attendees: list[str]) -> dict[str, Any]:
        prop_type = prop.get("type")
        if prop_type == "relation":
            relations = []
            for attendee in attendees:
                if team_id := self.lookup_attendee_team_id(attendee):
                    relations.append({"id": team_id})
            return {"relation": relations}
        if prop_type == "multi_select":
            return {"multi_select": [{"name": attendee} for attendee in attendees]}
        return self.runtime.notion._build_text_like_property_value(prop, ", ".join(attendees))

    def lookup_attendee_team_id(self, attendee: str) -> str | None:
        normalized = str(attendee or "").strip()
        if not normalized:
            return None
        role = normalized.upper()
        for founder in FOUNDER_BY_ID.values():
            if role == founder["role"]:
                return self.runtime.notion.lookup_team_member_id(founder["name"])
        return self.runtime.notion.lookup_team_member_id(normalized)

    def mark_meeting_announced(self, page: dict[str, Any]) -> None:
        prop_name = self.runtime.notion._existing_property_name(page.get("properties", {}), "Announced")
        if not prop_name:
            return
        self.runtime.notion.client.pages.update(page_id=page["id"], properties={prop_name: {"checkbox": True}})

    def announce_meeting(self, meeting: dict[str, Any]) -> None:
        if not self.runtime.discord_token or not self.runtime.discord_announcements_channel_id:
            raise RuntimeError("Discord token or announcements channel ID is missing.")
        mentions = self.meeting_mentions(meeting["attendees"])
        lines = [
            f"{mentions} New meeting scheduled!".strip(),
            "",
            f"{meeting['type']} - {meeting['date_label']}",
            f"Attendees: {', '.join(meeting['attendees'])}",
            f"Location: {meeting['location']}",
        ]
        if meeting.get("meeting_link"):
            lines.append(f"Link: {meeting['meeting_link']}")
        if meeting.get("address"):
            lines.append(f"Address: {meeting['address']}")
        if meeting.get("notes_enhanced"):
            lines.append(f"Overview: {meeting['notes_enhanced']}")
        self.runtime.post_discord_message(self.runtime.discord_announcements_channel_id, "\n".join(lines))

    def meeting_mentions(self, attendees: list[str]) -> str:
        parts = []
        seen = set()
        for attendee in attendees:
            attendee_text = str(attendee or "").strip()
            env_name = ROLE_TO_ENV.get(attendee_text.upper())
            if not env_name:
                for founder in FOUNDER_BY_ID.values():
                    if attendee_text.lower() == founder["name"].lower():
                        env_name = ROLE_TO_ENV.get(founder["role"])
                        break
            from backend.services.runtime import env
            user_id = env(env_name) if env_name else ""
            if user_id and user_id not in seen:
                seen.add(user_id)
                parts.append(f"<@{user_id}>")
        return " ".join(parts)
