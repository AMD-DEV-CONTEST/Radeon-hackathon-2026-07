"""Public planner facade for grounded, field-executable photography guidance."""

from __future__ import annotations

from typing import Any

from src.agent.field_plan import (
    PHOTO_PLAN_SCHEMA,
    PLANNER_PROMPT,
    build_field_plan,
    refine_field_plan,
)


class PhotographyPlanner:
    """Build and repair the fixed public guidance schema.

    Relative left/right/front/back camera position is intentionally absent.
    A single reference image cannot establish it reliably; the plan uses
    observable framing evidence for distance, angle, height, and background.
    """

    PROMPT = PLANNER_PROMPT
    OUTPUT_SCHEMA = PHOTO_PLAN_SCHEMA

    def plan(
        self,
        analysis: dict[str, Any],
        user_request: str,
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_field_plan(analysis, user_request, intent)

    def refine(
        self,
        plan: dict[str, Any],
        issues: list[str],
        *,
        analysis: dict[str, Any],
        user_request: str,
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply one bounded repair without inventing visual observations."""
        return refine_field_plan(
            plan,
            issues,
            analysis=analysis,
            user_request=user_request,
            intent=intent,
        )
