from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_agentomnia import DatasetPartition
from .v10_contracts import V10ContractError
from .v10_gtm_environment import Operation, stable_digest
from .v10_trajectory_distillation import (
    OutcomeKind,
    OutcomeTrajectory,
    RoleTrajectory,
    TrainingLabel,
    TrajectoryRole,
    decompose_role_trajectories,
    reward_outcome,
)


class LengthBucket(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class AblationArm(str, Enum):
    FULL_TRAJECTORY = "full_trajectory_supervision"
    NO_TRAJECTORY = "no_trajectory_supervision"
    FINAL_ANSWER_KD = "final_answer_only_kd"


@dataclass(frozen=True)
class CreditIncident:
    first_error_step: int
    origin_role: TrajectoryRole
    amplification_roles: tuple[TrajectoryRole, ...] = ()
    missed_detection_roles: tuple[TrajectoryRole, ...] = ()
    repair_role: TrajectoryRole | None = None
    repair_step: int | None = None

    def __post_init__(self) -> None:
        if self.first_error_step < 0:
            raise V10ContractError("credit incident first-error step is invalid")
        if len(set(self.amplification_roles)) != len(self.amplification_roles):
            raise V10ContractError("amplification roles must be unique")
        if len(set(self.missed_detection_roles)) != len(
            self.missed_detection_roles
        ):
            raise V10ContractError("missed-detection roles must be unique")
        if (self.repair_role is None) != (self.repair_step is None):
            raise V10ContractError("repair role and step must be supplied together")
        if self.repair_step is not None and self.repair_step <= self.first_error_step:
            raise V10ContractError("repair credit must follow the first error")


@dataclass(frozen=True)
class RoleCredit:
    role: TrajectoryRole
    planning: int = 0
    execution: int = 0
    detection: int = 0
    repair: int = 0
    supervision: int = 0
    error_penalty: int = 0
    evidence_step_indices: tuple[int, ...] = ()
    evidence_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "planning",
            "execution",
            "detection",
            "repair",
            "supervision",
            "error_penalty",
        ):
            if getattr(self, field_name) not in {-1, 0, 1}:
                raise V10ContractError(f"{field_name} credit must be -1, 0, or 1")
        if any(index < 0 for index in self.evidence_step_indices):
            raise V10ContractError("credit evidence step is invalid")
        if not self.evidence_codes:
            raise V10ContractError("role credit needs visible evidence codes")


@dataclass(frozen=True)
class HierarchicalCreditAssignment:
    trajectory_id: str
    step_reward_sha256: str
    role_credits: tuple[RoleCredit, ...]
    nonterminal_credited_steps: tuple[int, ...]
    terminal_credited_step: int
    final_only_credit_blocked: bool
    upstream_propagation_guarded: bool

    def __post_init__(self) -> None:
        if not self.trajectory_id.strip() or len(self.step_reward_sha256) != 64:
            raise V10ContractError("credit assignment identity is invalid")
        roles = [credit.role for credit in self.role_credits]
        if set(roles) != set(TrajectoryRole) or len(roles) != len(set(roles)):
            raise V10ContractError("credit assignment needs each role exactly once")
        if not self.nonterminal_credited_steps:
            raise V10ContractError("final-only credit is forbidden")
        if self.terminal_credited_step < 1:
            raise V10ContractError("terminal credit needs a preceding step")
        if not self.final_only_credit_blocked or not self.upstream_propagation_guarded:
            raise V10ContractError("credit safety guards must remain enabled")

    @property
    def digest(self) -> str:
        return stable_digest(asdict(self))


def infer_credit_incident(outcome: OutcomeTrajectory) -> CreditIncident | None:
    rejected = [event.step_index for event in outcome.events if not event.accepted]
    if not rejected:
        return None
    repair_step = None
    repair_role = None
    if outcome.outcome_kind == OutcomeKind.RETRY:
        repair_step = next(
            event.step_index
            for event in outcome.events
            if event.step_index > rejected[0]
            and event.accepted
            and event.action.operation != Operation.INSPECT
        )
        repair_role = TrajectoryRole.WORKER
    return CreditIncident(
        first_error_step=rejected[0],
        origin_role=TrajectoryRole.WORKER,
        repair_role=repair_role,
        repair_step=repair_step,
    )


def assign_hierarchical_credit(
    outcome: OutcomeTrajectory,
    incident: CreditIncident | None = None,
) -> HierarchicalCreditAssignment:
    step_rewards, _ = reward_outcome(outcome)
    incident = incident if incident is not None else infer_credit_incident(outcome)
    last_step = len(outcome.events) - 1
    nonterminal = tuple(
        reward.step_index
        for reward in step_rewards
        if reward.step_index != last_step
        and any(
            value != 0
            for value in (
                reward.correctness,
                reward.safety,
                reward.progress,
                reward.recovery,
            )
        )
    )
    values: dict[TrajectoryRole, dict[str, object]] = {
        role: {
            "planning": 0,
            "execution": 0,
            "detection": 0,
            "repair": 0,
            "supervision": 0,
            "error_penalty": 0,
            "evidence_step_indices": (),
            "evidence_codes": [],
        }
        for role in TrajectoryRole
    }
    values[TrajectoryRole.PLANNER]["planning"] = (
        1 if outcome.training_label == TrainingLabel.IMITATE else 0
    )
    values[TrajectoryRole.PLANNER]["evidence_step_indices"] = (0,)
    values[TrajectoryRole.PLANNER]["evidence_codes"].append("bounded_plan_trace")
    values[TrajectoryRole.WORKER]["execution"] = (
        1 if outcome.verification.issue_resolved else -1
    )
    values[TrajectoryRole.WORKER]["evidence_step_indices"] = tuple(
        event.step_index for event in outcome.events
    )
    values[TrajectoryRole.WORKER]["evidence_codes"].append(
        "visible_execution_transitions"
    )
    values[TrajectoryRole.CRITIC]["detection"] = 1
    values[TrajectoryRole.CRITIC]["evidence_step_indices"] = (last_step,)
    values[TrajectoryRole.CRITIC]["evidence_codes"].append(
        "kind_aware_verifier_pass"
    )
    values[TrajectoryRole.SUPERVISOR]["supervision"] = 1
    values[TrajectoryRole.SUPERVISOR]["evidence_step_indices"] = (last_step,)
    values[TrajectoryRole.SUPERVISOR]["evidence_codes"].append(
        "correct_training_admission"
    )
    if incident is not None:
        values[incident.origin_role]["error_penalty"] = -1
        values[incident.origin_role]["evidence_codes"].append("explicit_error_origin")
        for role in incident.amplification_roles:
            values[role]["error_penalty"] = -1
            values[role]["evidence_codes"].append("explicit_error_amplification")
        for role in incident.missed_detection_roles:
            values[role]["detection"] = -1
            values[role]["evidence_codes"].append("explicit_missed_detection")
        if incident.repair_role is not None:
            values[incident.repair_role]["repair"] = 1
            values[incident.repair_role]["evidence_codes"].append(
                "verified_post_error_repair"
            )
    role_credits = tuple(
        RoleCredit(
            role=role,
            planning=int(values[role]["planning"]),
            execution=int(values[role]["execution"]),
            detection=int(values[role]["detection"]),
            repair=int(values[role]["repair"]),
            supervision=int(values[role]["supervision"]),
            error_penalty=int(values[role]["error_penalty"]),
            evidence_step_indices=tuple(values[role]["evidence_step_indices"]),
            evidence_codes=tuple(values[role]["evidence_codes"]),
        )
        for role in TrajectoryRole
    )
    return HierarchicalCreditAssignment(
        trajectory_id=outcome.trajectory_id,
        step_reward_sha256=stable_digest([asdict(item) for item in step_rewards]),
        role_credits=role_credits,
        nonterminal_credited_steps=nonterminal,
        terminal_credited_step=last_step,
        final_only_credit_blocked=True,
        upstream_propagation_guarded=True,
    )


def bucket_for_role_trajectory(trajectory: RoleTrajectory) -> LengthBucket:
    length = len(trajectory.steps)
    if length == 1:
        return LengthBucket.SHORT
    if length <= 3:
        return LengthBucket.MEDIUM
    return LengthBucket.LONG


@dataclass(frozen=True)
class CurriculumStage:
    order: int
    bucket: LengthBucket
    trajectory_ids: tuple[str, ...]
    partition_counts: Mapping[str, int]
    maximum_steps: int | None

    def __post_init__(self) -> None:
        if self.order < 0 or not self.trajectory_ids:
            raise V10ContractError("curriculum stage order and trajectories are required")
        if len(self.trajectory_ids) != len(set(self.trajectory_ids)):
            raise V10ContractError("curriculum stage trajectories must be unique")
        if set(self.partition_counts) - {
            DatasetPartition.SFT.value,
            DatasetPartition.RL.value,
        }:
            raise V10ContractError("validation/evaluation leakage entered training curriculum")

    @property
    def digest(self) -> str:
        return stable_digest(asdict(self))


@dataclass(frozen=True)
class TemporalCurriculum:
    version: str
    stages: tuple[CurriculumStage, ...]
    held_out_partitions: tuple[DatasetPartition, ...]

    def __post_init__(self) -> None:
        if self.version != "trajectory-temporal-curriculum-v1":
            raise V10ContractError("unexpected temporal curriculum version")
        if [stage.bucket for stage in self.stages] != [
            LengthBucket.SHORT,
            LengthBucket.MEDIUM,
            LengthBucket.LONG,
        ]:
            raise V10ContractError("curriculum must progress short, medium, then long")
        ids = [item for stage in self.stages for item in stage.trajectory_ids]
        if len(ids) != len(set(ids)):
            raise V10ContractError("a role trajectory can enter only one curriculum stage")
        if set(self.held_out_partitions) != {
            DatasetPartition.VALIDATION,
            DatasetPartition.EVALUATION,
        }:
            raise V10ContractError("validation and evaluation must remain held out")

    @property
    def digest(self) -> str:
        return stable_digest(asdict(self))


def build_temporal_curriculum(
    outcomes: Sequence[OutcomeTrajectory],
) -> TemporalCurriculum:
    role_trajectories = tuple(
        role
        for outcome in outcomes
        if outcome.partition in {DatasetPartition.SFT, DatasetPartition.RL}
        for role in decompose_role_trajectories(outcome)
    )
    stages: list[CurriculumStage] = []
    for order, bucket in enumerate(LengthBucket):
        selected = tuple(
            sorted(
                (
                    item
                    for item in role_trajectories
                    if bucket_for_role_trajectory(item) == bucket
                ),
                key=lambda item: item.trajectory_id,
            )
        )
        counts = {
            partition.value: sum(item.partition == partition for item in selected)
            for partition in (DatasetPartition.SFT, DatasetPartition.RL)
            if any(item.partition == partition for item in selected)
        }
        stages.append(
            CurriculumStage(
                order=order,
                bucket=bucket,
                trajectory_ids=tuple(item.trajectory_id for item in selected),
                partition_counts=counts,
                maximum_steps=(1 if bucket == LengthBucket.SHORT else 3 if bucket == LengthBucket.MEDIUM else None),
            )
        )
    return TemporalCurriculum(
        version="trajectory-temporal-curriculum-v1",
        stages=tuple(stages),
        held_out_partitions=(
            DatasetPartition.VALIDATION,
            DatasetPartition.EVALUATION,
        ),
    )


def _normalized_distribution(distribution: Mapping[str, float]) -> dict[str, float]:
    if not distribution or any(
        not math.isfinite(value) or value < 0 for value in distribution.values()
    ):
        raise V10ContractError("action distribution is invalid")
    total = sum(distribution.values())
    if total <= 0:
        raise V10ContractError("action distribution must have positive mass")
    return {key: value / total for key, value in distribution.items()}


def categorical_kl(
    teacher: Mapping[str, float],
    student: Mapping[str, float],
    *,
    epsilon: float = 1e-12,
) -> float:
    teacher_norm = _normalized_distribution(teacher)
    student_norm = _normalized_distribution(student)
    support = set(teacher_norm) | set(student_norm)
    return sum(
        teacher_norm.get(action, 0.0)
        * math.log(
            max(teacher_norm.get(action, 0.0), epsilon)
            / max(student_norm.get(action, 0.0), epsilon)
        )
        for action in support
        if teacher_norm.get(action, 0.0) > 0
    )


@dataclass(frozen=True)
class TrajectoryDiagnostic:
    case_id: str
    mean_trajectory_kl: float
    first_action_mismatch_step: int | None
    compounding_error_rate: float
    tool_noise_sensitivity: float
    repeated_state_action_count: int
    flags: tuple[str, ...]
    evidence_scope: str = "controlled_mechanical_fixture_not_model_output"

    def __post_init__(self) -> None:
        for value in (
            self.mean_trajectory_kl,
            self.compounding_error_rate,
            self.tool_noise_sensitivity,
        ):
            if not math.isfinite(value) or value < 0:
                raise V10ContractError("trajectory diagnostic values must be finite and nonnegative")
        if self.repeated_state_action_count < 0:
            raise V10ContractError("loop count cannot be negative")

    @property
    def digest(self) -> str:
        return stable_digest(asdict(self))


def diagnose_trajectory(
    case_id: str,
    teacher_steps: Sequence[Mapping[str, float]],
    student_steps: Sequence[Mapping[str, float]],
    clean_tool_matches: Sequence[bool],
    noisy_tool_matches: Sequence[bool],
    state_action_keys: Sequence[str],
) -> TrajectoryDiagnostic:
    lengths = {
        len(teacher_steps),
        len(student_steps),
        len(clean_tool_matches),
        len(noisy_tool_matches),
        len(state_action_keys),
    }
    if len(lengths) != 1 or not teacher_steps or not case_id.strip():
        raise V10ContractError("diagnostic sequences must be nonempty and aligned")
    divergences = [
        categorical_kl(teacher, student)
        for teacher, student in zip(teacher_steps, student_steps, strict=True)
    ]
    mismatches = [
        max(teacher, key=teacher.get) != max(student, key=student.get)
        for teacher, student in zip(teacher_steps, student_steps, strict=True)
    ]
    first_mismatch = next((index for index, value in enumerate(mismatches) if value), None)
    if first_mismatch is None:
        compounding = 0.0
    else:
        suffix = mismatches[first_mismatch + 1 :]
        compounding = sum(suffix) / len(suffix) if suffix else 0.0
    clean_rate = sum(clean_tool_matches) / len(clean_tool_matches)
    noisy_rate = sum(noisy_tool_matches) / len(noisy_tool_matches)
    noise_sensitivity = max(0.0, clean_rate - noisy_rate)
    repeated = len(state_action_keys) - len(set(state_action_keys))
    mean_kl = sum(divergences) / len(divergences)
    flags = []
    if mean_kl > 0.5:
        flags.append("trajectory_kl_explosion")
    if first_mismatch is not None and compounding > 0.5:
        flags.append("compounding_error")
    if noise_sensitivity > 0.25:
        flags.append("tool_noise_regression")
    if repeated:
        flags.append("invalid_loop")
    return TrajectoryDiagnostic(
        case_id=case_id,
        mean_trajectory_kl=mean_kl,
        first_action_mismatch_step=first_mismatch,
        compounding_error_rate=compounding,
        tool_noise_sensitivity=noise_sensitivity,
        repeated_state_action_count=repeated,
        flags=tuple(flags),
    )


@dataclass(frozen=True)
class InformationAblation:
    arm: AblationArm
    retained_supervision_fields: tuple[str, ...]
    outcome_label_available: bool
    step_attribution_scorable: bool
    role_credit_scorable: bool
    policy_action_scorable: bool
    model_quality_measured: bool = False


def build_information_ablations() -> tuple[InformationAblation, ...]:
    return (
        InformationAblation(
            AblationArm.FULL_TRAJECTORY,
            ("outcome", "steps", "roles", "policy", "rewards"),
            True,
            True,
            True,
            True,
        ),
        InformationAblation(
            AblationArm.NO_TRAJECTORY,
            (),
            False,
            False,
            False,
            False,
        ),
        InformationAblation(
            AblationArm.FINAL_ANSWER_KD,
            ("outcome",),
            True,
            False,
            False,
            False,
        ),
    )


@dataclass(frozen=True)
class MechanicalEvaluation:
    held_out_partition: DatasetPartition
    held_out_task_count: int
    outcome_count: int
    attribution_eligible_count: int
    mechanical_first_error_accuracy: float
    clean_positive_success_rate: float
    recovery_success_rate: float
    negative_rejection_rate: float
    trained_model_attribution_accuracy: float | None = None
    trained_model_task_success_rate: float | None = None
    scope: str = "mechanical_oracle_evaluation_not_trained_model_quality"


def evaluate_mechanical_pipeline(
    outcomes: Sequence[OutcomeTrajectory],
) -> MechanicalEvaluation:
    held_out = tuple(
        item for item in outcomes if item.partition == DatasetPartition.EVALUATION
    )
    if not held_out:
        raise V10ContractError("evaluation partition is empty")
    attribution = [
        item for item in held_out if item.outcome_kind in {OutcomeKind.FAILURE, OutcomeKind.RETRY}
    ]
    correct_attribution = 0
    for outcome in attribution:
        observed = next(
            (event.step_index for event in outcome.events if not event.accepted),
            None,
        )
        incident = infer_credit_incident(outcome)
        predicted = incident.first_error_step if incident is not None else None
        correct_attribution += observed == predicted

    def rate(selected: Sequence[OutcomeTrajectory], predicate: object) -> float:
        if not selected:
            raise V10ContractError("mechanical evaluation subgroup is empty")
        return sum(bool(predicate(item)) for item in selected) / len(selected)  # type: ignore[operator]

    positives = [item for item in held_out if item.training_label == TrainingLabel.IMITATE]
    recoveries = [item for item in held_out if item.training_label == TrainingLabel.RECOVERY]
    negatives = [item for item in held_out if item.training_label == TrainingLabel.NEGATIVE]
    return MechanicalEvaluation(
        held_out_partition=DatasetPartition.EVALUATION,
        held_out_task_count=len({item.task_id for item in held_out}),
        outcome_count=len(held_out),
        attribution_eligible_count=len(attribution),
        mechanical_first_error_accuracy=correct_attribution / len(attribution),
        clean_positive_success_rate=rate(
            positives,
            lambda item: item.verification.issue_resolved,
        ),
        recovery_success_rate=rate(
            recoveries,
            lambda item: item.verification.issue_resolved
            and item.verification.rejected_action_count > 0,
        ),
        negative_rejection_rate=rate(
            negatives,
            lambda item: not item.verification.issue_resolved
            and item.verification.terminal_signal == "budget_exhausted_failure",
        ),
    )


def build_trajectory_card(
    outcomes: Sequence[OutcomeTrajectory],
    *,
    source_manifest_sha256: str,
    diagnostic_digests: Sequence[str],
) -> dict[str, object]:
    if len(source_manifest_sha256) != 64 or not diagnostic_digests:
        raise V10ContractError("trajectory card source and diagnostics are required")
    curriculum = build_temporal_curriculum(outcomes)
    evaluation = evaluate_mechanical_pipeline(outcomes)
    ablations = build_information_ablations()
    payload: dict[str, object] = {
        "schema": "ProofLaunchTrajectoryCardV1",
        "version": "trajectory-kd-v1",
        "frozen": True,
        "source_manifest_sha256": source_manifest_sha256,
        "outcome_trajectory_count": len(outcomes),
        "credit_assignment_count": len(outcomes),
        "curriculum_digest": curriculum.digest,
        "curriculum_stage_counts": {
            stage.bucket.value: len(stage.trajectory_ids)
            for stage in curriculum.stages
        },
        "diagnostic_digests": list(diagnostic_digests),
        "ablation_arms": [asdict(item) for item in ablations],
        "mechanical_evaluation": asdict(evaluation),
        "trained_model_metrics": None,
        "promotion_eligible": False,
        "truth_boundary": (
            "This frozen card proves local mechanical credit, curriculum, diagnostic, "
            "ablation-contract, and held-out oracle evaluation behavior only. It does not "
            "prove a trained model, distillation uplift, Radeon execution, 4A quality, or "
            "business outcomes."
        ),
        "content_sha256": None,
    }
    payload["content_sha256"] = stable_digest(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    return payload
