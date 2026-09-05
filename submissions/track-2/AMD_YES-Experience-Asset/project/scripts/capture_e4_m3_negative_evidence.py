#!/usr/bin/env python3
"""Capture deterministic sanitized E4/M3 denial and recovery evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.experience_asset.api.main import create_app  # noqa: E402
from app.experience_asset.inference import (  # noqa: E402
    FakeModelClient,
    InvalidModelOutput,
)
from app.experience_asset.inference.models import (  # noqa: E402
    M3LedgerProposal,
    M3LedgerResult,
    ModelMetadata,
    ToolCallProposal,
)
from scripts.capture_e4_m3_evidence import (  # noqa: E402
    FIXTURE_ID,
    FIXTURE_PATH,
    _seed_accepted_m2,
    _validate_commit,
    _write_json,
)


def _proposal(request: Any, *, unsupported: bool = False) -> M3LedgerProposal:
    moment = next(
        item
        for item in request.canonical_context["moments"]
        if item["source_statement_ids"]
    )
    statement_id = (
        str(uuid4()) if unsupported else str(moment["source_statement_ids"][0])
    )
    return M3LedgerProposal(
        entries=[
            {
                "prior_decision_id": request.canonical_context.get(
                    "affected_entry_ids", [None]
                )[0],
                "title": "Deterministic negative-path fixture",
                "source_moment_ids": [moment["moment_id"]],
                "statements": [
                    {
                        "role": role,
                        "text": f"{role} fixture evidence",
                        "source_moment_ids": [moment["moment_id"]],
                        "source_statement_ids": [statement_id],
                    }
                    for role in (
                        "ALTERNATIVE",
                        "REASON",
                        "DECISION",
                        "ACTION",
                        "OBSERVED_RESULT",
                    )
                ],
            }
        ]
    )


def _result(proposal: M3LedgerProposal) -> M3LedgerResult:
    return M3LedgerResult(
        proposal=proposal,
        metadata=ModelMetadata(
            server_kind="fake",
            server_base_url="http://127.0.0.1/fake",
            model_id="deterministic-e4-negative-fixture",
            elapsed_ms=0,
            received_at=datetime.now(UTC),
        ),
    )


class PolicyProposalClient(FakeModelClient):
    async def generate_m3_ledger(self, request):
        proposal = _proposal(request)
        proposal = proposal.model_copy(
            update={
                "tool_call_proposals": [
                    ToolCallProposal(
                        name="search_current_experience",
                        arguments={
                            "asset_id": request.canonical_context["asset_id"],
                            "current_version_id": request.canonical_context[
                                "version_id"
                            ],
                            "scope": "CURRENT_SOURCE",
                            "query": "chair support",
                            "top_k": 3,
                        },
                        requested_reason="Deterministic permission-denial fixture.",
                        permission_granted=False,
                    )
                ]
            }
        )
        return _result(proposal)


class RepairClient(FakeModelClient):
    def __init__(self) -> None:
        super().__init__()
        self.outcomes = deque([InvalidModelOutput("deterministic invalid output"), None])

    async def generate_m3_ledger(self, request):
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return _result(_proposal(request))


class UnsupportedClaimClient(FakeModelClient):
    async def generate_m3_ledger(self, request):
        return _result(_proposal(request, unsupported=True))


def _new_app(root: Path, model: FakeModelClient, code_commit: str):
    return create_app(
        database_path=root / "asset.sqlite3",
        workflow_database_path=root / "workflow.sqlite3",
        model_client=model,
        code_commit=code_commit,
    )


def _start_m3(client: TestClient, fixture_text: str) -> tuple[str, Any]:
    asset_id, m2, canonical = _seed_accepted_m2(client, fixture_text)
    response = client.post(
        f"/api/v1/m3/assets/{asset_id}",
        json={
            "expected_m2_artifact_id": m2["artifact_id"],
            "expected_canonical_version_id": canonical["version_id"],
        },
    )
    return asset_id, response


def capture(output_dir: Path, *, code_commit: str) -> dict[str, Any]:
    _validate_commit(code_commit)
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="e4-m3-negative-") as temporary:
        root = Path(temporary)

        policy_app = _new_app(root / "policy", PolicyProposalClient(), code_commit)
        with TestClient(policy_app) as client:
            _, policy_response = _start_m3(client, fixture_text)
            if policy_response.status_code != 422:
                raise RuntimeError("permission-denial fixture did not safe-stop")
            policy_detail = policy_response.json()["detail"]
            policy_status = client.get(policy_detail["status_url"])
            policy_status.raise_for_status()
        policy_run_id = UUID(policy_detail["run_id"])
        decisions = policy_app.state.repository.list_m3_policy_decisions(
            policy_run_id
        )
        policy_trace = {
            "schema_version": "e4-m3-policy-denial/v1",
            "fixture_id": FIXTURE_ID,
            "run_id": str(policy_run_id),
            "status": policy_status.json(),
            "policy_decisions": [
                decision.model_dump(mode="json") for decision in decisions
            ],
            "tool_execution_effect_count": policy_app.state.repository.count_workflow_effects(
                policy_run_id, "m3_tool_execution"
            ),
            "nodes": policy_app.state.repository.list_workflow_traces(policy_run_id),
            "raw_tool_arguments_or_observations_retained": False,
        }
        if (
            policy_status.json()["terminal_state"] != "POLICY_BLOCKED"
            or not decisions
            or policy_trace["tool_execution_effect_count"] != 0
        ):
            raise RuntimeError("M3 policy denial did not retain zero-effect evidence")

        repair_app = _new_app(root / "repair", RepairClient(), code_commit)
        with TestClient(repair_app) as client:
            _, repair_response = _start_m3(client, fixture_text)
            repair_response.raise_for_status()
        repair_run_id = UUID(
            repair_response.json()["artifact"]["generated_by_run_id"]
        )
        repair_outcome = repair_app.state.repository.get_m3_run_outcome(
            repair_run_id
        )
        repair_trace = {
            "schema_version": "e4-m3-invalid-output-recovery/v1",
            "fixture_id": FIXTURE_ID,
            "run_id": str(repair_run_id),
            "terminal_state": repair_outcome["terminal_state"],
            "model_call_count": repair_outcome["model_call_count"],
            "structured_repairs_used": repair_outcome["structured_repair_count"],
            "replans_used": repair_outcome["replan_count"],
            "nodes": repair_app.state.repository.list_workflow_traces(repair_run_id),
        }
        if (
            repair_outcome["terminal_state"] != "SUCCEEDED"
            or repair_outcome["model_call_count"] != 2
            or repair_outcome["structured_repair_count"] != 1
        ):
            raise RuntimeError("M3 bounded repair evidence differs from its contract")

        unsupported_app = _new_app(
            root / "unsupported", UnsupportedClaimClient(), code_commit
        )
        with TestClient(unsupported_app) as client:
            _, unsupported_response = _start_m3(client, fixture_text)
            if unsupported_response.status_code != 422:
                raise RuntimeError("unsupported evidence reference was not rejected")
            unsupported_detail = unsupported_response.json()["detail"]
            unsupported_status = client.get(unsupported_detail["status_url"])
            unsupported_status.raise_for_status()
        unsupported_run_id = UUID(unsupported_detail["run_id"])
        unsupported_trace = {
            "schema_version": "e4-m3-unsupported-claim/v1",
            "fixture_id": FIXTURE_ID,
            "run_id": str(unsupported_run_id),
            "status": unsupported_status.json(),
            "persisted_m3_artifact": (
                unsupported_app.state.repository.get_m3_run_commit(
                    unsupported_run_id
                )
                is not None
            ),
            "nodes": unsupported_app.state.repository.list_workflow_traces(
                unsupported_run_id
            ),
        }
        if (
            unsupported_status.json()["terminal_state"] != "INVALID_MODEL_OUTPUT"
            or unsupported_trace["persisted_m3_artifact"]
        ):
            raise RuntimeError("unsupported claim did not safe-stop before persistence")

    forged_permission_rejected = False
    safe_error = None
    try:
        ToolCallProposal.model_validate(
            {
                "name": "search_current_experience",
                "arguments": {},
                "permission_granted": True,
            }
        )
    except ValidationError as exc:
        forged_permission_rejected = True
        safe_error = exc.errors(include_input=False, include_url=False)
    if not forged_permission_rejected:
        raise RuntimeError("model-supplied permission_granted=true was accepted")

    artifacts = {
        "m3-policy-denial-trace.json": policy_trace,
        "m3-invalid-output-recovery-trace.json": repair_trace,
        "m3-unsupported-claim-trace.json": unsupported_trace,
        "m3-forged-permission-contract.json": {
            "schema_version": "e4-m3-forged-permission/v1",
            "fixture_id": FIXTURE_ID,
            "forged_permission_rejected": True,
            "validation_errors": safe_error,
            "tool_execution_effect_count": 0,
        },
    }
    for file_name, payload in artifacts.items():
        _write_json(output_dir / file_name, payload)
    return {"result": "PASS", "artifacts": sorted(artifacts)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = capture(args.output_dir, code_commit=args.code_commit)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
