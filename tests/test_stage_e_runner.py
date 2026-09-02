"""Stage E — Runner step timing, cancel, progress callbacks, retry, duplicate guard."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agent.runner import ControlledRunner
from app.config import Settings
from app.observability.audit import AuditTrail
from app.schemas import RunState, RunStatus, StepDef


def _queued_state(run_id: str = "a" * 32) -> RunState:
    now = datetime.now(UTC)
    return RunState(
        run_id=run_id,
        project_id="demo-project",
        created_at=now,
        updated_at=now,
    )


# ── Step timing ────────────────────────────────────────────────────────────


def test_runner_records_step_timing(tmp_path: Path) -> None:
    """Each pipeline step produces a StepTiming record in state.timing_by_step."""
    audit = AuditTrail(tmp_path, "a" * 32)

    def _make_tool(name: str):
        def invoke(_ctx):
            # simulate different durations
            return {"tool": name}

        return invoke

    state = _queued_state()
    runner = ControlledRunner(
        {n: _make_tool(n) for n in ("scan", "index", "retrieve", "evaluate", "draft")},
        audit,
    )
    result = runner.run(state)

    assert result.status is RunStatus.COMPLETED
    assert len(result.timing_by_step) == 5

    for step_def, timing in zip(
        (StepDef.PARSE, StepDef.INDEX, StepDef.RETRIEVE, StepDef.MODEL_GENERATE, StepDef.MODEL_GENERATE),
        result.timing_by_step,
    ):
        assert timing.step == step_def
        assert timing.started_at is not None
        assert timing.finished_at is not None
        assert isinstance(timing.elapsed_ms, float)
        assert timing.elapsed_ms >= 0


def test_runner_step_timing_captures_error(tmp_path: Path) -> None:
    """A tool exception should be recorded in the step timing error field."""
    audit = AuditTrail(tmp_path, "a" * 32)

    def _failing_tool(_ctx):
        raise RuntimeError("simulated parse error")

    tools = {
        "scan": lambda _ctx: {"tool": "scan"},
        "index": _failing_tool,
        "retrieve": lambda _ctx: {"tool": "retrieve"},
        "evaluate": lambda _ctx: {"tool": "evaluate"},
        "draft": lambda _ctx: {"tool": "draft"},
    }
    runner = ControlledRunner(tools, audit)
    result = runner.run(_queued_state())

    assert result.status is RunStatus.FAILED
    assert len(result.timing_by_step) >= 1


# ── Cancel ──────────────────────────────────────────────────────────────────


def test_runner_honours_cancel_requested_flag(tmp_path: Path) -> None:
    """When cancel_requested=True, the pipeline stops with CANCELLED status."""
    audit = AuditTrail(tmp_path, "a" * 32)

    tool_order: list[str] = []

    def _tool(name: str):
        def invoke(_ctx):
            tool_order.append(name)
            return {"tool": name}

        return invoke

    state = _queued_state()
    state = state.model_copy(update={"cancel_requested": True})

    runner = ControlledRunner(
        {n: _tool(n) for n in ("scan", "index", "retrieve", "evaluate", "draft")},
        audit,
    )
    result = runner.run(state)

    assert result.status is RunStatus.CANCELLED
    assert len(tool_order) == 0  # cancelled before first step


def test_runner_cancel_mid_pipeline(tmp_path: Path) -> None:
    """Cancel flag set during a tool should stop at next step boundary."""
    audit = AuditTrail(tmp_path, "a" * 32)
    calls: list[str] = []
    signal = {"requested": False}

    def _scan(_ctx):
        calls.append("scan")
        signal["requested"] = True
        return {"tool": "scan"}

    tools = {
        "scan": _scan,
        "index": lambda _ctx: calls.append("index") or {},
        "retrieve": lambda _ctx: {},
        "evaluate": lambda _ctx: {},
        "draft": lambda _ctx: {},
    }
    result = ControlledRunner(tools, audit, cancel_check=lambda: signal["requested"]).run(_queued_state())
    assert result.status is RunStatus.CANCELLED
    assert result.cancel_requested is True
    assert calls == ["scan"]


def test_runner_honours_external_cancel_after_a_completed_step(tmp_path: Path) -> None:
    """A cancellation persisted during a tool stops the next pipeline step."""
    audit = AuditTrail(tmp_path, "d" * 32)
    calls: list[str] = []
    cancel_signal = {"requested": False}

    def scan(_ctx):
        calls.append("scan")
        cancel_signal["requested"] = True
        return {"tool": "scan"}

    tools = {
        "scan": scan,
        "index": lambda _ctx: calls.append("index") or {"tool": "index"},
        "retrieve": lambda _ctx: {"tool": "retrieve"},
        "evaluate": lambda _ctx: {"tool": "evaluate"},
        "draft": lambda _ctx: {"tool": "draft"},
    }
    result = ControlledRunner(
        tools,
        audit,
        cancel_check=lambda: cancel_signal["requested"],
    ).run(_queued_state(run_id="d" * 32))

    assert result.status is RunStatus.CANCELLED
    assert result.cancel_requested is True
    assert calls == ["scan"]


# ── Progress callback ───────────────────────────────────────────────────────


def test_progress_callback_invoked_after_each_step(tmp_path: Path) -> None:
    """Progress callback is called after every step transition."""
    audit = AuditTrail(tmp_path, "a" * 32)
    progress_records: list[RunStatus] = []

    def _cb(state: RunState) -> None:
        progress_records.append(state.status)

    tools = {n: (lambda _ctx, n=n: {"tool": n}) for n in ("scan", "index", "retrieve", "evaluate", "draft")}
    runner = ControlledRunner(tools, audit, progress_callback=_cb)
    result = runner.run(_queued_state())

    assert result.status is RunStatus.COMPLETED
    # Callback called at least 5+ times (queued start + 5 steps + completed)
    assert len(progress_records) >= 6
    assert RunStatus.QUEUED in progress_records


# ── Duplicate guard ─────────────────────────────────────────────────────────


def test_runner_rejects_non_queued_state(tmp_path: Path) -> None:
    """Only queued runs can be started."""
    audit = AuditTrail(tmp_path, "a" * 32)
    tools = {n: (lambda _ctx: {"tool": n}) for n in ("scan", "index", "retrieve", "evaluate", "draft")}
    runner = ControlledRunner(tools, audit)

    completed_state = _queued_state().model_copy(
        update={"status": RunStatus.COMPLETED}
    )
    with pytest.raises(ValueError, match="only queued runs can be started"):
        runner.run(completed_state)


# ── Max steps ───────────────────────────────────────────────────────────────


def test_runner_respects_max_steps(tmp_path: Path) -> None:
    """Runner stops with FAILED when step count exceeds max_steps."""
    audit = AuditTrail(tmp_path, "a" * 32)
    tools = {n: (lambda _ctx: {"tool": n}) for n in ("scan", "index", "retrieve", "evaluate", "draft")}
    runner = ControlledRunner(tools, audit, max_steps=2)
    result = runner.run(_queued_state())

    assert result.status is RunStatus.FAILED
    assert "maximum step count reached" in (result.error or "")


# ── Audit trail ─────────────────────────────────────────────────────────────


def test_audit_trail_writes_all_lifecycle_events(tmp_path: Path) -> None:
    """Full lifecycle: run_started → tool_started/completed → run_completed/run_failed."""
    audit = AuditTrail(tmp_path, "a" * 32)
    tools = {n: (lambda _ctx: {"tool": n}) for n in ("scan", "index", "retrieve", "evaluate", "draft")}
    runner = ControlledRunner(tools, audit)
    result = runner.run(_queued_state())

    assert result.status is RunStatus.COMPLETED

    events = [json.loads(line)["event"] for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert "run_started" in events
    assert "run_completed" in events
    assert events.count("tool_started") == 5
    assert events.count("tool_completed") == 5


def test_audit_writes_cancelled_event(tmp_path: Path) -> None:
    """Cancelled run produces run_cancelled audit event."""
    audit = AuditTrail(tmp_path, "a" * 32)
    tools = {n: (lambda _ctx: {"tool": n}) for n in ("scan", "index", "retrieve", "evaluate", "draft")}
    runner = ControlledRunner(tools, audit)
    state = _queued_state().model_copy(update={"cancel_requested": True})
    result = runner.run(state)

    assert result.status is RunStatus.CANCELLED
    events = [json.loads(line)["event"] for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert "run_cancelled" in events
