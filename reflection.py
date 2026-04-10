from __future__ import annotations

import logging

from anthropic import Anthropic


LOGGER = logging.getLogger("xcg_bot.reflection")
MODEL = "claude-sonnet-4-20250514"
SYSTEM_PROMPT = (
    "You are an EOD reflection assistant for a B2B SaaS startup. "
    "Write a concise, honest 3-5 sentence reflection in first person based on the completed tasks and notes provided. "
    "Be direct, no fluff."
)


class ReflectionService:
    def __init__(self, api_key: str) -> None:
        self.client = Anthropic(api_key=api_key)

    def generate_reflection(
        self,
        *,
        founder_name: str,
        founder_role: str,
        today_iso: str,
        completed_tasks: list[str],
        raw_notes: str,
    ) -> str:
        task_text = "; ".join(completed_tasks) if completed_tasks else "none"
        notes_text = raw_notes if raw_notes else "none"
        user_prompt = (
            f"Founder: {founder_name} | Role: {founder_role} | Date: {today_iso}\n"
            f"Completed tasks: {task_text}\n"
            f"Raw notes: {notes_text}"
        )

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=250,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Anthropic reflection request failed: {exc}") from exc

        text_parts = [block.text for block in response.content if getattr(block, "type", "") == "text" and getattr(block, "text", "").strip()]
        reflection = "\n".join(text_parts).strip()
        if not reflection:
            raise RuntimeError("Anthropic returned an empty reflection.")
        return reflection
