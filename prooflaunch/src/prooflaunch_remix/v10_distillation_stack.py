from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_distillation import DistillationSignalKind, OutputRightsStatus
from .v10_on_policy_distillation import KDMethod
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_finite_nonnegative(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise V10ContractError(f"{field_name} must be finite and non-negative")


def _require_probabilities(values: Sequence[float], field_name: str) -> None:
    if len(values) < 2:
        raise V10ContractError(f"{field_name} needs at least two probabilities")
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise V10ContractError(f"{field_name} must be finite and strictly positive")
    if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise V10ContractError(f"{field_name} must sum to one")


class DistillationLane(str, Enum):
    MODEL_LOGITS = "model_logits"
    HIDDEN_FEATURE = "hidden_feature"
    VISUAL_CROP = "visual_crop"
    LAYOUT = "layout"
    VIDEO_TEMPORAL = "video_temporal"
    AGENT_PLAN = "agent_plan"
    AGENT_TOOL = "agent_tool"
    AGENT_STOP = "agent_stop"
    FAILURE_ATTRIBUTION = "failure_attribution"
    FOUR_A_CRITIQUE = "four_a_critique"
    AUDIT_REPAIR = "audit_repair"
    MATURE_WORKFLOW = "mature_workflow"


class SourceAssetPolicy(str, Enum):
    LICENSED_OR_OWNED = "licensed_owned_or_synthetic_only"
    DERIVED_ABSTRACTION = "rights_approved_derived_abstraction_only"


@dataclass(frozen=True)
class DistillationLaneSpec:
    lane: DistillationLane
    signal_kinds: tuple[DistillationSignalKind, ...]
    alignment_key: str
    losses: tuple[str, ...]
    objective_metrics: tuple[str, ...]
    source_asset_policy: SourceAssetPolicy
    maximum_gpu_seconds: int = 7_200
    rights_approval_required: bool = True
    hidden_reasoning_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.signal_kinds or not self.alignment_key.strip():
            raise V10ContractError("distillation lane needs signal kinds and alignment")
        if not self.losses or len(self.objective_metrics) < 2:
            raise V10ContractError("distillation lane needs loss and objective metrics")
        if self.maximum_gpu_seconds != 7_200:
            raise V10ContractError("each lane is bounded to a two-hour GPU experiment")
        if not self.rights_approval_required or self.hidden_reasoning_allowed:
            raise V10ContractError("lanes must be rights-gated and hidden-reasoning free")


def default_lane_specs() -> tuple[DistillationLaneSpec, ...]:
    rows = (
        (DistillationLane.MODEL_LOGITS, (DistillationSignalKind.TOKEN,), "token_id", ("temperature_kl",), ("heldout_nll", "expected_calibration_error"), SourceAssetPolicy.LICENSED_OR_OWNED),
        (DistillationLane.HIDDEN_FEATURE, (DistillationSignalKind.FEATURE,), "projected_feature_position", ("masked_cosine", "normalized_mse"), ("linear_probe_accuracy", "capability_retention"), SourceAssetPolicy.LICENSED_OR_OWNED),
        (DistillationLane.VISUAL_CROP, (DistillationSignalKind.REGION, DistillationSignalKind.FEATURE), "image_sha256_bbox", ("region_contrastive", "grounding_iou"), ("region_recall_at_05", "visual_retention"), SourceAssetPolicy.LICENSED_OR_OWNED),
        (DistillationLane.LAYOUT, (DistillationSignalKind.REGION, DistillationSignalKind.WORKFLOW), "canvas_node_edge_id", ("constraint_violation", "reading_order"), ("layout_constraint_pass_rate", "reading_order_accuracy"), SourceAssetPolicy.LICENSED_OR_OWNED),
        (DistillationLane.VIDEO_TEMPORAL, (DistillationSignalKind.FEATURE, DistillationSignalKind.TRAJECTORY), "video_sha256_timestamp_ms", ("temporal_alignment", "causal_consistency"), ("temporal_grounding_iou", "event_order_accuracy"), SourceAssetPolicy.LICENSED_OR_OWNED),
        (DistillationLane.AGENT_PLAN, (DistillationSignalKind.TRAJECTORY,), "task_step_id", ("visible_action_ce", "dependency_violation"), ("plan_validity", "task_success"), SourceAssetPolicy.DERIVED_ABSTRACTION),
        (DistillationLane.AGENT_TOOL, (DistillationSignalKind.TRAJECTORY,), "tool_call_id", ("tool_choice_ce", "argument_schema"), ("tool_success", "invalid_call_rate"), SourceAssetPolicy.DERIVED_ABSTRACTION),
        (DistillationLane.AGENT_STOP, (DistillationSignalKind.REWARD, DistillationSignalKind.TRAJECTORY), "terminal_step_id", ("stop_binary_ce", "overrun_penalty"), ("premature_stop_rate", "post_success_overrun_rate"), SourceAssetPolicy.DERIVED_ABSTRACTION),
        (DistillationLane.FAILURE_ATTRIBUTION, (DistillationSignalKind.REWARD, DistillationSignalKind.TRAJECTORY), "first_error_step_id", ("attribution_ce", "propagation_distance"), ("first_error_accuracy", "repair_success"), SourceAssetPolicy.DERIVED_ABSTRACTION),
        (DistillationLane.FOUR_A_CRITIQUE, (DistillationSignalKind.REWARD, DistillationSignalKind.UNCERTAINTY), "owned_asset_claim_id", ("rubric_pairwise", "unsupported_claim_penalty"), ("blind_preference_win_rate", "claim_precision"), SourceAssetPolicy.DERIVED_ABSTRACTION),
        (DistillationLane.AUDIT_REPAIR, (DistillationSignalKind.WORKFLOW, DistillationSignalKind.REWARD), "finding_repair_id", ("repair_selection_ce", "regression_penalty"), ("verified_fix_rate", "new_regression_rate"), SourceAssetPolicy.DERIVED_ABSTRACTION),
        (DistillationLane.MATURE_WORKFLOW, (DistillationSignalKind.WORKFLOW, DistillationSignalKind.TRAJECTORY), "workflow_transition_id", ("transition_ce", "policy_violation_penalty"), ("workflow_completion", "human_escalation_precision"), SourceAssetPolicy.DERIVED_ABSTRACTION),
    )
    return tuple(DistillationLaneSpec(*row) for row in rows)


def logits_kl_loss(
    teacher_probabilities: Sequence[float],
    student_probabilities: Sequence[float],
) -> float:
    _require_probabilities(teacher_probabilities, "teacher_probabilities")
    _require_probabilities(student_probabilities, "student_probabilities")
    if len(teacher_probabilities) != len(student_probabilities):
        raise V10ContractError("teacher and student vocabularies must align")
    return sum(
        teacher * math.log(teacher / student)
        for teacher, student in zip(teacher_probabilities, student_probabilities)
    )


@dataclass(frozen=True)
class HiddenFeaturePair:
    teacher: tuple[float, ...]
    student_projected: tuple[float, ...]
    projection_revision: str
    attention_mask: tuple[bool, ...]

    def __post_init__(self) -> None:
        if not self.projection_revision.strip():
            raise V10ContractError("hidden feature projection revision is required")
        if not self.teacher or len(self.teacher) != len(self.student_projected):
            raise V10ContractError("projected teacher and student features must align")
        if len(self.teacher) != len(self.attention_mask) or not any(self.attention_mask):
            raise V10ContractError("feature mask must align and retain an observed position")
        if any(not math.isfinite(value) for value in self.teacher + self.student_projected):
            raise V10ContractError("hidden features must be finite")

    def masked_mse(self) -> float:
        errors = [
            (teacher - student) ** 2
            for teacher, student, keep in zip(
                self.teacher, self.student_projected, self.attention_mask
            )
            if keep
        ]
        return sum(errors) / len(errors)


@dataclass(frozen=True)
class VisualCropTarget:
    image_sha256: str
    bbox_xyxy_normalized: tuple[float, float, float, float]
    label: str
    rights_status: OutputRightsStatus

    def __post_init__(self) -> None:
        _require_sha256(self.image_sha256, "image_sha256")
        x1, y1, x2, y2 = self.bbox_xyxy_normalized
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise V10ContractError("visual crop bbox must be non-empty and image-bounded")
        if not self.label.strip() or self.rights_status is not OutputRightsStatus.APPROVED:
            raise V10ContractError("visual crop requires a label and approved rights")


@dataclass(frozen=True)
class LayoutTarget:
    canvas_sha256: str
    node_ids: tuple[str, ...]
    directed_edges: tuple[tuple[str, str], ...]
    reading_order: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.canvas_sha256, "canvas_sha256")
        nodes = set(self.node_ids)
        if not nodes or len(nodes) != len(self.node_ids):
            raise V10ContractError("layout nodes must be present and unique")
        if set(self.reading_order) != nodes or len(self.reading_order) != len(nodes):
            raise V10ContractError("reading order must cover every layout node exactly once")
        if any(source not in nodes or target not in nodes or source == target for source, target in self.directed_edges):
            raise V10ContractError("layout edges must connect distinct declared nodes")


