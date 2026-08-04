"""LaunchKart AI 2.0 — Memory Recorder Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.memory.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class MemoryRecorderAgent(BaseAgent):
    name = "memory_agent"
    description = "Stores results in persistent memory"
    phase = 6
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        analysis = state.get("product_analysis", {})
        vision = state.get("vision_result", {})
        qa = state.get("qa_report", {})
        prompt = TASK_PROMPT.format(
            product_name=analysis.get("product_name", "Unknown"),
            category=vision.get("category", "General"),
            insights=json.dumps({"qa_score": qa.get("overall_confidence", 0), "features": analysis.get("key_features", [])[:5]})[:500],
        )
        response = await self.call_llm(prompt=prompt, state=state)
        # Memory storage will be connected to ChromaDB in Phase 6
        return state
