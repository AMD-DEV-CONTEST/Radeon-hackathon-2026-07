"""Tests for REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.real_model_patch_plan_with_verifier_context")
rec_mod = importlib.import_module("repair.real_model_patch_plan_with_verifier_context_record")
hc_mod = importlib.import_module("models.real_local_model_healthcheck_record")
sel_mod = importlib.import_module("repair.build_adapter_backed_verifier_selection_record")

quarantine_with_verifier_context = mod.quarantine_with_verifier_context
TOKENS = rec_mod.REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_STATUS_TOKENS
RealModelPatchPlanWithVerifierContextRecord = rec_mod.RealModelPatchPlanWithVerifierContextRecord
RealLocalModelHealthcheckRecord = hc_mod.RealLocalModelHealthcheckRecord
BuildAdapterBackedVerifierSelectionRecord = sel_mod.BuildAdapterBackedVerifierSelectionRecord

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_model_patch_plan_with_verifier_context"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_PATCH_PLAN_CONTEXT_QUARANTINED",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NO_VERIFIER",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_HEALTHCHECK",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NOT_OPTED_IN",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_SCHEMA_INVALID",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_PATH_ESCAPE",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_UNSUPPORTED_OPERATION",
        "REAL_PATCH_PLAN_CONTEXT_OUTPUT_UNTRUSTED",
        "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED",
    }
)


def _admission_admitted():
    """Real admission record matching the healthcheck fixture."""
    from models.real_local_model_admission_record import (
        RealLocalModelAdmissionRecord,
    )

    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        task_classes_admitted=("PATCH_GENERATION",),
        dry_run_default=True,
        opt_in=True,
    )


def _hc_passed():
    return RealLocalModelHealthcheckRecord(
        decision="REAL_LOCAL_MODEL_HEALTHCHECK_PASSED",
        model_id="determinex-engineer-v11-dsl",
        provider="ollama",
        endpoint="http://127.0.0.1:11434",
        prompt="trivial",
        response_chars=2,
        elapsed_ms=200,
    )


def _hc_failed():
    return RealLocalModelHealthcheckRecord(
        decision="REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_TIMEOUT",
        model_id="determinex-engineer-v11-dsl",
        provider="ollama",
        endpoint="http://127.0.0.1:11434",
        prompt="trivial",
        response_chars=0,
        elapsed_ms=5000,
    )


def _sel_selected():
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_SELECTED",
        workspace="/ws",
        adapter_name="Python",
        build_system_id="pip",
        test_framework_id="pytest",
        verifier_command=("pytest",),
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


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_healthcheck_failed_blocks(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_failed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/x.py", "new_content": "x = 1\n"}],
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_HEALTHCHECK"


def test_verifier_not_selected_blocks(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_blocked(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/x.py", "new_content": "x = 1\n"}],
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NO_VERIFIER"


def test_not_opted_in_blocks(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/x.py", "new_content": "x = 1\n"}],
        opt_in=False,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NOT_OPTED_IN"


def test_valid_plan_quarantined(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[
            {"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 2\n"}
        ],
        admission=_admission_admitted(),
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_QUARANTINED"
    assert r.quarantined is True
    assert r.patch_applied is False
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert r.output_trusted is False
    assert r.build_system_id == "pip"
    assert r.verifier_command == ("pytest",)
    assert "REAL_PATCH_PLAN_CONTEXT_OUTPUT_UNTRUSTED" in r.statuses_seen


def test_path_escape_blocks(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "../escape", "new_content": "x"}],
        admission=_admission_admitted(),
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_PATH_ESCAPE"


def test_unsupported_operation_blocks(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "rm_rf", "path": "src/lib.py", "new_content": ""}],
        admission=_admission_admitted(),
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_UNSUPPORTED_OPERATION"


def test_schema_invalid_blocks(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"path": "src/lib.py", "new_content": "x"}],  # no operation
        admission=_admission_admitted(),
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_SCHEMA_INVALID"


def test_no_filesystem_write(tmp_path):
    target = tmp_path / "src" / "lib.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original\n", encoding="utf-8")
    quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/lib.py", "new_content": "EDITED"}],
        admission=_admission_admitted(),
        opt_in=True,
    )
    assert target.read_text(encoding="utf-8") == "original\n"


def test_claude_auth_004_missing_admission_blocks(tmp_path):
    """CLAUDE-AUTH-004: no admission supplied → blocked, no synthesis."""
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/lib.py", "new_content": "x"}],
        admission=None,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED"


def test_claude_auth_004_blocked_admission_blocks(tmp_path):
    """CLAUDE-AUTH-004: not-admitted admission → blocked."""
    from models.real_local_model_admission_record import (
        RealLocalModelAdmissionRecord,
    )

    blocked = RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_BLOCKED_STALE",
        provider="ollama",
        model_id="determinex-engineer-v10-dsl",
        task_classes_admitted=(),
    )
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/lib.py", "new_content": "x"}],
        admission=blocked,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED"


def test_claude_auth_004_admission_model_must_match_healthcheck(tmp_path):
    """CLAUDE-AUTH-004: admission's model_id/provider must match healthcheck."""
    from models.real_local_model_admission_record import (
        RealLocalModelAdmissionRecord,
    )

    mismatched = RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider="ollama",
        model_id="determinex-observer-v6-dsl",  # ≠ healthcheck.model_id
        task_classes_admitted=("PATCH_GENERATION",),
        opt_in=True,
    )
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "src/lib.py", "new_content": "x"}],
        admission=mismatched,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED"


def test_module_does_not_open_network():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "httpx",
        "urllib.request",
        "socket.connect",
        "subprocess.Popen",
        "subprocess.run",
    ):
        assert forbidden not in src


def test_record_serializes_safely(tmp_path):
    r = quarantine_with_verifier_context(
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        workspace=tmp_path,
        plan_entries=[{"operation": "replace_file", "path": "a/b.py", "new_content": "x"}],
        admission=_admission_admitted(),
        opt_in=True,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["patch_applied"] is False
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False
    assert d["output_trusted"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("patch_applied") is False
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001" in ids
