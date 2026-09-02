"""Backend-neutral reliability guard for explicit model analysis providers."""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Mapping

from .exceptions import (
    AnalysisProviderError,
    ProviderInputError,
    ProviderInternalError,
    ProviderOutputError,
    ProviderTransportError,
)
from .models import AnalysisResult, Event, utc_now
from .skill import SkillContext

if TYPE_CHECKING:
    from .knowledge.context import ContextBuilder
    from .knowledge.models import KnowledgeContext
    from .providers.base import AnalysisProvider

_ANALYSIS_FIELDS = frozenset(AnalysisResult.__dataclass_fields__)
_SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
_RETRYABLE_FAILURES = frozenset(
    {
        "MODEL_CONNECTION_ERROR",
        "MODEL_TIMEOUT",
        "MODEL_UNAVAILABLE",
    }
)


class ValidationStatus(StrEnum):
    """Result of validating one provider response."""

    NOT_VALIDATED = "NOT_VALIDATED"
    VALID = "VALID"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    MISSING_FIELD = "MISSING_FIELD"
    UNSAFE_OUTPUT = "UNSAFE_OUTPUT"


class ModelFailureCode(StrEnum):
    """Stable model failure codes exposed to AlphaNoah callers and audits."""

    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    MODEL_CONNECTION_ERROR = "MODEL_CONNECTION_ERROR"
    MODEL_AUTHENTICATION_ERROR = "MODEL_AUTHENTICATION_ERROR"
    MODEL_INTERNAL_ERROR = "MODEL_INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ReliabilityPolicy:
    """Bound one logical analysis request, including all retry attempts."""

    timeout_seconds: float = 60.0
    max_retry: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 0 < float(self.timeout_seconds) <= 1800
        ):
            raise ValueError(
                "timeout_seconds must be a finite number between 0 and 1800"
            )
        if (
            isinstance(self.max_retry, bool)
            or not isinstance(self.max_retry, int)
            or not 0 <= self.max_retry <= 3
        ):
            raise ValueError("max_retry must be an integer between 0 and 3")


