"""Tests for SOURCE_MUTATION_APPLY_DRY_RUN_LOCK_001."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

dry_mod = importlib.import_module("repair.source_mutation_apply_dry_run")
rec_mod = importlib.import_module("repair.source_mutation_apply_record")
ui_mod = importlib.import_module("ide.human_approval_ui_model")

SourceMutationApplyDryRun = dry_mod.SourceMutationApplyDryRun
workspace_hash = dry_mod.workspace_hash
SOURCE_APPLY_DRY_RUN_STATUS_TOKENS = rec_mod.SOURCE_APPLY_DRY_RUN_STATUS_TOKENS
build_packet = ui_mod.build_packet

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "SOURCE_MUTATION_APPLY_DRY_RUN_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "source_mutation_apply_dry_run"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(SOURCE_APPLY_DRY_RUN_STATUS_TOKENS)


def _seed(tmp_path: Path) -> Path:
    ws = tmp_path / "orig"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 0\n", encoding="utf-8")
    return ws


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


def test_status_tokens_match_expected_set():
    expected = {
        "SOURCE_APPLY_DRY_RUN_READY",
        "SOURCE_APPLY_DRY_RUN_BLOCKED_NO_APPROVAL",
        "SOURCE_APPLY_DRY_RUN_BLOCKED_STALE_SOURCE",
        "SOURCE_APPLY_DRY_RUN_BLOCKED_DIFF_MISMATCH",
        "SOURCE_APPLY_DRY_RUN_BLOCKED_VERIFIER_NOT_PASSED",
        "SOURCE_APPLY_DRY_RUN_SOURCE_UNCHANGED",
    }
    assert set(STATUS_TOKENS) == expected


def test_happy_dry_run(tmp_path):
    ws = _seed(tmp_path)
    diff = "--- a/src/lib.py\n+++ b/src/lib.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n"
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    before = _hash_tree(ws)
    rec = SourceMutationApplyDryRun().run(
        ws,
        approval=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "SOURCE_APPLY_DRY_RUN_READY"
    assert rec.source_unchanged is True
    assert rec.training_eligible is False
    assert _hash_tree(ws) == before


def test_no_approval_blocks(tmp_path):
    ws = _seed(tmp_path)
    rec = SourceMutationApplyDryRun().run(
        ws,
        approval=None,
        observed_diff="x",
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "SOURCE_APPLY_DRY_RUN_BLOCKED_NO_APPROVAL"


def test_verifier_not_passed_blocks(tmp_path):
    ws = _seed(tmp_path)
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff="x",
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_FAILED",
    )
    rec = SourceMutationApplyDryRun().run(
        ws,
        approval=packet,
        observed_diff="x",
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_FAILED",
    )
    assert rec.decision == "SOURCE_APPLY_DRY_RUN_BLOCKED_VERIFIER_NOT_PASSED"


def test_diff_mismatch_blocks(tmp_path):
    ws = _seed(tmp_path)
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff="aaaa",
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    rec = SourceMutationApplyDryRun().run(
        ws,
        approval=packet,
        observed_diff="bbbb",
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "SOURCE_APPLY_DRY_RUN_BLOCKED_DIFF_MISMATCH"


def test_stale_source_blocks(tmp_path):
    ws = _seed(tmp_path)
    diff = "x"
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    rec = SourceMutationApplyDryRun().run(
        ws,
        approval=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time="stale-hash",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "SOURCE_APPLY_DRY_RUN_BLOCKED_STALE_SOURCE"


def test_dry_run_never_mutates_source(tmp_path):
    ws = _seed(tmp_path)
    before = _hash_tree(ws)
    diff = "x"
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    SourceMutationApplyDryRun().run(
        ws,
        approval=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert _hash_tree(ws) == before


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("source_mutation_apply_dry_run.py", "source_mutation_apply_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "SOURCE_MUTATION_APPLY_DRY_RUN_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "SOURCE_MUTATION_APPLY_DRY_RUN_LOCK_001" in ids
