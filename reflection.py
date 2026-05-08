from __future__ import annotations

import json
import logging
from urllib import error, request


LOGGER = logging.getLogger("xcg_bot.reflection")
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_API_STYLE = "openai"
SYSTEM_PROMPT = (
    "You are an EOD writing assistant for a B2B SaaS startup. "
    "Write a concise formal daily note in first person based on the completed tasks and notes provided. "
    "Use plain professional language, keep it specific, and avoid inflated or introspective wording. "
    "Return only the note body as a short paragraph or two. "
    "Do not add a title, heading, date line, greeting, sign-off, name, or role."
)


class ReflectionService:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        api_keys: tuple[str, ...] | list[str] | None = None,
        api_style: str = DEFAULT_API_STYLE,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_keys = tuple(key.strip() for key in (api_keys or (api_key,)) if key and key.strip())
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self.api_style = api_style.strip().lower() or DEFAULT_API_STYLE
        if self.api_style != "openai":
            raise RuntimeError("Only OpenAI-compatible LLM APIs are supported. Local LLM and Gemini fallbacks are disabled.")

    def _headers(self, api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = api_key if api_key is not None else self.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _request_json_with_key(self, path: str, *, method: str, payload: dict | None, api_key: str) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self._headers(api_key),
            method=method,
        )
        try:
            with request.urlopen(req, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed: {exc.code} {body}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"LLM request failed: {exc}") from exc

    def _request_json(self, path: str, *, method: str, payload: dict | None = None) -> dict:
        keys = self.api_keys or ("",)
        errors: list[str] = []
        for index, key in enumerate(keys, start=1):
            try:
                response = self._request_json_with_key(path, method=method, payload=payload, api_key=key)
                if index > 1:
                    LOGGER.info("LLM request succeeded with fallback API key #%s.", index)
                return response
            except Exception as exc:  # noqa: BLE001
                errors.append(f"key #{index}: {exc}")
                LOGGER.warning("LLM request failed with API key #%s; trying next key if configured: %s", index, exc)
        raise RuntimeError("All configured LLM API keys failed: " + " | ".join(errors))

    def _get_json(self, path: str) -> dict:
        return self._request_json(path, method="GET")

    def _post_json(self, path: str, payload: dict) -> dict:
        return self._request_json(path, method="POST", payload=payload)

    def verify_startup(self) -> None:
        payload = self._get_json("/models")
        models = {item.get("id", "").strip() for item in payload.get("data", [])}
        if self.model not in models:
            raise RuntimeError(
                f"Configured OpenAI-compatible model {self.model!r} is not available. "
                f"Available models: {', '.join(sorted(model for model in models if model)) or 'none'}"
            )

    def _openai_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_mime_type: str | None = None,
        max_output_tokens: int = 400,
    ) -> dict:
        if response_mime_type == "application/json":
            system_prompt = (
                system_prompt
                + "\n\nIMPORTANT: Your entire response must be valid JSON only. No markdown, no explanation."
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": max_output_tokens,
        }
        return self._post_json("/chat/completions", payload)

    def _model_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_mime_type: str | None = None,
        max_output_tokens: int = 400,
    ) -> dict:
        return self._openai_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_mime_type=response_mime_type,
            max_output_tokens=max_output_tokens,
        )

    def _extract_text(self, payload: dict) -> str:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                return str(message.get("content", "")).strip()
        if "response" in payload:
            return str(payload.get("response", "")).strip()
        return ""

    def _parse_json_text(self, text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(
                line for line in cleaned.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise

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
            f"Notes: {notes_text}"
        )

        try:
            payload = self._model_request(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_output_tokens=250,
            )
            reflection = self._extract_text(payload)
            if not reflection:
                raise RuntimeError("LLM backend returned an empty reflection.")
            return reflection
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Configured backend reflection failed: {exc}") from exc

    def build_fallback_reflection(
        self,
        *,
        founder_name: str,
        founder_role: str,
        today_iso: str,
        completed_tasks: list[str],
        raw_notes: str,
    ) -> str:
        del founder_name, founder_role
        task_text = "; ".join(task.strip() for task in completed_tasks if str(task).strip()) or "No completed tasks were recorded."
        notes_text = " ".join(str(raw_notes or "").strip().split())
        if notes_text:
            return f"On {today_iso}, I completed: {task_text}. Notes: {notes_text}"
        return f"On {today_iso}, I completed: {task_text}."

    def generate_json_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 500,
    ) -> dict:
        try:
            payload = self._model_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_mime_type="application/json",
                max_output_tokens=max_output_tokens,
            )
            text = self._extract_text(payload)
            if not text:
                raise RuntimeError("LLM backend returned an empty JSON response.")
            return self._parse_json_text(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM backend returned invalid JSON: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Configured backend JSON response failed: {exc}") from exc
