

"""LaunchKart AI 2.0 — Vision Agent

Uses a ROCm-optimized vision model (LLaVA) to analyze product images
and extract detailed product attributes.
"""

from __future__ import annotations

import json

from app.agents.base_agent import BaseAgent
from app.agents.state import LaunchState
from app.agents.vision.prompts import VISION_SYSTEM_PROMPT, VISION_TASK_PROMPT


class VisionAgent(BaseAgent):
    name = "vision"
    description = "Analyzes product image using vision model"
    phase = 1

    def get_system_prompt(self) -> str:
        return VISION_SYSTEM_PROMPT

    async def plan(self, state: LaunchState) -> list[str]:
        return [
            "Load product image",
            "Run vision model analysis",
            "Extract product attributes",
            "Assess image quality",
            "Generate structured output",
        ]

    async def execute(self, state: LaunchState) -> LaunchState:
        image_path = state.get("image_path", "")

        response = await self.call_llm(
            prompt=VISION_TASK_PROMPT,
            state=state,
            images=[image_path] if image_path else None,
        )

        try:
            result_text = response.strip()
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            vision_result = json.loads(result_text)
        except (json.JSONDecodeError, IndexError):
            vision_result = {
                "category": "Unknown",
                "subcategory": "Unknown",
                "brand": None,
                "colors": [],
                "material": None,
                "texture": None,
                "usage": [],
                "features": [response[:500]],
                "packaging": None,
                "damage_detected": False,
                "quality_score": 0.5,
                "estimated_dimensions": None,
                "confidence": 0.4,
                "raw_analysis": response[:1000],
            }

        state["vision_result"] = vision_result
        return state

    def _get_output_confidence(self, state: LaunchState) -> float:
        result = state.get("vision_result", {})
        return result.get("confidence", 0.5) if result else 0.0
