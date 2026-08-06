from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
import os
import time
from typing import AsyncIterator, Literal
from uuid import uuid4


AdmissionPriority = Literal["foreground", "normal", "background"]
_PRIORITY_VALUES: dict[AdmissionPriority, int] = {
    "foreground": 0,
    "normal": 10,
    "background": 20,
}


@dataclass(frozen=True, slots=True)
class InferenceAdmissionSettings:
    total_slots: int
    max_pending: int
    per_session_active: int
    queue_timeout_seconds: float
    priority_aging_seconds: float

    @classmethod
    def from_environment(cls, *, total_slots: int) -> "InferenceAdmissionSettings":
        return cls(
            total_slots=max(1, total_slots),
            max_pending=_positive_int("CHAT_ADMISSION_MAX_PENDING", 64),
            per_session_active=_positive_int("CHAT_ADMISSION_PER_SESSION_ACTIVE", 1),
            queue_timeout_seconds=_positive_float("CHAT_ADMISSION_QUEUE_TIMEOUT_SECONDS", 300.0),
            priority_aging_seconds=_positive_float("CHAT_ADMISSION_PRIORITY_AGING_SECONDS", 30.0),
        )


@dataclass(slots=True)
class AdmissionTicket:
    ticket_id: str
    session_id: str
    request_id: str
    priority: AdmissionPriority
    submitted_at: float
    admitted_at: float | None = None

    @property
    def queue_wait_seconds(self) -> float:
        endpoint = self.admitted_at if self.admitted_at is not None else time.monotonic()
        return max(0.0, endpoint - self.submitted_at)


@dataclass(slots=True)
class InferenceAdmissionScheduler:
    settings: InferenceAdmissionSettings
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    _pending: list[AdmissionTicket] = field(default_factory=list)
    _active_by_session: Counter[str] = field(default_factory=Counter)
    _admission_count_by_session: Counter[str] = field(default_factory=Counter)
    _active_total: int = 0
    _admitted_total: int = 0
    _cancelled_total: int = 0
    _timed_out_total: int = 0
    _rejected_total: int = 0

    @asynccontextmanager
    async def admit(
        self,
        *,
        session_id: str,
        request_id: str = "",
        priority: AdmissionPriority = "foreground",
    ) -> AsyncIterator[AdmissionTicket]:
        ticket = AdmissionTicket(
            ticket_id=uuid4().hex,
            session_id=_normalized_session_id(session_id),
            request_id=str(request_id or "").strip(),
            priority=priority,
            submitted_at=time.monotonic(),
        )
        await self._acquire(ticket)
        try:
            yield ticket
        finally:
            await self._release(ticket)

    async def _acquire(self, ticket: AdmissionTicket) -> None:
        async with self._condition:
            if len(self._pending) >= self.settings.max_pending:
                self._rejected_total += 1
                raise AdmissionQueueFull("inference admission queue is full")
            self._pending.append(ticket)
            deadline = ticket.submitted_at + self.settings.queue_timeout_seconds
            try:
                while True:
                    if self._can_admit(ticket):
                        self._pending.remove(ticket)
                        ticket.admitted_at = time.monotonic()
                        self._active_total += 1
                        self._active_by_session[ticket.session_id] += 1
                        self._admission_count_by_session[ticket.session_id] += 1
                        self._admitted_total += 1
                        self._condition.notify_all()
                        return
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._pending.remove(ticket)
                        self._timed_out_total += 1
                        self._condition.notify_all()
                        raise AdmissionQueueTimeout("inference admission queue wait timed out")
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                    except TimeoutError as exc:
                        if ticket in self._pending:
                            self._pending.remove(ticket)
                        self._timed_out_total += 1
                        self._condition.notify_all()
                        raise AdmissionQueueTimeout("inference admission queue wait timed out") from exc
            except asyncio.CancelledError:
                if ticket in self._pending:
                    self._pending.remove(ticket)
                self._cancelled_total += 1
                self._condition.notify_all()
                raise

    def _can_admit(self, ticket: AdmissionTicket) -> bool:
        if self._active_total >= self.settings.total_slots:
            return False
        if self._active_by_session[ticket.session_id] >= self.settings.per_session_active:
            return False
        return self._next_eligible_ticket() is ticket

    def _next_eligible_ticket(self) -> AdmissionTicket | None:
        now = time.monotonic()
        first_by_session: dict[str, AdmissionTicket] = {}
        for candidate in self._pending:
            if self._active_by_session[candidate.session_id] >= self.settings.per_session_active:
                continue
            first_by_session.setdefault(candidate.session_id, candidate)
        if not first_by_session:
            return None
        return min(
            first_by_session.values(),
            key=lambda candidate: (
                self._effective_priority(candidate, now=now),
                self._admission_count_by_session[candidate.session_id],
                candidate.submitted_at,
            ),
        )

    def _effective_priority(self, ticket: AdmissionTicket, *, now: float) -> int:
        base = _PRIORITY_VALUES[ticket.priority]
        aged_steps = int(max(0.0, now - ticket.submitted_at) / self.settings.priority_aging_seconds)
        return max(0, base - aged_steps * 10)

    async def _release(self, ticket: AdmissionTicket) -> None:
        async with self._condition:
            if ticket.admitted_at is None:
                return
            self._active_total = max(0, self._active_total - 1)
            self._active_by_session[ticket.session_id] -= 1
            if self._active_by_session[ticket.session_id] <= 0:
                del self._active_by_session[ticket.session_id]
            if not any(item.session_id == ticket.session_id for item in self._pending):
                self._admission_count_by_session.pop(ticket.session_id, None)
            ticket.admitted_at = None
            self._condition.notify_all()

    async def configure_total_slots(self, total_slots: int) -> None:
        normalized = max(1, int(total_slots))
        async with self._condition:
            if normalized == self.settings.total_slots:
                return
            self.settings = replace(self.settings, total_slots=normalized)
            self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        pending_by_priority = Counter(ticket.priority for ticket in self._pending)
        return {
            "total_slots": self.settings.total_slots,
            "active": self._active_total,
            "pending": len(self._pending),
            "available": max(0, self.settings.total_slots - self._active_total),
            "active_sessions": dict(self._active_by_session),
            "pending_by_priority": dict(pending_by_priority),
            "admitted_total": self._admitted_total,
            "cancelled_total": self._cancelled_total,
            "timed_out_total": self._timed_out_total,
            "rejected_total": self._rejected_total,
        }


class AdmissionQueueFull(RuntimeError):
    pass


class AdmissionQueueTimeout(TimeoutError):
    pass


def _normalized_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    return normalized or f"anonymous:{uuid4().hex}"


def _positive_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or default).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or default).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
