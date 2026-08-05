"""Tests for LOCAL_MODEL_ADMISSION_POLICY_LOCK_001.

Metadata-only admission. No model runs. No subprocess. No network.
Even the ADMITTED decision sets execution_authorized=False.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

policy_mod = importlib.import_module("models.local_model_admission_policy")
rec_mod = importlib.import_module("models.local_model_admission_record")
router_mod = importlib.import_module("models.model_router")

LocalModelAdmissionPolicy = policy_mod.LocalModelAdmissionPolicy
LocalModelAdmissionConfig = policy_mod.LocalModelAdmissionConfig
LocalModelCandidate = policy_mod.LocalModelCandidate
ModelProvider = policy_mod.ModelProvider
LOCAL_MODEL_ADMISSION_STATUS_TOKENS = rec_mod.LOCAL_MODEL_ADMISSION_STATUS_TOKENS
TaskClass = router_mod.TaskClass

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "local_model_admission_policy"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(LOCAL_MODEL_ADMISSION_STATUS_TOKENS)


def _valid_candidate(**overrides) -> LocalModelCandidate:
    base = {
        "model_id": "determinex-engineer-v11-dsl",
        "provider": ModelProvider.OLLAMA.value,
        "capability_tags": ("code_generation",),
        "supported_task_classes": (TaskClass.PATCH_GENERATION.value,),
        "requires_network": False,
        "declared_local": True,
    }
    base.update(overrides)
    return LocalModelCandidate(**base)


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "LOCAL_MODEL_ADMISSION_POLICY_WRITTEN",
        "LOCAL_MODEL_ADMISSION_REQUIRED",
        "LOCAL_MODEL_BLOCKED_STALE_ID",
        "LOCAL_MODEL_BLOCKED_UNKNOWN_PROVIDER",
        "LOCAL_MODEL_BLOCKED_NETWORK_MODEL",
        "LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS",
        "LOCAL_MODEL_BLOCKED_MISSING_CAPABILITIES",
        "LOCAL_MODEL_BLOCKED_UNVERIFIED_ID",
        "LOCAL_MODEL_METADATA_ADMITTED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_config_disallows_network_and_unverified():
    cfg = LocalModelAdmissionConfig()
    assert cfg.allow_network_models is False
    assert cfg.allow_unverified_ids is False


def test_required_emits_required_decision():
    d = LocalModelAdmissionPolicy.required()
    assert d.decision == "LOCAL_MODEL_ADMISSION_REQUIRED"
    assert d.execution_authorized is False
    assert d.metadata_admitted is False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_candidate_metadata_admitted():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate())
    assert d.decision == "LOCAL_MODEL_METADATA_ADMITTED"
    assert d.metadata_admitted is True
    # CRUCIAL: even ADMITTED keeps execution_authorized=False.
    assert d.execution_authorized is False
    assert d.training_eligible is False


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_unknown_provider_blocked():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate(provider="snake_oil_provider"))
    assert d.decision == "LOCAL_MODEL_BLOCKED_UNKNOWN_PROVIDER"
    assert d.execution_authorized is False


def test_stale_model_id_blocked():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate(model_id="determinex-observer-v5-dsl"))
    assert d.decision == "LOCAL_MODEL_BLOCKED_STALE_ID"


def test_network_model_blocked_by_default():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate(requires_network=True))
    assert d.decision == "LOCAL_MODEL_BLOCKED_NETWORK_MODEL"


def test_network_model_admitted_when_explicitly_allowed():
    p = LocalModelAdmissionPolicy(LocalModelAdmissionConfig(allow_network_models=True))
    d = p.evaluate(_valid_candidate(requires_network=True))
    assert d.decision == "LOCAL_MODEL_METADATA_ADMITTED"


def test_unverified_id_blocked_by_default():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate(model_id="some-other-id"))
    assert d.decision == "LOCAL_MODEL_BLOCKED_UNVERIFIED_ID"


def test_unverified_id_admitted_when_explicitly_allowed():
    p = LocalModelAdmissionPolicy(LocalModelAdmissionConfig(allow_unverified_ids=True))
    d = p.evaluate(_valid_candidate(model_id="some-other-id"))
    assert d.decision == "LOCAL_MODEL_METADATA_ADMITTED"


def test_missing_capabilities_blocked():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate(capability_tags=()))
    assert d.decision == "LOCAL_MODEL_BLOCKED_MISSING_CAPABILITIES"


def test_unsupported_task_class_blocked():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate(supported_task_classes=("NOT_A_TASK_CLASS",)))
    assert d.decision == "LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS"


def test_no_model_provider_with_no_capabilities_admitted():
    """The NO_MODEL provider bypasses capability + task-class checks
    because it represents 'we explicitly chose not to use a model.'"""
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(
        _valid_candidate(
            model_id="",
            provider=ModelProvider.NO_MODEL.value,
            capability_tags=(),
            supported_task_classes=(),
        )
    )
    assert d.decision == "LOCAL_MODEL_METADATA_ADMITTED"


# ---------------------------------------------------------------------------
# Execution authorization is NEVER opened by admission alone
# ---------------------------------------------------------------------------


def test_execution_authorized_false_on_every_decision():
    p = LocalModelAdmissionPolicy()
    candidates = [
        _valid_candidate(),  # ADMITTED
        _valid_candidate(provider="bad"),  # UNKNOWN_PROVIDER
        _valid_candidate(model_id="determinex-engineer-v10-dsl"),  # STALE
        _valid_candidate(requires_network=True),  # NETWORK
        _valid_candidate(model_id="unknown"),  # UNVERIFIED
        _valid_candidate(capability_tags=()),  # MISSING_CAPS
        _valid_candidate(supported_task_classes=("X",)),  # TASK_CLASS
    ]
    for c in candidates:
        d = p.evaluate(c)
        assert d.execution_authorized is False
        assert d.training_eligible is False


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("local_model_admission_policy.py", "local_model_admission_record.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_decision_json_round_trip():
    p = LocalModelAdmissionPolicy()
    d = p.evaluate(_valid_candidate())
    parsed = json.loads(d.to_json())
    assert parsed["decision"] == "LOCAL_MODEL_METADATA_ADMITTED"
    assert parsed["execution_authorized"] is False


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    assert blob["scope_discipline"]["live_model_call_made"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001" in ids