@dataclass(frozen=True)
class TemporalTarget:
    video_sha256: str
    timestamps_ms: tuple[int, ...]
    event_ids: tuple[str, ...]
    duration_ms: int

    def __post_init__(self) -> None:
        _require_sha256(self.video_sha256, "video_sha256")
        if self.duration_ms <= 0 or len(self.timestamps_ms) != len(self.event_ids):
            raise V10ContractError("temporal targets need aligned events inside a video")
        if not self.timestamps_ms or len(set(self.event_ids)) != len(self.event_ids):
            raise V10ContractError("temporal target events must be present and unique")
        if any(left >= right for left, right in zip(self.timestamps_ms, self.timestamps_ms[1:])):
            raise V10ContractError("video timestamps must be strictly increasing")
        if self.timestamps_ms[0] < 0 or self.timestamps_ms[-1] > self.duration_ms:
            raise V10ContractError("video timestamps must remain inside duration")


@dataclass(frozen=True)
class VisibleAgentTarget:
    lane: DistillationLane
    task_id: str
    visible_observation_sha256: str
    target_event: Mapping[str, object]
    hidden_reasoning_persisted: bool
    rights_status: OutputRightsStatus

    def __post_init__(self) -> None:
        allowed = {
            DistillationLane.AGENT_PLAN,
            DistillationLane.AGENT_TOOL,
            DistillationLane.AGENT_STOP,
            DistillationLane.FAILURE_ATTRIBUTION,
            DistillationLane.FOUR_A_CRITIQUE,
            DistillationLane.AUDIT_REPAIR,
            DistillationLane.MATURE_WORKFLOW,
        }
        if self.lane not in allowed or not self.task_id.strip() or not self.target_event:
            raise V10ContractError("visible agent target has an invalid lane or empty event")
        _require_sha256(self.visible_observation_sha256, "visible_observation_sha256")
        if self.hidden_reasoning_persisted:
            raise V10ContractError("hidden reasoning cannot be an agent distillation target")
        if self.rights_status is not OutputRightsStatus.APPROVED:
            raise V10ContractError("agent targets require approved output rights")
        forbidden = {"chain_of_thought", "hidden_reasoning", "private_scratchpad"}
        if forbidden & set(self.target_event):
            raise V10ContractError("agent target contains a forbidden reasoning field")


