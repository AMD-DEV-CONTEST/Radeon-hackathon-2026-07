"""Tests for REAL_TEMP_PATCH_VERIFY_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.real_temp_patch_verify")
rec_mod = importlib.import_module("repair.real_temp_patch_verify_record")
plan_mod = importlib.import_module("repair.real_patch_plan_quarantine")
adm_mod = importlib.import_module("models.real_local_model_admission_record")
spw = importlib.import_module("repair.safe_patch_workspace")

verify = mod.verify
TOKENS = rec_mod.REAL_TEMP_PATCH_VERIFY_STATUS_TOKENS
RealTempPatchVerifyRecord = rec_mod.RealTempPatchVerifyRecord
quarantine = plan_mod.quarantine
RealLocalModelAdmissionRecord = adm_mod.RealLocalModelAdmissionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_TEMP_PATCH_VERIFY_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_temp_patch_verify"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_TEMP_PATCH_VERIFIER_PASSED",
        "REAL_TEMP_PATCH_VERIFIER_FAILED",
        "REAL_TEMP_PATCH_SOURCE_UNCHANGED",
        "REAL_TEMP_PATCH_HUMAN_APPROVAL_REQUIRED",
        "REAL_TEMP_PATCH_BLOCKED_NOT_QUARANTINED",
        "REAL_TEMP_PATCH_BLOCKED_APPLY_REJECTED",
    }
)


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    return ws


def _admission():
    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        task_classes_admitted=("PATCH_GENERATION",),
        opt_in=True,
    )


def _entries():
    return ({"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 2\n"},)


def _make_quarantine(workspace):
    return quarantine(_entries(), admission=_admission(), workspace=workspace, opt_in=True)


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_not_quarantined_blocked(tmp_path):
    r = verify(
        plan=None, plan_entries=_entries(), workspace=_ws(tmp_path), temp_root=tmp_path / "tmp"
    )
    assert r.decision == "REAL_TEMP_PATCH_BLOCKED_NOT_QUARANTINED"


def test_passing_verifier_records_human_approval_required(tmp_path):
    ws = _ws(tmp_path)
    plan = _make_quarantine(ws)
    r = verify(
        plan=plan,
        plan_entries=_entries(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier=spw.stub_verifier_pass,
    )
    assert r.decision == "REAL_TEMP_PATCH_VERIFIER_PASSED"
    assert r.human_approval_required is True
    assert r.original_unchanged is True
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert "REAL_TEMP_PATCH_HUMAN_APPROVAL_REQUIRED" in r.statuses_seen
    assert "REAL_TEMP_PATCH_SOURCE_UNCHANGED" in r.statuses_seen


def test_failing_verifier_blocks(tmp_path):
    ws = _ws(tmp_path)
    plan = _make_quarantine(ws)
    r = verify(
        plan=plan,
        plan_entries=_entries(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier=spw.stub_verifier_fail,
    )
    assert r.decision == "REAL_TEMP_PATCH_VERIFIER_FAILED"
    assert r.human_approval_required is False
    assert r.original_unchanged is True
    assert "REAL_TEMP_PATCH_VERIFIER_FAILED" in r.statuses_seen


def test_original_source_unchanged_after_temp_apply(tmp_path):
    ws = _ws(tmp_path)
    pre = (ws / "src" / "lib.py").read_text(encoding="utf-8")
    plan = _make_quarantine(ws)
    verify(
        plan=plan,
        plan_entries=_entries(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier=spw.stub_verifier_pass,
    )
    post = (ws / "src" / "lib.py").read_text(encoding="utf-8")
    assert pre == post == "x = 1\n"


def test_temp_workspace_contents_modified_but_not_original(tmp_path):
    ws = _ws(tmp_path)
    plan = _make_quarantine(ws)
    r = verify(
        plan=plan,
        plan_entries=_entries(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier=spw.stub_verifier_pass,
    )
    assert r.decision == "REAL_TEMP_PATCH_VERIFIER_PASSED"
    # Diff should be non-empty since temp got the change.
    assert r.unified_diff
    # SHA before and after the original tree should match.
    assert r.original_sha256_before == r.original_sha256_after
    assert r.original_sha256_before  # non-empty


def test_empty_resolved_patches_blocks(tmp_path):
    """If quarantine accepted entries don't match plan_entries by path,
    no patches resolve and we block."""
    ws = _ws(tmp_path)
    plan = _make_quarantine(ws)
    # Pass plan_entries with a different path so resolution fails.
    r = verify(
        plan=plan,
        plan_entries=(
            {"operation": "replace_file", "path": "src/other.py", "new_content": "y = 3\n"},
        ),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier=spw.stub_verifier_pass,
    )
    assert r.decision == "REAL_TEMP_PATCH_BLOCKED_APPLY_REJECTED"


def test_record_serializes_safely(tmp_path):
    ws = _ws(tmp_path)
    plan = _make_quarantine(ws)
    r = verify(
        plan=plan,
        plan_entries=_entries(),
        workspace=ws,
        temp_root=tmp_path / "tmp",
        verifier=spw.stub_verifier_pass,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["original_unchanged"] is True
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


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


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_TEMP_PATCH_VERIFY_LOCK_001"
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
    assert "REAL_TEMP_PATCH_VERIFY_LOCK_001" in ids
