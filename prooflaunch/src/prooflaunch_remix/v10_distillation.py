from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .v10_contracts import V10ContractError


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit_interval(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise V10ContractError(f"{field_name} must be between 0 and 1")


def _require_signed_unit_interval(value: float, field_name: str) -> None:
    if not -1.0 <= value <= 1.0:
        raise V10ContractError(f"{field_name} must be between -1 and 1")


class DistillationSignalKind(str, Enum):
    TOKEN = "token"
    FEATURE = "feature"
    REWARD = "reward"
    TRAJECTORY = "trajectory"
    REGION = "region"
    WORKFLOW = "workflow"
    UNCERTAINTY = "uncertainty"


class OutputRightsStatus(str, Enum):
    APPROVED = "approved"
    REVIEW_REQUIRED = "rights_review_required"
    PROHIBITED = "prohibited"


class DistillationAdmissionStatus(str, Enum):
    ADMIT = "admit"
    HOLD = "hold"


@dataclass(frozen=True)
class FrozenModelRef:
    provider: str
    model_id: str
    revision: str
    revision_verified: bool
    license_id: str

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model_id.strip():
            raise V10ContractError("provider and model_id are required")
        if not self.revision.strip():
            raise V10ContractError("model revision is required")
        if not self.license_id.strip():
            raise V10ContractError("model license_id is required")


@dataclass(frozen=True)
class DistillationSignal:
    kind: DistillationSignalKind
    artifact_sha256: str
    source_locator: str
    sample_count: int
    privileged_only: bool = False

    def __post_init__(self) -> None:
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        if not self.source_locator.strip():
            raise V10ContractError("distillation signal needs a source locator")
        if self.sample_count < 1:
            raise V10ContractError("distillation signal sample_count must be positive")


@dataclass(frozen=True)
class TeacherStudentDiagnostics:
    top_k_support_overlap: float
    token_advantage: float
    teacher_information_gain: float
    privileged_context_divergence: float
    calibration_error: float
    student_overconfidence_rate: float
    high_entropy_fork_retention: float
    reconsideration_retention: float
    verification_retention: float
    backtracking_retention: float
    style_token_kl: float

    def __post_init__(self) -> None:
        values = asdict(self)
        _require_signed_unit_interval(
            float(values.pop("token_advantage")),
            "token_advantage",
        )
        for field_name, value in values.items():
            _require_unit_interval(float(value), field_name)


@dataclass(frozen=True)
class DistillationAdmissionPolicy:
    minimum_top_k_support_overlap: float = 0.15
    maximum_top_k_support_overlap: float = 0.98
    minimum_token_advantage: float = 0.01
    minimum_teacher_information_gain: float = 0.02
    maximum_privileged_context_divergence: float = 0.20
    maximum_calibration_error: float = 0.05
    maximum_student_overconfidence_rate: float = 0.05
    minimum_correction_retention: float = 0.98
    maximum_style_token_kl: float = 0.10

    def __post_init__(self) -> None:
        values = asdict(self)
        _require_signed_unit_interval(
            float(values.pop("minimum_token_advantage")),
            "minimum_token_advantage",
        )
        for field_name, value in values.items():
            _require_unit_interval(float(value), field_name)
        if (
            self.minimum_top_k_support_overlap
            >= self.maximum_top_k_support_overlap
        ):
            raise V10ContractError(
                "teacher/student overlap policy needs a non-empty interval"
            )


@dataclass(frozen=True)
class DistillationAdmissionDecision:
    status: DistillationAdmissionStatus
    failures: tuple[str, ...]
    episode_digest: str
    schema: str = "ProofLaunchDistillationAdmissionV1"

    @property
    def admitted(self) -> bool:
        return self.status == DistillationAdmissionStatus.ADMIT


@dataclass(frozen=True)
class DistillationEpisodeV1:
    episode_id: str
    teacher: FrozenModelRef
    student: FrozenModelRef
    privileged_context_sha256: str
    deployment_context_sha256: str
    teacher_response_sha256: str
    source_todo_sha256: str
    signals: tuple[DistillationSignal, ...]
    diagnostics: TeacherStudentDiagnostics
    output_rights_status: OutputRightsStatus
    created_at: str
    hidden_reasoning_persisted: bool = False
    competition_core_eligible: bool = False
    schema: str = "ProofLaunchDistillationEpisodeV1"

    def __post_init__(self) -> None:
        if not self.episode_id.strip():
            raise V10ContractError("distillation episode_id is required")
        for field_name in (
            "privileged_context_sha256",
            "deployment_context_sha256",
            "teacher_response_sha256",
            "source_todo_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        if not self.signals:
            raise V10ContractError("distillation episode needs at least one signal")
        kinds = [signal.kind for signal in self.signals]
        if len(kinds) != len(set(kinds)):
            raise V10ContractError(
                "distillation episode permits one artifact per signal kind"
            )
        if (
            any(signal.privileged_only for signal in self.signals)
            and self.privileged_context_sha256
            == self.deployment_context_sha256
        ):
            raise V10ContractError(
                "privileged signals require a distinct deployment context"
            )
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("created_at must be ISO-8601") from error

    @property
    def digest(self) -> str:
        payload: dict[str, Any] = {
            **asdict(self),
            "output_rights_status": self.output_rights_status.value,
            "signals": [
                {
                    **asdict(signal),
                    "kind": signal.kind.value,
                }
                for signal in self.signals
            ],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def evaluate(
        self,
        policy: DistillationAdmissionPolicy | None = None,
    ) -> DistillationAdmissionDecision:
        gate = policy or DistillationAdmissionPolicy()
        failures: list[str] = []
        if not self.teacher.revision_verified:
            failures.append("teacher revision is not verified")
        if not self.student.revision_verified:
            failures.append("student revision is not verified")
        if self.output_rights_status != OutputRightsStatus.APPROVED:
            failures.append(
                f"output rights are {self.output_rights_status.value}"
            )
        if self.hidden_reasoning_persisted:
            failures.append("hidden reasoning must not be persisted")
        if self.competition_core_eligible:
            failures.append(
                "external distillation episode cannot be competition-core evidence"
            )

        diagnostics = self.diagnostics
        if (
            diagnostics.top_k_support_overlap
            < gate.minimum_top_k_support_overlap
        ):
            failures.append("teacher/student top-k support overlap is too low")
        if (
            diagnostics.top_k_support_overlap
            > gate.maximum_top_k_support_overlap
        ):
            failures.append(
                "teacher adds insufficiently distinct support over the student"
            )
        if (
            diagnostics.teacher_information_gain
            < gate.minimum_teacher_information_gain
        ):
            failures.append("teacher information gain is below threshold")
        if diagnostics.token_advantage < gate.minimum_token_advantage:
            failures.append("teacher token advantage is below threshold")
        if (
            diagnostics.privileged_context_divergence
            > gate.maximum_privileged_context_divergence
        ):
            failures.append(
                "privileged/deployment context divergence exceeds threshold"
            )
        if diagnostics.calibration_error > gate.maximum_calibration_error:
            failures.append("calibration error exceeds threshold")
        if (
            diagnostics.student_overconfidence_rate
            > gate.maximum_student_overconfidence_rate
        ):
            failures.append("student overconfidence exceeds threshold")
        correction_metrics = {
            "high-entropy fork": diagnostics.high_entropy_fork_retention,
            "reconsideration": diagnostics.reconsideration_retention,
            "verification": diagnostics.verification_retention,
            "backtracking": diagnostics.backtracking_retention,
        }
        for metric, value in correction_metrics.items():
            if value < gate.minimum_correction_retention:
                failures.append(f"{metric} retention regressed")
        if diagnostics.style_token_kl > gate.maximum_style_token_kl:
            failures.append("style-token KL exceeds the clipping gate")

        return DistillationAdmissionDecision(
            status=(
                DistillationAdmissionStatus.HOLD
                if failures
                else DistillationAdmissionStatus.ADMIT
            ),
            failures=tuple(failures),
            episode_digest=self.digest,
        )


# Canonical product-contract name used by the single-port API and Workstream 24.
# The V1 suffix remains available for compatibility with the training modules.
DistillationEpisode = DistillationEpisodeV1
