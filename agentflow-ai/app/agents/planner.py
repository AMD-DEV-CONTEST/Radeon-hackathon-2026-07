from __future__ import annotations

from typing import Any

from app.schemas import PlanResult
from app.services.ollama_client import OllamaClient


PLANNER_SYSTEM = """You are the Planner Agent inside AgentFlow AI.
Return valid JSON only.
You decompose requests into execution steps for an autonomous multi-agent system.
Schema:
{
  "goal": string,
  "tasks": [string],
  "tools": [string],
  "risks": [string],
  "success_criteria": [string]
}
"""


class PlannerAgent:
    def __init__(self, ollama: OllamaClient) -> None:
        self.ollama = ollama

    def run(self, user_request: str, requested_model: str | None = None) -> tuple[PlanResult, str | None, str | None]:
        prompt = (
            "Break this user request into a concise autonomous workflow plan for Planner -> Research -> Memory -> Tool -> Reviewer.\n"
            f"User request:\n{user_request}"
        )
        try:
            response = self.ollama.generate_json(prompt=prompt, system=PLANNER_SYSTEM, requested_model=requested_model)
            payload = response["content"]
            plan = PlanResult(
                goal=payload.get("goal") or user_request,
                tasks=[str(item) for item in payload.get("tasks", [])][:6],
                tools=[str(item) for item in payload.get("tools", [])][:6],
                risks=[str(item) for item in payload.get("risks", [])][:6],
                success_criteria=[str(item) for item in payload.get("success_criteria", [])][:6],
            )
            return plan, response.get("model"), None
        except Exception as exc:
            return self._fallback_plan(user_request), None, str(exc)

    @staticmethod
    def _fallback_plan(user_request: str) -> PlanResult:
        normalized = " ".join(user_request.split())
        return PlanResult(
            goal=normalized,
            tasks=[
                "Clarify the user objective and expected deliverable.",
                "Search uploaded knowledge sources for supporting evidence.",
                "Recall prior conversation memory and persistent notes.",
                "Execute safe local tools only when they improve the answer.",
                "Review the draft for completeness, risks, and next steps.",
            ],
            tools=["rag_search", "conversation_memory", "safe_calculator", "document_inventory"],
            risks=[
                "Ollama may be offline or no preferred model may be installed.",
                "Uploaded documents may not contain enough context.",
            ],
            success_criteria=[
                "The response is actionable, grounded in local context, and clearly structured.",
                "Any tool output and citations are surfaced transparently.",
            ],
        )
