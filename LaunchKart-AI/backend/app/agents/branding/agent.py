"""LaunchKart AI 2.0 — Branding Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.branding.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class BrandingAgent(BaseAgent):
    name = "branding"
    description = "Creates brand voice and identity"
    phase = 3
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        analysis = state.get("product_analysis", {})
        vision = state.get("vision_result", {})
        research = state.get("research_data", {})
        prompt = TASK_PROMPT.format(product_name=analysis.get("product_name", "Unknown"), category=vision.get("category", "General"), usps=json.dumps(analysis.get("unique_selling_points", []))[:300], audience=json.dumps(research.get("target_demographics", []))[:200])
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["branding_data"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["branding_data"] = {"brand_voice": "Professional and trustworthy", "brand_personality": ["innovative"], "tagline_options": []}
        return state
