from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, TypeAlias
from uuid import UUID

from shared_contracts import (
    AtomicArtifactRef,
    OperationStatus,
    ProviderState,
    RetryClass,
    SafeErrorV2,
)


class ErrorMappingError(ValueError):
    """Raised when an immutable exception mapping is malformed or ambiguous."""


class LeaseLostError(RuntimeError):
    """Marker for lease-loss control flow that must bypass SafeError mapping."""


ExceptionTypeRef: TypeAlias = type[BaseException] | str


@dataclass(frozen=True, slots=True)
class ErrorContext:
    """Non-secret facts available while converting an exception to SafeErrorV2."""

    correlation_id: UUID
    provider_state: ProviderState = ProviderState.NOT_APPLICABLE
    evidence_refs: tuple[AtomicArtifactRef, ...] = ()
    outcome_unknown: bool = False
    lease_lost: bool = False


@dataclass(frozen=True, slots=True)
class SafeErrorTemplate:
    """Constant, reviewable public/operator text for one exception class.

    Exception messages, reprs, arguments, and tracebacks are deliberately not
    accepted.  This makes mapping safe for provider responses, paths, tokens,
    prompts, and other values that may appear in an exception.
    """

    error_code: str
    retry_class: RetryClass
    public_message: str
    operator_detail: str
    provider_state: ProviderState | None = None

    def __post_init__(self) -> None:
        # Validate all contract constraints at mapper construction time.
        SafeErrorV2(
            error_code=self.error_code,
            retry_class=self.retry_class,
            public_message=self.public_message,
            operator_detail=self.operator_detail,
            provider_state=self.provider_state or ProviderState.NOT_APPLICABLE,
            correlation_id=UUID(int=0),
        )


DEFAULT_UNKNOWN_ERROR = SafeErrorTemplate(
    error_code="unclassified_failure",
    retry_class=RetryClass.HUMAN_REQUIRED,
    public_message="The operation failed safely.",
    operator_detail="Unclassified exception; inspect protected telemetry by correlation ID.",
)

DEFAULT_OUTCOME_UNKNOWN_ERROR = SafeErrorTemplate(
    error_code="provider_outcome_unknown",
    retry_class=RetryClass.RECONCILE_PROVIDER,
    public_message="The provider outcome is not yet known.",
    operator_detail="Reconcile the persisted provider identity before any new submission.",
    provider_state=ProviderState.OUTCOME_UNKNOWN,
)


