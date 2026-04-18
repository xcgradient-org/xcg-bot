from __future__ import annotations

import json
import logging
import subprocess
from urllib import error, request


LOGGER = logging.getLogger("xcg_bot.reflection")
DEFAULT_MODEL = "qwen2.5:32b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_API_STYLE = "ollama"
GEMINI_MODEL = "gemini-2.5-flash-lite-preview"
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
        api_style: str = DEFAULT_API_STYLE,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_style = api_style.strip().lower() or DEFAULT_API_STYLE

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ------------------------------------------------------------------
    # Ollama transport
    # ------------------------------------------------------------------

    def _get_json(self, path: str) -> dict:
        req = request.Request(
            f"{self.base_url}{path}",
            headers=self._headers(),
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
            headers=self._headers(),
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
        if self.api_style == "openai":
            payload = self._get_json("/models")
            models = {item.get("id", "").strip() for item in payload.get("data", [])}
            if self.model not in models:
                raise RuntimeError(
                    f"Configured OpenAI-compatible model {self.model!r} is not available. "
                    f"Available models: {', '.join(sorted(model for model in models if model)) or 'none'}"
                )
            return

        payload = self._get_json("/api/tags")
        models = {item.get("name", "").strip() for item in payload.get("models", [])}
        if self.model not in models:
            raise RuntimeError(
                f"Configured Ollama model {self.model!r} is not installed. "
                f"Available models: {', '.join(sorted(model for model in models if model)) or 'none'}"
            )

    def _ollama_request(
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
        del response_mime_type
        return self._post_json("/chat/completions", payload)

    def _model_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_mime_type: str | None = None,
        max_output_tokens: int = 400,
    ) -> dict:
        if self.api_style == "openai":
            return self._openai_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_mime_type=response_mime_type,
                max_output_tokens=max_output_tokens,
            )
        return self._ollama_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_mime_type=response_mime_type,
            max_output_tokens=max_output_tokens,
        )

    def _extract_text(self, payload: dict) -> str:
        if "response" in payload:
            return str(payload.get("response", "")).strip()
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                return str(message.get("content", "")).strip()
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

    # ------------------------------------------------------------------
    # Gemini CLI fallback
    # ------------------------------------------------------------------

    def _gemini_text(self, *, system_prompt: str, user_prompt: str) -> str:
        """Call the local `gemini` CLI and return its text output."""
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        try:
            result = subprocess.run(  # noqa: S603
                ["gemini", "-p", full_prompt],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("gemini CLI not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("gemini CLI timed out") from exc

        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            stderr = result.stderr.strip()
            raise RuntimeError(f"gemini CLI failed (exit {result.returncode}): {stderr or 'no output'}")
        return output

    def _gemini_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        """Call the Gemini CLI asking for JSON output and parse the result."""
        json_system = (
            system_prompt
            + "\n\nIMPORTANT: Your entire response must be valid JSON only. No markdown, no explanation."
        )
        text = self._gemini_text(system_prompt=json_system, user_prompt=user_prompt)
        # Strip markdown code fences if the model wrapped the JSON
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(
                line for line in cleaned.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemini CLI returned invalid JSON: {exc}\nRaw: {text[:300]}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
                raise RuntimeError("Ollama returned an empty reflection.")
            return reflection
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Primary LLM reflection failed, trying Gemini CLI: %s", exc)

        reflection = self._gemini_text(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        if not reflection:
            raise RuntimeError("Gemini CLI returned an empty reflection.")
        return reflection

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
                raise RuntimeError("Ollama returned an empty JSON response.")
            return self._parse_json_text(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM backend returned invalid JSON: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Primary LLM JSON response failed, trying Gemini CLI: %s", exc)

        return self._gemini_json(system_prompt=system_prompt, user_prompt=user_prompt)
