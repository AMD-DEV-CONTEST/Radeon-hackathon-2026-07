from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.observability.audit import validate_run_id
from app.schemas import RunProgress, RunState, RunStatus, StepTiming
from app.security.paths import ensure_project_path, validate_project_id
from app.services.projects import ProjectNotFoundError, project_paths
from app.agent.runner import ControlledRunner, ProgressCallback
from app.observability.audit import AuditTrail
from app.services.project_workflow import build_project_report_tools


class RunNotFoundError(RuntimeError):
    pass


class RunAlreadyExecutedError(RuntimeError):
    pass


class RunWrongStatusError(RuntimeError):
    pass


class RunCancelTooLateError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# In-memory store for background task tracking (Stage E)
# ---------------------------------------------------------------------------
_running_tasks: dict[str, asyncio.Task[RunState]] = {}


def _run_path(settings: Settings, project_id: str, run_id: str) -> Path:
    validate_project_id(project_id)
    validate_run_id(run_id)
    return ensure_project_path(settings.output_root, project_id, "runs", f"{run_id}.json")


def _runs_dir(settings: Settings, project_id: str) -> Path:
    validate_project_id(project_id)
    return ensure_project_path(settings.output_root, project_id, "runs")


def _write_state(path: Path, state: RunState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_run(settings: Settings, project_id: str) -> RunState:
    project_id = validate_project_id(project_id)
    metadata_path = project_paths(settings.project_root, settings.output_root, project_id)["project"] / "project.json"
    if not metadata_path.is_file():
        raise ProjectNotFoundError(project_id)

    now = datetime.now(UTC)
    state = RunState(
        run_id=uuid4().hex,
        project_id=project_id,
        status=RunStatus.QUEUED,
        created_at=now,
        updated_at=now,
    )
    _write_state(_run_path(settings, project_id, state.run_id), state)
    return state


def get_run(settings: Settings, project_id: str, run_id: str) -> RunState:
    path = _run_path(settings, project_id, run_id)
    if not path.is_file():
        raise RunNotFoundError(run_id)
    try:
        return RunState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise RunNotFoundError(run_id) from error


def save_run(settings: Settings, state: RunState) -> RunState:
    updated = state.model_copy(update={"updated_at": datetime.now(UTC)})
    _write_state(_run_path(settings, updated.project_id, updated.run_id), updated)
    return updated


# ---------------------------------------------------------------------------
# List runs
# ---------------------------------------------------------------------------


def list_runs(settings: Settings, project_id: str) -> list[RunState]:
    """Return all runs for this project, newest first."""
    validate_project_id(project_id)
    runs_dir = _runs_dir(settings, project_id)
    if not runs_dir.is_dir():
        return []
    results: list[RunState] = []
    for fpath in runs_dir.glob("*.json"):
        try:
            results.append(RunState.model_validate(json.loads(fpath.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    results.sort(key=lambda s: s.created_at, reverse=True)
    return results


def list_all_runs(settings: Settings) -> list[RunState]:
    """Return all runs across all projects, newest first (for global history)."""
    results: list[RunState] = []
    output_root = settings.output_root
    if not output_root.is_dir():
        return results
    for project_dir in output_root.iterdir():
        if not project_dir.is_dir():
            continue
        runs_dir = project_dir / "runs"
        if not runs_dir.is_dir():
            continue
        for fpath in runs_dir.glob("*.json"):
            try:
                results.append(RunState.model_validate(json.loads(fpath.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
    results.sort(key=lambda s: s.created_at, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------


def build_progress(state: RunState) -> RunProgress:
    """Build a RunProgress snapshot from a RunState."""
    total = state.total_steps or 8
    current = state.current_step
    percentage = min(round(current / total * 100), 100) if total > 0 else 0

    current_step_name = ""
    if state.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        current_step_name = state.status.value
    elif state.timing_by_step:
        last = state.timing_by_step[-1]
        current_step_name = last.step.value
    else:
        current_step_name = state.status.value

    error_summary: str | None = None
    if state.error:
        error_summary = state.error[:1000]
    elif state.timing_by_step:
        last_err = next((t.error for t in reversed(state.timing_by_step) if t.error), None)
        error_summary = last_err

    return RunProgress(
        run_id=state.run_id,
        status=state.status,
        current_step=current,
        current_step_name=current_step_name,
        percentage=percentage,
        current_file=state.current_file,
        error_summary=error_summary,
        timing_by_step=list(state.timing_by_step),
        retry_count=state.retry_count,
    )


# ---------------------------------------------------------------------------
# Background execution (Stage E)
# ---------------------------------------------------------------------------


async def _background_execute(
    settings: Settings,
    project_id: str,
    run_id: str,
    *,
    index_factory: Any = None,
    use_llm: bool = True,
    retrieval_min_score: float = 0.35,
) -> RunState:
    """Internal async runner. Writes progress to disk after every step."""
    state = get_run(settings, project_id, run_id)

    def _cancel_requested() -> bool:
        try:
            return get_run(settings, project_id, run_id).cancel_requested
        except RunNotFoundError:
            return True

    def _persist(run_state: RunState) -> None:
        try:
            current = get_run(settings, project_id, run_id)
            if current.cancel_requested and not run_state.cancel_requested:
                run_state = run_state.model_copy(update={"cancel_requested": True})
            save_run(settings, run_state)
        except Exception:
            pass  # save failure must not crash the pipeline

    tools, artifacts = build_project_report_tools(
        settings,
        index_factory=index_factory,
        use_llm=use_llm,
        retrieval_min_score=retrieval_min_score,
    )
    runner = ControlledRunner(
        tools,
        AuditTrail(settings.log_root, state.run_id),
        max_steps=settings.agent_max_steps,
        progress_callback=_persist,
        cancel_check=_cancel_requested,
    )
    # The pipeline uses synchronous parsing, indexing and model calls.  Keep
    # it off the ASGI event loop so progress and cancellation remain available.
    completed = await asyncio.to_thread(runner.run, state)
    completed = completed.model_copy(update={"artifacts": artifacts.summary()})
    return save_run(settings, completed)


def dispatch_background_run(
    settings: Settings,
    project_id: str,
    run_id: str,
    *,
    index_factory: Any = None,
    use_llm: bool = True,
    retrieval_min_score: float = 0.35,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Queue a background execution.  Guards against duplicate run_id."""
    state = get_run(settings, project_id, run_id)

    # No duplicate execution
    if state.status not in (RunStatus.QUEUED,):
        raise RunAlreadyExecutedError(
            f"Run {run_id} is in {state.status.value}, cannot execute again"
        )

    if run_id in _running_tasks:
        raise RunAlreadyExecutedError(f"Run {run_id} is already being executed")

    if loop is None:
        loop = asyncio.get_event_loop()

    task = loop.create_task(
        _background_execute(
            settings,
            project_id,
            run_id,
            index_factory=index_factory,
            use_llm=use_llm,
            retrieval_min_score=retrieval_min_score,
        )
    )
    _running_tasks[run_id] = task

    def _cleanup(_future: asyncio.Future[RunState]) -> None:
        _running_tasks.pop(run_id, None)

    task.add_done_callback(_cleanup)


# ---------------------------------------------------------------------------
# Cancel / Retry (Stage E)
# ---------------------------------------------------------------------------


def cancel_run(settings: Settings, project_id: str, run_id: str) -> RunState:
    """Request cancellation of a running run."""
    state = get_run(settings, project_id, run_id)

    if state.status == RunStatus.CANCELLED:
        raise RunAlreadyExecutedError(f"Run {run_id} is already cancelled")

    if state.status in (RunStatus.COMPLETED, RunStatus.FAILED):
        raise RunCancelTooLateError(f"Run {run_id} is in terminal state {state.status.value}")

    if state.status in (RunStatus.QUEUED,):
        # Not yet started — just mark cancelled
        now = datetime.now(UTC)
        state = state.model_copy(
            update={
                "status": RunStatus.CANCELLED,
                "cancel_requested": True,
                "completed_at": now,
                "updated_at": now,
            }
        )
        return save_run(settings, state)

    # Running — set cancel_requested flag; the pipeline checks it
    state = state.model_copy(update={"cancel_requested": True, "updated_at": datetime.now(UTC)})
    return save_run(settings, state)


def retry_run(settings: Settings, project_id: str, run_id: str) -> RunState:
    """Retry a failed or cancelled run (creates a new queued entry)."""
    state = get_run(settings, project_id, run_id)

    if state.status not in (RunStatus.FAILED, RunStatus.CANCELLED):
        raise RunWrongStatusError(
            f"Only failed or cancelled runs can be retried, got {state.status.value}"
        )

    if state.retry_count >= settings.run_max_retries:
        raise RunWrongStatusError(
            f"Maximum retry count ({settings.run_max_retries}) exceeded"
        )

    now = datetime.now(UTC)
    new_state = RunState(
        run_id=uuid4().hex,
        project_id=project_id,
        status=RunStatus.QUEUED,
        created_at=now,
        updated_at=now,
        retry_count=state.retry_count + 1,
    )
    _write_state(_run_path(settings, project_id, new_state.run_id), new_state)
    return new_state


# ---------------------------------------------------------------------------
# Synchronous execute (used by tests that need blocking execution)
# ---------------------------------------------------------------------------


def execute_project_report_run(
    settings: Settings,
    project_id: str,
    run_id: str,
    *,
    index_factory=None,
    use_llm: bool = True,
    retrieval_min_score: float = 0.35,
) -> RunState:
    """Execute the approved RAG-to-report workflow for one queued project run.

    Synchronous version — used by tests.  For production use
    ``dispatch_background_run``.
    """
    state = get_run(settings, project_id, run_id)
    tools, artifacts = build_project_report_tools(
        settings,
        index_factory=index_factory,
        use_llm=use_llm,
        retrieval_min_score=retrieval_min_score,
    )
    runner = ControlledRunner(
        tools,
        AuditTrail(settings.log_root, state.run_id),
        max_steps=settings.agent_max_steps,
    )
    completed = runner.run(state)
    completed = completed.model_copy(update={"artifacts": artifacts.summary()})
    return save_run(settings, completed)