class SafeErrorMapper:
    """Immutable, MRO-specific and fail-closed exception mapper."""

    __slots__ = (
        "_lease_loss_types",
        "_outcome_unknown_types",
        "_rules",
        "_unknown",
        "_unknown_outcome",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("SafeErrorMapper is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        rules: Mapping[ExceptionTypeRef, SafeErrorTemplate] | None = None,
        *,
        lease_loss_types: tuple[ExceptionTypeRef, ...] = (LeaseLostError,),
        outcome_unknown_types: tuple[ExceptionTypeRef, ...] = (),
        unknown: SafeErrorTemplate = DEFAULT_UNKNOWN_ERROR,
        unknown_outcome: SafeErrorTemplate = DEFAULT_OUTCOME_UNKNOWN_ERROR,
    ) -> None:
        copied = dict(rules or {})
        for exception_type, template in copied.items():
            if not self._is_exception_type_ref(exception_type):
                raise ErrorMappingError("error mapping keys must be exception types")
            if not isinstance(template, SafeErrorTemplate):
                raise ErrorMappingError(
                    "error mapping values must be constant SafeErrorTemplate objects"
                )
        self._rules = MappingProxyType(copied)
        self._lease_loss_types = self._validate_types(
            lease_loss_types,
            label="lease-loss",
        )
        self._outcome_unknown_types = self._validate_types(
            outcome_unknown_types,
            label="outcome-unknown",
        )
        self._unknown = unknown
        self._unknown_outcome = unknown_outcome

    @staticmethod
    def _is_exception_type_ref(value: object) -> bool:
        if isinstance(value, type):
            return issubclass(value, BaseException)
        if isinstance(value, str):
            module, separator, name = value.partition(":")
            return bool(
                separator
                and module
                and name
                and all(
                    part.isidentifier()
                    for part in (*module.split("."), *name.split("."))
                )
            )
        return False

    @staticmethod
    def _validate_types(
        values: tuple[ExceptionTypeRef, ...],
        *,
        label: str,
    ) -> tuple[ExceptionTypeRef, ...]:
        for value in values:
            if not SafeErrorMapper._is_exception_type_ref(value):
                raise ErrorMappingError(f"{label} values must be exception types")
        if len(values) != len(set(values)):
            raise ErrorMappingError(f"{label} exception types must be unique")
        return tuple(values)

    @property
    def rules(self) -> Mapping[ExceptionTypeRef, SafeErrorTemplate]:
        return self._rules

    @property
    def lease_loss_types(self) -> tuple[ExceptionTypeRef, ...]:
        return self._lease_loss_types

    @property
    def outcome_unknown_types(self) -> tuple[ExceptionTypeRef, ...]:
        return self._outcome_unknown_types

    @staticmethod
    def _qualified_name(value: type[BaseException]) -> str:
        return f"{value.__module__}:{value.__qualname__}"

    @classmethod
    def _matches(
        cls,
        exception: BaseException,
        references: tuple[ExceptionTypeRef, ...],
    ) -> bool:
        concrete_types = tuple(
            reference for reference in references if isinstance(reference, type)
        )
        if concrete_types and isinstance(exception, concrete_types):
            return True
        qualified_mro = {
            cls._qualified_name(exception_type)
            for exception_type in type(exception).__mro__
            if issubclass(exception_type, BaseException)
        }
        return any(
            reference in qualified_mro
            for reference in references
            if isinstance(reference, str)
        )

    def _most_specific_template(
        self,
        exception: BaseException,
    ) -> SafeErrorTemplate | None:
        # The exception's MRO, rather than registration order or a broad
        # isinstance scan, makes selection deterministic and most-specific.
        for exception_type in type(exception).__mro__:
            template = self._rules.get(exception_type)
            if template is None and issubclass(exception_type, BaseException):
                template = self._rules.get(self._qualified_name(exception_type))
            if template is not None:
                return template
        return None

    def map_exception(
        self,
        exception: BaseException,
        context: ErrorContext,
    ) -> SafeErrorV2:
        if context.lease_lost or self._matches(exception, self._lease_loss_types):
            # Lease loss is orchestration control flow.  Converting it to a
            # normal operation failure could let a stale worker publish state.
            raise exception

        template = self._most_specific_template(exception)
        provider_reconciliation_required = context.provider_state in {
            ProviderState.SUBMITTED,
            ProviderState.OUTCOME_UNKNOWN,
        }
        outcome_unknown = (
            context.outcome_unknown
            or context.provider_state is ProviderState.OUTCOME_UNKNOWN
            or self._matches(exception, self._outcome_unknown_types)
        )
        if outcome_unknown or provider_reconciliation_required:
            template = template or self._unknown_outcome
            retry_class = (
                RetryClass.HUMAN_REQUIRED
                if template.retry_class is RetryClass.HUMAN_REQUIRED
                else RetryClass.RECONCILE_PROVIDER
            )
            provider_state = (
                ProviderState.OUTCOME_UNKNOWN
                if outcome_unknown
                else context.provider_state
            )
        else:
            template = template or self._unknown
            retry_class = template.retry_class
            provider_state = template.provider_state or context.provider_state

        return SafeErrorV2(
            error_code=template.error_code,
            retry_class=retry_class,
            public_message=template.public_message,
            operator_detail=template.operator_detail,
            provider_state=provider_state,
            evidence_refs=context.evidence_refs,
            correlation_id=context.correlation_id,
        )

    # A short alias is convenient at exception boundaries.
    map = map_exception


def operation_status_for_error(error: SafeErrorV2) -> OperationStatus:
    """Choose the only safe terminal status for unresolved provider effects."""

    if error.provider_state in {
        ProviderState.SUBMITTED,
        ProviderState.OUTCOME_UNKNOWN,
    }:
        return OperationStatus.OUTCOME_UNKNOWN
    return OperationStatus.FAILED


ErrorMapper = SafeErrorMapper
