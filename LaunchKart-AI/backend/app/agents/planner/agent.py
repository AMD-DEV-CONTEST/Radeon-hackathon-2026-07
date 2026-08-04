"""
LaunchKart AI 2.0 — Planner Agent

Analyzes the product image and creates a comprehensive execution plan
that drives all downstream agents.
"""

from __future__ import annotations

import json

from app.agents.base_agent import BaseAgent
from app.agents.planner.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_TASK_PROMPT
from app.agents.state import LaunchState


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Creates execution plan from product image"
    phase = 0

    def get_system_prompt(self) -> str:
        return PLANNER_SYSTEM_PROMPT

    async def plan(self, state: LaunchState) -> list[str]:
        return [
            "Analyze product image",
            "Identify product category and type",
            "Create execution plan with dependencies",
            "Set quality thresholds",
            "Determine marketplace suitability",
        ]

    async def execute(self, state: LaunchState) -> LaunchState:
        image_path = state.get("image_path", "")
        marketplaces = state.get("target_marketplaces", ["amazon", "shopify"])
        preferences = state.get("user_preferences", {})

        prompt = PLANNER_TASK_PROMPT.format(
            marketplaces=", ".join(marketplaces),
            preferences=json.dumps(preferences) if preferences else "None specified",
        )

        # Call vision model with the product image
        response = await self.call_llm(
            prompt=prompt,
            state=state,
            images=[image_path] if image_path else None,
        )

        # Parse the execution plan
        try:
            # Extract JSON from response
            plan_text = response.strip()
            if "```json" in plan_text:
                plan_text = plan_text.split("```json")[1].split("```")[0].strip()
            elif "```" in plan_text:
                plan_text = plan_text.split("```")[1].split("```")[0].strip()

            execution_plan = json.loads(plan_text)
        except (json.JSONDecodeError, IndexError):
            # Fallback plan if parsing fails
            execution_plan = {
                "product_summary": response[:200],
                "category": "General",
                "analysis_priorities": [
                    "vision_analysis",
                    "feature_extraction",
                    "market_research",
                    "pricing_analysis",
                    "seo_optimization",
                    "listing_generation",
                    "marketing_content",
                    "quality_assurance",
                ],
                "marketplace_recommendations": {m: 0.8 for m in marketplaces},
                "quality_thresholds": {
                    "confidence": 0.7,
                    "grammar_score": 0.9,
                    "seo_score": 70.0,
                },
                "estimated_steps": 14,
                "risk_factors": [],
                "special_instructions": "",
            }

        state["execution_plan"] = execution_plan
        state["current_phase"] = 0

        return state

    def _get_output_confidence(self, state: LaunchState) -> float:
        plan = state.get("execution_plan", {})
        if plan and plan.get("product_summary"):
            return 0.9
        return 0.6
