from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

from app.experience_asset.api.routes.m1 import build_m1_router
from app.experience_asset.domain.models import (
    HealthStatusV1,
    ProgressEventV1,
    TerminalResultV1,
)
from app.experience_asset.inference.models import StructuredProposal
from app.experience_asset.workflow import (
    GRAPH_STATE_ALLOWED_KEYS,
    M1_GRAPH_EDGES,
    M1_GRAPH_NODES,
    TOPOLOGY_HASH,
    WORKFLOW_VERSION,
)
from qa.scripts.check_progress_invariants import check as check_progress

ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_contracts_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/export_contracts.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_lane_b_examples_validate_against_frozen_models() -> None:
    examples = ROOT / "contracts" / "examples"
    cases = {
        "health.json": HealthStatusV1,
        "progress-running.json": ProgressEventV1,
        "terminal-model-unavailable.json": TerminalResultV1,
        "structured-tool-proposal.json": StructuredProposal,
    }
    for file_name, model in cases.items():
        payload = json.loads((examples / file_name).read_text(encoding="utf-8"))
        model.model_validate(payload)

    progress = json.loads((examples / "progress-running.json").read_text(encoding="utf-8"))
    assert check_progress(progress) == []


def test_e2_langgraph_conformance_contract_matches_production_topology() -> None:
    contract = json.loads(
        (
            ROOT
            / "contracts"
            / "checkpoints"
            / "e2-m1-workflow-conformance-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert contract["workflow_version"] == WORKFLOW_VERSION
    assert contract["topology_hash"] == TOPOLOGY_HASH
    assert contract["nodes"] == list(M1_GRAPH_NODES)
    assert contract["edges"] == [list(edge) for edge in M1_GRAPH_EDGES]
    assert set(contract["graph_state_allowlist"]) == GRAPH_STATE_ALLOWED_KEYS
    assert "DurableFakeAgentLoop" not in inspect.getsource(build_m1_router)


def test_e2_local_candidate_artifacts_are_complete_and_hash_bound() -> None:
    artifact_dir = (
        ROOT
        / "evidence"
        / "milestones"
        / "e2-m1-langgraph-local"
        / "20260728T102918Z"
        / "artifacts"
    )
    hash_manifest = json.loads(
        (artifact_dir / "artifact-hashes.json").read_text(encoding="utf-8")
    )
    expected_files = {
        "experience-asset.public.json",
        "langgraph-node-trace.json",
        "m1-live-ui.png",
        "m1-progress.json",
        "m1-workspace.public-fixture.json",
        "retrieval-phase-trace.json",
    }
    assert set(hash_manifest["sha256"]) == expected_files
    for file_name, expected_hash in hash_manifest["sha256"].items():
        path = artifact_dir / file_name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
