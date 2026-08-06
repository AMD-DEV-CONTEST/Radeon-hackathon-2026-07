"""Privacy-safe result and case contracts for Agent Harness benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class BenchmarkRunStatus(StrEnum):
    COMPLETED = "completed"
    INVALID_SETUP = "invalid_setup"
    RUNTIME_ERROR = "runtime_error"
    MEASUREMENT_ERROR = "measurement_error"


class BenchmarkExecutionMode(StrEnum):
    HEADLESS = "headless"
    HEADED = "headed"


class SemanticVerdict(StrEnum):
    """Meaning of the final user-visible outcome, not runner health."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_EVALUATED = "not_evaluated"


class JudgeStatus(StrEnum):
    """Whether V2 was able to obtain a trustworthy judge response."""

    NOT_REQUESTED = "not_requested"
    NOT_CONFIGURED = "not_configured"
    BLOCKED = "blocked"
    INVALID_SETUP = "invalid_setup"
    PROVIDER_ERROR = "provider_error"
    INVALID_RESPONSE = "invalid_response"
    COMPLETED = "completed"


class JudgeIndependence(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    INDEPENDENT = "independent"
    SAME_MODEL = "same_model"


class BenchmarkInputError(ValueError):
    """A safe, stable case/setup problem suitable for a result report."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OutcomeCheck:
    """One bounded deterministic check in either the semantic or integrity channel."""

    name: str
    passed: bool
    summary: str

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "summary": self.summary}


@dataclass(frozen=True)
class JudgeRubric:
    """Author-controlled scoring vocabulary for one case's judge request."""

    rubric_id: str
    score_dimensions: tuple[str, ...]
    allowed_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class JudgeInput:
    """Case-owned, privacy-reviewed final-product evidence; never persisted."""

    rubric: JudgeRubric
    task_intent: str
    facts: tuple[str, ...]
    artifact_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rubric.rubric_id.strip():
            raise ValueError("judge_rubric_id_required")
        if not self.rubric.score_dimensions:
            raise ValueError("judge_score_dimensions_required")
        if (
            not isinstance(self.task_intent, str)
            or not self.task_intent.strip()
            or len(self.task_intent) > 512
        ):
            raise ValueError("judge_task_intent_required")
        _validate_bounded_strings("judge_facts", self.facts, maximum_items=12)
        _validate_bounded_strings("judge_artifact_evidence", self.artifact_evidence, maximum_items=48)


@dataclass(frozen=True)
class BenchmarkCaseAssessment:
    """Case-owned final-outcome facts after one subject cell settles."""

    semantic_checks: tuple[OutcomeCheck, ...] = ()
    integrity_checks: tuple[OutcomeCheck, ...] = ()
    judge_input: JudgeInput | None = None
    judge_required: bool = False
    terminal_shape: tuple[int, int] | None = None

    @property
    def semantic_checks_passed(self) -> bool:
        return bool(self.semantic_checks) and all(check.passed for check in self.semantic_checks)

    @property
    def integrity_passed(self) -> bool:
        """Whether this case supplied and passed its measurement safeguards."""

        return bool(self.integrity_checks) and all(check.passed for check in self.integrity_checks)


class BenchmarkDatasetAccess(Protocol):
    def get_dataset(self, dataset_id: str) -> Any: ...

    def list_datasets(self) -> list[Any]: ...


class BenchmarkArtifactAccess(Protocol):
    def resolve_uri(self, uri: str) -> Any: ...


class BenchmarkKnowledgeImportAccess(Protocol):
    def import_file(self, source_path: Path, *, timeout: float = 60.0) -> Any: ...


class BenchmarkKnowledgeDerivationAccess(Protocol):
    def status_for_import(self, import_id: str) -> Any: ...


class BenchmarkKnowledgeIndexAccess(Protocol):
    def enqueue_rebuild(self, index_kinds: Any, *, trigger: str) -> str: ...

    def rebuild_now(self, task_id: str) -> Any: ...


@dataclass(frozen=True)
class BenchmarkCasePreparationServices:
    """The narrow production-service seam available before subject timing."""

    knowledge_import: BenchmarkKnowledgeImportAccess
    knowledge_derivation: BenchmarkKnowledgeDerivationAccess
    knowledge_index: BenchmarkKnowledgeIndexAccess


@dataclass(frozen=True)
class BenchmarkCaseServices:
    """The read-only public product services available to a case oracle."""

    datasets: BenchmarkDatasetAccess
    artifacts: BenchmarkArtifactAccess


@dataclass(frozen=True)
class BenchmarkCaseContext:
    """One isolated cell's public state after the submitted turn settles."""

    snapshot: Any | None
    services: BenchmarkCaseServices
    source_state: Any | None
    run_dataset_ids: frozenset[str]
    runtime_home: Path
    settings_unchanged: bool


class BenchmarkCase(Protocol):
    """Small outcome-first contract; the runner never branches on case id.

    A case may additionally define ``prepare(*, services)`` when its isolated
    cell needs public product state before the measured subject turn.
    """

    case_id: str

    def validate_input(self) -> str: ...

    def build_submission(self, *, thread_id: str, fq_model_key: str) -> Any: ...

    def capture_source_state(self, *, snapshot: Any, services: BenchmarkCaseServices) -> Any: ...

    def assess(self, *, context: BenchmarkCaseContext) -> BenchmarkCaseAssessment: ...


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int

    def to_payload(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Measurements attributable to the subject AgentHarness cell only."""

    turn_seconds: float | None = None
    assessment_seconds: float | None = None
    sampling_round_count: int = 0
    usage_reported_primary_response_count: int | None = None
    token_usage: TokenUsage | None = None
    message_counts: dict[str, int] = field(default_factory=dict)
    tool_call_counts_by_name: dict[str, int] = field(default_factory=dict)
    tool_result_counts_by_status: dict[str, int] = field(default_factory=dict)
    provider_retry_count: int = 0
    derived_dataset_count: int = 0
    terminal_shape: tuple[int, int] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "turn_seconds": self.turn_seconds,
            "assessment_seconds": self.assessment_seconds,
            "sampling_round_count": self.sampling_round_count,
            "usage_reported_primary_response_count": self.usage_reported_primary_response_count,
            "token_usage": self.token_usage.to_payload() if self.token_usage is not None else None,
            "message_counts": dict(sorted(self.message_counts.items())),
            "tool_call_counts_by_name": dict(sorted(self.tool_call_counts_by_name.items())),
            "tool_result_counts_by_status": dict(sorted(self.tool_result_counts_by_status.items())),
            "provider_retry_count": self.provider_retry_count,
            "derived_dataset_count": self.derived_dataset_count,
            "terminal_shape": list(self.terminal_shape) if self.terminal_shape is not None else None,
        }


@dataclass(frozen=True)
class JudgeMetrics:
    elapsed_seconds: float | None = None
    token_usage: TokenUsage | None = None
    provider_retry_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "token_usage": self.token_usage.to_payload() if self.token_usage is not None else None,
            "provider_retry_count": self.provider_retry_count,
        }


@dataclass(frozen=True)
class JudgeResult:
    status: JudgeStatus = JudgeStatus.NOT_REQUESTED
    verdict: SemanticVerdict = SemanticVerdict.NOT_EVALUATED
    provider_model: str | None = None
    independence: JudgeIndependence = JudgeIndependence.NOT_APPLICABLE
    scores: dict[str, int] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    summary: str = "judge_not_requested"
    metrics: JudgeMetrics = field(default_factory=JudgeMetrics)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "verdict": self.verdict.value,
            "provider_model": self.provider_model,
            "independence": self.independence.value,
            "scores": dict(sorted(self.scores.items())),
            "reason_codes": list(self.reason_codes),
            "summary": self.summary,
            "metrics": self.metrics.to_payload(),
        }


@dataclass(frozen=True)
class BenchmarkIdentity:
    fixture_sha256: str | None = None
    settings_sha256: str | None = None
    embedding_settings_sha256: str | None = None
    judge_settings_sha256: str | None = None
    repository_commit: str | None = None
    repository_dirty: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "fixture_sha256": self.fixture_sha256,
            "settings_sha256": self.settings_sha256,
            "embedding_settings_sha256": self.embedding_settings_sha256,
            "judge_settings_sha256": self.judge_settings_sha256,
            "repository_commit": self.repository_commit,
            "repository_dirty": self.repository_dirty,
        }


@dataclass(frozen=True)
class AgentHarnessBenchmarkResult:
    case_id: str
    run_id: str
    provider_model: str
    execution_mode: BenchmarkExecutionMode
    run_status: BenchmarkRunStatus
    subject_metrics: BenchmarkMetrics
    semantic_verdict: SemanticVerdict = SemanticVerdict.NOT_EVALUATED
    semantic_checks: tuple[OutcomeCheck, ...] = ()
    integrity_checks: tuple[OutcomeCheck, ...] = ()
    judge: JudgeResult = field(default_factory=JudgeResult)
    identity: BenchmarkIdentity = field(default_factory=BenchmarkIdentity)
    failure_kind: str | None = None
    schema_version: int = 4

    @property
    def integrity_passed(self) -> bool:
        """Whether the completed cell produced a trustworthy measurement."""

        return (
            self.run_status is BenchmarkRunStatus.COMPLETED
            and bool(self.integrity_checks)
            and all(check.passed for check in self.integrity_checks)
        )

    @property
    def outcome_passed(self) -> bool:
        """Compatibility projection: semantic pass only, never integrity state."""

        return self.semantic_verdict is SemanticVerdict.PASS

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "provider_model": self.provider_model,
            "execution_mode": self.execution_mode.value,
            "run_status": self.run_status.value,
            "semantic": {
                "verdict": self.semantic_verdict.value,
                "passed": self.outcome_passed,
                "checks": [check.to_payload() for check in self.semantic_checks],
            },
            "integrity": {
                "passed": self.integrity_passed,
                "checks": [check.to_payload() for check in self.integrity_checks],
            },
            "judge": self.judge.to_payload(),
            "subject_metrics": self.subject_metrics.to_payload(),
            "identity": self.identity.to_payload(),
            "failure_kind": self.failure_kind,
        }


def _validate_bounded_strings(label: str, values: tuple[str, ...], *, maximum_items: int) -> None:
    if len(values) > maximum_items:
        raise ValueError(f"{label}_too_many")
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise ValueError(f"{label}_invalid")
