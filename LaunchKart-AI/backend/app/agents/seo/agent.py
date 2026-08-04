"""LaunchKart AI 2.0 — SEO Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.seo.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class SEOAgent(BaseAgent):
    name = "seo"
    description = "Generates SEO keywords and metadata"
    phase = 3
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        analysis = state.get("product_analysis", {})
        vision = state.get("vision_result", {})
        competitor = state.get("competitor_data", {})
        prompt = TASK_PROMPT.format(
            product_name=analysis.get("product_name", "Unknown"),
            category=vision.get("category", "General"),
            features=json.dumps(analysis.get("key_features", []))[:300],
            marketplaces=", ".join(state.get("target_marketplaces", [])),
            competitor_keywords=json.dumps(competitor.get("opportunities", []))[:200],
        )
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["seo_data"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["seo_data"] = {"title": analysis.get("product_name", "Product"), "primary_keywords": [], "search_score": 50.0}
        return state
