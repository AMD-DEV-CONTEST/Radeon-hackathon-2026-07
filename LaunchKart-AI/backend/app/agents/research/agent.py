"""LaunchKart AI 2.0 — Research Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.research.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class ResearchAgent(BaseAgent):
    name = "research"
    description = "Researches market and product category"
    phase = 2

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    async def execute(self, state: LaunchState) -> LaunchState:
        vision = state.get("vision_result", {})
        analysis = state.get("product_analysis", {})
        prompt = TASK_PROMPT.format(
            product_name=analysis.get("product_name", vision.get("category", "Unknown")),
            category=vision.get("category", "General"),
            features=json.dumps(analysis.get("key_features", vision.get("features", []))),
        )
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["research_data"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["research_data"] = {"market_overview": response[:500], "confidence": 0.4}
        return state
