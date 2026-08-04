"""LaunchKart AI 2.0 — Pricing Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.pricing.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class PricingAgent(BaseAgent):
    name = "pricing"
    description = "Recommends optimal pricing strategy"
    phase = 3
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        analysis = state.get("product_analysis", {})
        vision = state.get("vision_result", {})
        competitor = state.get("competitor_data", {})
        research = state.get("research_data", {})
        prompt = TASK_PROMPT.format(
            product_name=analysis.get("product_name", "Unknown"),
            category=vision.get("category", "General"),
            competitor_prices=json.dumps(competitor.get("competitors", []))[:500],
            positioning=research.get("recommended_positioning", "mid-range"),
            marketplaces=", ".join(state.get("target_marketplaces", [])),
        )
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["pricing_recommendation"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["pricing_recommendation"] = {"recommended_price": 29.99, "pricing_strategy": "competitive", "confidence": 0.4}
        return state
