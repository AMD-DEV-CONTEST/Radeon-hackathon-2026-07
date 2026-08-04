"""LaunchKart AI 2.0 — Product Analysis Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.product_analysis.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class ProductAnalysisAgent(BaseAgent):
    name = "product_analysis"
    description = "Extracts detailed product features"
    phase = 1

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    async def execute(self, state: LaunchState) -> LaunchState:
        vision_data = state.get("vision_result", {})
        prompt = TASK_PROMPT.format(vision_data=json.dumps(vision_data))
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["product_analysis"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["product_analysis"] = {"product_name": "Unknown", "key_features": [response[:500]], "confidence": 0.4}
        return state
