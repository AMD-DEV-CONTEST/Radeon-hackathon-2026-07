#!/usr/bin/env python3
from __future__ import annotations

import io
import hashlib
import json
import zipfile
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_contracts import EvidenceClass
from prooflaunch_remix.v10_submission_api import (
    AgencyEvalRecord,
    AgencyLaunchRequest,
    AgencyRunStore,
    ModelCard,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_submission_api_contract.json"
EVIDENCE = ROOT / "evidence/v10/submission-api-mechanical-fixture.json"
SHA = "a" * 64


def main() -> int:
    card = ModelCard(
        model_id="mechanical-fixture-model",
        revision="mechanical-fixture-revision",
        role="API contract fixture only",
        capabilities=("typed_contract", "single_port_api"),
        limitations=("not trained", "not Radeon execution", "not a quality result"),
        training_data_manifest_sha256=None,
        evaluation_record_ids=("eval-mechanical-001",),
        radeon_execution_evidence=None,
        promotion_status="planned",
        created_at="2026-07-31T12:00:00Z",
    )
    evaluation = AgencyEvalRecord(
        eval_id="eval-mechanical-001",
        model_id=card.model_id,
        model_revision=card.revision,
        benchmark_id="submission-api-mechanical-fixture",
        benchmark_sha256=SHA,
        metrics={"overall": 1.0, "schema": 1.0},
        raw_counts={"passed": 1, "possible": 1},
        evidence_class=EvidenceClass.SIMULATED,
        evidence_locator="tests/test_v10_submission_api.py",
        observed_at="2026-07-31T12:00:00Z",
        blinded=True,
    )
    request = AgencyLaunchRequest(
        request_id="request-mechanical-001",
        campaign_id="campaign-mechanical-001",
        objective="Exercise the API mechanics without external release",
        required_capabilities=("strategy", "safety"),
        input_artifacts={"brief": SHA},
        maximum_actions=8,
        maximum_cost_usd=0,
        created_at="2026-07-31T12:00:00Z",
        data_class="synthetic",
    )
    store = AgencyRunStore(model_cards=(card,), eval_records=(evaluation,))
    record = store.create(request)
    pre_approval_status = record.status
    store.approve(
        record.run_id,
        decision="approve",
        approver="mechanical-fixture-human",
        decided_at="2026-07-31T12:30:00Z",
        reason="mechanical fixture only",
    )
    bundle = store.bundle(record.run_id)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        bundle_names = sorted(archive.namelist())

    contract = {
        "schema": "ProofLaunchSubmissionApiContractV1",
        "bind_default": "127.0.0.1:8765",
        "single_port": True,
        "static_ui_same_port": True,
        "state_changing_external_actions": False,
        "human_release_required": True,
        "contracts": [
            "AgencyLaunchRequest",
            "CampaignWorldState",
            "DistillationEpisode",
            "MemoryAtom",
            "RewardVector",
            "ModelCard",
            "AgencyEvalRecord",
        ],
        "endpoints": [
            {"method": "GET", "path": "/v1/health", "purpose": "truth-bounded control-plane health"},
            {"method": "POST", "path": "/v1/runs", "purpose": "idempotent run creation"},
            {"method": "GET", "path": "/v1/runs/{run_id}", "purpose": "run status"},
            {"method": "GET", "path": "/v1/runs/{run_id}/events", "purpose": "SSE event stream"},
            {"method": "POST", "path": "/v1/runs/{run_id}/approvals", "purpose": "named human decision"},
            {"method": "GET/POST", "path": "/v1/runs/{run_id}/publication-receipts", "purpose": "manual publication attestations"},
            {"method": "GET", "path": "/v1/runs/{run_id}/bundle", "purpose": "approved evidence bundle"},
            {"method": "GET", "path": "/v1/model-cards", "purpose": "model cards"},
            {"method": "GET", "path": "/v1/evals/leaderboard", "purpose": "evidence-labeled eval leaderboard"},
        ],
        "bundle_files": bundle_names,
        "truth_boundary": "The API mechanics do not prove model training, Radeon execution, product quality, publication, or causal business outcomes.",
        "ui_surfaces": [
            {"todo_id": str(todo_id), "route": route}
            for todo_id, route in (
                (1166, "/control/world-state"), (1167, "/control/trajectory"),
                (1168, "/control/topology"), (1169, "/control/memory"),
                (1170, "/control/distillation"), (1171, "/control/training"),
                (1172, "/control/audit"), (1173, "/control/repair"),
                (1174, "/control/human-gate"), (1175, "/control/images"),
                (1176, "/control/videos"), (1177, "/control/landing"),
                (1178, "/control/email"), (1179, "/control/ledger"),
                (1180, "/control/performance"),
            )
        ],
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CONFIG, json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    fixture = {
        "schema": "ProofLaunchSubmissionApiMechanicalFixtureV1",
        "contract_sha256": sha256_file(CONFIG),
        "request_digest": request.digest,
        "run_id": record.run_id,
        "pre_approval_status": pre_approval_status,
        "post_approval_status": record.status,
        "event_count": len(record.events),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "bundle_files": bundle_names,
        "model_card_digest": card.digest,
        "eval_record_digest": evaluation.digest,
        "leaderboard": store.leaderboard(),
        "external_release_executed": False,
        "radeon_execution_observed": False,
        "model_quality_observed": False,
        "ui_surface_count": 15,
        "ui_truth_boundary": "Image/video/channel surfaces expose exact required slots while reporting zero unobserved deliverables.",
    }
    atomic_write_text(EVIDENCE, json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"contract_sha256": sha256_file(CONFIG), "fixture_sha256": sha256_file(EVIDENCE), "run_id": record.run_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