class DistillationControl(str, Enum):
    CAOPD = "caopd_control"
    OFFLINE_KD = "offline_kd_control"
    ON_POLICY_KD = "on_policy_kd_control"
    SELF_KD = "self_kd_control"
    NO_KD = "no_kd_control"


@dataclass(frozen=True)
class ControlArmSpec:
    control: DistillationControl
    method: KDMethod
    teacher_required: bool
    student_generated_rollouts: bool


def default_control_arms() -> tuple[ControlArmSpec, ...]:
    return (
        ControlArmSpec(DistillationControl.CAOPD, KDMethod.CAOPD, True, True),
        ControlArmSpec(DistillationControl.OFFLINE_KD, KDMethod.OFF_POLICY_KD, True, False),
        ControlArmSpec(DistillationControl.ON_POLICY_KD, KDMethod.ON_POLICY_KD, True, True),
        ControlArmSpec(DistillationControl.SELF_KD, KDMethod.OPSD, True, True),
        ControlArmSpec(DistillationControl.NO_KD, KDMethod.NO_KD, False, False),
    )


@dataclass(frozen=True)
class MatchedControlMatrix:
    arms: tuple[ControlArmSpec, ...]
    base_revision: str
    dataset_sha256: str
    evaluation_sha256: str
    hardware_fingerprint: str
    seed: int
    maximum_train_tokens: int

    def __post_init__(self) -> None:
        if {arm.control for arm in self.arms} != set(DistillationControl):
            raise V10ContractError("the exact five distillation controls are required")
        if len(self.arms) != len(DistillationControl):
            raise V10ContractError("distillation controls cannot be duplicated")
        _require_sha256(self.dataset_sha256, "dataset_sha256")
        _require_sha256(self.evaluation_sha256, "evaluation_sha256")
        if not self.base_revision.strip() or not self.hardware_fingerprint.strip():
            raise V10ContractError("matched controls require frozen model and hardware")
        if self.seed < 0 or self.maximum_train_tokens < 1:
            raise V10ContractError("matched controls require a seed and token budget")


def capability_retention(
    before: Mapping[str, float], after: Mapping[str, float]
) -> float:
    if not before or set(before) != set(after):
        raise V10ContractError("capability measurements must align")
    for name, value in {**before, **after}.items():
        if not math.isfinite(value) or value < 0:
            raise V10ContractError(f"capability {name} must be finite and non-negative")
    denominator = sum(before.values())
    if denominator <= 0:
        raise V10ContractError("pre-distillation capability must be positive")
    return sum(min(before[name], after[name]) for name in before) / denominator


