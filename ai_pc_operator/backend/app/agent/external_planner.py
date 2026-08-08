"""External reasoning model client (OpenAI-compatible chat completions).

The external model is advisory: it is consulted only for ambiguous/unknown
intent, complex planning, or chat replies when the local planner cannot
decide. Its returned plans are validated before execution.

Security:
  - The API key is read from the SCREEN_AI_EXTERNAL_API_KEY environment
    variable at request time. It is never stored in code, config, prompts,
    or logs, and is placed only in the Authorization header.
  - Exceptions are redacted before logging (the key must never leak).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional

from app.agent.prompts import CHAT_SYSTEM_PROMPT, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
DEFAULT_MODEL = "DeepSeek-V4-Flash"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 1

# Tool namespace the planner/router accept; plans proposing tools outside this
# set are rejected (advisory-only enforcement).
ALLOWED_TOOL_PREFIXES = (
    "system.", "file.", "browser.", "auth.", "screen.", "window.",
    "app.", "terminal.", "dev.", "ocr.", "vision.", "clipboard.",
    "email.", "network.", "media.", "doc.", "memory.", "task.",
    "research.", "approval.",
)


class ExternalPlanner:
    """Advisory external reasoning model via an OpenAI-compatible endpoint."""

    def is_configured(self) -> bool:
        return bool(os.environ.get("SCREEN_AI_EXTERNAL_API_KEY", "").strip())

    def _base_url(self) -> str:
        return (
            os.environ.get("SCREEN_AI_EXTERNAL_BASE_URL", "").strip()
            or DEFAULT_BASE_URL
        )

    def _model(self) -> str:
        return (
            os.environ.get("SCREEN_AI_EXTERNAL_MODEL", "").strip()
            or DEFAULT_MODEL
        )

    def _timeout(self) -> int:
        try:
            return max(1, int(os.environ.get("SCREEN_AI_EXTERNAL_TIMEOUT", str(DEFAULT_TIMEOUT))))
        except ValueError:
            return DEFAULT_TIMEOUT

    def _max_retries(self) -> int:
        try:
            return max(0, int(os.environ.get("SCREEN_AI_EXTERNAL_RETRIES", str(DEFAULT_MAX_RETRIES))))
        except ValueError:
            return DEFAULT_MAX_RETRIES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_plan(self, command: str) -> Optional[Dict[str, Any]]:
        """Ask the external model for a tool plan (advisory).

        Returns {"intent", "risk_level", "steps", "source"} or None when the
        model is not configured, the call fails, or the plan is invalid.
        """
        if not self.is_configured() or not command or not command.strip():
            return None

        prompt = USER_PROMPT_TEMPLATE.format(command=command)
        payload = {
            "model": self._model(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        try:
            response = await asyncio.to_thread(
                self._post_chat, payload, self._max_retries()
            )
        except Exception as e:  # pragma: no cover - network dependent
            logger.warning("external planner request failed: %s", self._redact(str(e)))
            return None

        text = self._extract_text(response)
        parsed = self._parse_json(text)
        if not parsed:
            return None

        steps = parsed.get("plan") or parsed.get("steps") or []
        if not isinstance(steps, list):
            return None

        validated = self._validate_steps(steps)
        if validated is None:
            logger.info("external planner returned invalid plan; rejected")
            return None

        return {
            "intent": str(parsed.get("intent") or "unknown"),
            "risk_level": self._clamp_risk(parsed.get("risk_level")),
            "steps": validated,
            "source": "external-llm",
        }

    async def chat_reply(self, user_text: str) -> Optional[str]:
        """Get a conversational reply for chat-mode requests (not a plan)."""
        if not self.is_configured() or not user_text or not user_text.strip():
            return None

        payload = {
            "model": self._model(),
            "messages": [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.4,
            "max_tokens": 256,
        }
        try:
            response = await asyncio.to_thread(
                self._post_chat, payload, self._max_retries()
            )
        except Exception as e:  # pragma: no cover - network dependent
            logger.warning("external chat request failed: %s", self._redact(str(e)))
            return None

        text = self._extract_text(response)
        return text.strip() or None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _post_chat(self, payload: Dict[str, Any], max_retries: int) -> Dict[str, Any]:
        """POST to {base}/chat/completions with retry. Returns the JSON body."""
        url = self._base_url().rstrip("/") + "/chat/completions"
        api_key = os.environ.get("SCREEN_AI_EXTERNAL_API_KEY", "").strip()
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self._timeout()) as resp:  # noqa: S310
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < max_retries:
                    continue
        raise last_error if last_error else RuntimeError("external request failed")

    # ------------------------------------------------------------------
    # Parsing / validation
    # ------------------------------------------------------------------

    def _extract_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                return message.get("content") or choices[0].get("text") or ""
        return ""

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = (text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def _validate_steps(self, steps: List[Any]) -> Optional[List[Dict[str, Any]]]:
        """Validate that every step has a tool + args and uses an allowed tool.

        Returns the cleaned step list, or None when any step is malformed.
        """
        cleaned: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                return None
            tool = step.get("tool")
            if not isinstance(tool, str) or not tool:
                return None
            if not tool.startswith(ALLOWED_TOOL_PREFIXES):
                return None
            args = step.get("args", {})
            if not isinstance(args, dict):
                return None
            cleaned.append({"tool": tool, "args": args})
        return cleaned

    @staticmethod
    def _clamp_risk(value: Any) -> int:
        try:
            return max(0, min(5, int(value)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _redact(message: str) -> str:
        """Strip anything that looks like an Authorization/bearer token."""
        return re.sub(
            r"(?i)(authorization|bearer|api[_-]?key)[:=]\s*\S+",
            r"\1=[REDACTED]",
            message,
        )
