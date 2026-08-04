"""LaunchKart AI 2.0 — Marketing Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.marketing.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class MarketingAgent(BaseAgent):
    name = "marketing"
    description = "Creates marketing campaigns and content"
    phase = 4
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        analysis = state.get("product_analysis", {})
        branding = state.get("branding_data", {})
        pricing = state.get("pricing_recommendation", {})
        research = state.get("research_data", {})
        prompt = TASK_PROMPT.format(
            product_name=analysis.get("product_name", "Unknown"),
            brand_voice=branding.get("brand_voice", "Professional"),
            features=json.dumps(analysis.get("key_features", []))[:300],
            audience=json.dumps(research.get("target_demographics", []))[:200],
            price=pricing.get("recommended_price", "TBD"),
        )
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["marketing_content"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["marketing_content"] = {"instagram_caption": response[:300], "facebook_ad": response[:300], "google_ad_copy": response[:150], "product_story": response[:500]}
        return state
