"""LaunchKart AI 2.0 — Listing Generation Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.listing.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class ListingAgent(BaseAgent):
    name = "listing"
    description = "Generates marketplace product listings"
    phase = 4
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        analysis = state.get("product_analysis", {})
        seo = state.get("seo_data", {})
        pricing = state.get("pricing_recommendation", {})
        branding = state.get("branding_data", {})
        marketplaces = state.get("target_marketplaces", ["amazon"])
        prompt = TASK_PROMPT.format(
            product_name=analysis.get("product_name", "Unknown"),
            seo_data=json.dumps(seo)[:500],
            pricing=json.dumps(pricing)[:300],
            branding=json.dumps(branding)[:300],
            marketplaces=", ".join(marketplaces),
            features=json.dumps(analysis.get("key_features", []))[:300],
        )
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["listings"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            default_listing = {"title": seo.get("title", "Product"), "description": response[:1000], "bullet_points": seo.get("bullet_points", []), "keywords": seo.get("primary_keywords", [])}
            state["listings"] = {m: default_listing for m in marketplaces}
        return state
