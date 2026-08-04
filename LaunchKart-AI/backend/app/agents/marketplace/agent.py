"""LaunchKart AI 2.0 — Marketplace Export Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.marketplace.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class MarketplaceExportAgent(BaseAgent):
    name = "marketplace"
    description = "Formats and exports for each marketplace"
    phase = 5
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        marketplaces = state.get("target_marketplaces", ["amazon"])
        prompt = TASK_PROMPT.format(marketplaces=", ".join(marketplaces), listings=json.dumps(state.get("listings", {}))[:800], qa_report=json.dumps(state.get("qa_report", {}))[:300])
        response = await self.call_llm(prompt=prompt, state=state)
        try:
            text = response.strip()
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            state["marketplace_exports"] = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            state["marketplace_exports"] = {m: json.dumps(state.get("listings", {}).get(m, {})) for m in marketplaces}
        return state
