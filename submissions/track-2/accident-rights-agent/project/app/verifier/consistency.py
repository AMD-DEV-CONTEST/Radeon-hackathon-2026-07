"""Cross-output consistency checks for responsibility, deadlines, and approval."""

from __future__ import annotations

from typing import Any

from app.schemas.business import (
    CompensationRegime,
    LiabilityResult,
    VehicleNatureClassification,
    VehicleNatureResult,
)
from app.schemas.rights import DeadlineResult, ReviewApplicationDraft
from app.schemas.verification import (
    ComponentVerifierResult,
    VerificationIssue,
    VerificationSeverity,
)


class ConsistencyVerifier:
    def verify(
        self,
        *,
        state: dict[str, Any],
        evidence_export: dict[str, Any],
    ) -> ComponentVerifierResult:
        issues: list[VerificationIssue] = []
        vehicle = None
        liability = None
        try:
            if state.get("vehicle_nature_result"):
                vehicle = VehicleNatureResult.model_validate(
                    state["vehicle_nature_result"]
                )
            if state.get("liability_result"):
                liability = LiabilityResult.model_validate(state["liability_result"])
        except Exception as exc:
            issues.append(
                _issue(
                    "CONSISTENCY-BUSINESS-SCHEMA",
                    f"Business output schema invalid: {exc}",
                    "Repair the structured business output.",
                )
            )
        if vehicle and liability:
            expected = {
                VehicleNatureClassification.MOTOR_VEHICLE: CompensationRegime.MOTOR_VS_MOTOR,
                VehicleNatureClassification.NON_MOTOR_VEHICLE: CompensationRegime.MOTOR_VS_NON_MOTOR_OR_PEDESTRIAN,
                VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE: CompensationRegime.PENDING_VEHICLE_CLASSIFICATION,
                VehicleNatureClassification.INSUFFICIENT_EVIDENCE: CompensationRegime.INSUFFICIENT_EVIDENCE,
            }[vehicle.classification]
            routed = (
                state.get("compensation_route_result", {}).get("regime")
                or liability.compensation_regime.value
            )
            if routed != expected.value:
                issues.append(
                    _issue(
                        "CONSISTENCY-VEHICLE-COMPENSATION",
                        (
                            f"Vehicle classification {vehicle.classification.value} "
                            f"conflicts with compensation regime {routed}."
                        ),
                        "Re-run the deterministic CompensationRegimeRouter.",
                    )
                )
            probability_sum = sum(liability.responsibility_probabilities.values())
            if abs(probability_sum - 1.0) > 1e-6:
                issues.append(
                    _issue(
                        "CONSISTENCY-PROBABILITY-SUM",
                        f"Responsibility probabilities sum to {probability_sum}.",
                        "Normalize the distribution to exactly 1.",
                    )
                )
            finding_ids = {
                item.behavior_id for item in liability.violation_matrix
            }
            causal_ids = {item.behavior_id for item in liability.causation_matrix}
            for hypothesis in liability.liability_hypotheses:
                if not set(hypothesis.supporting_findings) <= finding_ids:
                    issues.append(
                        _issue(
                            "CONSISTENCY-HYPOTHESIS-FINDINGS",
                            (
                                f"Hypothesis {hypothesis.hypothesis_id} references "
                                "unknown supporting findings."
                            ),
                            "Use existing violation finding IDs.",
                        )
                    )
            confirmed_ids = {
                item.behavior_id
                for item in liability.violation_matrix
                if item.status.value == "confirmed"
            }
            if confirmed_ids - causal_ids:
                issues.append(
                    _issue(
                        "CONSISTENCY-CAUSE-MISSING",
                        "Confirmed violations are missing causation analysis.",
                        "Add a causation finding for every confirmed violation.",
                    )
                )

        required_separation = {
            "accident_responsibility",
            "civil_compensation_allocation",
            "insurance_payment_estimate",
        }
        if not required_separation <= set(state):
            issues.append(
                _issue(
                    "CONSISTENCY-RESPONSIBILITY-LAYERS",
                    "Accident, civil, and insurance outputs are not separately present.",
                    "Provide all three structured outputs.",
                )
            )
        if state.get("accident_responsibility") == state.get(
            "insurance_payment_estimate"
        ):
            issues.append(
                _issue(
                    "CONSISTENCY-RESPONSIBILITY-CONFLATION",
                    "Accident responsibility and insurance payment were conflated.",
                    "Keep legal responsibility and insurance calculation separate.",
                )
            )

        for payload in state.get("deadlines", []):
            try:
                deadline = DeadlineResult.model_validate(payload)
                if deadline.status.value not in {"disputed", "not_started"} and (
                    deadline.trigger_date is None or deadline.due_at is None
                ):
                    raise ValueError("active/expired deadline lacks trigger or due time")
            except Exception as exc:
                issues.append(
                    _issue(
                        "CONSISTENCY-DEADLINE",
                        f"Invalid deadline: {exc}",
                        "Re-run deterministic delivery-date and deadline tools.",
                    )
                )

        valid_fact_ids = {
            str(item["fact_id"]) for item in evidence_export.get("facts", [])
        }
        valid_evidence_ids = {
            str(item["node_id"])
            for item in evidence_export.get("evidence_nodes", [])
        } | {
            str(item["source_id"]) for item in evidence_export.get("sources", [])
        }
        for task in state.get("rights_tasks", []):
            bad_facts = set(task.get("related_fact_ids", [])) - valid_fact_ids
            bad_evidence = (
                set(task.get("related_evidence_ids", [])) - valid_evidence_ids
            )
            if bad_facts or bad_evidence:
                issues.append(
                    _issue(
                        "CONSISTENCY-TASK-REFERENCES",
                        (
                            f"RightsTask {task.get('task_id')} references missing "
                            f"facts/evidence: {sorted(bad_facts | bad_evidence)}"
                        ),
                        "Use only current-case Fact/Evidence IDs.",
                    )
                )

        if state.get("review_application_draft"):
            try:
                draft = ReviewApplicationDraft.model_validate(
                    state["review_application_draft"]
                )
                approval = state.get("approval_state", {})
                if approval.get("state") == "approved" and (
                    approval.get("inputs_hash") != draft.inputs_hash
                    or approval.get("document_version") != draft.document_version
                ):
                    issues.append(
                        _issue(
                            "CONSISTENCY-STALE-APPROVAL",
                            "Modified document incorrectly retains an old approval.",
                            "Invalidate the approval and return to pending.",
                        )
                    )
            except Exception as exc:
                issues.append(
                    _issue(
                        "CONSISTENCY-DRAFT-SCHEMA",
                        f"Review draft schema invalid: {exc}",
                        "Repair the draft schema and citations.",
                    )
                )
        return ComponentVerifierResult(
            verifier="consistency",
            passed=not issues,
            issues=issues,
        )


def _issue(code: str, message: str, action: str) -> VerificationIssue:
    return VerificationIssue(
        code=code,
        message=message,
        severity=VerificationSeverity.BLOCKING,
        required_action=action,
    )
