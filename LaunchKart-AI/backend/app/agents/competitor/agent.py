"""LaunchKart AI 2.0 — Competitor Analysis Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.competitor.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class CompetitorAgent(BaseAgent):
    name = "competitor"
    description = "Analyzes competitor products and pricing"
    phase = 2
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        vision = state.get("vision_result", {})
        analysis = state.get("product_analysis", {})
        prompt = TASK_PROMPT.format(product_name=analysis.get("product_name", "Unknown"), category=vision.get("category", "General"), research_data=json.dumps(state.get("research_data", {}))[:500])
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["competitor_data"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["competitor_data"] = {"competitors": [], "competitive_landscape": response[:500], "confidence": 0.4}
        return state
