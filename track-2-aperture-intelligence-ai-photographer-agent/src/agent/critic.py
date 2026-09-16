"""Grounding, completeness and safety checks for a generated plan."""

from __future__ import annotations

from typing import Any

from src.agent.field_critic import CRITIC_PROMPT, FieldPlanCritic


class LegacyPlanCritic:
    REQUIRED_ANALYSIS_FIELDS = (
        "scene",
        "subject",
        "environment",
        "relationship",
        "composition",
        "recommendation",
    )

    def review(
        self, analysis: dict[str, Any], plan: dict[str, Any]
    ) -> dict[str, Any]:
        missing = [
            field for field in self.REQUIRED_ANALYSIS_FIELDS if not analysis.get(field)
        ]
        issues: list[str] = []
        if missing:
            issues.append("Missing visual evidence: " + ", ".join(missing))
        mode = plan.get("mode")
        if mode in {"shooting", "hybrid"}:
            if len(plan.get("on_location_sequence", [])) < 4:
                issues.append("The plan needs at least four on-location actions.")
            if len(plan.get("shot_list", [])) < 3:
                issues.append("The plan needs at least three distinct shots.")
            photographer = plan.get("photographer_direction", {})
            required_photographer = (
                "camera_position",
                "camera_height",
                "distance",
                "lens_plan",
                "settings",
                "lighting",
                "composition",
            )
            missing_photographer = [
                field for field in required_photographer if not photographer.get(field)
            ]
            if missing_photographer:
                issues.append(
                    "Photographer direction is missing: "
                    + ", ".join(missing_photographer)
                )
            lens_plan = photographer.get("lens_plan", {})
            if not lens_plan.get("environment_frame") or not lens_plan.get("hero_frame"):
                issues.append("The lens plan must separate environment and hero frames.")
            model = plan.get("model_direction", {})
            required_model = (
                "position",
                "body_angle",
                "feet_and_weight",
                "hands",
                "gaze",
                "expression",
                "action",
            )
            missing_model = [field for field in required_model if not model.get(field)]
            if missing_model:
                issues.append(
                    "Model direction is missing: " + ", ".join(missing_model)
                )
        if mode in {"photo_edit", "hybrid"}:
            if len(plan.get("editing_steps", [])) < 3:
                issues.append("The plan needs at least three editing actions.")
        constraints = " ".join(plan.get("preserve_constraints", [])).lower()
        if "identity" not in constraints or "location" not in constraints:
            issues.append("Identity and real-location preserve constraints are required.")
        if not plan.get("success_checks") and not plan.get("editing_success_checks"):
            issues.append("The plan needs explicit success checks.")
        return {
            "status": "pass" if not issues else "needs_review",
            "issues": issues,
            "checks_run": [
                "visual evidence completeness",
                "mode-specific actionability",
                "camera/shot specificity",
                "photographer/model direction completeness",
                "environment-versus-hero lens consistency",
                "identity and location preservation",
                "delivery success criteria",
            ],
        }


# Public critic now enforces the field-guidance schema; legacy class remains
# temporarily available for older internal fixtures during migration.
PlanCritic = FieldPlanCritic
