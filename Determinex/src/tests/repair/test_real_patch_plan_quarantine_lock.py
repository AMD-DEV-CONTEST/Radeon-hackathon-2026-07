"""Tests for REAL_PATCH_PLAN_QUARANTINE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.real_patch_plan_quarantine")
rec_mod = importlib.import_module("repair.real_patch_plan_quarantine_record")
adm_mod = importlib.import_module("models.real_local_model_admission_record")

quarantine = mod.quarantine
TOKENS = rec_mod.REAL_PATCH_PLAN_QUARANTINE_STATUS_TOKENS
RealPatchPlanQuarantineRecord = rec_mod.RealPatchPlanQuarantineRecord
RealLocalModelAdmissionRecord = adm_mod.RealLocalModelAdmissionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_PATCH_PLAN_QUARANTINE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_patch_plan_quarantine"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_PATCH_PLAN_QUARANTINED",
        "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
        "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE",
        "REAL_PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION",
        "REAL_PATCH_PLAN_BLOCKED_NO_MODEL",
        "REAL_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
    }
)


def _admitted():
    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        task_classes_admitted=("PATCH_GENERATION",),
        dry_run_default=True,
        opt_in=True,
    )


def _blocked_admission():
    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
        provider="ollama",
        model_id="x",
        task_classes_admitted=(),
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_admission_required(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "x"}],
        admission=None,
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_NO_MODEL"
    assert r.source_mutation_authorized is False


def test_blocked_admission_refused(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "x"}],
        admission=_blocked_admission(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_NO_MODEL"


def test_not_opted_in_blocked(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "x"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=False,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_NOT_OPTED_IN"


def test_valid_entry_quarantined(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": "x=2"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_QUARANTINED"
    assert r.is_quarantined
    assert r.patch_applied is False
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert r.output_trusted is False
    assert len(r.accepted) == 1


def test_absolute_path_rejected_as_escape(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "/etc/passwd", "new_content": "x"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE"


def test_drive_path_rejected_as_escape(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "C:\\Windows\\x", "new_content": "x"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE"


def test_dotdot_path_rejected_as_escape(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "../../etc/passwd", "new_content": "x"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE"


def test_unsupported_operation_rejected(tmp_path):
    r = quarantine(
        [{"operation": "rm_rf", "path": "src/lib.py", "new_content": ""}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION"


def test_missing_operation_is_schema_invalid(tmp_path):
    r = quarantine(
        [{"path": "src/lib.py", "new_content": "x"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID"


def test_nul_byte_in_content_rejected(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": "ok\x00bytes"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert r.decision == "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID"


def test_mixed_accept_and_reject_quarantines_overall(tmp_path):
    r = quarantine(
        [
            {"operation": "replace_file", "path": "src/lib.py", "new_content": "ok"},
            {"operation": "rm_rf", "path": "src/x.py", "new_content": ""},
        ],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    # Has accepted entries → overall QUARANTINED
    assert r.decision == "REAL_PATCH_PLAN_QUARANTINED"
    assert len(r.accepted) == 1
    assert len(r.rejected) == 1


def test_no_filesystem_write(tmp_path):
    target = tmp_path / "src" / "lib.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original\n", encoding="utf-8")
    quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": "EDITED"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    assert target.read_text(encoding="utf-8") == "original\n"


def test_record_serializes_safely(tmp_path):
    r = quarantine(
        [{"operation": "replace_file", "path": "a/b.py", "new_content": "x"}],
        admission=_admitted(),
        workspace=tmp_path,
        opt_in=True,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["patch_applied"] is False
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False
    assert d["output_trusted"] is False


def test_module_does_not_open_network(tmp_path):
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
    assert blob["lock_id"] == "REAL_PATCH_PLAN_QUARANTINE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("patch_applied") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_PATCH_PLAN_QUARANTINE_LOCK_001" in ids
