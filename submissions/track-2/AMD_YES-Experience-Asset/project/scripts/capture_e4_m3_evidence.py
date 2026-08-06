#!/usr/bin/env python3
"""Capture sanitized E4/M3 artifacts from one fixed public W7900 scenario."""

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
from app.experience_asset.persistence import AssetNotFoundError  # noqa: E402
from app.experience_asset.workflow.m3_state import (  # noqa: E402
    M3_TOPOLOGY_HASH,
    M3_WORKFLOW_VERSION,
)

FIXTURE_ID = "chair_public_complete"
FIXTURE_VERSION = "0.1.0"
FIXTURE_PATH = ROOT / "qa" / "fixtures" / f"{FIXTURE_ID}.md"
FIXTURE_SOURCE_URL = "https://www.reddit.com/r/OfficeChairs/comments/hem1s7/"
INITIAL_CONTEXT = (
    "I compared several chairs, changed course during the return window, "
    "and later observed that the padded chair fit better."
)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_commit(code_commit: str) -> None:
    if len(code_commit) != 40 or any(
        character not in "0123456789abcdef" for character in code_commit
    ):
        raise ValueError("code_commit must be a lowercase 40-character Git SHA")


def _seed_accepted_m2(client: TestClient, fixture_text: str) -> tuple[str, dict, dict]:
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
            "goal_hint": "Build an evidence-linked decision ledger.",
        },
    )
    ingested.raise_for_status()
    asset_id = ingested.json()["asset"]["asset_id"]
    prepared = client.patch(
        f"/api/v1/m1/assets/{asset_id}/brief",
        json={
            "expected_version_id": ingested.json()["asset"]["version_id"],
            "context": INITIAL_CONTEXT,
        },
    )
    prepared.raise_for_status()
    accepted_m1 = client.post(
        f"/api/v1/m1/assets/{asset_id}/confirm",
        json={
            "expected_version_id": prepared.json()["asset"]["version_id"],
            "complete_with_gaps": True,
        },
    )
    accepted_m1.raise_for_status()
    proposed_m2 = client.post(
        f"/api/v1/m2/assets/{asset_id}",
        json={
            "expected_m1_version_id": accepted_m1.json()["asset"]["version_id"],
        },
    )
    proposed_m2.raise_for_status()
    moments = proposed_m2.json()["artifact"]["moments"]
    trusted_m2 = client.patch(
        f"/api/v1/m2/assets/{asset_id}",
        json={
            "expected_artifact_id": proposed_m2.json()["artifact"]["artifact_id"],
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
    trusted_m2.raise_for_status()
    accepted_m2 = client.post(
        f"/api/v1/m2/assets/{asset_id}/confirm",
        json={
            "expected_artifact_id": trusted_m2.json()["artifact"]["artifact_id"],
            "complete_with_gaps": True,
        },
    )
    accepted_m2.raise_for_status()
    canonical = client.get(f"/api/v1/m1/assets/{asset_id}")
    canonical.raise_for_status()
    return asset_id, accepted_m2.json()["artifact"], canonical.json()["asset"]


def _assert_ledger_evidence(workspace: dict[str, Any], m2: dict[str, Any]) -> None:
    moments = {
        moment["moment_id"]: set(moment["source_statement_ids"])
        for moment in m2["moments"]
    }
    for entry in workspace["artifact"]["entries"]:
        roles = {statement["role"] for statement in entry["statements"]}
        required = {"ALTERNATIVE", "REASON", "DECISION", "ACTION", "OBSERVED_RESULT"}
        if roles != required:
            raise RuntimeError(f"M3 entry role coverage differs: {sorted(roles)}")
        for statement in entry["statements"]:
            declared_statement_ids: set[str] = set()
            for moment_id in statement["source_moment_ids"]:
                if moment_id not in moments:
                    raise RuntimeError("M3 statement references an unknown M2 moment")
                declared_statement_ids.update(moments[moment_id])
            evidence_ids = set(statement["source_statement_ids"]) | set(
                statement["derived_from_statement_ids"]
            )
            if not evidence_ids.issubset(declared_statement_ids):
                raise RuntimeError(
                    "M3 evidence reference is outside its declared M2 moments"
                )


def _run_record(repository: Any, run_id: UUID) -> dict[str, Any]:
    context = repository.get_workflow_run_context(run_id)
    terminal = repository.get_terminal_result(run_id)
    outcome = repository.get_m3_run_outcome(run_id)
    if terminal is None or outcome is None:
        raise RuntimeError(f"M3 run {run_id} has no durable terminal outcome")
    if not str(context["server_base_url"]).startswith(
        ("http://127.0.0.1", "http://localhost", "http://[::1]")
    ):
        raise RuntimeError("M3 run did not retain a loopback model endpoint")
    proposal_metadata = []
    for attempt in range(1, terminal.model_call_count + 1):
        try:
            metadata = repository.get_m3_proposal_metadata(run_id, attempt)
        except AssetNotFoundError:
            continue
        proposal_metadata.append(
            {
                "attempt": attempt,
                **metadata.model_dump(mode="json"),
            }
        )
    return {
        "run_id": str(run_id),
        "code_commit": context["code_commit"],
        "workflow_version": context["workflow_version"],
        "topology_hash": context["topology_hash"],
        "model_id": context["model_id"],
        "server_base_url": context["server_base_url"],
        "model_config_hash": context["model_config_hash"],
        "terminal_state": terminal.state.value,
        "elapsed_ms": terminal.elapsed_ms,
        "model_call_count": terminal.model_call_count,
        "structured_repairs_used": outcome["structured_repair_count"],
        "replans_used": outcome["replan_count"],
        "proposal_metadata": proposal_metadata,
        "raw_prompt_or_response_retained": False,
    }


def capture(
    output_dir: Path,
    *,
    code_commit: str,
    model_client: ModelClient | None = None,
) -> dict[str, str]:
    _validate_commit(code_commit)
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="e4-m3-evidence-") as temporary:
        temporary_path = Path(temporary)
        database = temporary_path / "asset.sqlite3"
        workflow_database = temporary_path / "workflow.sqlite3"
        app = create_app(
            database_path=database,
            workflow_database_path=workflow_database,
            model_client=model_client,
            code_commit=code_commit,
        )
        with TestClient(app) as client:
            asset_id, accepted_m2, canonical = _seed_accepted_m2(client, fixture_text)
            created = client.post(
                f"/api/v1/m3/assets/{asset_id}",
                json={
                    "expected_m2_artifact_id": accepted_m2["artifact_id"],
                    "expected_canonical_version_id": canonical["version_id"],
                },
            )
            created.raise_for_status()
            initial_workspace = created.json()
            _assert_ledger_evidence(initial_workspace, accepted_m2)
            initial_run_id = UUID(
                initial_workspace["artifact"]["generated_by_run_id"]
            )

            statements = [
                statement
                for entry in initial_workspace["artifact"]["entries"]
                for statement in entry["statements"]
            ]
            reviewed = client.patch(
                f"/api/v1/m3/assets/{asset_id}",
                json={
                    "expected_artifact_id": initial_workspace["artifact"][
                        "artifact_id"
                    ],
                    "statements": [
                        {
                            "statement_id": statement["statement_id"],
                            "text": statement["text"],
                            "user_action": "CONFIRM",
                        }
                        for statement in statements
                    ],
                },
            )
            reviewed.raise_for_status()
            confirmed = client.post(
                f"/api/v1/m3/assets/{asset_id}/confirm",
                json={
                    "expected_artifact_id": reviewed.json()["artifact"][
                        "artifact_id"
                    ],
                    "complete_with_gaps": False,
                },
            )
            confirmed.raise_for_status()
            if confirmed.json()["artifact"]["state"] != "CONFIRMED":
                raise RuntimeError("explicit M3 review did not reach CONFIRMED")

            current_m2 = client.get(f"/api/v1/m2/assets/{asset_id}")
            current_m2.raise_for_status()
            corrected_m2 = client.patch(
                f"/api/v1/m2/assets/{asset_id}",
                json={
                    "expected_artifact_id": current_m2.json()["artifact"][
                        "artifact_id"
                    ],
                    "moments": [
                        {
                            "moment_id": moment["moment_id"],
                            "title": (
                                f"{moment['title']} (evidence wording corrected)"
                                if index == 0
                                else moment["title"]
                            ),
                            "criticality_status": moment["criticality_status"],
                        }
                        for index, moment in enumerate(
                            current_m2.json()["artifact"]["moments"]
                        )
                    ],
                },
            )
            corrected_m2.raise_for_status()
            invalidated = client.get(f"/api/v1/m3/assets/{asset_id}")
            invalidated.raise_for_status()
            if invalidated.json()["artifact"]["state"] != "INVALIDATED":
                raise RuntimeError("M2 correction did not invalidate dependent M3")
            accepted_corrected_m2 = client.post(
                f"/api/v1/m2/assets/{asset_id}/confirm",
                json={
                    "expected_artifact_id": corrected_m2.json()["artifact"][
                        "artifact_id"
                    ],
                    "complete_with_gaps": True,
                },
            )
            accepted_corrected_m2.raise_for_status()
            invalidated = client.get(f"/api/v1/m3/assets/{asset_id}")
            invalidated.raise_for_status()
            if invalidated.json()["artifact"]["state"] != "INVALIDATED":
                raise RuntimeError(
                    "accepted M2 correction did not retain an invalidated M3"
                )
            latest_canonical = client.get(f"/api/v1/m1/assets/{asset_id}")
            latest_canonical.raise_for_status()
            regenerated = client.post(
                f"/api/v1/m3/assets/{asset_id}/regenerate",
                json={
                    "expected_m2_artifact_id": accepted_corrected_m2.json()[
                        "artifact"
                    ]["artifact_id"],
                    "expected_canonical_version_id": latest_canonical.json()["asset"][
                        "version_id"
                    ],
                    "expected_invalidated_artifact_id": invalidated.json()[
                        "artifact"
                    ]["artifact_id"],
                },
            )
            if regenerated.status_code >= 400:
                raise RuntimeError(
                    "M3 regeneration failed in the fixed public scenario: "
                    f"{regenerated.status_code} {regenerated.text}"
                )
            regenerated_workspace = regenerated.json()
            _assert_ledger_evidence(
                regenerated_workspace,
                accepted_corrected_m2.json()["artifact"],
            )
            regenerated_run_id = UUID(
                regenerated_workspace["artifact"]["generated_by_run_id"]
            )

        initial_run = _run_record(app.state.repository, initial_run_id)
        regenerated_run = _run_record(app.state.repository, regenerated_run_id)
        if any(
            run["code_commit"] != code_commit
            or run["workflow_version"] != M3_WORKFLOW_VERSION
            or run["topology_hash"] != M3_TOPOLOGY_HASH
            for run in (initial_run, regenerated_run)
        ):
            raise RuntimeError("M3 run identity differs from the requested exact commit")
        node_trace = {
            "schema_version": "e4-m3-node-trace/v1",
            "fixture_id": FIXTURE_ID,
            "runs": [
                {
                    "run_id": str(run_id),
                    "nodes": app.state.repository.list_workflow_traces(run_id),
                }
                for run_id in (initial_run_id, regenerated_run_id)
            ],
        }
        if not all(run["nodes"] for run in node_trace["runs"]):
            raise RuntimeError("M3 sanitized LangGraph node trace is missing")

        restarted = create_app(
            database_path=database,
            workflow_database_path=workflow_database,
            model_client=model_client,
            code_commit=code_commit,
        )
        with TestClient(restarted) as client:
            restored = client.get(f"/api/v1/m3/assets/{asset_id}")
            restored.raise_for_status()
            restored_workspace = restored.json()
        if (
            restored_workspace["artifact"]["artifact_id"]
            != regenerated_workspace["artifact"]["artifact_id"]
        ):
            raise RuntimeError("restart did not restore the current M3 artifact")
        with app.state.repository._connect() as connection:
            effect_rows = connection.execute(
                """SELECT effect_key, COUNT(*) AS copies
                FROM workflow_effects
                WHERE run_id IN (?, ?) AND node_name='m3_model_call'
                GROUP BY effect_key""",
                (str(initial_run_id), str(regenerated_run_id)),
            ).fetchall()
        expected_model_effects = (
            initial_run["model_call_count"] + regenerated_run["model_call_count"]
        )
        if len(effect_rows) != expected_model_effects or any(
            row["copies"] != 1 for row in effect_rows
        ):
            raise RuntimeError("M3 model effects are missing or duplicated")

        role_counts = {
            role: sum(
                statement["role"] == role
                for entry in regenerated_workspace["artifact"]["entries"]
                for statement in entry["statements"]
            )
            for role in (
                "ALTERNATIVE",
                "REASON",
                "DECISION",
                "ACTION",
                "OBSERVED_RESULT",
            )
        }
        original_decision_ids = {
            entry["decision_id"] for entry in invalidated.json()["artifact"]["entries"]
        }
        regenerated_decision_ids = {
            entry["decision_id"]
            for entry in regenerated_workspace["artifact"]["entries"]
        }
        artifact_payloads = {
            "m3-workspace.public.json": regenerated_workspace,
            "m3-role-evidence-summary.json": {
                "schema_version": "e4-m3-role-evidence-summary/v1",
                "fixture_id": FIXTURE_ID,
                "role_counts": role_counts,
                "all_required_roles_present": all(role_counts.values()),
                "all_evidence_refs_validated_against_declared_moment": True,
                "raw_source_text_retained": False,
            },
            "m3-correction-regeneration-trace.json": {
                "schema_version": "e4-m3-correction-regeneration/v1",
                "fixture_id": FIXTURE_ID,
                "asset_id": asset_id,
                "confirmed_m3_artifact_id": confirmed.json()["artifact"][
                    "artifact_id"
                ],
                "invalidated_m3_artifact_id": invalidated.json()["artifact"][
                    "artifact_id"
                ],
                "invalidated_by_m2_artifact_id": invalidated.json()["artifact"][
                    "invalidated_by_m2_artifact_id"
                ],
                "regenerated_m3_artifact_id": regenerated_workspace["artifact"][
                    "artifact_id"
                ],
                "regenerated_base_m2_artifact_id": regenerated_workspace["artifact"][
                    "base_m2_artifact_id"
                ],
                "old_artifact_not_current": not invalidated.json()["is_current"],
                "regenerated_artifact_current": regenerated_workspace["is_current"],
                "affected_decision_identity_reused": bool(
                    original_decision_ids & regenerated_decision_ids
                ),
            },
            "m3-langgraph-node-trace.json": node_trace,
            "m3-model-summary.json": {
                "schema_version": "e4-m3-model-summary/v1",
                "fixture_id": FIXTURE_ID,
                "runs": [initial_run, regenerated_run],
            },
            "m3-restart-idempotency-summary.json": {
                "schema_version": "e4-m3-restart-idempotency/v1",
                "fixture_id": FIXTURE_ID,
                "restored_artifact_id": restored_workspace["artifact"]["artifact_id"],
                "expected_artifact_id": regenerated_workspace["artifact"][
                    "artifact_id"
                ],
                "restored_current_identity": True,
                "model_effect_count": len(effect_rows),
                "duplicate_model_effect_key_count": sum(
                    max(0, int(row["copies"]) - 1) for row in effect_rows
                ),
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
            "workflow_version": M3_WORKFLOW_VERSION,
            "topology_hash": M3_TOPOLOGY_HASH,
            "sha256": hashes,
        },
    )
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    hashes = capture(args.output_dir, code_commit=args.code_commit)
    print(
        json.dumps(
            {"result": "PASS", "output_dir": str(args.output_dir), "artifacts": hashes},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
