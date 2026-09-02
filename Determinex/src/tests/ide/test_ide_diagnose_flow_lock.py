"""Tests for IDE_DIAGNOSE_FLOW_LOCK_001."""

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

flow_mod = importlib.import_module("ide.diagnose_flow")
rec_mod = importlib.import_module("ide.diagnose_flow_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")
harness_mod = importlib.import_module("models.live_model_compat_harness")

IDEDiagnoseFlow = flow_mod.IDEDiagnoseFlow
IDE_DIAGNOSE_FLOW_STATUS_TOKENS = rec_mod.IDE_DIAGNOSE_FLOW_STATUS_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

DeterministicProvider = harness_mod.DeterministicProvider
TimeoutProvider = harness_mod.TimeoutProvider

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_DIAGNOSE_FLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_diagnose_flow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_DIAGNOSE_FLOW_STATUS_TOKENS)


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


def _cfg(tmp_path):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path))
    return w.write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("diagnose",),
        task_classes_allowed=("BUILD_DIAGNOSIS",),
        enabled=True,
    )


def test_status_tokens_match_expected_set():
    expected = {
        "IDE_DIAGNOSE_DRY_RUN_READY",
        "IDE_DIAGNOSE_LIVE_OPT_IN_READY",
        "IDE_DIAGNOSE_BLOCKED_NO_MODEL",
        "IDE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
        "IDE_DIAGNOSE_ADVISORY_AVAILABLE",
        "IDE_DIAGNOSE_SOURCE_UNCHANGED",
        "IDE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
    }
    assert set(STATUS_TOKENS) == expected


def test_dry_run_default(tmp_path):
    rec = IDEDiagnoseFlow().run(FIXTURES / "python_broken", mode="dry_run")
    assert rec.decision == "IDE_DIAGNOSE_DRY_RUN_READY"
    assert rec.patch_generated is False
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_live_opt_in_with_config(tmp_path):
    cfg = _cfg(tmp_path)
    rec = IDEDiagnoseFlow().run(
        FIXTURES / "python_broken",
        mode="live_opt_in",
        config=cfg,
        provider=DeterministicProvider(canned={"summary": "ok"}),
    )
    assert rec.decision == "IDE_DIAGNOSE_LIVE_OPT_IN_READY"
    assert "IDE_DIAGNOSE_ADVISORY_AVAILABLE" in rec.statuses_seen
    assert rec.training_eligible is False


def test_live_opt_in_without_config_blocks():
    rec = IDEDiagnoseFlow().run(
        FIXTURES / "python_broken",
        mode="live_opt_in",
        config=None,
        provider=DeterministicProvider(canned={"summary": "ok"}),
    )
    assert rec.decision == "IDE_DIAGNOSE_BLOCKED_NO_MODEL"


def test_unsupported_task_blocks():
    rec = IDEDiagnoseFlow().run(
        FIXTURES / "python_broken",
        task_class="PATCH_GENERATION",
    )
    assert rec.decision == "IDE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK"


def test_provider_unavailable_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    rec = IDEDiagnoseFlow().run(
        FIXTURES / "python_broken",
        mode="live_opt_in",
        config=cfg,
        provider=TimeoutProvider(),
    )
    assert rec.decision == "IDE_DIAGNOSE_BLOCKED_NOT_OPTED_IN"


def test_flow_does_not_mutate_workspace(tmp_path):
    cfg = _cfg(tmp_path)
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    IDEDiagnoseFlow().run(
        ws,
        mode="live_opt_in",
        config=cfg,
        provider=DeterministicProvider(canned={"summary": "x"}),
    )
    assert _hash_tree(ws) == before


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("diagnose_flow.py", "diagnose_flow_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_DIAGNOSE_FLOW_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_DIAGNOSE_FLOW_LOCK_001" in ids
