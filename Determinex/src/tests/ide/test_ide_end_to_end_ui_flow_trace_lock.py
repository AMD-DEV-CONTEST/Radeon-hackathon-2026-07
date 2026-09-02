"""Tests for IDE_END_TO_END_UI_FLOW_TRACE_LOCK_001."""

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

trace_mod = importlib.import_module("ide.ide_end_to_end_ui_flow_trace")
rec_mod = importlib.import_module("ide.ide_end_to_end_ui_flow_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")

build_ui_flow_trace = trace_mod.build_ui_flow_trace
IDE_END_TO_END_UI_FLOW_TOKENS = rec_mod.IDE_END_TO_END_UI_FLOW_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_END_TO_END_UI_FLOW_TRACE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_end_to_end_ui_flow_trace"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_END_TO_END_UI_FLOW_TOKENS)


def _hash_tree(root: Path):
    out = {}
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


def _seed(tmp_path):
    ws = tmp_path / "orig"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 0\n", encoding="utf-8")
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return ws


def _cfg(tmp_path):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path / "cfg"))
    return w.write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("BUILD_DIAGNOSIS", "PATCH_GENERATION"),
        enabled=True,
    )


def test_status_tokens_match_expected_set():
    expected = {
        "IDE_UI_FLOW_TRACE_WRITTEN",
        "IDE_UI_FLOW_SOURCE_UNCHANGED",
        "IDE_UI_FLOW_APPROVAL_REQUIRED",
        "IDE_UI_FLOW_TRAINING_ELIGIBLE_FALSE",
    }
    assert set(STATUS_TOKENS) == expected


def test_trace_writes_with_all_stages(tmp_path):
    ws = _seed(tmp_path)
    cfg = _cfg(tmp_path)
    before = _hash_tree(ws)
    trace = build_ui_flow_trace(ws, config=cfg, temp_root=tmp_path / "tmp")
    assert "IDE_UI_FLOW_TRACE_WRITTEN" in trace.statuses_seen
    assert "IDE_UI_FLOW_SOURCE_UNCHANGED" in trace.statuses_seen
    assert "IDE_UI_FLOW_APPROVAL_REQUIRED" in trace.statuses_seen
    assert "IDE_UI_FLOW_TRAINING_ELIGIBLE_FALSE" in trace.statuses_seen
    assert trace.source_unchanged is True
    assert trace.approval_required is True
    assert trace.training_eligible is False
    assert _hash_tree(ws) == before


def test_trace_includes_all_seven_stages(tmp_path):
    ws = _seed(tmp_path)
    cfg = _cfg(tmp_path)
    trace = build_ui_flow_trace(ws, config=cfg, temp_root=tmp_path / "tmp")
    names = [s.name for s in trace.stages]
    assert names == [
        "open_workspace",
        "model_route_panel",
        "diagnose",
        "patch_plan",
        "temp_verify",
        "approval_packet",
        "source_apply_gate",
    ]


def test_trace_json_round_trip(tmp_path):
    ws = _seed(tmp_path)
    cfg = _cfg(tmp_path)
    trace = build_ui_flow_trace(ws, config=cfg, temp_root=tmp_path / "tmp")
    parsed = json.loads(trace.to_json())
    assert parsed["training_eligible"] is False
    assert parsed["approval_required"] is True


def test_module_does_not_import_subprocess_or_urllib():
    for fname in ("ide_end_to_end_ui_flow_trace.py", "ide_end_to_end_ui_flow_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_END_TO_END_UI_FLOW_TRACE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_END_TO_END_UI_FLOW_TRACE_LOCK_001" in ids
