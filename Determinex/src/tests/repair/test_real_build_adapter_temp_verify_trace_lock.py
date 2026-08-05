"""Tests for REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.real_build_adapter_temp_verify_trace")
rec_mod = importlib.import_module("repair.real_build_adapter_temp_verify_trace_record")
plan_rec_mod = importlib.import_module("repair.real_model_patch_plan_with_verifier_context_record")
sel_mod = importlib.import_module("repair.build_adapter_backed_verifier_selection_record")

trace = mod.trace
TOKENS = rec_mod.REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_STATUS_TOKENS
RealBuildAdapterTempVerifyTraceRecord = rec_mod.RealBuildAdapterTempVerifyTraceRecord
RealModelPatchPlanWithVerifierContextRecord = (
    plan_rec_mod.RealModelPatchPlanWithVerifierContextRecord
)
RealPatchPlanContextEntry = plan_rec_mod.RealPatchPlanContextEntry
BuildAdapterBackedVerifierSelectionRecord = sel_mod.BuildAdapterBackedVerifierSelectionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_build_adapter_temp_verify_trace"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_PASSED_APPROVAL_REQUIRED",
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_FAILED",
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_SOURCE_UNCHANGED",
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NO_VERIFIER",
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NOT_QUARANTINED",
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_HARDENED_RUNNER",
        "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_APPLY_REJECTED",
    }
)


def _ws_python(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    # Minimal pytest discoverable test that passes.
    (ws / "tests").mkdir()
    (ws / "tests" / "test_x.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    return ws


def _ws_python_failing(tmp_path):
    ws = _ws_python(tmp_path)
    (ws / "tests" / "test_x.py").write_text(
        "def test_fail():\n    assert False\n",
        encoding="utf-8",
    )
    return ws


def _plan_quarantined():
    return RealModelPatchPlanWithVerifierContextRecord(
        decision="REAL_PATCH_PLAN_CONTEXT_QUARANTINED",
        workspace="/ws",
        model_id="determinex-engineer-v11-dsl",
        provider="ollama",
        build_system_id="pip",
        verifier_command=("pytest",),
        accepted=(
            RealPatchPlanContextEntry(
                operation="replace_file",
                path="src/lib.py",
                new_content_chars=6,
            ),
        ),
        rejected=tuple(),
        quarantined=True,
        output_trusted=False,
        patch_applied=False,
    )


def _plan_blocked():
    return RealModelPatchPlanWithVerifierContextRecord(
        decision="REAL_PATCH_PLAN_CONTEXT_BLOCKED_PATH_ESCAPE",
        workspace="/ws",
        model_id="x",
        provider="ollama",
        build_system_id="",
        verifier_command=(),
        accepted=tuple(),
        rejected=tuple(),
        quarantined=False,
    )


def _sel_selected(argv=("pytest", "-q")):
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_SELECTED",
        workspace="/ws",
        adapter_name="Python",
        build_system_id="pip",
        test_framework_id=" ".join(argv),
        verifier_command=tuple(argv),
        hardened_runner="intake.hardened_runner",
        multi_match=False,
        matched_adapters=("Python",),
    )


def _sel_blocked():
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO",
        workspace="/ws",
        adapter_name="",
        build_system_id="",
        test_framework_id="",
        verifier_command=(),
        hardened_runner="intake.hardened_runner",
        multi_match=False,
        matched_adapters=(),
    )


def _entries():
    return ({"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 2\n"},)


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_plan_not_quarantined_blocks(tmp_path):
    r = trace(
        plan=_plan_blocked(),
        plan_entries=_entries(),
        verifier_selection=_sel_selected(),
        workspace=_ws_python(tmp_path),
        temp_root=tmp_path / "tmp",
    )
    assert r.decision == "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NOT_QUARANTINED"


def test_verifier_not_selected_blocks(tmp_path):
    r = trace(
        plan=_plan_quarantined(),
        plan_entries=_entries(),
        verifier_selection=_sel_blocked(),
        workspace=_ws_python(tmp_path),
        temp_root=tmp_path / "tmp",
    )
    assert r.decision == "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NO_VERIFIER"


def test_passing_verifier_records_approval_required(tmp_path):
    ws = _ws_python(tmp_path)
    pre = (ws / "src" / "lib.py").read_text(encoding="utf-8")
    r = trace(
        plan=_plan_quarantined(),
        plan_entries=_entries(),
        verifier_selection=_sel_selected(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier_timeout_seconds=120,
    )
    assert r.decision == "REAL_BUILD_ADAPTER_TEMP_VERIFY_PASSED_APPROVAL_REQUIRED"
    assert r.human_approval_required is True
    assert r.original_unchanged is True
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    # Source unchanged.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == pre


def test_failing_verifier_blocks(tmp_path):
    ws = _ws_python_failing(tmp_path)
    pre = (ws / "src" / "lib.py").read_text(encoding="utf-8")
    r = trace(
        plan=_plan_quarantined(),
        plan_entries=_entries(),
        verifier_selection=_sel_selected(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier_timeout_seconds=120,
    )
    assert r.decision == "REAL_BUILD_ADAPTER_TEMP_VERIFY_FAILED"
    assert r.human_approval_required is False
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == pre


def test_record_serializes_safely(tmp_path):
    ws = _ws_python(tmp_path)
    r = trace(
        plan=_plan_quarantined(),
        plan_entries=_entries(),
        verifier_selection=_sel_selected(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


def test_module_does_not_open_network():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "urllib.request", "socket.connect"):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("network_called") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_LOCK_001" in ids