def expected_calibration_error(
    confidences: Sequence[float],
    predictions: Sequence[int],
    labels: Sequence[int],
    *,
    bins: int = 10,
) -> float:
    if not confidences or not (len(confidences) == len(predictions) == len(labels)):
        raise V10ContractError("calibration rows must be non-empty and aligned")
    if bins < 2 or any(not math.isfinite(value) or not 0 <= value <= 1 for value in confidences):
        raise V10ContractError("calibration confidences and bin count are invalid")
    total = len(confidences)
    error = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        indices = [
            index
            for index, confidence in enumerate(confidences)
            if lower <= confidence <= upper and (bin_index == bins - 1 or confidence < upper)
        ]
        if not indices:
            continue
        accuracy = sum(predictions[index] == labels[index] for index in indices) / len(indices)
        confidence = sum(confidences[index] for index in indices) / len(indices)
        error += len(indices) / total * abs(accuracy - confidence)
    return error


def token_efficiency(verified_successes: int, generated_tokens: int) -> float:
    if not 0 <= verified_successes <= generated_tokens or generated_tokens < 1:
        raise V10ContractError("token efficiency needs bounded successes and positive tokens")
    return 1_000 * verified_successes / generated_tokens


def wall_clock_benefit(baseline_seconds: float, candidate_seconds: float) -> float:
    if baseline_seconds <= 0 or candidate_seconds <= 0:
        raise V10ContractError("wall-clock observations must be positive")
    if not math.isfinite(baseline_seconds) or not math.isfinite(candidate_seconds):
        raise V10ContractError("wall-clock observations must be finite")
    return baseline_seconds / candidate_seconds


@dataclass(frozen=True)
class TeacherCandidate:
    teacher_id: str
    revision: str
    revision_verified: bool
    rights_status: OutputRightsStatus
    information_gain: float | None
    observed_examples: int


def teacher_elimination_reasons(
    candidate: TeacherCandidate,
    *,
    minimum_information_gain: float = 0.02,
    minimum_observed_examples: int = 30,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not candidate.teacher_id.strip() or not candidate.revision.strip() or not candidate.revision_verified:
        reasons.append("unverified_teacher_revision")
    if candidate.rights_status is not OutputRightsStatus.APPROVED:
        reasons.append("output_rights_not_approved")
    if candidate.information_gain is None:
        reasons.append("information_gain_unobserved")
    elif not math.isfinite(candidate.information_gain) or candidate.information_gain < minimum_information_gain:
        reasons.append("teacher_adds_no_new_information")
    if candidate.observed_examples < minimum_observed_examples:
        reasons.append("insufficient_observed_examples")
    return tuple(reasons)


def planned_distillation_stack_card(
    lanes: Sequence[DistillationLaneSpec],
    controls: MatchedControlMatrix,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "ProofLaunchDistillationStackCardV1",
        "lane_registry_sha256": stable_sha256([asdict(item) for item in lanes]),
        "control_matrix_sha256": stable_sha256(asdict(controls)),
        "training_observed": False,
        "radeon_execution_observed": False,
        "capability_retention": None,
        "expected_calibration_error": None,
        "token_efficiency_per_1k": None,
        "wall_clock_benefit": None,
        "selected_teacher": None,
        "selected_control": None,
        "selected_adapter": None,
        "promotion_eligible": False,
        "truth_boundary": "Frozen executable contracts and mechanical fixtures only; no training, Radeon runtime, quality gain, teacher winner, or adapter promotion is claimed.",
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload


def freeze_distillation_stack_v1() -> dict[str, object]:
    lanes = default_lane_specs()
    controls = MatchedControlMatrix(
        arms=default_control_arms(),
        base_revision="AI-ModelScope/Gemma-4-E4B-it@4f5f0c899a9b6d34c4b463f557c31c8ac6c767cc",
        dataset_sha256=stable_sha256(
            {"fixture": "distillation-stack-v1-synthetic-mechanical-train"}
        ),
        evaluation_sha256=stable_sha256(
            {"fixture": "distillation-stack-v1-synthetic-mechanical-eval"}
        ),
        hardware_fingerprint="AMD_RADEON_PENDING_OBSERVATION",
        seed=42,
        maximum_train_tokens=1_000_000,
    )
    body: dict[str, object] = {
        "schema": "ProofLaunchDistillationStackV1",
        "version": "1.0.0",
        "status": "frozen_contract_not_executed",
        "lanes": [asdict(item) for item in lanes],
        "controls": asdict(controls),
        "teacher_gate": {
            "minimum_information_gain": 0.02,
            "minimum_observed_examples": 30,
            "unverified_or_unlicensed_teacher": "eliminate",
        },
        "runtime_truth": {
            "training_observed": False,
            "radeon_execution_observed": False,
            "external_teacher_calls_observed": False,
        },
        "card": planned_distillation_stack_card(lanes, controls),
    }
    body["content_sha256"] = stable_sha256(body)
    return body
