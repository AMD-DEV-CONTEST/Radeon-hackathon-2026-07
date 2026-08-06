"""
Hierarchical task planner.
Breaks complex goals into ordered, concrete sub-tasks.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from .llm import LLMEngine

logger = logging.getLogger(__name__)


class HierarchicalPlanner:
    """
    Uses the LLM to decompose a high-level goal into a sequence of
    actionable steps that an agent can execute one by one.
    """

    def __init__(self, llm: LLMEngine):
        self.llm = llm

    def plan(self, goal: str, context: str = "", max_steps: int = 7) -> List[str]:
        system_prompt = (
            "You are an expert AI planner. Your job is to break a high-level goal "
            "into a clear, ordered list of concrete sub-tasks that an agent can execute.\n\n"
            "Rules:\n"
            "- Output ONLY a numbered list (1. 2. 3. ...)\n"
            "- Each step must be specific and actionable\n"
            "- Keep the list between 2 and 7 steps\n"
            "- Do not add explanations, just the numbered steps\n"
            "- If the goal is already simple, return a single step"
        )

        user_content = f"Goal: {goal}"
        if context:
            user_content += f"\n\nAdditional context:\n{context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = self.llm.generate(
            messages,
            max_new_tokens=512,
            temperature=0.2,
        )

        steps = self._parse_steps(response)
        if not steps:
            logger.warning("Planner returned no steps – using goal as single step")
            return [goal]
        return steps[:max_steps]

    def _parse_steps(self, text: str) -> List[str]:
        steps = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Match "1. xxx", "1) xxx", "- xxx", "* xxx"
            match = re.match(r"^(?:\d+[\.\)]\s*|[-*•]\s+)(.+)$", line)
            if match:
                step = match.group(1).strip()
                if step:
                    steps.append(step)
            elif line and not steps:
                # First non-empty line without numbering – treat as single step
                steps.append(line)
        return steps
