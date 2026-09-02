"""Tests for OPT_IN_LIVE_DIAGNOSE_COMMAND_LOCK_001."""

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

cmd_mod = importlib.import_module("repair.opt_in_live_diagnose_command")
rec_mod = importlib.import_module("repair.opt_in_live_diagnose_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")
harness_mod = importlib.import_module("models.live_model_compat_harness")

OptInLiveDiagnoseCommand = cmd_mod.OptInLiveDiagnoseCommand
OPT_IN_LIVE_DIAGNOSE_STATUS_TOKENS = rec_mod.OPT_IN_LIVE_DIAGNOSE_STATUS_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

DeterministicProvider = harness_mod.DeterministicProvider
TimeoutProvider = harness_mod.TimeoutProvider

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "OPT_IN_LIVE_DIAGNOSE_COMMAND_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "opt_in_live_diagnose_command"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(OPT_IN_LIVE_DIAGNOSE_STATUS_TOKENS)


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


def _cfg(tmp_path: Path):
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
        "OPT_IN_LIVE_DIAGNOSE_READY",
        "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NO_MODEL_CONFIG",
        "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
        "OPT_IN_LIVE_DIAGNOSE_BLOCKED_PROVIDER_UNAVAILABLE",
        "OPT_IN_LIVE_DIAGNOSE_ADVISORY_WRITTEN",
        "OPT_IN_LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
    }
    assert set(STATUS_TOKENS) == expected


def test_no_opt_in_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInLiveDiagnoseCommand().run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        config=cfg,
        provider=DeterministicProvider(canned={"summary": "ok"}),
        opt_in=False,
    )
    assert rec.decision == "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN"
    assert rec.source_mutation_authorized is False


def test_no_model_config_blocks(tmp_path):
    rec = OptInLiveDiagnoseCommand().run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        config=None,
        provider=DeterministicProvider(canned={"summary": "x"}),
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NO_MODEL_CONFIG"


def test_unsupported_task_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInLiveDiagnoseCommand().run(
        FIXTURES / "python_broken",
        task_class="PATCH_GENERATION",
        config=cfg,
        provider=DeterministicProvider(canned={"summary": "x"}),
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK"


def test_provider_unavailable_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInLiveDiagnoseCommand().run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        config=cfg,
        provider=TimeoutProvider(),
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_LIVE_DIAGNOSE_BLOCKED_PROVIDER_UNAVAILABLE"


def test_happy_path_writes_advisory(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInLiveDiagnoseCommand().run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        config=cfg,
        provider=DeterministicProvider(canned={"summary": "fixture diagnose"}),
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_LIVE_DIAGNOSE_READY"
    assert rec.advisory_only is True
    assert rec.patch_generated is False
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False
    assert "OPT_IN_LIVE_DIAGNOSE_ADVISORY_WRITTEN" in rec.statuses_seen


def test_command_does_not_mutate_workspace(tmp_path):
    cfg = _cfg(tmp_path)
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    OptInLiveDiagnoseCommand().run(
        ws,
        task_class="BUILD_DIAGNOSIS",
        config=cfg,
        provider=DeterministicProvider(canned={"summary": "x"}),
        opt_in=True,
    )
    assert _hash_tree(ws) == before


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("opt_in_live_diagnose_command.py", "opt_in_live_diagnose_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "OPT_IN_LIVE_DIAGNOSE_COMMAND_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "OPT_IN_LIVE_DIAGNOSE_COMMAND_LOCK_001" in ids
