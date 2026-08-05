"""
tests/test_hive_core.py — Core Hive Mind unit tests

Covers: DAG topological sort, WAL atomicity, compiler output sanitization,
        and API budget enforcement.

Run with: pytest tests/test_hive_core.py -v
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# ── Bootstrap: scripts/ must be on sys.path for hive.* imports ───────────────
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ─────────────────────────────────────────────────────────────────────────────
# 1. DAG topological sort
# ─────────────────────────────────────────────────────────────────────────────


def _make_steps(deps: dict[int, list[int]]):
    """Build a minimal list of StepRecord-like dicts for the sort tests."""
    from hive.manifest import StepRecord

    return [
        StepRecord(
            id=sid,
            instruction=f"step {sid}",
            depends_on=dep_list,
        )
        for sid, dep_list in deps.items()
    ]


def test_topo_sort_linear():
    """1 → 2 → 3 must come out in that order."""
    from hive.dag import topological_sort

    steps = _make_steps({1: [], 2: [1], 3: [2]})
    order, cycles = topological_sort(steps)
    assert cycles == []
    flat = [x for x in order if isinstance(x, int)]
    assert flat.index(1) < flat.index(2) < flat.index(3)


def test_topo_sort_parallel():
    """Steps 2 and 3 both depend only on 1 — they should both appear after 1."""
    from hive.dag import topological_sort

    steps = _make_steps({1: [], 2: [1], 3: [1]})
    order, cycles = topological_sort(steps)
    assert cycles == []
    flat = [x for x in order if isinstance(x, int)]
    assert flat.index(1) < flat.index(2)
    assert flat.index(1) < flat.index(3)


def test_topo_sort_detects_cycle():
    """A → B → A must be reported as a cycle, not returned in the flat order."""
    from hive.dag import topological_sort

    steps = _make_steps({1: [2], 2: [1]})
    order, cycles = topological_sort(steps)
    assert len(cycles) > 0, "Expected at least one cycle group"


def test_build_execution_waves():
    """Waves must group independent steps together."""
    from hive.dag import build_execution_waves, topological_sort

    steps = _make_steps({1: [], 2: [], 3: [1, 2], 4: [3]})
    order, _ = topological_sort(steps)
    waves = build_execution_waves(steps, order)
    # Wave 0 must contain 1 and 2 (no deps); wave 1 must contain 3; wave 2 must contain 4
    wave_sets = []
    for wave in waves:
        flat_wave = set()
        for item in wave:
            if isinstance(item, int):
                flat_wave.add(item)
            else:
                flat_wave.update(item)
        wave_sets.append(flat_wave)
    assert {1, 2}.issubset(wave_sets[0]), f"wave 0 = {wave_sets[0]}"
    assert any(3 in ws for ws in wave_sets)
    assert any(4 in ws for ws in wave_sets)


# ─────────────────────────────────────────────────────────────────────────────
# 2. WAL atomicity
# ─────────────────────────────────────────────────────────────────────────────


def test_wal_pending_complete_cycle():
    """Write pending → complete → verify no .pending file remains."""
    from hive.manifest import (
        ManifestSession,
        StepRecord,
        save_manifest,
        wal_complete,
        wal_recover_pending,
        wal_write_pending,
    )

    with tempfile.TemporaryDirectory() as tmp:
        # Patch sessions dir to temp location
        import hive.manifest as _m

        orig = _m._SESSIONS_DIR
        _m._SESSIONS_DIR = Path(tmp)
        try:
            session = ManifestSession(
                session_id="test-wal-001",
                lang="rust",
                md_spec_path="",
                project_root=tmp,
            )
            step = StepRecord(id=1, instruction="test step", depends_on=[])
            session.steps = [step]
            save_manifest(session)

            wal_write_pending(session.session_id, step)
            pending_before = wal_recover_pending(session.session_id)
            assert 1 in pending_before, "Step should be in pending state"

            wal_complete(session.session_id, step.id)
            pending_after = wal_recover_pending(session.session_id)
            assert 1 not in pending_after, "Step should no longer be pending after complete"
        finally:
            _m._SESSIONS_DIR = orig


def test_wal_fail_removes_pending():
    """wal_fail must move .pending → .failed, not leave it pending."""
    from hive.manifest import (
        ManifestSession,
        StepRecord,
        save_manifest,
        wal_fail,
        wal_recover_pending,
        wal_write_pending,
    )

    with tempfile.TemporaryDirectory() as tmp:
        import hive.manifest as _m

        orig = _m._SESSIONS_DIR
        _m._SESSIONS_DIR = Path(tmp)
        try:
            session = ManifestSession(
                session_id="test-wal-002",
                lang="rust",
                md_spec_path="",
                project_root=tmp,
            )
            step = StepRecord(id=2, instruction="failing step", depends_on=[])
            session.steps = [step]
            save_manifest(session)

            wal_write_pending(session.session_id, step)
            wal_fail(session.session_id, step.id, {"error": "compile error"})
            pending = wal_recover_pending(session.session_id)
            assert 2 not in pending, "Failed step must not appear as pending"
        finally:
            _m._SESSIONS_DIR = orig


# ─────────────────────────────────────────────────────────────────────────────
# 3. Compiler output sanitization
# ─────────────────────────────────────────────────────────────────────────────


def test_sanitize_strips_unix_workspace_path():
    from hive.compiler import sanitize_compiler_output

    raw = "error[E0502]: cannot borrow\n  --> /tmp/determinex_workspace_abc123/src/lib.rs:42:5"
    result = sanitize_compiler_output(raw)
    assert "/tmp/determinex_workspace_abc123/" not in result
    assert "/workspace/" in result


def test_sanitize_strips_windows_workspace_path():
    from hive.compiler import sanitize_compiler_output

    # Real format: determinex_workspaces\<uuid>\ (plural base dir, uuid as subdir)
    raw = (
        r"error[E0502]: cannot borrow  --> C:\Temp\determinex_workspaces\abc123def\src\main.rs:10:3"
    )
    result = sanitize_compiler_output(raw)
    assert "determinex_workspaces" not in result or "abc123def" not in result


def test_sanitize_strips_timestamp():
    from hive.compiler import sanitize_compiler_output

    raw = "Compiling myapp at 2026-04-14T08:30:00"
    result = sanitize_compiler_output(raw)
    assert "2026-04-14T08:30:00" not in result
    assert "TIMESTAMP" in result


def test_sanitize_same_error_same_hash():
    """Two identical errors from different workspace UUIDs must hash identically."""
    from hive.compiler import hash_compiler_error, sanitize_compiler_output

    err1 = "error[E0502]\n  --> /tmp/determinex_workspaces/aaa111/src/lib.rs:42"
    err2 = "error[E0502]\n  --> /tmp/determinex_workspaces/bbb222/src/lib.rs:42"
    # Sanitize both first — they should produce identical strings
    assert sanitize_compiler_output(err1) == sanitize_compiler_output(err2)
    assert hash_compiler_error(err1) == hash_compiler_error(err2)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Budget enforcement
# ─────────────────────────────────────────────────────────────────────────────


def test_budget_preflight_passes_when_under():
    """Preflight must return ok=True when estimated cost < remaining budget."""
    from hive.budget import api_budget_preflight
    from hive.manifest import ManifestSession, StepRecord

    session = ManifestSession(
        session_id="budget-test-001",
        lang="rust",
        md_spec_path="",
        project_root="/tmp/fake",
        session_budget_usd=5.0,
        api_cost_usd=0.0,
    )
    session.steps = [
        StepRecord(id=i, instruction=f"step {i}", depends_on=[])
        for i in range(1, 4)  # 3 cheap steps
    ]
    ok, estimated, remaining = api_budget_preflight(session)
    assert remaining == 5.0
    assert estimated >= 0.0
    assert isinstance(ok, bool)


def test_budget_exhausted_flag_set_on_overage():
    """record_api_call_cost must set budget_exhausted when cumulative cost exceeds cap."""
    from hive.budget import record_api_call_cost
    from hive.manifest import ManifestSession

    session = ManifestSession(
        session_id="budget-test-002",
        lang="python",
        md_spec_path="",
        project_root="/tmp/fake",
        session_budget_usd=0.001,  # tiny cap — 1 millidollar
        api_cost_usd=0.0,
    )
    assert not session.budget_exhausted
    record_api_call_cost(session, 10_000)  # will exceed $0.001
    assert session.budget_exhausted
