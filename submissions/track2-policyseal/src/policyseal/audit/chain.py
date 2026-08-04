from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock

from policyseal.audit.models import (
    AuditAppendResult,
    AuditEvent,
    AuditEventType,
    AuditVerification,
)
from policyseal.audit.sanitizer import AuditPayloadError, sanitize_payload

_GENESIS_HASH = "0" * 64
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_CORE_ID = re.compile(r"^[A-Za-z0-9_.:@\-]{1,200}$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _validate_core_id(name: str, value: str | None) -> None:
    if value is not None and _CORE_ID.fullmatch(value) is None:
        raise AuditPayloadError(f"{name} is not a controlled ID")


class AuditChain:
    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._events: list[AuditEvent] = []
        self._clock = clock
        self._lock = RLock()

    @classmethod
    def in_memory(cls, *, clock: Callable[[], datetime] = _utc_now) -> AuditChain:
        return cls(clock=clock)

    @classmethod
    def restore(
        cls,
        events: tuple[AuditEvent, ...],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> AuditChain:
        chain = cls(clock=clock)
        chain._events.extend(events)
        verification = chain.verify()
        if not verification.valid:
            raise AuditPayloadError("stored audit chain is invalid")
        return chain

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def append(
        self,
        event_type: AuditEventType | str,
        payload: Mapping[str, object],
        *,
        event_id: str | None = None,
        actor: str = "system",
        task_id: str | None = None,
        revision_id: str | None = None,
        policy_sha256: str | None = None,
    ) -> AuditEvent:
        controlled_type, sanitized_payload = sanitize_payload(event_type, payload)
        event_id = event_id or f"audit-{uuid.uuid4().hex}"
        for name, value in (
            ("event_id", event_id),
            ("actor", actor),
            ("task_id", task_id),
            ("revision_id", revision_id),
        ):
            _validate_core_id(name, value)
        if policy_sha256 is not None and _HEX_64.fullmatch(policy_sha256) is None:
            raise AuditPayloadError("policy_sha256 must be a lowercase SHA-256 digest")

        occurred_at = self._clock()
        if occurred_at.tzinfo is None:
            raise AuditPayloadError("audit timestamps must be timezone aware")
        occurred_at = occurred_at.astimezone(UTC)
        with self._lock:
            if any(existing.event_id == event_id for existing in self._events):
                raise AuditPayloadError("audit event IDs must be unique")
            previous_hash = self._events[-1].event_hash if self._events else _GENESIS_HASH
            pending = AuditEvent(
                event_id=event_id,
                event_type=controlled_type,
                occurred_at=occurred_at,
                actor=actor,
                task_id=task_id,
                revision_id=revision_id,
                policy_sha256=policy_sha256,
                payload=sanitized_payload,
                previous_hash=previous_hash,
                event_hash="",
            )
            event = replace(
                pending,
                event_hash=hashlib.sha256(pending.canonical_bytes()).hexdigest(),
            )
            self._events.append(event)
            return event

    def try_append(
        self,
        event_type: AuditEventType | str,
        payload: Mapping[str, object],
        **kwargs: object,
    ) -> AuditAppendResult:
        try:
            event = self.append(event_type, payload, **kwargs)  # type: ignore[arg-type]
        except (AuditPayloadError, TypeError, ValueError) as error:
            return AuditAppendResult(accepted=False, error=type(error).__name__)
        return AuditAppendResult(accepted=True, event=event)

    def verify(self) -> AuditVerification:
        previous_hash = _GENESIS_HASH
        seen_ids: set[str] = set()
        with self._lock:
            for index, event in enumerate(self._events):
                if event.event_id in seen_ids:
                    return AuditVerification(False, index, index, "duplicate_event_id")
                if event.previous_hash != previous_hash:
                    return AuditVerification(False, index, index, "broken_previous_hash")
                expected = hashlib.sha256(event.canonical_bytes()).hexdigest()
                if event.event_hash != expected:
                    return AuditVerification(False, index, index, "event_hash_mismatch")
                seen_ids.add(event.event_id)
                previous_hash = event.event_hash
            return AuditVerification(True, len(self._events))

    def unsafe_replace_payload_for_test(
        self,
        index: int,
        payload: Mapping[str, object],
    ) -> None:
        with self._lock:
            event = self._events[index]
            _, sanitized = sanitize_payload(event.event_type, payload)
            self._events[index] = replace(event, payload=sanitized)

    def unsafe_swap_events_for_test(self, left: int, right: int) -> None:
        with self._lock:
            self._events[left], self._events[right] = self._events[right], self._events[left]
