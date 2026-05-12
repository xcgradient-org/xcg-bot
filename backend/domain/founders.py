from __future__ import annotations

from typing import Any


FOUNDER_BY_ID = {
    "oriol": {"name": "Oriol", "role": "CEO"},
    "arnau": {"name": "Arnau", "role": "CTO"},
    "adam": {"name": "Adam", "role": "COO"},
}

ROLE_TO_ENV = {
    "CEO": "DISCORD_USER_ID_ORIOL",
    "CTO": "DISCORD_USER_ID_ARNAU",
    "COO": "DISCORD_USER_ID_ADAM",
}


def resolve_founder(payload: dict[str, Any]) -> dict[str, str]:
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


def founder_for_attendee(attendee: str) -> dict[str, str] | None:
    normalized = str(attendee or "").strip()
    if not normalized:
        return None
    role = normalized.upper()
    for founder in FOUNDER_BY_ID.values():
        if role == founder["role"] or normalized.lower() == founder["name"].lower():
            return dict(founder)
    return None
