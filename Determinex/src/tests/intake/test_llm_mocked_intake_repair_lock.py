"""Tests for LLM_MOCKED_INTAKE_REPAIR_LOCK_001.

Wires the model router into the intake/diagnose/repair path using
mocked model outputs only. Asserts that:

  * Every fixture (python_broken, rust_broken, go_broken, ts_broken)
    drives a clean trace where:
      - diagnose route was selected
      - patch plan was generated
      - patch was NOT applied to source
      - verifier result was captured
      - training_eligible is False
  * The unsupported repo fixture terminates with terminus=UNSUPPORTED_REPO
    and never invokes the mock.
  * The loop performs no network/subprocess work and never mutates the
    fixture tree (sha256 before/after equality).
  * The mock client refuses to fabricate a response for an
    unauthorized route.
  * The lock manifest, evidence artifact, and evidence_index entry are
    all present and well-formed.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

loop_mod = importlib.import_module("intake.mocked_intake_repair")
record_mod = importlib.import_module("intake.mocked_repair_loop_record")
router_mod = importlib.import_module("models.model_router")
mock_mod = importlib.import_module("models.mock_client")
inventory_mod = importlib.import_module("models.model_inventory")

MockedIntakeRepairLoop = loop_mod.MockedIntakeRepairLoop
MockedIntakeRepairTrace = loop_mod.MockedIntakeRepairTrace
default_mock_canned = loop_mod.default_mock_canned
TASK_CLASS_PIPELINE = loop_mod.TASK_CLASS_PIPELINE
MOCKED_LOOP_STATUS_TOKENS = loop_mod.MOCKED_LOOP_STATUS_TOKENS

MockModelClient = mock_mod.MockModelClient
LocalModelInventory = inventory_mod.LocalModelInventory
ModelRouter = router_mod.ModelRouter
TaskClass = router_mod.TaskClass
RouterMode = router_mod.RouterMode
CURRENT_MODEL_IDS = router_mod.CURRENT_MODEL_IDS

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LLM_MOCKED_INTAKE_REPAIR_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "llm_mocked_intake_repair"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(
    {
        "DIAGNOSE_MOCK_ROUTE_SELECTED",
        "PATCH_PLAN_MOCK_GENERATED",
        "PATCH_NOT_APPLIED_TO_SOURCE",
        "VERIFIER_RESULT_CAPTURED",
        "TRAINING_ELIGIBLE_FALSE",
        "EVIDENCE_WRITTEN",
        "UNSUPPORTED_REPO_BLOCKED",
        "NO_NETWORK_CALL_MADE",
        "NO_SUBPROCESS_CALL_MADE",
        "NO_SOURCE_MUTATION",
    }
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


def _stocked_router() -> ModelRouter:
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
    return ModelRouter(inventory=inv)


@pytest.fixture
def loop() -> MockedIntakeRepairLoop:
    return MockedIntakeRepairLoop(
        router=_stocked_router(),
        mock_client=MockModelClient(default_mock_canned()),
    )


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "DIAGNOSE_MOCK_ROUTE_SELECTED",
        "PATCH_PLAN_MOCK_GENERATED",
        "PATCH_NOT_APPLIED_TO_SOURCE",
        "VERIFIER_RESULT_CAPTURED",
        "TRAINING_ELIGIBLE_FALSE",
        "EVIDENCE_WRITTEN",
        "UNSUPPORTED_REPO_BLOCKED",
        "NO_NETWORK_CALL_MADE",
        "NO_SUBPROCESS_CALL_MADE",
        "NO_SOURCE_MUTATION",
    }
    assert set(STATUS_TOKENS) == expected
    assert set(MOCKED_LOOP_STATUS_TOKENS) == expected


def test_record_module_reexports_trace_types():
    assert record_mod.MockedIntakeRepairTrace is MockedIntakeRepairTrace
    assert record_mod.MOCKED_LOOP_STATUS_TOKENS is MOCKED_LOOP_STATUS_TOKENS


# ---------------------------------------------------------------------------
# Pipeline coverage — four supported fixtures
# ---------------------------------------------------------------------------


SUPPORTED_FIXTURES = [
    ("python_broken", "pip"),
    ("rust_broken", "cargo"),
    ("go_broken", "go"),
    ("ts_broken", "npm"),
]


@pytest.mark.parametrize("fixture_name,expected_build_system", SUPPORTED_FIXTURES)
def test_loop_drives_supported_fixture_to_complete_trace(loop, fixture_name, expected_build_system):
    ws = FIXTURES / fixture_name
    assert ws.is_dir(), f"Missing fixture: {ws}"
    trace = loop.run(ws)
    assert trace.build_system_id == expected_build_system, (
        f"{fixture_name}: expected {expected_build_system}, got {trace.build_system_id}"
    )
    assert trace.terminus == "MOCK_LOOP_COMPLETE"
    assert trace.diagnose_mock_route_selected is True
    assert trace.patch_plan_mock_generated is True
    assert trace.patch_not_applied_to_source is True
    assert trace.verifier_result_captured is True
    assert trace.training_eligible is False


@pytest.mark.parametrize("fixture_name,_bs", SUPPORTED_FIXTURES)
def test_loop_does_not_mutate_fixture_tree(loop, fixture_name, _bs):
    ws = FIXTURES / fixture_name
    before = _hash_tree(ws)
    loop.run(ws)
    after = _hash_tree(ws)
    assert before == after, f"Loop mutated fixture {fixture_name}"


@pytest.mark.parametrize("fixture_name,_bs", SUPPORTED_FIXTURES)
def test_loop_walks_full_task_class_pipeline(loop, fixture_name, _bs):
    ws = FIXTURES / fixture_name
    trace = loop.run(ws)
    seen = [s.task_class for s in trace.steps]
    expected = [tc.value for tc in TASK_CLASS_PIPELINE]
    assert seen == expected, f"{fixture_name}: step order mismatch {seen} vs {expected}"


# ---------------------------------------------------------------------------
# Unsupported repo
# ---------------------------------------------------------------------------


def test_unsupported_repo_blocks_without_invoking_mock(loop):
    ws = FIXTURES / "unsupported_repo"
    assert ws.is_dir(), f"Missing unsupported_repo fixture: {ws}"
    trace = loop.run(ws)
    assert trace.terminus == "UNSUPPORTED_REPO"
    assert trace.diagnose_mock_route_selected is False
    assert trace.patch_plan_mock_generated is False
    assert trace.patch_not_applied_to_source is True
    assert trace.training_eligible is False
    # No mock calls should have been made.
    for step in trace.steps:
        assert step.invoked_mock is False


def test_unsupported_repo_terminus_status_token_in_lock():
    """The UNSUPPORTED_REPO_BLOCKED token must be in MOCKED_LOOP_STATUS_TOKENS."""
    assert "UNSUPPORTED_REPO_BLOCKED" in MOCKED_LOOP_STATUS_TOKENS


# ---------------------------------------------------------------------------
# Mock client invariants
# ---------------------------------------------------------------------------


def test_mock_client_refuses_unauthorized_route():
    """If a RouteRecord has execution_authorized=False, MockModelClient
    must raise rather than fabricate a response."""
    from models.model_router_record import RouteRecord

    client = MockModelClient(default_mock_canned())
    blocked = RouteRecord(
        task_class=TaskClass.BUILD_DIAGNOSIS.value,
        requested_mode="live",
        selected_route="NO_MODEL",
        selected_model_id="",
        fallback_chain=("NO_MODEL",),
        availability_checked=False,
        stale_model_id_detected=False,
        decision="ROUTE_BLOCKED_UNSUPPORTED_TASK_CLASS",
        execution_authorized=False,
    )
    with pytest.raises(MockModelClient.RouteNotAuthorizedError):
        client.invoke(TaskClass.BUILD_DIAGNOSIS, blocked, payload={})


def test_mock_client_raises_on_unknown_task_class():
    """The mock fixture must enumerate every class it intends to exercise."""
    from models.model_router_record import RouteRecord

    client = MockModelClient({TaskClass.BUILD_DIAGNOSIS: {"kind": "MOCK"}})
    authorized = RouteRecord(
        task_class=TaskClass.PATCH_PLANNING.value,
        requested_mode="live",
        selected_route="CODE_SPECIALIST",
        selected_model_id="determinex-engineer-v11-dsl",
        fallback_chain=("CODE_SPECIALIST", "NO_MODEL"),
        availability_checked=True,
        stale_model_id_detected=False,
        decision="ROUTE_SELECTED",
        execution_authorized=True,
    )
    with pytest.raises(KeyError):
        client.invoke(TaskClass.PATCH_PLANNING, authorized, payload={})


def test_mock_client_records_every_invocation(loop):
    ws = FIXTURES / "python_broken"
    loop.run(ws)
    calls = loop._mock_client.calls  # type: ignore[attr-defined]
    # Four pipeline steps; each one with a current id and routes through mock.
    assert len(calls) == len(TASK_CLASS_PIPELINE)
    seen = [c.task_class for c in calls]
    assert seen == [tc.value for tc in TASK_CLASS_PIPELINE]


# ---------------------------------------------------------------------------
# Source / I/O invariants
# ---------------------------------------------------------------------------


def test_loop_module_does_not_import_subprocess_or_urllib():
    for fname in ("mocked_intake_repair.py", "mocked_repair_loop_record.py"):
        src = (_REPO_ROOT / "scripts" / "intake" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_mock_client_does_not_import_subprocess_or_urllib():
    src = (_REPO_ROOT / "scripts" / "models" / "mock_client.py").read_text(encoding="utf-8")
    assert "import subprocess" not in src
    assert "from subprocess" not in src
    assert "import urllib" not in src
    assert "from urllib" not in src


def test_loop_terminus_no_model_for_summary_when_inventory_empty():
    """If FAST_LOCAL is unavailable, VERIFIER_SUMMARY resolves to NO_MODEL
    and the loop records it without invoking the mock for that step."""
    loop = MockedIntakeRepairLoop(
        router=ModelRouter(inventory=LocalModelInventory.empty()),
        mock_client=MockModelClient(default_mock_canned()),
    )
    ws = FIXTURES / "python_broken"
    trace = loop.run(ws)
    # When inventory is empty, BUILD_DIAGNOSIS falls through to NO_MODEL,
    # which means the mock is never invoked for any step.
    assert trace.diagnose_mock_route_selected is False
    assert trace.terminus == "ROUTER_BLOCKED"


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file(), f"Missing lock: {LOCK_PATH}"
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LLM_MOCKED_INTAKE_REPAIR_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    assert blob["scope_discipline"]["programbench_touched"] is False
    assert blob["scope_discipline"]["docker_pulls"] is False
    assert blob["scope_discipline"]["live_model_call_made"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates, f"No evidence artifact in {EVIDENCE_DIR}"
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LLM_MOCKED_INTAKE_REPAIR_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LLM_MOCKED_INTAKE_REPAIR_LOCK_001" in ids
