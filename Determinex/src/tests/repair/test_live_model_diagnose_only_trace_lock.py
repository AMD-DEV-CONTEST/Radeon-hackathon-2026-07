"""Tests for LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001."""

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

trace_mod = importlib.import_module("repair.live_diagnose_trace")
rec_mod = importlib.import_module("repair.live_diagnose_trace_record")
admission_mod = importlib.import_module("models.live_model_admission")
admission_rec = importlib.import_module("models.live_model_admission_record")
harness_mod = importlib.import_module("models.live_model_compat_harness")
policy_mod = importlib.import_module("models.local_model_admission_policy")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")

LiveDiagnoseTraceRunner = trace_mod.LiveDiagnoseTraceRunner
LIVE_DIAGNOSE_STATUS_TOKENS = rec_mod.LIVE_DIAGNOSE_STATUS_TOKENS
allowed_task_classes = rec_mod.allowed_task_classes

LiveModelAdmissionGate = admission_mod.LiveModelAdmissionGate
LiveModelAdmissionConfig = admission_mod.LiveModelAdmissionConfig
LiveAdmissionMode = admission_mod.LiveAdmissionMode

DeterministicProvider = harness_mod.DeterministicProvider
TimeoutProvider = harness_mod.TimeoutProvider
EmptyProvider = harness_mod.EmptyProvider

LocalModelCandidate = policy_mod.LocalModelCandidate
ModelProvider = policy_mod.ModelProvider

ModelRouter = router_mod.ModelRouter
RouterMode = router_mod.RouterMode
TaskClass = router_mod.TaskClass
CURRENT_MODEL_IDS = router_mod.CURRENT_MODEL_IDS
LocalModelInventory = inv_mod.LocalModelInventory

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "live_model_diagnose_only_trace"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LIVE_DIAGNOSE_STATUS_TOKENS)


def _stocked_inventory() -> LocalModelInventory:
    return LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))


def _admission_ready():
    gate = LiveModelAdmissionGate(
        config=LiveModelAdmissionConfig(
            mode=LiveAdmissionMode.OPT_IN_LIVE,
            opt_in_live=True,
        )
    )
    candidate = LocalModelCandidate(
        model_id="determinex-engineer-v11-dsl",
        provider=ModelProvider.OLLAMA.value,
        capability_tags=("diagnose",),
        supported_task_classes=(TaskClass.BUILD_DIAGNOSIS.value,),
    )
    return gate.evaluate(
        candidate,
        TaskClass.BUILD_DIAGNOSIS,
        _stocked_inventory(),
        ModelRouter(inventory=_stocked_inventory()).route(
            TaskClass.BUILD_DIAGNOSIS, mode=RouterMode.LIVE
        ),
    )


def _admission_blocked():
    # Dry-run default → blocked admission record.
    gate = LiveModelAdmissionGate()  # default config = dry_run
    candidate = LocalModelCandidate(
        model_id="determinex-engineer-v11-dsl",
        provider=ModelProvider.OLLAMA.value,
        capability_tags=("diagnose",),
        supported_task_classes=(TaskClass.BUILD_DIAGNOSIS.value,),
    )
    return gate.evaluate(
        candidate,
        TaskClass.BUILD_DIAGNOSIS,
        _stocked_inventory(),
        ModelRouter(inventory=_stocked_inventory()).route(TaskClass.BUILD_DIAGNOSIS),
    )


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


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "LIVE_DIAGNOSE_TRACE_WRITTEN",
        "LIVE_DIAGNOSE_BLOCKED_MODEL_NOT_ADMITTED",
        "LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
        "LIVE_DIAGNOSE_RESPONSE_CAPTURED_ADVISORY_ONLY",
        "LIVE_DIAGNOSE_NO_SOURCE_MUTATION",
        "LIVE_DIAGNOSE_BLOCKED_PROVIDER_REJECTED",
    }
    assert set(STATUS_TOKENS) == expected


def test_allowed_task_classes_are_diagnose_only():
    assert allowed_task_classes() == frozenset(
        {
            "BUILD_DIAGNOSIS",
            "TEST_FAILURE_LOCALIZATION",
        }
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_admitted_provider_produces_advisory_trace():
    runner = LiveDiagnoseTraceRunner()
    provider = DeterministicProvider(canned={"summary": "fixture diagnose"})
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        admission=_admission_ready(),
        provider=provider,
    )
    assert trace.is_written
    assert trace.advisory_only is True
    assert trace.patch_generated is False
    assert trace.source_mutation_authorized is False
    assert trace.corpus_write_authorized is False
    assert trace.training_eligible is False
    assert "LIVE_DIAGNOSE_TRACE_WRITTEN" in trace.statuses_seen
    assert "LIVE_DIAGNOSE_RESPONSE_CAPTURED_ADVISORY_ONLY" in trace.statuses_seen
    assert "LIVE_DIAGNOSE_NO_SOURCE_MUTATION" in trace.statuses_seen


def test_test_failure_localization_also_admitted():
    runner = LiveDiagnoseTraceRunner()
    provider = DeterministicProvider(canned={"summary": "localized at lib.py:3"})
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="TEST_FAILURE_LOCALIZATION",
        admission=_admission_ready(),
        provider=provider,
    )
    assert trace.is_written


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_admission_not_ready_blocks():
    runner = LiveDiagnoseTraceRunner()
    provider = DeterministicProvider(canned={"summary": "ok"})
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        admission=_admission_blocked(),
        provider=provider,
    )
    assert trace.decision == "LIVE_DIAGNOSE_BLOCKED_MODEL_NOT_ADMITTED"
    assert trace.patch_generated is False
    assert trace.source_mutation_authorized is False


def test_unsupported_task_class_blocks():
    runner = LiveDiagnoseTraceRunner()
    provider = DeterministicProvider(canned={"summary": "ok"})
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="PATCH_GENERATION",  # not allowed for diagnose-only
        admission=_admission_ready(),
        provider=provider,
    )
    assert trace.decision == "LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK"


def test_provider_timeout_blocks_provider_rejected():
    runner = LiveDiagnoseTraceRunner()
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        admission=_admission_ready(),
        provider=TimeoutProvider(),
    )
    assert trace.decision == "LIVE_DIAGNOSE_BLOCKED_PROVIDER_REJECTED"


def test_empty_provider_blocks_provider_rejected():
    runner = LiveDiagnoseTraceRunner()
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        admission=_admission_ready(),
        provider=EmptyProvider(),
    )
    assert trace.decision == "LIVE_DIAGNOSE_BLOCKED_PROVIDER_REJECTED"


# ---------------------------------------------------------------------------
# Source-preservation
# ---------------------------------------------------------------------------


def test_runner_does_not_mutate_workspace():
    runner = LiveDiagnoseTraceRunner()
    provider = DeterministicProvider(canned={"summary": "ok"})
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    runner.run(
        ws,
        task_class="BUILD_DIAGNOSIS",
        admission=_admission_ready(),
        provider=provider,
    )
    after = _hash_tree(ws)
    assert before == after


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("live_diagnose_trace.py", "live_diagnose_trace_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src


def test_trace_json_round_trip():
    runner = LiveDiagnoseTraceRunner()
    trace = runner.run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        admission=_admission_ready(),
        provider=DeterministicProvider(canned={"summary": "ok"}),
    )
    parsed = json.loads(trace.to_json())
    assert parsed["decision"] == "LIVE_DIAGNOSE_TRACE_WRITTEN"
    assert parsed["training_eligible"] is False


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001" in ids
