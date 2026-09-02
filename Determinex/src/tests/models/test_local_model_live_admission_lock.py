"""Tests for LOCAL_MODEL_LIVE_ADMISSION_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

gate_mod = importlib.import_module("models.live_model_admission")
rec_mod = importlib.import_module("models.live_model_admission_record")
policy_mod = importlib.import_module("models.local_model_admission_policy")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")

LiveModelAdmissionGate = gate_mod.LiveModelAdmissionGate
LiveModelAdmissionConfig = gate_mod.LiveModelAdmissionConfig
LiveAdmissionMode = gate_mod.LiveAdmissionMode
LOCAL_MODEL_LIVE_ADMISSION_STATUS_TOKENS = rec_mod.LOCAL_MODEL_LIVE_ADMISSION_STATUS_TOKENS

LocalModelCandidate = policy_mod.LocalModelCandidate
LocalModelAdmissionPolicy = policy_mod.LocalModelAdmissionPolicy
ModelProvider = policy_mod.ModelProvider

ModelRouter = router_mod.ModelRouter
RouterMode = router_mod.RouterMode
TaskClass = router_mod.TaskClass
CURRENT_MODEL_IDS = router_mod.CURRENT_MODEL_IDS
LocalModelInventory = inv_mod.LocalModelInventory

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LOCAL_MODEL_LIVE_ADMISSION_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "local_model_live_admission"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LOCAL_MODEL_LIVE_ADMISSION_STATUS_TOKENS)


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


def _opt_in_config() -> LiveModelAdmissionConfig:
    return LiveModelAdmissionConfig(
        mode=LiveAdmissionMode.OPT_IN_LIVE,
        opt_in_live=True,
    )


def _stocked_inventory() -> LocalModelInventory:
    return LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))


def _route(tc: TaskClass = TaskClass.PATCH_GENERATION):
    return ModelRouter(inventory=_stocked_inventory()).route(tc, mode=RouterMode.LIVE)


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "LOCAL_MODEL_LIVE_ADMISSION_READY",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_DRY_RUN_DEFAULT",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NO_CONFIG",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MODEL_UNAVAILABLE",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_STALE_MODEL_ID",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNPINNED_MODEL",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NETWORK_PROVIDER",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNSUPPORTED_TASK_CLASS",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNKNOWN_PROVIDER",
        "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MISSING_INVENTORY",
        "LOCAL_MODEL_LIVE_ADMISSION_METADATA_ONLY",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_config_is_dry_run_and_not_opt_in():
    cfg = LiveModelAdmissionConfig()
    assert cfg.mode is LiveAdmissionMode.DRY_RUN
    assert cfg.opt_in_live is False
    assert cfg.allow_network_provider is False
    assert cfg.require_pinned_id is True


def test_dry_run_default_blocks_live_call():
    gate = LiveModelAdmissionGate()  # default config = dry_run
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_DRY_RUN_DEFAULT"
    assert rec.live_call_authorized is False
    assert rec.source_mutation_authorized is False
    assert rec.corpus_write_authorized is False
    assert rec.training_eligible is False


# ---------------------------------------------------------------------------
# Happy path — explicit opt-in
# ---------------------------------------------------------------------------


def test_explicit_opt_in_admits_live_call_for_pinned_available_local():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_READY"
    assert rec.live_call_authorized is True
    assert rec.availability_checked is True
    assert rec.pinned is True
    # CRUCIAL: source mutation / corpus / training stay blocked.
    assert rec.source_mutation_authorized is False
    assert rec.corpus_write_authorized is False
    assert rec.training_eligible is False


# ---------------------------------------------------------------------------
# Blocked paths
# ---------------------------------------------------------------------------


def test_opt_in_without_flag_blocks_no_config():
    cfg = LiveModelAdmissionConfig(mode=LiveAdmissionMode.OPT_IN_LIVE, opt_in_live=False)
    gate = LiveModelAdmissionGate(config=cfg)
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NO_CONFIG"
    assert rec.live_call_authorized is False


def test_stale_model_id_blocks():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(model_id="determinex-engineer-v10-dsl"),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_STALE_MODEL_ID"
    assert rec.stale_model_id_detected is True
    assert rec.live_call_authorized is False


def test_unpinned_model_blocks():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(model_id="some-unverified-id"),
        TaskClass.PATCH_GENERATION,
        LocalModelInventory.of(["some-unverified-id"]),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNPINNED_MODEL"
    assert rec.live_call_authorized is False


def test_network_provider_blocked_by_default():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(provider="anthropic"),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_NETWORK_PROVIDER"
    assert rec.network_required is True
    assert rec.live_call_authorized is False


def test_unknown_provider_blocked():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(provider="exotic_provider"),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNKNOWN_PROVIDER"


def test_unsupported_task_class_blocks():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        "NOT_A_TASK_CLASS",
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_UNSUPPORTED_TASK_CLASS"


def test_missing_inventory_blocks():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        LocalModelInventory.empty(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MISSING_INVENTORY"


def test_model_unavailable_blocks():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    # Inventory has SOMETHING (not empty) but not the requested model.
    inv = LocalModelInventory.of(["determinex-observer-v6-dsl"])
    rec = gate.evaluate(
        _valid_candidate(model_id="determinex-engineer-v11-dsl"),
        TaskClass.PATCH_GENERATION,
        inv,
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_BLOCKED_MODEL_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Metadata-only fallthrough
# ---------------------------------------------------------------------------


def test_metadata_only_when_base_policy_refuses_capabilities():
    """If the base policy refuses (e.g. no capabilities) but live opt-in
    is set, the gate emits METADATA_ONLY — live not authorized."""
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(capability_tags=()),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.decision == "LOCAL_MODEL_LIVE_ADMISSION_METADATA_ONLY"
    assert rec.live_call_authorized is False


# ---------------------------------------------------------------------------
# Source / corpus / training-eligibility invariants
# ---------------------------------------------------------------------------


def test_admitted_record_cannot_mutate_source():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.is_ready
    assert rec.source_mutation_authorized is False


def test_admitted_record_cannot_write_corpus():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.corpus_write_authorized is False


def test_admitted_record_cannot_mark_training_eligible():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    assert rec.training_eligible is False


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


def test_route_decision_ref_carried_in_record():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    route = _route(TaskClass.BUILD_DIAGNOSIS)
    rec = gate.evaluate(
        _valid_candidate(supported_task_classes=(TaskClass.BUILD_DIAGNOSIS.value,)),
        TaskClass.BUILD_DIAGNOSIS,
        _stocked_inventory(),
        route,
    )
    assert rec.route_decision_ref == route.decision


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("live_model_admission.py", "live_model_admission_record.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_record_json_round_trip():
    gate = LiveModelAdmissionGate(config=_opt_in_config())
    rec = gate.evaluate(
        _valid_candidate(),
        TaskClass.PATCH_GENERATION,
        _stocked_inventory(),
        _route(),
    )
    parsed = json.loads(rec.to_json())
    assert parsed["decision"] == "LOCAL_MODEL_LIVE_ADMISSION_READY"
    assert parsed["live_call_authorized"] is True
    assert parsed["source_mutation_authorized"] is False


# ---------------------------------------------------------------------------
# Audit guard
# ---------------------------------------------------------------------------


def test_audit_counts_invariants_preserved():
    audit = importlib.import_module("dev.parallel_execution_layer_audit")
    counts = audit.run_audit(_REPO_ROOT / "scripts").counts_by_classification()
    assert counts.get("BLOCKED_UNSAFE", 0) == 0
    assert counts.get("MUST_MIGRATE_TO_HARDENED_RUNNER", 0) == 0
    assert counts.get("UNKNOWN_REQUIRES_REVIEW", 0) == 0


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_LIVE_ADMISSION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    assert blob["scope_discipline"]["live_model_call_made"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_LIVE_ADMISSION_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LOCAL_MODEL_LIVE_ADMISSION_LOCK_001" in ids
