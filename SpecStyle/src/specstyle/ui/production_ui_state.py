"""Bounded process-local state for the Production UI controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import threading

from specstyle.ui.view_models import JobStatusView, ProductionRunUiView
from specstyle.workflow.production_replay import ProductionReplayEvidence


@dataclass(frozen=True, slots=True)
class ProductionTerminalProjection:
    run_view: ProductionRunUiView
    status: JobStatusView
    qa_table: str
    repair_timeline: str
    export_summary: str


@dataclass(slots=True)
class _ActiveInvocation:
    token: int
    kind: str
    total: int
    phase: str = "STAGING"
    current_index: int = 0
    job_id: str = ""
    execution: object | None = None
    cancel_requested: bool = False
    item_projections: list[ProductionTerminalProjection] = field(default_factory=list)


class ProductionUiState:
    """Coordinate one invocation and retain one lightweight terminal view."""

    def __init__(
        self, status_reader: Callable[[str], str | None] | None = None
    ) -> None:
        self._single_flight = threading.Lock()
        self._state_lock = threading.RLock()
        self._cancel_close_gate = threading.Lock()
        self._next_token = 0
        self._active: _ActiveInvocation | None = None
        self._terminal: ProductionTerminalProjection | None = None
        self._replay_baseline: ProductionReplayEvidence | None = None
        self._status_reader = status_reader

    def try_begin(self, kind: str, total: int) -> int | None:
        if (
            kind not in ("single", "batch", "replay")
            or type(total) is not int
            or total < 1
        ):
            raise TypeError("invalid production invocation")
        if not self._single_flight.acquire(blocking=False):
            return None
        with self._state_lock:
            self._next_token += 1
            token = self._next_token
            self._active = _ActiveInvocation(token, kind, total)
        return token

    def set_phase(
        self,
        token: int,
        phase: str,
        *,
        job_id: str | None = None,
        current_index: int | None = None,
    ) -> None:
        with self._state_lock:
            active = self._matching(token)
            active.phase = phase
            if job_id is not None:
                active.job_id = job_id
            if current_index is not None:
                active.current_index = current_index

    def is_cancel_requested(self, token: int) -> bool:
        with self._state_lock:
            return self._matching(token).cancel_requested

    def register_execution(self, token: int, execution: object) -> bool:
        with self._state_lock:
            active = self._matching(token)
            active.execution = execution
            active.phase = "ACTIVE"
            return active.cancel_requested

    def close_execution(self, token: int, execution: object) -> None:
        with self._cancel_close_gate:
            with self._state_lock:
                active = self._matching(token)
                if active.execution is execution:
                    active.execution = None
                active.phase = "CLEANUP"
            execution.close()

    def add_item_projection(
        self, token: int, projection: ProductionTerminalProjection
    ) -> None:
        if type(projection) is not ProductionTerminalProjection:
            raise TypeError("invalid production item projection")
        with self._state_lock:
            active = self._matching(token)
            if len(active.item_projections) >= 4:
                raise RuntimeError("production item projection limit exceeded")
            active.item_projections.append(projection)

    def item_projections(self, token: int) -> tuple[ProductionTerminalProjection, ...]:
        with self._state_lock:
            return tuple(self._matching(token).item_projections)

    def cancel_registered_execution(self, token: int) -> str:
        with self._cancel_close_gate:
            with self._state_lock:
                execution = self._matching(token).execution
            if execution is None:
                return "cancel requested"
            return self._cancel_execution(execution)

    def finish(
        self,
        token: int,
        projection: ProductionTerminalProjection,
        *,
        replay_baseline: ProductionReplayEvidence | None = None,
    ) -> None:
        if type(projection) is not ProductionTerminalProjection:
            raise TypeError("invalid production terminal projection")
        if (
            replay_baseline is not None
            and type(replay_baseline) is not ProductionReplayEvidence
        ):
            raise TypeError("invalid production replay baseline")
        with self._state_lock:
            active = self._matching(token)
            if replay_baseline is not None:
                if active.kind != "single":
                    raise TypeError("invalid production replay baseline")
                self._replay_baseline = replay_baseline
            self._terminal = projection
            self._active = None
        self._single_flight.release()

    def replay_baseline(self, token: int) -> ProductionReplayEvidence | None:
        with self._state_lock:
            active = self._matching(token)
            if active.kind != "replay":
                raise RuntimeError("invalid production replay invocation")
            return self._replay_baseline

    def abandon(self, token: int) -> None:
        release = False
        with self._state_lock:
            if self._active is not None and self._active.token == token:
                self._active = None
                release = True
        if release:
            self._single_flight.release()

    def get_job_status(self) -> JobStatusView:
        for _attempt in range(2):
            with self._state_lock:
                active = self._active
                if active is None:
                    return self._terminal_status()
                token = active.token
                job_id = active.job_id
                phase = active.phase
                current_index = active.current_index
                message = self._active_message(active)
            persisted = (
                self._read_status(job_id)
                if job_id and phase in ("ACTIVE", "CANCEL_REQUESTED")
                else None
            )
            with self._state_lock:
                if (
                    self._active is not None
                    and self._active.token == token
                    and self._active.job_id == job_id
                    and self._active.phase == phase
                    and self._active.current_index == current_index
                ):
                    return self._status_view(job_id, persisted or phase, message)
        with self._state_lock:
            if self._active is None:
                return self._terminal_status()
            active = self._active
            return self._status_view(
                active.job_id, active.phase, self._active_message(active)
            )

    def cancel_job(self) -> str:
        with self._cancel_close_gate:
            with self._state_lock:
                if self._active is None:
                    if self._terminal is not None:
                        return "cancel unavailable; latest run is terminal"
                    return "cancel unavailable; no active production run"
                if self._active.cancel_requested:
                    return "cancel already requested"
                if self._active.phase in ("RESULT_READY", "CLEANUP"):
                    return "cancel unavailable; latest run is terminal"
                self._active.cancel_requested = True
                execution = self._active.execution
                if execution is not None:
                    self._active.phase = "CANCEL_REQUESTED"
            if execution is None:
                return "cancel requested"
            return self._cancel_execution(execution)

    def get_qa_table(self) -> str:
        with self._state_lock:
            if self._active is not None:
                return self._active_projection_text(
                    self._active,
                    "qa_table",
                    "qa unavailable while production run is active",
                )
            return "no qa" if self._terminal is None else self._terminal.qa_table

    def get_repair_timeline(self) -> str:
        with self._state_lock:
            if self._active is not None:
                return self._active_projection_text(
                    self._active,
                    "repair_timeline",
                    "repair unavailable while production run is active",
                )
            return (
                "no repair"
                if self._terminal is None
                else self._terminal.repair_timeline
            )

    def get_export_summary(self) -> str:
        with self._state_lock:
            if self._active is not None:
                return self._active_projection_text(
                    self._active,
                    "export_summary",
                    "export unavailable while production run is active",
                    inline=True,
                )
            return (
                "no export" if self._terminal is None else self._terminal.export_summary
            )

    def _matching(self, token: int) -> _ActiveInvocation:
        if self._active is None or self._active.token != token:
            raise RuntimeError("stale production invocation")
        return self._active

    def _terminal_status(self) -> JobStatusView:
        if self._terminal is not None:
            return self._terminal.status
        return JobStatusView("", "IDLE", "no production run", False, "production")

    @staticmethod
    def _status_view(job_id: str, status: str, message: str) -> JobStatusView:
        can_cancel = status not in (
            "COMPLETED",
            "JOB_FAILED",
            "CANCELLED",
            "RESULT_READY",
            "CLEANUP",
        )
        return JobStatusView(job_id, status, message, can_cancel, "production")

    def _read_status(self, job_id: str) -> str | None:
        if self._status_reader is None:
            return None
        try:
            value = self._status_reader(job_id)
        except Exception:
            return None
        return value if type(value) is str and value else None

    @staticmethod
    def _cancel_execution(execution: object) -> str:
        try:
            state = execution.cancel(reason="user requested")
        except Exception as exc:
            message = str(exc).replace("\r", " ").replace("\n", " ")[:160]
            if message == "job is terminal":
                return "cancel unavailable; job is terminal"
            return "cancel failed: internal error"
        status = getattr(
            getattr(getattr(state, "job", None), "status", None), "value", None
        )
        if status is None:
            return "cancel requested"
        if status != "CANCELLED":
            return f"cancel unavailable; job status={status}"
        return "cancel requested; job status=CANCELLED"

    @staticmethod
    def _active_message(active: _ActiveInvocation) -> str:
        message = f"{active.kind} phase={active.phase}"
        if active.kind == "batch":
            statuses = tuple(item.status.status for item in active.item_projections)
            completed = statuses.count("COMPLETED")
            failed = statuses.count("JOB_FAILED")
            cancelled = statuses.count("CANCELLED")
            remaining = active.total - len(statuses)
            message += (
                f" item={active.current_index + 1}/{active.total} aggregate_ui=yes"
                f" completed={completed} failed={failed} cancelled={cancelled}"
                f" remaining={remaining}"
            )
        return message

    @staticmethod
    def _active_projection_text(
        active: _ActiveInvocation,
        field_name: str,
        unavailable: str,
        *,
        inline: bool = False,
    ) -> str:
        if not active.item_projections:
            return unavailable
        separator = "\n" if inline else "\n\n"
        return separator.join(
            f"item={index} {getattr(item, field_name)}"
            if inline
            else f"item={index}\n{getattr(item, field_name)}"
            for index, item in enumerate(active.item_projections)
        )
