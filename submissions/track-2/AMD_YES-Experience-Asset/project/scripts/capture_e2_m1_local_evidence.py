#!/usr/bin/env python3
"""Capture a sanitized, deterministic E2/M1 local evidence artifact set."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.domain.public_serialization import to_public_asset
from app.experience_asset.inference import (
    ModelRequest,
    ModelResult,
    StructuredProposal,
    ToolCallProposal,
)
from app.experience_asset.inference.models import ModelMetadata
from app.experience_asset.workflow import TOPOLOGY_HASH, WORKFLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SOURCE_URL = "https://www.reddit.com/r/OfficeChairs/comments/hem1s7/"
E2_FIXTURE_IDS = {
    "chair_public_complete",
    "chair_incomplete",
    "chair_conflicting",
    "chair_resume",
}


class EvidenceModelClient:
    """Deterministic local-only proposal producer for public evidence capture."""

    model_id = "deterministic-public-evidence-model"
    base_url = "http://127.0.0.1/evidence-fake"

    async def generate(self, request: ModelRequest) -> ModelResult:
        asset_id = str(request.canonical_context["asset_id"])
        version_id = str(request.canonical_context["version_id"])
        return ModelResult(
            proposal=StructuredProposal(
                summary="Search the current public fixture only.",
                tool_call_proposals=[
                    ToolCallProposal(
                        name="search_current_experience",
                        arguments={
                            "asset_id": asset_id,
                            "current_version_id": version_id,
                            "scope": "CURRENT_SOURCE",
                            "query": "办公椅 腰部支撑 退货 更换",
                            "top_k": 5,
                        },
                    )
                ],
            ),
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url=self.base_url,
                model_id=self.model_id,
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def capture(
    output_dir: Path,
    *,
    code_commit: str,
    fixture_id: str,
    ui_screenshot: Path | None = None,
) -> dict[str, str]:
    if fixture_id not in E2_FIXTURE_IDS:
        raise ValueError(f"unsupported E2 fixture: {fixture_id}")
    fixture_path = ROOT / "qa" / "fixtures" / f"{fixture_id}.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e2-m1-evidence-") as temporary:
        temporary_path = Path(temporary)
        app = create_app(
            database_path=temporary_path / "asset.sqlite3",
            workflow_database_path=temporary_path / "workflow.sqlite3",
            model_client=EvidenceModelClient(),
            code_commit=code_commit,
        )
        with TestClient(app) as client:
            ingest = client.post(
                "/api/v1/m1/assets",
                json={
                    "source_kind": "ADAPTED_PUBLIC_FIXTURE",
                    "display_label": fixture_id,
                    "text": fixture_path.read_text(encoding="utf-8"),
                    "authorship": "ADAPTED_RESEARCH",
                    "source_url": FIXTURE_SOURCE_URL,
                    "adapted_provenance_notice": (
                        "Paraphrased, anonymized public-research fixture; "
                        "not first-party testimony."
                    ),
                    "goal_hint": "Create a reusable private Experience Brief.",
                },
            )
            ingest.raise_for_status()
            initial_workspace = ingest.json()
            asset_id = initial_workspace["asset"]["asset_id"]
            version_id = initial_workspace["asset"]["version_id"]
            run_response = client.post(
                f"/api/v1/m1/assets/{asset_id}/agent-runs",
                json={
                    "expected_version_id": version_id,
                    "user_goal": "Ground the M1 brief in the current public fixture.",
                    "allow_current_source_search": True,
                },
            )
            run_response.raise_for_status()
            workspace = run_response.json()

        run = workspace["latest_agent_run"]
        if run is None or run["terminal_state"] != "SUCCEEDED":
            raise RuntimeError("public evidence run did not reach SUCCEEDED")
        run_id = UUID(run["run_id"])
        canonical = app.state.repository.get_current(UUID(asset_id))
        # E2/M1 evidence predates any relation state, so the empty tuple is a
        # statement that this export carries none — not an omission.
        public_asset = to_public_asset(canonical, relations=())
        public_asset["fixture_id"] = fixture_id
        retrieval_trace = {
            "schema_version": "retrieval-phase-trace/v1",
            "asset_id": asset_id,
            "events": [
                {
                    "sequence": 0,
                    "event_type": "current_source_retrieval",
                    "scope": "current_asset",
                    "related_asset_id": asset_id,
                    "provenance_refs": [
                        item["provenance_ref"]
                        for item in run["retrieved_evidence"]
                    ],
                    "mutated_current_statements": False,
                }
            ],
        }
        run_context = app.state.repository.get_workflow_run_context(run_id)
        sanitized_trace = {
            "schema_version": "e2-m1-node-trace/v1",
            "fixture_id": fixture_id,
            "run_id": str(run_id),
            "code_commit": run_context["code_commit"],
            "model_id": run_context["model_id"],
            "server_base_url": run_context["server_base_url"],
            "model_config_hash": run_context["model_config_hash"],
            "workflow_version": run_context["workflow_version"],
            "topology_hash": run_context["topology_hash"],
            "nodes": app.state.repository.list_workflow_traces(run_id),
        }

        artifact_payloads = {
            "experience-asset.public.json": public_asset,
            "m1-progress.json": workspace["progress"],
            "m1-workspace.public-fixture.json": workspace,
            "retrieval-phase-trace.json": retrieval_trace,
            "langgraph-node-trace.json": sanitized_trace,
        }
        for file_name, payload in artifact_payloads.items():
            _write_json(output_dir / file_name, payload)
        if ui_screenshot is not None:
            if not ui_screenshot.is_file():
                raise FileNotFoundError(ui_screenshot)
            shutil.copyfile(ui_screenshot, output_dir / "m1-live-ui.png")

    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "artifact-hashes.json"
    }
    _write_json(
        output_dir / "artifact-hashes.json",
        {
            "schema_version": "artifact-hashes/v1",
            "fixture_id": fixture_id,
            "code_commit": code_commit,
            "workflow_version": WORKFLOW_VERSION,
            "topology_hash": TOPOLOGY_HASH,
            "sha256": hashes,
        },
    )
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--fixture-id",
        choices=sorted(E2_FIXTURE_IDS),
        default="chair_incomplete",
    )
    parser.add_argument("--ui-screenshot", type=Path)
    args = parser.parse_args()
    hashes = capture(
        args.output_dir,
        code_commit=args.code_commit,
        fixture_id=args.fixture_id,
        ui_screenshot=args.ui_screenshot,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "artifacts": hashes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
