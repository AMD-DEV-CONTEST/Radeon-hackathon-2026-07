from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import threading
from typing import Any


PrepareEvent = Callable[[dict[str, Any]], dict[str, Any]]
DeliverEvent = Callable[[dict[str, Any]], None]
ReportFailure = Callable[[str, BaseException], None]


@dataclass(frozen=True, slots=True)
class RuntimeEventPipelineStats:
    queued: int
    submitted: int
    delivered: int
    coalesced: int
    dropped_transient: int
    critical_overflow: int

    def payload(self) -> dict[str, int]:
        return {
            "queued": self.queued,
            "submitted": self.submitted,
            "delivered": self.delivered,
            "coalesced": self.coalesced,
            "dropped_transient": self.dropped_transient,
            "critical_overflow": self.critical_overflow,
        }


class RuntimeEventPipeline:
    """Move durable event processing away from the ASGI event loop.

    Runtime producers may be ordinary threads.  They must never block on WebUI
    persistence or enqueue one event-loop callback per streamed event.  A single
    worker preserves event order, performs durable preparation, and schedules
    only the lightweight delivery step back onto the ASGI loop.
    """

    def __init__(
        self,
        *,
        prepare: PrepareEvent,
        deliver: DeliverEvent,
        report_failure: ReportFailure,
        capacity: int,
    ) -> None:
        if capacity <= 0:
            raise ValueError("runtime event pipeline capacity must be greater than zero")
        self._prepare = prepare
        self._deliver = deliver
        self._report_failure = report_failure
        self._capacity = capacity
        self._condition = threading.Condition()
        self._events: deque[dict[str, Any]] = deque()
        self._thread: threading.Thread | None = None
        self._accepting = False
        self._stop_requested = False
        self._submitted = 0
        self._delivered = 0
        self._coalesced = 0
        self._dropped_transient = 0
        self._critical_overflow = 0

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                self._accepting = True
                return
            self._accepting = True
            self._stop_requested = False
            self._thread = threading.Thread(
                target=self._run,
                name="runtime-event-pipeline",
                daemon=True,
            )
            self._thread.start()

    def submit(self, event_payload: dict[str, Any]) -> None:
        item = dict(event_payload)
        with self._condition:
            self._submitted += 1
            if not self._accepting:
                self._deliver(item)
                return
            if len(self._events) >= self._capacity and not self._make_room(item):
                return
            self._events.append(item)
            self._condition.notify()

    def stop(self, *, drain: bool = True, timeout_seconds: float = 5.0) -> None:
        with self._condition:
            self._accepting = False
            self._stop_requested = True
            if not drain:
                self._events.clear()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, timeout_seconds))
        with self._condition:
            self._thread = None

    def stats(self) -> RuntimeEventPipelineStats:
        with self._condition:
            return RuntimeEventPipelineStats(
                queued=len(self._events),
                submitted=self._submitted,
                delivered=self._delivered,
                coalesced=self._coalesced,
                dropped_transient=self._dropped_transient,
                critical_overflow=self._critical_overflow,
            )

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._events and not self._stop_requested:
                    self._condition.wait()
                if not self._events and self._stop_requested:
                    return
                item = self._events.popleft()
            try:
                prepared = self._prepare(item)
            except BaseException as exc:
                self._report_failure("prepare", exc)
                prepared = item
            try:
                self._deliver(prepared)
            except BaseException as exc:
                self._report_failure("deliver", exc)
                continue
            with self._condition:
                self._delivered += 1

    def _make_room(self, incoming: dict[str, Any]) -> bool:
        incoming_key = _transient_key(incoming)
        if incoming_key is not None:
            for index in range(len(self._events) - 1, -1, -1):
                if _transient_key(self._events[index]) == incoming_key:
                    self._events[index] = incoming
                    self._coalesced += 1
                    return False
        for index, queued in enumerate(self._events):
            if _is_transient(queued):
                del self._events[index]
                self._dropped_transient += 1
                return True
        if _is_transient(incoming):
            self._dropped_transient += 1
            return False
        self._critical_overflow += 1
        return True


def _is_transient(event_payload: dict[str, Any]) -> bool:
    return str(event_payload.get("persistence") or "").strip().lower() == "transient"


def _transient_key(event_payload: dict[str, Any]) -> tuple[str, ...] | None:
    if not _is_transient(event_payload):
        return None
    payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
    return (
        str(event_payload.get("request_id") or ""),
        str(event_payload.get("event_type") or ""),
        str(event_payload.get("node_id") or payload.get("node_id") or ""),
        str(payload.get("stream_id") or ""),
    )
