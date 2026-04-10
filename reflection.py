from __future__ import annotations

import json
import logging
from urllib import error, request


LOGGER = logging.getLogger("xcg_bot.reflection")
DEFAULT_MODEL = "qwen2.5:32b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
SYSTEM_PROMPT = (
    "You are an EOD reflection assistant for a B2B SaaS startup. "
    "Write a concise, honest 3-5 sentence reflection in first person based on the completed tasks and notes provided. "
    "Be direct, no fluff."
)


class ReflectionService:
    def __init__(self, *, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def _get_json(self, path: str) -> dict:
        req = request.Request(
            f"{self.base_url}{path}",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed: {exc.code} {body}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

    def _post_json(self, path: str, payload: dict) -> dict:
        req = request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed: {exc.code} {body}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

    def verify_startup(self) -> None:
        payload = self._get_json("/api/tags")
        models = {item.get("name", "").strip() for item in payload.get("models", [])}
        if self.model not in models:
            raise RuntimeError(
                f"Configured Ollama model {self.model!r} is not installed. "
                f"Available models: {', '.join(sorted(model for model in models if model)) or 'none'}"
            )

    def _request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_mime_type: str | None = None,
        max_output_tokens: int = 400,
    ) -> dict:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": max_output_tokens,
            },
        }
        if response_mime_type == "application/json":
            payload["format"] = "json"
        return self._post_json("/api/generate", payload)

    def _extract_text(self, payload: dict) -> str:
        return str(payload.get("response", "")).strip()

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

        payload = self._request(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=250,
        )
        reflection = self._extract_text(payload)
        if not reflection:
            raise RuntimeError("Ollama returned an empty reflection.")
        return reflection

    def generate_json_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 500,
    ) -> dict:
        payload = self._request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_mime_type="application/json",
            max_output_tokens=max_output_tokens,
        )
        text = self._extract_text(payload)
        if not text:
            raise RuntimeError("Ollama returned an empty JSON response.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc
