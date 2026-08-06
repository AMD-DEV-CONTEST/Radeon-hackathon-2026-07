from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_probability_vector(values: Sequence[float], name: str) -> None:
    if len(values) < 2:
        raise V10ContractError(f"{name} needs at least two probabilities")
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise V10ContractError(f"{name} probabilities must be finite and positive")
    if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise V10ContractError(f"{name} probabilities must sum to one")


class KDMethod(str, Enum):
    GKD = "gkd_baseline"
    OFF_POLICY_KD = "off_policy_kd"
    ON_POLICY_KD = "on_policy_kd"
    OPSD = "on_policy_self_distillation"
    SDFT = "self_distillation_finetuning"
    TCOD = "temporal_curriculum_on_policy_distillation"
    CAOPD = "compatibility_aware_on_policy_distillation"
    NO_KD = "no_kd_control"


class PrivilegedKind(str, Enum):
    EVIDENCE = "privileged_evidence"
    CRITIQUE = "privileged_critique"
    REPAIR = "privileged_repair"


class CorrectionTokenKind(str, Enum):
    SELF_CORRECTION = "self_correction"
    VERIFICATION = "verification"
    BACKTRACKING = "backtracking"


class TemporalStageKind(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass(frozen=True)
class KDMethodSpec:
    method: KDMethod
    on_policy: bool
    teacher_required: bool
    self_teacher: bool
    temporal_curriculum: bool
    divergence: str | None
    control_arm: bool

    def __post_init__(self) -> None:
        allowed_divergences = {None, "forward_kl", "reverse_kl", "jsd"}
        if self.divergence not in allowed_divergences:
            raise V10ContractError("unsupported distillation divergence")
        if self.method is KDMethod.NO_KD:
            if self.teacher_required or self.divergence is not None or not self.control_arm:
                raise V10ContractError("no-KD must remain a teacher-free control")
        elif not self.teacher_required:
            raise V10ContractError("every KD method requires a frozen teacher identity")
        if self.method is KDMethod.TCOD and not (
            self.on_policy and self.temporal_curriculum
        ):
            raise V10ContractError("TCOD requires on-policy temporal curriculum")
        if self.method is KDMethod.OPSD and not (
            self.on_policy and self.self_teacher
        ):
            raise V10ContractError("OPSD requires on-policy self-distillation")


def default_method_specs() -> tuple[KDMethodSpec, ...]:
    return (
        KDMethodSpec(KDMethod.GKD, True, True, False, False, "jsd", True),
        KDMethodSpec(
            KDMethod.OFF_POLICY_KD,
            False,
            True,
            False,
            False,
            "forward_kl",
            True,
        ),
        KDMethodSpec(
            KDMethod.ON_POLICY_KD,
            True,
            True,
            False,
            False,
            "reverse_kl",
            False,
        ),
        KDMethodSpec(KDMethod.OPSD, True, True, True, False, "reverse_kl", False),
        KDMethodSpec(KDMethod.SDFT, False, True, True, False, "forward_kl", False),
        KDMethodSpec(KDMethod.TCOD, True, True, False, True, "reverse_kl", False),
        KDMethodSpec(KDMethod.CAOPD, True, True, False, False, "jsd", False),
        KDMethodSpec(KDMethod.NO_KD, False, False, False, False, None, True),
    )


@dataclass(frozen=True)
class PrivilegedSignalSpec:
    kind: PrivilegedKind
    artifact_sha256: str
    source_locator: str
    training_only: bool = True

    def __post_init__(self) -> None:
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        if not self.source_locator.strip() or not self.training_only:
            raise V10ContractError("privileged signals must be located and training-only")


@dataclass(frozen=True)
class DeploymentInputContract:
    deployment_fields: tuple[str, ...]
    privileged_fields: tuple[str, ...]
    hidden_reasoning_persisted: bool = False

    def __post_init__(self) -> None:
        if not self.deployment_fields or not self.privileged_fields:
            raise V10ContractError("deployment and privileged fields are required")
        if set(self.deployment_fields) & set(self.privileged_fields):
            raise V10ContractError("privileged data leaked into deployment input")
        if self.hidden_reasoning_persisted:
            raise V10ContractError("hidden reasoning cannot be a distillation artifact")


def default_deployment_contract() -> DeploymentInputContract:
    return DeploymentInputContract(
        deployment_fields=(
            "user_request",
            "licensed_assets",
            "visible_tool_observations",
            "campaign_state",
        ),
        privileged_fields=tuple(kind.value for kind in PrivilegedKind),
    )


@dataclass(frozen=True)
class RolloutContract:
    rollout_id: str
    student_revision: str
    teacher_revision: str
    deployment_input_sha256: str
    teacher_evaluation_sha256: str
    student_generated: bool
    teacher_evaluates_student_rollout: bool
    hidden_reasoning_persisted: bool
    output_rights_approved: bool

    def __post_init__(self) -> None:
        if not self.rollout_id.strip():
            raise V10ContractError("rollout identity is required")
        if not self.student_revision.strip() or not self.teacher_revision.strip():
            raise V10ContractError("teacher and student revisions must be frozen")
        _require_sha256(self.deployment_input_sha256, "deployment_input_sha256")
        _require_sha256(self.teacher_evaluation_sha256, "teacher_evaluation_sha256")
        if not self.student_generated or not self.teacher_evaluates_student_rollout:
            raise V10ContractError("on-policy rollout must be student-generated and teacher-evaluated")
        if self.hidden_reasoning_persisted:
            raise V10ContractError("hidden reasoning cannot be persisted")
        if not self.output_rights_approved:
            raise V10ContractError("teacher output rights must be approved before training")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


@dataclass(frozen=True)
class DivergenceDiagnostics:
    forward_kl: float
    reverse_kl: float
    jsd: float
    top_k_overlap: float
    token_advantage: float
    fork_entropy: float

    def __post_init__(self) -> None:
        for field in ("forward_kl", "reverse_kl", "jsd"):
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0:
                raise V10ContractError(f"{field} must be finite and non-negative")
        for field in ("top_k_overlap", "fork_entropy"):
            value = getattr(self, field)
            if not 0 <= value <= 1:
                raise V10ContractError(f"{field} must be in the unit interval")
        if not -1 <= self.token_advantage <= 1:
            raise V10ContractError("token advantage must be in the signed unit interval")


def compute_divergence_diagnostics(
    teacher: Sequence[float],
    student: Sequence[float],
    *,
    target_index: int,
    top_k: int = 2,
) -> DivergenceDiagnostics:
    _require_probability_vector(teacher, "teacher")
    _require_probability_vector(student, "student")
    if len(teacher) != len(student):
        raise V10ContractError("teacher and student vocabularies must match")
    if not 0 <= target_index < len(teacher):
        raise V10ContractError("target token index is invalid")
    if not 1 <= top_k <= len(teacher):
        raise V10ContractError("top_k is invalid")
    forward = sum(p * math.log(p / q) for p, q in zip(teacher, student))
    reverse = sum(q * math.log(q / p) for p, q in zip(teacher, student))
    midpoint = tuple((p + q) / 2 for p, q in zip(teacher, student))
    jsd = 0.5 * sum(
        p * math.log(p / m) + q * math.log(q / m)
        for p, q, m in zip(teacher, student, midpoint)
    )
    teacher_top = set(sorted(range(len(teacher)), key=teacher.__getitem__, reverse=True)[:top_k])
    student_top = set(sorted(range(len(student)), key=student.__getitem__, reverse=True)[:top_k])
    overlap = len(teacher_top & student_top) / len(teacher_top | student_top)
    entropy = -sum(p * math.log(p) for p in teacher) / math.log(len(teacher))
    return DivergenceDiagnostics(
        forward_kl=forward,
        reverse_kl=reverse,
        jsd=jsd,
        top_k_overlap=overlap,
        token_advantage=teacher[target_index] - student[target_index],
        fork_entropy=entropy,
    )


@dataclass(frozen=True)
class CorrectionProtectionPolicy:
    minimum_retention: Mapping[CorrectionTokenKind, float]
    style_token_kl_clip: float
    pointwise_kl_clip: float

    def __post_init__(self) -> None:
        if set(self.minimum_retention) != set(CorrectionTokenKind):
            raise V10ContractError("all correction-token classes require retention gates")
        if any(not 0 < value <= 1 for value in self.minimum_retention.values()):
            raise V10ContractError("correction retention gates must be probabilities")
        if not 0 < self.style_token_kl_clip <= self.pointwise_kl_clip:
            raise V10ContractError("style KL clip must be positive and no looser than pointwise KL")


def default_protection_policy() -> CorrectionProtectionPolicy:
    return CorrectionProtectionPolicy(
        minimum_retention={kind: 0.98 for kind in CorrectionTokenKind},
        style_token_kl_clip=0.10,
        pointwise_kl_clip=0.20,
    )


def clip_pointwise_kl(
    values: Sequence[float],
    *,
    style_mask: Sequence[bool],
    policy: CorrectionProtectionPolicy | None = None,
) -> tuple[float, ...]:
    gate = policy or default_protection_policy()
    if len(values) != len(style_mask):
        raise V10ContractError("KL values and style mask must align")
    clipped = []
    for value, is_style in zip(values, style_mask):
        if not math.isfinite(value):
            raise V10ContractError("pointwise KL must be finite")
        limit = gate.style_token_kl_clip if is_style else gate.pointwise_kl_clip
        clipped.append(max(-limit, min(limit, value)))
    return tuple(clipped)


@dataclass(frozen=True)
class TemporalKDStage:
    order: int
    kind: TemporalStageKind
    maximum_turns: int
    requires_prior: tuple[TemporalStageKind, ...]

    def __post_init__(self) -> None:
        if self.order < 0 or self.maximum_turns < 1:
            raise V10ContractError("temporal stage order and turn budget must be positive")


def default_temporal_curriculum() -> tuple[TemporalKDStage, ...]:
    kinds = tuple(TemporalStageKind)
    limits = (4, 16, 64)
    return tuple(
        TemporalKDStage(index, kind, limits[index], kinds[:index])
        for index, kind in enumerate(kinds)
    )


@dataclass(frozen=True)
class ExperimentBudget:
    wall_clock_seconds: int = 7_200
    hard_stop: bool = True
    unapproved_extension_allowed: bool = False

    def __post_init__(self) -> None:
        if self.wall_clock_seconds != 7_200:
            raise V10ContractError("KD experiment budget must be exactly two hours")
        if not self.hard_stop or self.unapproved_extension_allowed:
            raise V10ContractError("KD budget must stop hard without silent extension")


@dataclass(frozen=True)
class MonitoringThresholds:
    maximum_trajectory_kl: float = 0.25
    minimum_top_k_overlap: float = 0.15
    maximum_top_k_overlap: float = 0.98
    minimum_teacher_information_gain: float = 0.02
    maximum_privileged_divergence: float = 0.20
    maximum_overconfidence_rate: float = 0.05
    minimum_verification_retention: float = 0.98
    minimum_backtracking_retention: float = 0.98
    minimum_distinct_n_ratio: float = 0.80


@dataclass(frozen=True)
class MonitoringObservation:
    trajectory_kl: float
    top_k_overlap: float
    teacher_information_gain: float
    privileged_divergence: float
    overconfidence_rate: float
    verification_retention: float
    backtracking_retention: float
    distinct_n_ratio: float


def monitor_failures(
    observation: MonitoringObservation,
    thresholds: MonitoringThresholds | None = None,
) -> tuple[str, ...]:
    gate = thresholds or MonitoringThresholds()
    failures = []
    if observation.trajectory_kl > gate.maximum_trajectory_kl:
        failures.append("trajectory_kl_explosion")
    if not gate.minimum_top_k_overlap <= observation.top_k_overlap <= gate.maximum_top_k_overlap:
        failures.append("teacher_student_mismatch")
    if observation.privileged_divergence > gate.maximum_privileged_divergence:
        failures.append("teacher_student_mismatch")
    if observation.teacher_information_gain < gate.minimum_teacher_information_gain:
        failures.append("teacher_adds_no_new_knowledge")
    if observation.overconfidence_rate > gate.maximum_overconfidence_rate:
        failures.append("student_overconfidence")
    if observation.verification_retention < gate.minimum_verification_retention:
        failures.append("verification_behavior_reduced")
    if observation.backtracking_retention < gate.minimum_backtracking_retention:
        failures.append("backtracking_behavior_reduced")
    if observation.distinct_n_ratio < gate.minimum_distinct_n_ratio:
        failures.append("diversity_collapse")
    return tuple(dict.fromkeys(failures))


@dataclass(frozen=True)
class FrozenRevisionPair:
    teacher_revision: str
    student_revision: str

    def __post_init__(self) -> None:
        if not self.teacher_revision.strip() or not self.student_revision.strip():
            raise V10ContractError("teacher and student revisions are mandatory")


@dataclass(frozen=True)
class MethodRunReceipt:
    method: KDMethod
    revision_pair: FrozenRevisionPair
    observed_run: bool
    rollout_sha256: str | None
    diagnostics_sha256: str | None
    failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.observed_run:
            if self.rollout_sha256 is None or self.diagnostics_sha256 is None:
                raise V10ContractError("observed KD run needs rollout and diagnostics artifacts")
            _require_sha256(self.rollout_sha256, "rollout_sha256")
            _require_sha256(self.diagnostics_sha256, "diagnostics_sha256")
        elif self.rollout_sha256 is not None or self.diagnostics_sha256 is not None:
            raise V10ContractError("unobserved KD run cannot carry runtime artifact hashes")


def promotion_eligible(receipt: MethodRunReceipt) -> bool:
    return receipt.observed_run and not receipt.failures


def planned_distillation_card(
    methods: Sequence[KDMethodSpec],
    revision_pair: FrozenRevisionPair,
) -> dict:
    payload = {
        "schema": "ProofLaunchOnPolicyDistillationCardV1",
        "method_matrix_sha256": stable_sha256([asdict(item) for item in methods]),
        "teacher_revision": revision_pair.teacher_revision,
        "student_revision": revision_pair.student_revision,
        "training_observed": False,
        "token_efficiency": None,
        "capability_gain": None,
        "capability_retention": None,
        "calibration_error": None,
        "long_trajectory_success": None,
        "rollout_artifact": None,
        "kl_diagnostics_artifact": None,
        "negative_experiments": None,
        "selected_adapter": None,
        "promotion_eligible": False,
        "truth_boundary": "Executable KD method, diagnostic, protection, curriculum and elimination contract only; no KD run or adapter is claimed.",
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload
