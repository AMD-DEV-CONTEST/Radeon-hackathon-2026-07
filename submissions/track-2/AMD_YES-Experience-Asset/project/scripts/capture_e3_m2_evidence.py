#!/usr/bin/env python3
"""Capture sanitized E3/M2 artifacts from one fixed public scenario."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.experience_asset.api.main import create_app  # noqa: E402
from app.experience_asset.inference import ModelClient  # noqa: E402
from app.experience_asset.workflow import (  # noqa: E402
    M2_TOPOLOGY_HASH,
    M2_WORKFLOW_VERSION,
)

FIXTURE_ID = "chair_public_complete"
FIXTURE_VERSION = "0.1.0"
FIXTURE_PATH = ROOT / "qa" / "fixtures" / f"{FIXTURE_ID}.md"
FIXTURE_SOURCE_URL = "https://www.reddit.com/r/OfficeChairs/comments/hem1s7/"
INITIAL_CONTEXT = (
    "Because the return window was open, I changed course; unexpectedly, "
    "the padded chair fit better."
)
CORRECTED_CONTEXT = (
    "Correction: the return window was only one constraint; keep the final "
    "turning point open for review."
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
    model_client: ModelClient | None = None,
) -> dict[str, str]:
    invalid_commit = len(code_commit) != 40 or any(
        character not in "0123456789abcdef" for character in code_commit
    )
    if invalid_commit:
        raise ValueError("code_commit must be a lowercase 40-character Git SHA")
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="e3-m2-evidence-") as temporary:
        temporary_path = Path(temporary)
        app = create_app(
            database_path=temporary_path / "asset.sqlite3",
            workflow_database_path=temporary_path / "workflow.sqlite3",
            model_client=model_client,
            code_commit=code_commit,
        )
        with TestClient(app) as client:
            ingested = client.post(
                "/api/v1/m1/assets",
                json={
                    "source_kind": "ADAPTED_PUBLIC_FIXTURE",
                    "display_label": FIXTURE_ID,
                    "text": fixture_text,
                    "authorship": "ADAPTED_RESEARCH",
                    "source_url": FIXTURE_SOURCE_URL,
                    "adapted_provenance_notice": (
                        "Paraphrased, anonymized public-research fixture; "
                        "not first-party testimony."
                    ),
                    "goal_hint": "Build a source-linked Critical Moment Map.",
                },
            )
            ingested.raise_for_status()
            initial_m1 = ingested.json()
            asset_id = initial_m1["asset"]["asset_id"]

            prepared = client.patch(
                f"/api/v1/m1/assets/{asset_id}/brief",
                json={
                    "expected_version_id": initial_m1["asset"]["version_id"],
                    "context": INITIAL_CONTEXT,
                },
            )
            prepared.raise_for_status()
            accepted = client.post(
                f"/api/v1/m1/assets/{asset_id}/confirm",
                json={
                    "expected_version_id": prepared.json()["asset"]["version_id"],
                    "complete_with_gaps": True,
                },
            )
            accepted.raise_for_status()

            created = client.post(
                f"/api/v1/m2/assets/{asset_id}",
                json={
                    "expected_m1_version_id": accepted.json()["asset"]["version_id"],
                },
            )
            created.raise_for_status()
            initial_m2 = created.json()
            moments = initial_m2["artifact"]["moments"]
            if not any(moment["cue_statement_ids"] for moment in moments):
                raise RuntimeError("public E3 evidence did not identify an explicit cue")
            if not any(moment["change_statement_ids"] for moment in moments):
                raise RuntimeError("public E3 evidence did not identify an explicit change")
            if not any(moment["surprise_statement_ids"] for moment in moments):
                raise RuntimeError("public E3 evidence did not identify an explicit surprise")

            trusted = client.patch(
                f"/api/v1/m2/assets/{asset_id}",
                json={
                    "expected_artifact_id": initial_m2["artifact"]["artifact_id"],
                    "moments": [
                        {
                            "moment_id": moment["moment_id"],
                            "title": moment["title"],
                            "criticality_status": "USER_CONFIRMED",
                        }
                        for moment in moments
                    ],
                },
            )
            trusted.raise_for_status()
            confirmed = client.post(
                f"/api/v1/m2/assets/{asset_id}/confirm",
                json={
                    "expected_artifact_id": trusted.json()["artifact"]["artifact_id"],
                    "complete_with_gaps": True,
                },
            )
            confirmed.raise_for_status()

            current_m1 = client.get(f"/api/v1/m1/assets/{asset_id}")
            current_m1.raise_for_status()
            corrected = client.patch(
                f"/api/v1/m1/assets/{asset_id}/brief",
                json={
                    "expected_version_id": current_m1.json()["asset"]["version_id"],
                    "context": CORRECTED_CONTEXT,
                },
            )
            corrected.raise_for_status()
            invalidated = client.get(f"/api/v1/m2/assets/{asset_id}")
            invalidated.raise_for_status()
            invalidated_workspace = invalidated.json()
            if invalidated_workspace["artifact"]["state"] != "INVALIDATED":
                raise RuntimeError("dependent M1 correction did not invalidate M2")

            reaccepted = client.post(
                f"/api/v1/m1/assets/{asset_id}/confirm",
                json={
                    "expected_version_id": corrected.json()["asset"]["version_id"],
                    "complete_with_gaps": True,
                },
            )
            reaccepted.raise_for_status()
            latest_m1 = client.get(f"/api/v1/m1/assets/{asset_id}")
            latest_m1.raise_for_status()
            latest_m1_version = latest_m1.json()["asset"]["version_id"]
            regenerated = client.post(
                f"/api/v1/m2/assets/{asset_id}",
                json={"expected_m1_version_id": latest_m1_version},
            )
            regenerated.raise_for_status()
            regenerated_workspace = regenerated.json()

        run_id = UUID(regenerated_workspace["artifact"]["generated_by_run_id"])
        run_context = app.state.repository.get_workflow_run_context(run_id)
        terminal = app.state.repository.get_terminal_result(run_id)
        _, semantic_proposal_hash = (
            app.state.repository.get_m2_semantic_role_proposal(run_id)
        )
        trace = app.state.repository.list_workflow_traces(run_id)
        if run_context["code_commit"] != code_commit:
            raise RuntimeError("M2 run identity does not match requested code commit")
        if terminal is None or terminal.model_call_count != 1:
            raise RuntimeError("M2 semantic run must record exactly one model call")
        if not str(run_context["server_base_url"]).startswith(
            ("http://127.0.0.1", "http://localhost", "http://[::1]")
        ):
            raise RuntimeError("M2 semantic run must retain loopback model identity")

        def role_counts(workspace: dict[str, Any]) -> dict[str, int]:
            workspace_moments = workspace["artifact"]["moments"]
            return {
                "cue": sum(
                    len(moment["cue_statement_ids"]) for moment in workspace_moments
                ),
                "change_or_turning": sum(
                    len(moment["change_statement_ids"])
                    for moment in workspace_moments
                ),
                "surprise": sum(
                    len(moment["surprise_statement_ids"])
                    for moment in workspace_moments
                ),
                "conflict": sum(
                    len(moment["conflict_statement_ids"])
                    for moment in workspace_moments
                ),
            }

        evidenced_moments = [
            *initial_m2["artifact"]["moments"],
            *regenerated_workspace["artifact"]["moments"],
        ]
        artifact_payloads = {
            "m2-workspace.public.json": regenerated_workspace,
            "correction-invalidation-trace.json": {
                "schema_version": "e3-m2-correction-trace/v1",
                "fixture_id": FIXTURE_ID,
                "asset_id": asset_id,
                "initial_m2_artifact_id": initial_m2["artifact"]["artifact_id"],
                "confirmed_m2_artifact_id": confirmed.json()["artifact"]["artifact_id"],
                "invalidated_m2_artifact_id": invalidated_workspace["artifact"][
                    "artifact_id"
                ],
                "invalidated_by_m1_version_id": invalidated_workspace["artifact"][
                    "invalidated_by_m1_version_id"
                ],
                "latest_m1_version_id": latest_m1_version,
                "regenerated_m2_artifact_id": regenerated_workspace["artifact"][
                    "artifact_id"
                ],
                "regenerated_base_m1_version_id": regenerated_workspace["artifact"][
                    "base_m1_version_id"
                ],
                "old_artifact_not_current": not invalidated_workspace["is_current"],
                "regenerated_artifact_current": regenerated_workspace["is_current"],
            },
            "langgraph-node-trace.json": {
                "schema_version": "e3-m2-node-trace/v1",
                "fixture_id": FIXTURE_ID,
                "run_id": str(run_id),
                "code_commit": run_context["code_commit"],
                "workflow_version": run_context["workflow_version"],
                "topology_hash": run_context["topology_hash"],
                "nodes": trace,
            },
            "role-summary.json": {
                "schema_version": "e3-m2-role-summary/v1",
                "fixture_id": FIXTURE_ID,
                "initial_role_counts": role_counts(initial_m2),
                "regenerated_role_counts": role_counts(regenerated_workspace),
                "all_roles_source_linked": all(
                    set(
                        moment["cue_statement_ids"]
                        + moment["change_statement_ids"]
                        + moment["surprise_statement_ids"]
                        + moment["conflict_statement_ids"]
                    ).issubset(moment["source_statement_ids"])
                    for moment in evidenced_moments
                ),
            },
            "semantic-model-summary.json": {
                "schema_version": "e3-m2-semantic-model-summary/v1",
                "fixture_id": FIXTURE_ID,
                "run_id": str(run_id),
                "model_id": run_context["model_id"],
                "server_base_url": run_context["server_base_url"],
                "model_config_hash": run_context["model_config_hash"],
                "model_call_count": terminal.model_call_count,
                "semantic_role_proposal_hash": semantic_proposal_hash,
                "raw_prompt_or_response_retained": False,
            },
        }
        for file_name, payload in artifact_payloads.items():
            _write_json(output_dir / file_name, payload)

    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "artifact-hashes.json"
    }
    _write_json(
        output_dir / "artifact-hashes.json",
        {
            "schema_version": "artifact-hashes/v1",
            "fixture_id": FIXTURE_ID,
            "fixture_version": FIXTURE_VERSION,
            "fixture_sha256": hashlib.sha256(fixture_text.encode("utf-8")).hexdigest(),
            "code_commit": code_commit,
            "workflow_version": M2_WORKFLOW_VERSION,
            "topology_hash": M2_TOPOLOGY_HASH,
            "sha256": hashes,
        },
    )
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    hashes = capture(args.output_dir, code_commit=args.code_commit)
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
