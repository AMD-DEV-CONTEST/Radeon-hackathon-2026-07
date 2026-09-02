"""Synthetic food cold-holding SOP anomaly Skill.

The threshold and scenario are demo fixtures, not production food-safety advice.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..exceptions import InvalidAnalysisOutput
from ..models import AnalysisResult, SkillDefinition
from ..skill import SkillStatus


class FoodColdHoldingSkill:
    skill_id = "food-cold-holding-anomaly"
    rule_id = "rule:synthetic-cold-holding-v1"
    task_template = {
        "task_type": "food_sop_corrective_action",
        "assignee": "demo:shift-supervisor",
        "description": (
            "Inspect the synthetic cold-holding unit, correct the simulated "
            "condition, and submit a follow-up temperature record."
        ),
        "expected_result": (
            "Synthetic follow-up evidence at or below the demo threshold."
        ),
    }

    definition = SkillDefinition(
        skill_id=skill_id,
        version="1.0.0",
        status=SkillStatus.ACTIVE,
        supported_event_types=("food_safety_observation",),
        analysis_instructions=(
            "Apply only the synthetic cold-holding threshold rule. "
            "Require human review for an anomaly."
        ),
        escalation_rules=(
            "Escalate a synthetic threshold anomaly to the demo supervisor.",
        ),
        knowledge_query_hints=(
            "cold storage",
            "temperature observation",
        ),
    )

    def analyze(self, normalized_input: Mapping[str, Any]) -> AnalysisResult:
        self._validate_input(normalized_input)
        observed = float(normalized_input["observed_temperature_c"])
        maximum = float(normalized_input["demo_max_temperature_c"])
        delta = observed - maximum

        if delta > 0:
            severity = "CRITICAL" if delta >= 8.0 else "HIGH"
            payload = {
                "detected_issue": "synthetic_cold_holding_temperature_anomaly",
                "decision_type": "corrective_action_required",
                "reasoning_summary": (
                    f"Observed {observed:.1f}°C exceeds the synthetic demo "
                    f"threshold {maximum:.1f}°C by {delta:.1f}°C."
                ),
                "evidence": [
                    f"location={normalized_input['location']}",
                    f"observed_temperature_c={observed:.1f}",
                    f"demo_max_temperature_c={maximum:.1f}",
                    f"observation={normalized_input['observation']}",
                ],
                "model_or_rule": self.rule_id,
                "confidence": 1.0,
                "requires_human_review": True,
                "severity": severity,
            }
        else:
            payload = {
                "detected_issue": "",
                "decision_type": "no_issue",
                "reasoning_summary": (
                    f"Observed {observed:.1f}°C is within the synthetic demo "
                    f"threshold {maximum:.1f}°C."
                ),
                "evidence": [
                    f"location={normalized_input['location']}",
                    f"observed_temperature_c={observed:.1f}",
                    f"demo_max_temperature_c={maximum:.1f}",
                ],
                "model_or_rule": self.rule_id,
                "confidence": 1.0,
                "requires_human_review": False,
                "severity": "LOW",
            }
        return self.parse_analysis_output(payload)

    def parse_analysis_output(
        self, payload: Mapping[str, Any]
    ) -> AnalysisResult:
        """Validate a rule/model-shaped payload before it reaches DecisionHook."""

        required_types: dict[str, type | tuple[type, ...]] = {
            "detected_issue": str,
            "decision_type": str,
            "reasoning_summary": str,
            "evidence": list,
            "model_or_rule": str,
            "confidence": (int, float),
            "requires_human_review": bool,
            "severity": str,
        }
        errors = [
            key
            for key, expected in required_types.items()
            if key not in payload or not isinstance(payload[key], expected)
        ]
        if errors:
            raise InvalidAnalysisOutput(
                "Analysis output has missing/invalid fields: " + ", ".join(errors)
            )

        confidence = float(payload["confidence"])
        if not 0.0 <= confidence <= 1.0:
            raise InvalidAnalysisOutput("confidence must be between 0 and 1")
        if not all(isinstance(item, str) for item in payload["evidence"]):
            raise InvalidAnalysisOutput("evidence must be a list of strings")

        return AnalysisResult(
            detected_issue=payload["detected_issue"],
            decision_type=payload["decision_type"],
            reasoning_summary=payload["reasoning_summary"],
            evidence=list(payload["evidence"]),
            model_or_rule=payload["model_or_rule"],
            confidence=confidence,
            requires_human_review=payload["requires_human_review"],
            severity=payload["severity"].upper(),
        )

    @staticmethod
    def _validate_input(normalized_input: Mapping[str, Any]) -> None:
        required = {
            "data_classification",
            "location",
            "observed_temperature_c",
            "demo_max_temperature_c",
            "observation",
        }
        missing = sorted(required - normalized_input.keys())
        if missing:
            raise InvalidAnalysisOutput(
                "Normalized input is missing fields: " + ", ".join(missing)
            )
        if normalized_input["data_classification"] != "Synthetic demo data":
            raise InvalidAnalysisOutput(
                "The built-in demo Skill accepts only 'Synthetic demo data'."
            )
        try:
            float(normalized_input["observed_temperature_c"])
            float(normalized_input["demo_max_temperature_c"])
        except (TypeError, ValueError) as exc:
            raise InvalidAnalysisOutput(
                "Temperature fields must be numeric."
            ) from exc
