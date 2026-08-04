"""LaunchKart AI 2.0 — Coordinator Agent"""

from __future__ import annotations

import json

from app.agents.base_agent import BaseAgent
from app.agents.coordinator.prompts import COORDINATOR_SYSTEM_PROMPT, COORDINATOR_TASK_PROMPT
from app.agents.state import LaunchState


class CoordinatorAgent(BaseAgent):
    name = "coordinator"
    description = "Distributes tasks to worker agents"
    phase = 0

    def get_system_prompt(self) -> str:
        return COORDINATOR_SYSTEM_PROMPT

    async def execute(self, state: LaunchState) -> LaunchState:
        execution_plan = state.get("execution_plan", {})
        marketplaces = state.get("target_marketplaces", [])
        has_image = bool(state.get("image_path"))

        prompt = COORDINATOR_TASK_PROMPT.format(
            execution_plan=json.dumps(execution_plan),
            marketplaces=", ".join(marketplaces),
            has_image=has_image,
        )

        response = await self.call_llm(prompt=prompt, state=state)

        try:
            plan_text = response.strip()
            if "```json" in plan_text:
                plan_text = plan_text.split("```json")[1].split("```")[0].strip()
            coordination_plan = json.loads(plan_text)
        except (json.JSONDecodeError, IndexError):
            coordination_plan = {
                "plan_valid": True,
                "phases": [
                    {"phase": 1, "agents": ["vision", "product_analysis"], "parallel": True},
                    {"phase": 2, "agents": ["research", "competitor"], "parallel": True},
                    {"phase": 3, "agents": ["pricing", "seo", "branding"], "parallel": True},
                    {"phase": 4, "agents": ["listing", "marketing"], "parallel": True},
                    {"phase": 5, "agents": ["qa", "marketplace"], "parallel": False},
                    {"phase": 6, "agents": ["memory_agent", "analytics_agent"], "parallel": True},
                ],
                "total_agents": 14,
                "estimated_duration_minutes": 5,
            }

        state["execution_plan"] = {**execution_plan, "coordination": coordination_plan}
        return state
