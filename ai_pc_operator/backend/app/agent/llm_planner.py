"""LLM-assisted planning using the project prompt templates."""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


class LLMPlanner:
    """Optional local-LLM planner used only when the model tier allows it."""

    def build_prompt(self, command: str) -> str:
        return f"{SYSTEM_PROMPT}\n\n{USER_PROMPT_TEMPLATE.format(command=command)}"

    async def create_plan(self, command: str, loaded_model: dict[str, Any] | None) -> dict[str, Any] | None:
        """Return an LLM tool plan when a callable local model is loaded."""
        if not loaded_model or loaded_model.get("status") != "loaded":
            return None

        model = loaded_model.get("model")
        if model is None:
            return None

        prompt = self.build_prompt(command)
        try:
            response = model(
                prompt,
                max_tokens=512,
                temperature=0.0,
                stop=["\n\nUser command:"],
            )
        except Exception:
            return None

        text = self._extract_text(response)
        payload = self._parse_json(text)
        if not payload:
            return None

        steps = payload.get("plan") or payload.get("steps") or []
        if not isinstance(steps, list):
            return None

        return {
            "intent": str(payload.get("intent") or "llm_plan"),
            "risk_level": int(payload.get("risk_level", 1)),
            "steps": steps,
            "source": "local-llm",
        }

    def _extract_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                return choices[0].get("text") or choices[0].get("message", {}).get("content", "")
        return ""

    def _parse_json(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
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
