from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.observability.audit import AuditTrail, StepTimer
from app.schemas import RunState, RunStatus, StepDef, StepTiming


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: str
    project_id: str


# Map pipeline tool names to StepDef values
_TOOL_TO_STEP: dict[str, StepDef] = {
    "parse": StepDef.PARSE,
    "scan": StepDef.PARSE,
    "embed": StepDef.EMBED,
    "index": StepDef.INDEX,
    "retrieve": StepDef.RETRIEVE,
    "rules": StepDef.RULES,
    "evaluate": StepDef.MODEL_GENERATE,
    "draft": StepDef.MODEL_GENERATE,
    "write": StepDef.FILE_WRITE,
}


Tool = Callable[[RunContext], dict[str, Any]]

# Progress callback signature: called after each step with the latest RunState
ProgressCallback = Callable[[RunState], None] | None
CancelCheck = Callable[[], bool] | None


class ControlledRunner:
    """Execute a fixed, registered tool chain without model-selected actions.

    Stage E additions:
    - Per-step timing via ``StepTimer`` written to ``state.timing_by_step``.
    - Cancel check: if ``state.cancel_requested`` is True the pipeline stops.
    - Optional ``progress_callback`` invoked after every step transition.
    """

    PIPELINE: tuple[tuple[RunStatus, str], ...] = (
        (RunStatus.SCANNING, "scan"),
        (RunStatus.INDEXING, "index"),
        (RunStatus.RETRIEVING, "retrieve"),
        (RunStatus.EVALUATING, "evaluate"),
        (RunStatus.DRAFTING, "draft"),
    )

    def __init__(
        self,
        tools: dict[str, Tool],
        audit: AuditTrail,
        *,
        max_steps: int = 8,
        progress_callback: ProgressCallback = None,
        cancel_check: CancelCheck = None,
    ):
        if not 1 <= max_steps <= 8:
            raise ValueError("max_steps must be between 1 and 8")
        self._tools = dict(tools)
        self._audit = audit
        self._max_steps = max_steps
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check

    def run(self, state: RunState) -> RunState:
        if state.status is not RunStatus.QUEUED:
            raise ValueError("only queued runs can be started")

        context = RunContext(run_id=state.run_id, project_id=state.project_id)
        timing_list: list[StepTiming] = list(state.timing_by_step)
        total_steps = min(len(self.PIPELINE), self._max_steps)

        self._audit.write("run_started", {"project_id": state.project_id})
        state = state.model_copy(update={"status": RunStatus.QUEUED, "updated_at": datetime.now(UTC)})
        self._notify_progress(state)

        for step, (status, tool_name) in enumerate(self.PIPELINE, start=1):
            if step > self._max_steps:
                return self._fail(state, timing_list, step - 1, "maximum step count reached")

            # Cancel check
            if self._is_cancel_requested(state):
                state = state.model_copy(update={"cancel_requested": True})
                return self._cancel(state, timing_list, step - 1)

            tool = self._tools.get(tool_name)
            if tool is None:
                return self._fail(state, timing_list, step - 1, f"required tool is not registered: {tool_name}")

            step_def = _TOOL_TO_STEP.get(tool_name, StepDef.MODEL_GENERATE)
            state = state.model_copy(
                update={
                    "status": status,
                    "current_step": step,
                    "updated_at": datetime.now(UTC),
                    "total_steps": total_steps,
                    "timing_by_step": list(timing_list),
                }
            )
            self._audit.write("tool_started", {"step": step, "tool": tool_name})
            self._notify_progress(state)

            try:
                with self._audit.step_timer(timing_list, step_def) as st:
                    result = tool(context)
                    if isinstance(result, dict) and result.get("current_file"):
                        st.current_file = result["current_file"]
            except Exception as error:  # Tool errors must become an auditable run result.
                return self._fail(state, timing_list, step, f"{tool_name} failed: {error}")

            self._audit.write("tool_completed", {"step": step, "tool": tool_name, "result": result})

        completed_at = datetime.now(UTC)
        state = state.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "current_step": len(self.PIPELINE),
                "updated_at": completed_at,
                "completed_at": completed_at,
                "timing_by_step": list(timing_list),
                "total_steps": total_steps,
            }
        )
        self._audit.write("run_completed", {"steps": state.current_step})
        self._notify_progress(state)
        return state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cancel_requested(self, state: RunState) -> bool:
        """Read the latest external cancellation signal between pipeline steps."""
        if state.cancel_requested:
            return True
        return bool(self._cancel_check and self._cancel_check())

    def _fail(self, state: RunState, timing_list: list[StepTiming], step: int, error: str) -> RunState:
        failed_at = datetime.now(UTC)
        failed = state.model_copy(
            update={
                "status": RunStatus.FAILED,
                "current_step": step,
                "error": error,
                "updated_at": failed_at,
                "completed_at": failed_at,
                "timing_by_step": list(timing_list),
            }
        )
        self._audit.write("run_failed", {"step": step, "error": error})
        self._notify_progress(failed)
        return failed

    def _cancel(self, state: RunState, timing_list: list[StepTiming], step: int) -> RunState:
        cancelled_at = datetime.now(UTC)
        cancelled = state.model_copy(
            update={
                "status": RunStatus.CANCELLED,
                "current_step": step,
                "updated_at": cancelled_at,
                "completed_at": cancelled_at,
                "timing_by_step": list(timing_list),
            }
        )
        self._audit.write("run_cancelled", {"step": step})
        self._notify_progress(cancelled)
        return cancelled

    def _notify_progress(self, state: RunState) -> None:
        if self._progress_callback is not None:
            try:
                self._progress_callback(state)
            except Exception:
                pass  # progress callback must not crash the pipeline
