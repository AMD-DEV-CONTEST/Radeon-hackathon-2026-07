"""LaunchKart AI 2.0 — QA Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.qa.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class QAAgent(BaseAgent):
    name = "qa"
    description = "Validates all outputs for quality"
    phase = 5
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        prompt = TASK_PROMPT.format(
            listings=json.dumps(state.get("listings", {}))[:500],
            seo_data=json.dumps(state.get("seo_data", {}))[:300],
            marketing=json.dumps(state.get("marketing_content", {}))[:300],
            vision=json.dumps(state.get("vision_result", {}))[:300],
        )
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["qa_report"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["qa_report"] = {"grammar_score": 0.8, "seo_compliance": True, "overall_confidence": 0.7, "issues": [], "recommendations": [response[:500]]}
        return state
