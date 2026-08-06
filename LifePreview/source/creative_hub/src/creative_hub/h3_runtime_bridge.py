"""Bounded H3 attempt, QC, repair, and deterministic selection controller."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Protocol
from uuid import UUID

from shared_contracts import (
    H3AttemptSelectionV1,
    H3CandidateScoreV1,
    select_best_h3_attempt,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_EXECUTION_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_MAX_LEDGER_ENTRIES = 10_000
_QC_POLICY_REVISION = "h3.selection.v1"


def _validate_datetime(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")


def _validate_execution_key(value: str) -> None:
    if type(value) is not str or _EXECUTION_KEY.fullmatch(value) is None:
        raise ValueError("H3 execution key is invalid")


def _validate_identifiers(
    value: tuple[str, ...],
    label: str,
    *,
    minimum: int,
) -> None:
    if type(value) is not tuple or not minimum <= len(value) <= 100:
        raise ValueError(f"{label} count is invalid")
    if any(type(item) is not str or _IDENTIFIER.fullmatch(item) is None for item in value):
        raise ValueError(f"{label} contains an invalid identifier")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")


@dataclass(frozen=True, slots=True)
class H3GeneratedAttempt:
    sequence_id: UUID
    execution_key: str
    attempt_ordinal: int
    artifact_digest: str
    qc_evidence_ids: tuple[str, ...]
    generated_at: datetime
    repair_trigger_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.sequence_id) is not UUID:
            raise ValueError("H3 attempt sequence ID is invalid")
        _validate_execution_key(self.execution_key)
        if type(self.attempt_ordinal) is not int or self.attempt_ordinal not in (0, 1):
            raise ValueError("H3 attempt ordinal must be 0 or 1")
        if type(self.artifact_digest) is not str or _SHA256.fullmatch(
            self.artifact_digest
        ) is None:
            raise ValueError("H3 attempt artifact digest is invalid")
        _validate_identifiers(self.qc_evidence_ids, "H3 QC evidence IDs", minimum=1)
        _validate_identifiers(
            self.repair_trigger_codes,
            "H3 repair trigger codes",
            minimum=0,
        )
        _validate_datetime(self.generated_at, "H3 attempt generation time")
        if self.attempt_ordinal == 0 and self.repair_trigger_codes:
            raise ValueError("initial H3 attempt cannot have repair trigger codes")
        if self.attempt_ordinal == 1 and not self.repair_trigger_codes:
            raise ValueError("repair H3 attempt requires trigger codes")


@dataclass(frozen=True, slots=True)
class H3AttemptQCMetrics:
    attempt_ordinal: int
    artifact_digest: str
    media_integrity: float
    identity_and_semantics: float
    technical_quality: float
    aesthetic_quality: float
    exception_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.attempt_ordinal) is not int or self.attempt_ordinal not in (0, 1):
            raise ValueError("H3 QC attempt ordinal must be 0 or 1")
        if type(self.artifact_digest) is not str or _SHA256.fullmatch(
            self.artifact_digest
        ) is None:
            raise ValueError("H3 QC artifact digest is invalid")
        scores = (
            self.media_integrity,
            self.identity_and_semantics,
            self.technical_quality,
            self.aesthetic_quality,
        )
        if any(
            type(score) is not float or not math.isfinite(score) or not 0.0 <= score <= 1.0
            for score in scores
        ):
            raise ValueError("H3 QC scores must be finite floats between 0 and 1")
        _validate_identifiers(self.exception_codes, "H3 QC exception codes", minimum=0)


@dataclass(frozen=True, slots=True)
class H3SequenceExecutionResult:
    sequence_id: UUID
    execution_key: str
    attempts: tuple[H3GeneratedAttempt, ...]
    selection: H3AttemptSelectionV1
    delivery_allowed: bool = field(default=True, init=False)
    failed_final: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.sequence_id) is not UUID:
            raise ValueError("H3 result sequence ID is invalid")
        _validate_execution_key(self.execution_key)
        if (
            type(self.attempts) is not tuple
            or len(self.attempts) not in (1, 2)
            or any(type(attempt) is not H3GeneratedAttempt for attempt in self.attempts)
        ):
            raise ValueError("H3 result must contain one or two strict attempts")
        expected_ordinals = (0,) if len(self.attempts) == 1 else (0, 1)
        if tuple(attempt.attempt_ordinal for attempt in self.attempts) != expected_ordinals:
            raise ValueError("H3 result attempt order is invalid")
        if any(
            attempt.sequence_id != self.sequence_id
            or attempt.execution_key != self.execution_key
            for attempt in self.attempts
        ):
            raise ValueError("H3 result attempt authority does not match execution")
        if type(self.selection) is not H3AttemptSelectionV1:
            raise ValueError("H3 result selection is invalid")
        if self.selection.sequence_id != self.sequence_id:
            raise ValueError("H3 selection belongs to another sequence")
        candidate_ordinals = tuple(
            candidate.attempt_ordinal for candidate in self.selection.candidates
        )
        if candidate_ordinals != expected_ordinals:
            raise ValueError("H3 selection candidates do not match generated attempts")
        if len(self.attempts) == 1:
            if self.selection.candidates[0].exception_codes:
                raise ValueError("an exceptional initial H3 attempt requires one repair")
        else:
            initial_exceptions = self.selection.candidates[0].exception_codes
            if not initial_exceptions:
                raise ValueError("a clean initial H3 attempt cannot have a repair")
            if self.attempts[1].repair_trigger_codes != initial_exceptions:
                raise ValueError("H3 repair triggers do not match initial QC exceptions")
            if self.attempts[1].generated_at < self.attempts[0].generated_at:
                raise ValueError("H3 repair cannot precede the initial attempt")
        if any(
            attempt.generated_at > self.selection.selected_at
            for attempt in self.attempts
        ):
            raise ValueError("H3 selection cannot precede generation")


class H3AttemptGenerator(Protocol):
    def generate(
        self,
        *,
        sequence_id: UUID,
        execution_key: str,
        attempt_ordinal: int,
        repair_trigger_codes: tuple[str, ...],
    ) -> H3GeneratedAttempt: ...


class H3AttemptQCEvaluator(Protocol):
    def evaluate(self, attempt: H3GeneratedAttempt) -> H3AttemptQCMetrics: ...


class H3ExecutionLedger(Protocol):
    def get_or_generate_attempt(
        self,
        *,
        execution_key: str,
        sequence_id: UUID,
        selected_at: datetime,
        attempt_ordinal: int,
        repair_trigger_codes: tuple[str, ...],
        generate: Callable[[], H3GeneratedAttempt],
    ) -> H3GeneratedAttempt: ...

    def execute_once(
        self,
        *,
        execution_key: str,
        sequence_id: UUID,
        selected_at: datetime,
        execute: Callable[[], H3SequenceExecutionResult],
    ) -> H3SequenceExecutionResult: ...


class InMemoryH3ExecutionLedger:
    """Bounded atomic replay ledger for tests and one-process deployments."""

    __slots__ = ("_attempts", "_authorities", "_entries", "_lock", "_max_entries")

    def __init__(self, *, max_entries: int = 1_024) -> None:
        if (
            type(max_entries) is not int
            or max_entries < 1
            or max_entries > _MAX_LEDGER_ENTRIES
        ):
            raise ValueError("H3 execution ledger bound is invalid")
        self._max_entries = max_entries
        self._authorities: dict[str, tuple[UUID, datetime]] = {}
        self._attempts: dict[tuple[str, int], H3GeneratedAttempt] = {}
        self._entries: dict[str, H3SequenceExecutionResult] = {}
        self._lock = RLock()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._authorities)

    def get(self, execution_key: str) -> H3SequenceExecutionResult | None:
        _validate_execution_key(execution_key)
        with self._lock:
            return self._entries.get(execution_key)

    def _bind_authority(
        self,
        *,
        execution_key: str,
        sequence_id: UUID,
        selected_at: datetime,
    ) -> None:
        authority = (sequence_id, selected_at)
        existing = self._authorities.get(execution_key)
        if existing is not None:
            if existing != authority:
                raise ValueError("H3 execution key was reused with different authority")
            return
        if len(self._authorities) >= self._max_entries:
            raise OverflowError("H3 execution ledger is full")
        self._authorities[execution_key] = authority

    def get_or_generate_attempt(
        self,
        *,
        execution_key: str,
        sequence_id: UUID,
        selected_at: datetime,
        attempt_ordinal: int,
        repair_trigger_codes: tuple[str, ...],
        generate: Callable[[], H3GeneratedAttempt],
    ) -> H3GeneratedAttempt:
        _validate_execution_key(execution_key)
        if type(sequence_id) is not UUID:
            raise ValueError("H3 sequence ID is invalid")
        _validate_datetime(selected_at, "H3 selection time")
        if type(attempt_ordinal) is not int or attempt_ordinal not in (0, 1):
            raise ValueError("H3 attempt ordinal must be 0 or 1")
        _validate_identifiers(
            repair_trigger_codes,
            "H3 repair trigger codes",
            minimum=0,
        )
        if (attempt_ordinal == 0) != (not repair_trigger_codes):
            raise ValueError("H3 attempt repair authority is invalid")
        if not callable(generate):
            raise TypeError("H3 attempt factory is invalid")
        with self._lock:
            self._bind_authority(
                execution_key=execution_key,
                sequence_id=sequence_id,
                selected_at=selected_at,
            )
            key = (execution_key, attempt_ordinal)
            existing = self._attempts.get(key)
            if existing is not None:
                if (
                    existing.sequence_id != sequence_id
                    or existing.execution_key != execution_key
                    or existing.attempt_ordinal != attempt_ordinal
                    or existing.repair_trigger_codes != repair_trigger_codes
                ):
                    raise ValueError("persisted H3 attempt authority conflicts")
                return existing
            attempt = generate()
            if type(attempt) is not H3GeneratedAttempt:
                raise TypeError("H3 attempt factory returned an invalid attempt")
            if (
                attempt.sequence_id != sequence_id
                or attempt.execution_key != execution_key
                or attempt.attempt_ordinal != attempt_ordinal
                or attempt.repair_trigger_codes != repair_trigger_codes
            ):
                raise ValueError("generated H3 attempt authority conflicts")
            self._attempts[key] = attempt
            return attempt

    def execute_once(
        self,
        *,
        execution_key: str,
        sequence_id: UUID,
        selected_at: datetime,
        execute: Callable[[], H3SequenceExecutionResult],
    ) -> H3SequenceExecutionResult:
        _validate_execution_key(execution_key)
        if type(sequence_id) is not UUID:
            raise ValueError("H3 sequence ID is invalid")
        _validate_datetime(selected_at, "H3 selection time")
        if not callable(execute):
            raise TypeError("H3 execution factory is invalid")
        with self._lock:
            self._bind_authority(
                execution_key=execution_key,
                sequence_id=sequence_id,
                selected_at=selected_at,
            )
            existing = self._entries.get(execution_key)
            if existing is not None:
                return existing
            result = execute()
            if type(result) is not H3SequenceExecutionResult:
                raise TypeError("H3 execution factory returned an invalid result")
            if (
                result.execution_key != execution_key
                or result.sequence_id != sequence_id
                or result.selection.selected_at != selected_at
            ):
                raise ValueError("H3 execution result does not match ledger authority")
            self._entries[execution_key] = result
            return result


class H3SequenceController:
    __slots__ = ("generator", "ledger", "qc_evaluator")

    def __init__(
        self,
        *,
        generator: H3AttemptGenerator,
        qc_evaluator: H3AttemptQCEvaluator,
        ledger: H3ExecutionLedger,
    ) -> None:
        if not callable(getattr(generator, "generate", None)):
            raise TypeError("H3 attempt generator is invalid")
        if not callable(getattr(qc_evaluator, "evaluate", None)):
            raise TypeError("H3 QC evaluator is invalid")
        if not callable(getattr(ledger, "execute_once", None)):
            raise TypeError("H3 execution ledger is invalid")
        if not callable(getattr(ledger, "get_or_generate_attempt", None)):
            raise TypeError("H3 execution ledger cannot persist attempts")
        self.generator = generator
        self.qc_evaluator = qc_evaluator
        self.ledger = ledger

    def execute(
        self,
        *,
        sequence_id: UUID,
        execution_key: str,
        selected_at: datetime,
    ) -> H3SequenceExecutionResult:
        if type(sequence_id) is not UUID:
            raise ValueError("H3 sequence ID is invalid")
        _validate_execution_key(execution_key)
        _validate_datetime(selected_at, "H3 selection time")

        def execute_new() -> H3SequenceExecutionResult:
            attempts: list[H3GeneratedAttempt] = []
            candidates: list[H3CandidateScoreV1] = []

            initial = self._generate(
                sequence_id=sequence_id,
                execution_key=execution_key,
                selected_at=selected_at,
                attempt_ordinal=0,
                repair_trigger_codes=(),
            )
            initial_qc = self._evaluate(initial)
            attempts.append(initial)
            candidates.append(self._candidate(sequence_id, initial, initial_qc))

            if initial_qc.exception_codes:
                repair = self._generate(
                    sequence_id=sequence_id,
                    execution_key=execution_key,
                    selected_at=selected_at,
                    attempt_ordinal=1,
                    repair_trigger_codes=initial_qc.exception_codes,
                )
                if repair.generated_at < initial.generated_at:
                    raise ValueError("H3 repair cannot precede the initial attempt")
                repair_qc = self._evaluate(repair)
                attempts.append(repair)
                candidates.append(self._candidate(sequence_id, repair, repair_qc))

            reason = (
                "initial attempt passed QC without exceptions"
                if len(candidates) == 1
                else "best QC candidate selected after one repair attempt"
            )
            selection = select_best_h3_attempt(
                candidates=tuple(candidates),
                sequence_id=sequence_id,
                qc_policy_revision=_QC_POLICY_REVISION,
                selected_at=selected_at,
                selection_reason=reason,
            )
            return H3SequenceExecutionResult(
                sequence_id=sequence_id,
                execution_key=execution_key,
                attempts=tuple(attempts),
                selection=selection,
            )

        return self.ledger.execute_once(
            execution_key=execution_key,
            sequence_id=sequence_id,
            selected_at=selected_at,
            execute=execute_new,
        )

    def _generate(
        self,
        *,
        sequence_id: UUID,
        execution_key: str,
        selected_at: datetime,
        attempt_ordinal: int,
        repair_trigger_codes: tuple[str, ...],
    ) -> H3GeneratedAttempt:
        def generate() -> H3GeneratedAttempt:
            attempt = self.generator.generate(
                sequence_id=sequence_id,
                execution_key=execution_key,
                attempt_ordinal=attempt_ordinal,
                repair_trigger_codes=repair_trigger_codes,
            )
            if type(attempt) is not H3GeneratedAttempt:
                raise TypeError("H3 generator returned an invalid attempt")
            if (
                attempt.sequence_id != sequence_id
                or attempt.execution_key != execution_key
                or attempt.attempt_ordinal != attempt_ordinal
                or attempt.repair_trigger_codes != repair_trigger_codes
            ):
                raise ValueError("H3 generator returned an authority-mismatched attempt")
            return attempt

        return self.ledger.get_or_generate_attempt(
            execution_key=execution_key,
            sequence_id=sequence_id,
            selected_at=selected_at,
            attempt_ordinal=attempt_ordinal,
            repair_trigger_codes=repair_trigger_codes,
            generate=generate,
        )

    def _evaluate(self, attempt: H3GeneratedAttempt) -> H3AttemptQCMetrics:
        metrics = self.qc_evaluator.evaluate(attempt)
        if type(metrics) is not H3AttemptQCMetrics:
            raise TypeError("H3 QC evaluator returned invalid metrics")
        if (
            metrics.attempt_ordinal != attempt.attempt_ordinal
            or metrics.artifact_digest != attempt.artifact_digest
        ):
            raise ValueError("H3 QC metrics do not match attempt authority")
        return metrics

    @staticmethod
    def _candidate(
        sequence_id: UUID,
        attempt: H3GeneratedAttempt,
        metrics: H3AttemptQCMetrics,
    ) -> H3CandidateScoreV1:
        return H3CandidateScoreV1(
            sequence_id=sequence_id,
            attempt_ordinal=metrics.attempt_ordinal,
            media_integrity=metrics.media_integrity,
            identity_and_semantics=metrics.identity_and_semantics,
            technical_quality=metrics.technical_quality,
            aesthetic_quality=metrics.aesthetic_quality,
            exception_codes=metrics.exception_codes,
        )


__all__ = [
    "H3AttemptGenerator",
    "H3AttemptQCEvaluator",
    "H3AttemptQCMetrics",
    "H3ExecutionLedger",
    "H3GeneratedAttempt",
    "H3SequenceController",
    "H3SequenceExecutionResult",
    "InMemoryH3ExecutionLedger",
]
