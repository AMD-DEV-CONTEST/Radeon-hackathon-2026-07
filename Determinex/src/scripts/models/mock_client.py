"""Typed mocked-model client.

Used by ``LLM_MOCKED_INTAKE_REPAIR_LOCK_001`` to drive the intake/repair
loop without ever calling a real model. The client takes a task-class →
canned-response mapping and returns the canned record when asked.

The client carries no I/O. It cannot reach a network, cannot reach a
subprocess, and cannot read the corpus or training data. Construction
is the only place a fixture sets up its expected canned responses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .model_router import TaskClass
from .model_router_record import RouteRecord


@dataclass(frozen=True)
class MockedCall:
    """Single recorded mock invocation. Immutable so the trace is stable."""

    task_class: str
    route_decision: str
    selected_model_id: str
    execution_authorized: bool
    payload_keys: tuple[str, ...]
    response_key: str


class MockModelClient:
    """Task-class-typed canned-response client.

    Construction takes a mapping ``{TaskClass: dict}``. Calling
    ``invoke(task_class, route_record, payload)`` returns the canned
    response (a dict) and records the call in ``calls``.

    Invariants:
      * If the route record is not ``execution_authorized``, ``invoke``
        raises ``RouteNotAuthorizedError`` — the mock client refuses to
        pretend an unauthorized route succeeded. The caller is expected
        to short-circuit at the router rather than asking the mock to
        respond.
      * Unknown task classes raise ``KeyError`` — the fixture is
        expected to enumerate every class it intends to exercise.
      * The mock client never mutates the canned mapping; it returns a
        shallow copy of the canned dict.
    """

    class RouteNotAuthorizedError(RuntimeError):
        pass

    def __init__(self, canned: Mapping[TaskClass | str, Mapping[str, object]]):
        # Normalize keys to TaskClass.value strings for stable lookup.
        self._canned: dict[str, dict[str, object]] = {}
        for k, v in canned.items():
            key = k.value if isinstance(k, TaskClass) else str(k)
            self._canned[key] = dict(v)
        self._calls: list[MockedCall] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def calls(self) -> tuple[MockedCall, ...]:
        return tuple(self._calls)

    @property
    def canned_task_classes(self) -> frozenset[str]:
        return frozenset(self._canned.keys())

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def invoke(
        self,
        task_class: TaskClass | str,
        route_record: RouteRecord,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        tc_key = task_class.value if isinstance(task_class, TaskClass) else str(task_class)

        if not route_record.execution_authorized:
            raise MockModelClient.RouteNotAuthorizedError(
                f"Route for {tc_key} is not execution_authorized "
                f"(decision={route_record.decision}). The mock client refuses "
                f"to fabricate a response for an unauthorized route."
            )

        if tc_key not in self._canned:
            raise KeyError(
                f"No canned response registered for task class {tc_key!r}. "
                f"Registered: {sorted(self._canned.keys())}"
            )

        response = dict(self._canned[tc_key])
        payload_keys = tuple(sorted((payload or {}).keys()))
        response_key = str(response.get("kind") or response.get("status") or "MOCKED")
        self._calls.append(
            MockedCall(
                task_class=tc_key,
                route_decision=route_record.decision,
                selected_model_id=route_record.selected_model_id,
                execution_authorized=route_record.execution_authorized,
                payload_keys=payload_keys,
                response_key=response_key,
            )
        )
        return response