@dataclass(frozen=True, slots=True)
class ModelAuditMetadata:
    """Bounded metadata explaining one model analysis attempt sequence."""

    model_name: str
    provider_name: str
    analysis_timestamp: str
    validation_status: str
    attempt_count: int
    max_retry: int
    prompt_version: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_resolution: str | None = None
    model_digest: str | None = None
    model_failure_code: str | None = None
    source_error_codes: tuple[str, ...] = ()
    knowledge_sources: tuple[str, ...] | None = None
    knowledge_version: str | None = None
    context_count: int | None = None
    knowledge_statuses: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe defensive copy without absent optional fields."""

        result = asdict(self)
        result["source_error_codes"] = list(self.source_error_codes)
        if self.knowledge_sources is not None:
            result["knowledge_sources"] = list(self.knowledge_sources)
        if self.knowledge_statuses is not None:
            result["knowledge_statuses"] = list(self.knowledge_statuses)
        return {
            key: value
            for key, value in result.items()
            if value is not None
        }


class ModelOutputInvalidError(ProviderOutputError):
    """Standardized failure for output rejected by the reliability guard."""

    def __init__(
        self,
        message: str,
        *,
        validation_status: ValidationStatus,
    ):
        super().__init__(
            message,
            code=ModelFailureCode.MODEL_OUTPUT_INVALID.value,
        )
        self.validation_status = validation_status


class AnalysisResultGuard:
    """Strictly validate the existing canonical AnalysisResult contract."""

    def validate(self, candidate: object) -> AnalysisResult:
        """Accept an exact result/mapping without guessing or repairing fields."""

        result = self._coerce_exact_mapping(candidate)
        self._require_text(result.detected_issue, "detected_issue", 500)
        self._require_text(result.decision_type, "decision_type", 100)
        self._require_text(
            result.reasoning_summary, "reasoning_summary", 4_000
        )
        self._require_text(result.model_or_rule, "model_or_rule", 500)
        if (
            not isinstance(result.evidence, list)
            or not 1 <= len(result.evidence) <= 32
        ):
            self._invalid_schema(
                "evidence must contain between 1 and 32 strings."
            )
        for value in result.evidence:
            self._require_text(value, "evidence item", 1_000)
        if (
            isinstance(result.confidence, bool)
            or not isinstance(result.confidence, (int, float))
            or not math.isfinite(float(result.confidence))
            or not 0 <= float(result.confidence) <= 1
        ):
            self._invalid_schema(
                "confidence must be a finite number between 0 and 1."
            )
        if result.requires_human_review is not True:
            raise ModelOutputInvalidError(
                "Model output cannot bypass mandatory human review.",
                validation_status=ValidationStatus.UNSAFE_OUTPUT,
            )
        if (
            not isinstance(result.severity, str)
            or result.severity not in _SEVERITIES
        ):
            self._invalid_schema(
                "severity must be LOW, MEDIUM, HIGH, or CRITICAL."
            )

        return AnalysisResult(
            detected_issue=result.detected_issue,
            decision_type=result.decision_type,
            reasoning_summary=result.reasoning_summary,
            evidence=list(result.evidence),
            model_or_rule=result.model_or_rule,
            confidence=float(result.confidence),
            requires_human_review=True,
            severity=result.severity,
        )

    def _coerce_exact_mapping(self, candidate: object) -> AnalysisResult:
        if isinstance(candidate, AnalysisResult):
            return candidate
        if not isinstance(candidate, Mapping):
            self._invalid_schema(
                "Provider output must be an AnalysisResult or exact mapping."
            )
        keys = frozenset(candidate)
        missing = sorted(_ANALYSIS_FIELDS - keys)
        if missing:
            raise ModelOutputInvalidError(
                "Provider output is missing fields: " + ", ".join(missing),
                validation_status=ValidationStatus.MISSING_FIELD,
            )
        extra = sorted(keys - _ANALYSIS_FIELDS)
        if extra:
            self._invalid_schema(
                "Provider output contains unexpected fields: "
                + ", ".join(extra)
            )
        try:
            return AnalysisResult(**dict(candidate))
        except (TypeError, ValueError) as exc:
            raise ModelOutputInvalidError(
                "Provider output could not be mapped to AnalysisResult.",
                validation_status=ValidationStatus.INVALID_SCHEMA,
            ) from exc

    @staticmethod
    def _require_text(value: object, field: str, maximum: int) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > maximum
            or "\x00" in value
        ):
            AnalysisResultGuard._invalid_schema(
                f"{field} must be a non-empty string of at most "
                f"{maximum} characters."
            )

    @staticmethod
    def _invalid_schema(message: str) -> None:
        raise ModelOutputInvalidError(
            message,
            validation_status=ValidationStatus.INVALID_SCHEMA,
        )


class _HardModelTimeout(Exception):
    """Internal signal when an attempt exceeds the remaining total deadline."""


class ReliableAnalysisProvider:
    """Apply validation, a total deadline, finite retry and audit metadata."""

    def __init__(
        self,
        provider: AnalysisProvider,
        *,
        policy: ReliabilityPolicy | None = None,
        guard: AnalysisResultGuard | None = None,
        model_name: str | None = None,
        provider_name: str | None = None,
        prompt_version: str | None = None,
        skill_version: str | None = None,
        context_builder: ContextBuilder | None = None,
    ):
        self.provider = provider
        self.policy = policy or ReliabilityPolicy()
        self.guard = guard or AnalysisResultGuard()
        self.provider_id = f"reliable:{provider.provider_id}"
        self.model_name = model_name or str(
            getattr(provider, "model", "unknown")
        )
        self.provider_name = provider_name or provider.provider_id.split(
            ":", 1
        )[0]
        self.prompt_version = prompt_version or getattr(
            provider, "prompt_version", None
        )
        self.skill_version = skill_version or getattr(
            provider, "skill_version", None
        )
        self.model_digest = getattr(provider, "model_digest", None)
        if context_builder is not None and not callable(
            getattr(provider, "analyze_with_context", None)
        ):
            raise ValueError(
                "context-aware analysis requires analyze_with_context"
            )
        self.context_builder = context_builder
        self._metadata_lock = threading.Lock()
        self._latest_metadata: ModelAuditMetadata | None = None

    def analyze(self, event: Event) -> AnalysisResult:
        """Run a bounded attempt sequence and return only a guarded result."""

        return self._analyze(event, skill_context=None)

    def analyze_with_skill(
        self,
        event: Event,
        skill_context: SkillContext,
    ) -> AnalysisResult:
        """Run guarded analysis with an explicitly resolved SkillContext."""

        if not isinstance(skill_context, SkillContext):
            raise ProviderInputError(
                "Skill context has an invalid type.",
                code="invalid_skill_context",
            )
        if not callable(
            getattr(self.provider, "analyze_with_contexts", None)
        ):
            raise ProviderInputError(
                "Provider does not support explicit SkillContext.",
                code="skill_context_unsupported",
            )
        return self._analyze(event, skill_context=skill_context)

    def _analyze(
        self,
        event: Event,
        *,
        skill_context: SkillContext | None,
    ) -> AnalysisResult:
        started_at = utc_now()
        deadline = time.monotonic() + float(self.policy.timeout_seconds)
        source_error_codes: list[str] = []
        maximum_attempts = self.policy.max_retry + 1
        knowledge_context: KnowledgeContext | None = None
        context_metadata: dict[str, Any] = {}
        if skill_context is not None:
            from .knowledge.models import KnowledgeContext

            knowledge_context = KnowledgeContext()
            context_metadata.update(skill_context.audit_metadata())
            context_metadata.update(knowledge_context.audit_metadata())
        if self.context_builder is not None:
            try:
                knowledge_context = self.context_builder.build(
                    event,
                    skill_context=skill_context,
                )
                context_metadata.update(knowledge_context.audit_metadata())
            except Exception as exc:
                error = ProviderInternalError(
                    "Knowledge context could not be built.",
                    code=ModelFailureCode.MODEL_INTERNAL_ERROR.value,
                )
                source_error_codes.append("knowledge_context_error")
                self._publish_metadata(
                    started_at,
                    ValidationStatus.NOT_VALIDATED,
                    0,
                    error.code,
                    source_error_codes,
                    context_metadata,
                )
                raise error from exc

        for attempt in range(1, maximum_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = self._timeout_error()
                self._publish_metadata(
                    started_at,
                    ValidationStatus.NOT_VALIDATED,
                    attempt - 1,
                    error.code,
                    source_error_codes,
                    context_metadata,
                )
                raise error
            try:
                candidate = self._call_with_timeout(
                    event,
                    remaining,
                    knowledge_context,
                    skill_context,
                )
                result = self.guard.validate(candidate)
            except _HardModelTimeout:
                error = self._timeout_error()
                source_error_codes.append("hard_deadline")
                self._publish_metadata(
                    started_at,
                    ValidationStatus.NOT_VALIDATED,
                    attempt,
                    error.code,
                    source_error_codes,
                    context_metadata,
                )
                raise error
            except ProviderInputError as exc:
                source_error_codes.append(exc.code)
                self._publish_metadata(
                    started_at,
                    ValidationStatus.NOT_VALIDATED,
                    attempt,
                    None,
                    source_error_codes,
                    context_metadata,
                )
                raise
            except AnalysisProviderError as exc:
                source_error_codes.append(exc.code)
                error, validation_status = self._standardize_failure(exc)
                if (
                    error.code in _RETRYABLE_FAILURES
                    and attempt < maximum_attempts
                    and time.monotonic() < deadline
                ):
                    continue
                self._publish_metadata(
                    started_at,
                    validation_status,
                    attempt,
                    error.code,
                    source_error_codes,
                    context_metadata,
                )
                if error is exc:
                    raise
                raise error from exc
            except Exception as exc:
                error = ProviderInternalError(
                    "Model provider failed internally.",
                    code=ModelFailureCode.MODEL_INTERNAL_ERROR.value,
                )
                source_error_codes.append(type(exc).__name__)
                self._publish_metadata(
                    started_at,
                    ValidationStatus.NOT_VALIDATED,
                    attempt,
                    error.code,
                    source_error_codes,
                    context_metadata,
                )
                raise error from exc

            self._publish_metadata(
                started_at,
                ValidationStatus.VALID,
                attempt,
                None,
                source_error_codes,
                context_metadata,
            )
            return result

        raise AssertionError("bounded provider loop ended unexpectedly")

    def get_audit_metadata(self) -> dict[str, Any]:
        """Return a defensive JSON-safe copy of the latest analysis metadata."""

        with self._metadata_lock:
            if self._latest_metadata is None:
                return {}
            return self._latest_metadata.to_dict()

    def _call_with_timeout(
        self,
        event: Event,
        timeout: float,
        knowledge_context: KnowledgeContext | None,
        skill_context: SkillContext | None,
    ) -> object:
        outcomes: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                if skill_context is not None:
                    result = self.provider.analyze_with_contexts(
                        event,
                        skill_context,
                        knowledge_context,
                    )
                elif knowledge_context is None:
                    result = self.provider.analyze(event)
                else:
                    result = self.provider.analyze_with_context(
                        event,
                        knowledge_context,
                    )
                outcomes.put(("result", result))
            except Exception as exc:
                outcomes.put(("error", exc))

        worker = threading.Thread(
            target=invoke,
            name="alphanoah-model-provider",
            daemon=True,
        )
        worker.start()
        try:
            outcome, value = outcomes.get(timeout=timeout)
        except queue.Empty as exc:
            raise _HardModelTimeout from exc
        if outcome == "error":
            if isinstance(value, Exception):
                raise value
            raise ProviderInternalError(
                "Model provider returned an invalid failure signal.",
                code=ModelFailureCode.MODEL_INTERNAL_ERROR.value,
            )
        return value

    @staticmethod
    def _timeout_error() -> ProviderTransportError:
        return ProviderTransportError(
            "Model analysis exceeded its configured total timeout.",
            code=ModelFailureCode.MODEL_TIMEOUT.value,
        )

    @staticmethod
    def _standardize_failure(
        error: AnalysisProviderError,
    ) -> tuple[AnalysisProviderError, ValidationStatus]:
        if isinstance(error, ModelOutputInvalidError):
            return error, error.validation_status
        if isinstance(error, ProviderOutputError):
            validation_status = (
                ValidationStatus.UNSAFE_OUTPUT
                if error.code == "human_review_required"
                else ValidationStatus.INVALID_SCHEMA
            )
            return (
                ModelOutputInvalidError(
                    "Model output failed structured validation.",
                    validation_status=validation_status,
                ),
                validation_status,
            )
        if isinstance(error, ProviderTransportError):
            if error.code in {
                "timeout",
                ModelFailureCode.MODEL_TIMEOUT.value,
            }:
                code = ModelFailureCode.MODEL_TIMEOUT
                message = "Model analysis timed out."
            elif error.code in {
                "connection_error",
                ModelFailureCode.MODEL_CONNECTION_ERROR.value,
            }:
                code = ModelFailureCode.MODEL_CONNECTION_ERROR
                message = "Model provider connection failed."
            elif error.code in {
                "http_error",
                ModelFailureCode.MODEL_UNAVAILABLE.value,
            }:
                code = ModelFailureCode.MODEL_UNAVAILABLE
                message = "Model provider was unavailable."
            elif error.code in {
                "authentication_error",
                ModelFailureCode.MODEL_AUTHENTICATION_ERROR.value,
            }:
                code = ModelFailureCode.MODEL_AUTHENTICATION_ERROR
                message = "Model provider authentication failed."
            elif error.code == "response_too_large":
                invalid = ModelOutputInvalidError(
                    "Model output exceeded the configured size limit.",
                    validation_status=ValidationStatus.INVALID_SCHEMA,
                )
                return invalid, ValidationStatus.INVALID_SCHEMA
            else:
                internal = ProviderInternalError(
                    "Model provider failed internally.",
                    code=ModelFailureCode.MODEL_INTERNAL_ERROR.value,
                )
                return internal, ValidationStatus.NOT_VALIDATED
            return (
                ProviderTransportError(message, code=code.value),
                ValidationStatus.NOT_VALIDATED,
            )
        return (
            ProviderInternalError(
                "Model provider failed internally.",
                code=ModelFailureCode.MODEL_INTERNAL_ERROR.value,
            ),
            ValidationStatus.NOT_VALIDATED,
        )

    def _publish_metadata(
        self,
        analysis_timestamp: str,
        validation_status: ValidationStatus,
        attempt_count: int,
        model_failure_code: str | None,
        source_error_codes: list[str],
        context_metadata: Mapping[str, Any],
    ) -> None:
        raw_sources = context_metadata.get("knowledge_sources")
        knowledge_sources = (
            tuple(
                source
                for source in raw_sources
                if isinstance(source, str)
            )
            if isinstance(raw_sources, list)
            else None
        )
        knowledge_version = context_metadata.get("knowledge_version")
        context_count = context_metadata.get("context_count")
        raw_statuses = context_metadata.get("knowledge_statuses")
        knowledge_statuses = (
            tuple(
                status
                for status in raw_statuses
                if isinstance(status, str)
            )
            if isinstance(raw_statuses, list)
            else None
        )
        metadata = ModelAuditMetadata(
            model_name=self.model_name,
            provider_name=self.provider_name,
            analysis_timestamp=analysis_timestamp,
            validation_status=validation_status.value,
            attempt_count=attempt_count,
            max_retry=self.policy.max_retry,
            prompt_version=self.prompt_version,
            skill_id=(
                context_metadata.get("skill_id")
                if isinstance(context_metadata.get("skill_id"), str)
                else None
            ),
            skill_version=(
                context_metadata.get("skill_version")
                if isinstance(
                    context_metadata.get("skill_version"),
                    str,
                )
                else self.skill_version
            ),
            skill_resolution=(
                context_metadata.get("skill_resolution")
                if isinstance(
                    context_metadata.get("skill_resolution"),
                    str,
                )
                else None
            ),
            model_digest=self.model_digest,
            model_failure_code=model_failure_code,
            source_error_codes=tuple(source_error_codes),
            knowledge_sources=knowledge_sources,
            knowledge_version=(
                knowledge_version
                if isinstance(knowledge_version, str)
                else None
            ),
            context_count=(
                context_count
                if isinstance(context_count, int)
                and not isinstance(context_count, bool)
                else None
            ),
            knowledge_statuses=knowledge_statuses,
        )
        with self._metadata_lock:
            self._latest_metadata = metadata
