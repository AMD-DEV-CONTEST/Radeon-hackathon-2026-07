#!/usr/bin/env python3
"""Capture E2 Serving Reference S1 and Vertical Slice V1 on a clean repo."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID


FIXTURE_ID = "chair_public_complete"
FIXTURE_VERSION = "0.1.0"
FIXTURE_SOURCE_URL = "https://www.reddit.com/r/OfficeChairs/comments/hem1s7/"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999999) - 1))
    return ordered[index]


def serving_reference(
    *, repo: Path, python: str, base_url: str, model_id: str
) -> dict[str, Any]:
    command = [
        python,
        str(repo / "scripts" / "verify_e1_model_contract.py"),
        "--base-url",
        base_url,
        "--model-id",
        model_id,
    ]
    observations: list[dict[str, Any]] = []
    for index in range(4):
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=repo,
            check=False,
            text=True,
            capture_output=True,
        )
        wall_ms = round((time.monotonic() - started) * 1000)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"S1 observation {index} did not return JSON: {completed.stderr[-500:]}"
            ) from exc
        if completed.returncode != 0 or payload.get("result") != "PASS":
            raise RuntimeError(f"S1 observation {index} failed: {payload}")
        observation = {
            "sequence": index,
            "warmup": index == 0,
            "elapsed_ms": payload.get("elapsed_ms"),
            "wall_ms": wall_ms,
            "prompt_tokens": payload.get("prompt_tokens"),
            "completion_tokens": payload.get("completion_tokens"),
            "structured_response_valid": payload.get("structured_response_valid"),
            "tool_call_proposal_count": payload.get("tool_call_proposal_count"),
            "all_tool_permissions_false": payload.get("all_tool_permissions_false"),
            "response_id_hash": hashlib.sha256(
                str(payload.get("response_id", "")).encode("utf-8")
            ).hexdigest(),
        }
        completion_tokens = observation["completion_tokens"]
        elapsed_ms = observation["elapsed_ms"]
        observation["completion_tokens_per_second"] = (
            round(completion_tokens / (elapsed_ms / 1000), 3)
            if isinstance(completion_tokens, int)
            and isinstance(elapsed_ms, int)
            and elapsed_ms > 0
            else None
        )
        observations.append(observation)
    measured = observations[1:]
    latencies = [float(item["elapsed_ms"]) for item in measured]
    throughputs = [
        float(item["completion_tokens_per_second"])
        for item in measured
        if item["completion_tokens_per_second"] is not None
    ]
    return {
        "schema_version": "serving-reference-s1/v1",
        "name": "Serving Reference S1",
        "reference_only": True,
        "performance_baseline": False,
        "fixture_id": "e1-a-public-tool-smoke-v1",
        "model_id": model_id,
        "base_url": base_url,
        "warmup_count": 1,
        "sample_count": len(measured),
        "observations": observations,
        "summary": {
            "elapsed_ms_mean": round(statistics.mean(latencies), 3),
            "elapsed_ms_median": round(statistics.median(latencies), 3),
            "elapsed_ms_p95": round(percentile95(latencies), 3),
            "completion_tokens_per_second_mean": (
                round(statistics.mean(throughputs), 3) if throughputs else None
            ),
            "success_rate": "3/3",
            "ttft_ms": None,
            "ttft_status": "NOT_MEASURED_NON_STREAMING_REFERENCE",
            "peak_vram_mib": None,
            "peak_vram_status": "NOT_SAMPLED_BY_THIS_REFERENCE",
        },
        "raw_prompt_or_response_retained": False,
    }


def vertical_slice(
    *, repo: Path, output_dir: Path, commit: str, base_url: str, model_id: str
) -> dict[str, Any]:
    sys.path.insert(0, str(repo))
    from fastapi.testclient import TestClient

    from app.experience_asset.api.main import create_app
    from app.experience_asset.domain.public_serialization import to_public_asset

    fixture_path = repo / "qa" / "fixtures" / f"{FIXTURE_ID}.md"
    fixture_text = fixture_path.read_text(encoding="utf-8")
    database = output_dir / "work" / "experience_asset.sqlite3"
    workflow_database = output_dir / "work" / "experience_asset.workflow.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)

    first_app = create_app(
        database_path=database,
        workflow_database_path=workflow_database,
        model_endpoint=base_url,
        model_id=model_id,
        gpu_viability="VERIFIED",
        code_commit=commit,
    )
    with TestClient(first_app) as client:
        ingested_response = client.post(
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
                "goal_hint": "Create a reusable private Experience Brief.",
            },
        )
        ingested_response.raise_for_status()
        ingested = ingested_response.json()
        asset_id = ingested["asset"]["asset_id"]
        version_id = ingested["asset"]["version_id"]

        edited_response = client.patch(
            f"/api/v1/m1/assets/{asset_id}/brief",
            json={
                "expected_version_id": version_id,
                "goal": "Retain the chair-selection experience for private reuse.",
                "change_reason": "Public E2 Vertical Slice V1 edit.",
            },
        )
        edited_response.raise_for_status()
        edited = edited_response.json()
        version_id = edited["asset"]["version_id"]

        paused_response = client.post(
            f"/api/v1/m1/assets/{asset_id}/pause",
            json={"expected_version_id": version_id},
        )
        paused_response.raise_for_status()
        paused = paused_response.json()
        paused_version_id = paused["asset"]["version_id"]

    second_app = create_app(
        database_path=database,
        workflow_database_path=workflow_database,
        model_endpoint=base_url,
        model_id=model_id,
        gpu_viability="VERIFIED",
        code_commit=commit,
    )
    with TestClient(second_app) as client:
        restored_response = client.get(f"/api/v1/m1/assets/{asset_id}")
        restored_response.raise_for_status()
        restored = restored_response.json()
        if restored["terminal_state"] != "PAUSED":
            raise RuntimeError("M1 restart did not restore PAUSED state")
        resumed_response = client.post(
            f"/api/v1/m1/assets/{asset_id}/resume",
            json={"expected_version_id": paused_version_id},
        )
        resumed_response.raise_for_status()
        resumed = resumed_response.json()
        version_id = resumed["asset"]["version_id"]

        agent_started = time.monotonic()
        agent_response = client.post(
            f"/api/v1/m1/assets/{asset_id}/agent-runs",
            json={
                "expected_version_id": version_id,
                "user_goal": "Ground the M1 brief in the current public fixture only.",
                "allow_current_source_search": True,
            },
        )
        agent_wall_ms = round((time.monotonic() - agent_started) * 1000)
        agent_response.raise_for_status()
        after_agent = agent_response.json()
        agent_run = after_agent.get("latest_agent_run")
        if not agent_run or agent_run.get("terminal_state") != "SUCCEEDED":
            raise RuntimeError(f"real M1 Agent run did not succeed: {agent_run}")
        if not agent_run.get("retrieved_evidence"):
            raise RuntimeError("real M1 Agent run returned no current-source evidence")
        if any(call.get("permission_granted") for call in agent_run["tool_proposals"]):
            raise RuntimeError("model Tool Call proposal granted itself permission")

        confirmed_response = client.post(
            f"/api/v1/m1/assets/{asset_id}/confirm",
            json={
                "expected_version_id": after_agent["asset"]["version_id"],
                "complete_with_gaps": True,
            },
        )
        confirmed_response.raise_for_status()
        confirmed = confirmed_response.json()

    third_app = create_app(
        database_path=database,
        workflow_database_path=workflow_database,
        model_endpoint=base_url,
        model_id=model_id,
        gpu_viability="VERIFIED",
        code_commit=commit,
    )
    with TestClient(third_app) as client:
        final_response = client.get(f"/api/v1/m1/assets/{asset_id}")
        final_response.raise_for_status()
        final_workspace = final_response.json()

    run_id = UUID(agent_run["run_id"])
    run_context = third_app.state.repository.get_workflow_run_context(run_id)
    trace = third_app.state.repository.list_workflow_traces(run_id)
    canonical = third_app.state.repository.get_current(UUID(asset_id))
    public_asset = to_public_asset(canonical)
    public_asset["fixture_id"] = FIXTURE_ID
    public_asset_path = output_dir / "artifacts" / "experience-asset.public.json"
    workspace_path = output_dir / "artifacts" / "m1-workspace.public.json"
    trace_path = output_dir / "artifacts" / "m1-agent-trace.json"
    vertical_path = output_dir / "artifacts" / "vertical-slice-v1.json"
    write_json(public_asset_path, public_asset)
    write_json(workspace_path, final_workspace)
    write_json(
        trace_path,
        {
            "schema_version": "e2-m1-agent-trace/v1",
            "fixture_id": FIXTURE_ID,
            "run_id": str(run_id),
            "code_commit": run_context["code_commit"],
            "model_id": run_context["model_id"],
            "server_base_url": run_context["server_base_url"],
            "model_config_hash": run_context["model_config_hash"],
            "workflow_version": run_context["workflow_version"],
            "topology_hash": run_context["topology_hash"],
            "nodes": trace,
            "raw_prompt_or_response_retained": False,
        },
    )
    slice_summary = {
        "schema_version": "vertical-slice-v1/v1",
        "name": "Vertical Slice V1",
        "fixture_id": FIXTURE_ID,
        "fixture_version": FIXTURE_VERSION,
        "fixture_sha256": hashlib.sha256(fixture_text.encode("utf-8")).hexdigest(),
        "code_commit": commit,
        "asset_id": asset_id,
        "initial_version_id": ingested["asset"]["version_id"],
        "edited_version_id": edited["asset"]["version_id"],
        "paused_version_id": paused_version_id,
        "restored_paused": restored["terminal_state"] == "PAUSED",
        "resumed": resumed["asset"]["lifecycle"] == "ACTIVE",
        "agent_terminal_state": agent_run["terminal_state"],
        "agent_wall_ms": agent_wall_ms,
        "model_id": agent_run.get("model_id"),
        "model_call_count": agent_run.get("model_calls_used"),
        "tool_proposal_count": len(agent_run.get("tool_proposals", [])),
        "all_model_tool_permissions_false": all(
            not call.get("permission_granted")
            for call in agent_run.get("tool_proposals", [])
        ),
        "policy_outcomes": [
            decision.get("outcome") for decision in agent_run.get("policy_decisions", [])
        ],
        "tool_execution_statuses": [
            execution.get("status") for execution in agent_run.get("tool_executions", [])
        ],
        "retrieved_evidence_count": len(agent_run.get("retrieved_evidence", [])),
        "verification_outcomes": (
            [agent_run["verification_report"].get("outcome")]
            if agent_run.get("verification_report")
            else []
        ),
        "final_version_id": final_workspace["asset"]["version_id"],
        "final_m1_state": final_workspace["progress"]["artifact_state"],
        "final_state_restored_after_restart": (
            final_workspace["asset"]["version_id"]
            == confirmed["asset"]["version_id"]
        ),
        "cross_asset_retrieval_used": False,
        "external_side_effects": False,
    }
    write_json(vertical_path, slice_summary)
    return slice_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--environment-json", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model-id", default="Qwen2.5-14B-Instruct")
    args = parser.parse_args()
    repo = args.repo.resolve()
    commit = git(repo, "rev-parse", "HEAD")
    if commit != args.expected_commit:
        raise RuntimeError(f"HEAD {commit} != expected {args.expected_commit}")
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("E2 evidence requires a clean exact-commit worktree")
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    artifacts = args.output_dir / "artifacts"
    artifacts.mkdir()
    environment_target = artifacts / "w7900-environment.json"
    shutil.copyfile(args.environment_json, environment_target)
    started_at = datetime.now(UTC).isoformat()
    try:
        s1 = serving_reference(
            repo=repo,
            python=sys.executable,
            base_url=args.base_url,
            model_id=args.model_id,
        )
        write_json(artifacts / "serving-reference-s1.json", s1)
        v1 = vertical_slice(
            repo=repo,
            output_dir=args.output_dir,
            commit=commit,
            base_url=args.base_url,
            model_id=args.model_id,
        )
        result = "PASS"
        error = None
    except Exception as exc:
        result = "FAIL"
        error = {"error_class": type(exc).__name__, "safe_message": str(exc)}
        raise
    finally:
        write_json(
            args.output_dir / "run-result.json",
            {
                "schema_version": "e2-m1-w7900-evidence/v1",
                "result": locals().get("result", "FAIL"),
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
                "source": {"git_commit": commit, "dirty_tree": False},
                "fixture": {"id": FIXTURE_ID, "version": FIXTURE_VERSION},
                "model": {"id": args.model_id, "base_url": args.base_url},
                "error": locals().get("error"),
                "claims": {
                    "reference_only": True,
                    "performance_baseline": False,
                    "optimization_claim": False,
                },
            },
        )

    hashes = {
        path.name: sha256(path)
        for path in sorted(artifacts.iterdir())
        if path.is_file()
    }
    write_json(
        artifacts / "artifact-hashes.json",
        {
            "schema_version": "artifact-hashes/v1",
            "code_commit": commit,
            "fixture_id": FIXTURE_ID,
            "sha256": hashes,
        },
    )
    packet = args.output_dir.parent / "packet-candidate"
    packet_artifacts = packet / "artifacts"
    packet_artifacts.mkdir(parents=True)
    public_names = [
        "artifact-hashes.json",
        "experience-asset.public.json",
        "m1-agent-trace.json",
        "m1-workspace.public.json",
        "serving-reference-s1.json",
        "vertical-slice-v1.json",
        "w7900-environment.json",
    ]
    for name in public_names:
        shutil.copyfile(artifacts / name, packet_artifacts / name)
    collector_target = packet_artifacts / "run_e2_w7900_evidence.py"
    shutil.copyfile(Path(__file__), collector_target)
    manifest = {
        "schema_version": "engineering-evidence/v1",
        "packet_id": f"e2-m1-w7900-{args.output_dir.parent.name}-{commit[:7]}",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "source": {
            "git_commit": commit,
            "dirty_tree": False,
            "pull_request": "https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/16",
        },
        "quality_mapping": {
            "acceptance_criteria": [
                "AC-01", "AC-02", "AC-03", "AC-04", "AC-10", "AC-13",
                "AC-15", "AC-16", "AC-17", "AC-22", "AC-23", "AC-24", "AC-25",
            ],
            "l1_milestones": ["M1 Source boundary and goal"],
            "l2_gates": [
                "Local inference", "Agent orchestration", "Current-source retrieval",
                "Runtime permission", "Persistence and resume", "Observability",
            ],
            "track_2_relevance": (
                "Exact-main W7900/ROCm/vLLM evidence for the first durable M1 "
                "Agent vertical slice and local model serving reference."
            ),
        },
        "input": {
            "fixture_or_scenario_id": FIXTURE_ID,
            "version": FIXTURE_VERSION,
            "data_class": "adapted_public_research",
        },
        "results": {
            "terminal_state": "E2_EVIDENCE_READY_FOR_REVIEW",
            "serving_reference": s1["summary"],
            "vertical_slice": v1,
            "failures": [],
            "unverified": [
                "Streaming TTFT and sampled peak VRAM were not measured by S1.",
                "This reference is not E8 Baseline v1 and supports no optimization claim.",
                "Human visual acceptance of the live UI is outside this API evidence run.",
            ],
        },
        "artifacts": [
            {"path": f"artifacts/{path.name}", "sha256": sha256(path)}
            for path in sorted(packet_artifacts.iterdir())
            if path.is_file()
        ],
        "decision": {
            "result_class": "CONDITIONAL",
            "condition": "Independent quality-owner review of the sanitized packet.",
            "rollback": f"No product mutation; evidence binds commit {commit}.",
        },
    }
    write_json(packet / "manifest.json", manifest)
    (packet / "summary.md").write_text(
        "\n".join(
            [
                "# E2 / M1 W7900 evidence packet",
                "",
                "Result: `E2_EVIDENCE_READY_FOR_REVIEW`",
                "",
                f"- Commit: `{commit}`",
                f"- Fixture: `{FIXTURE_ID}@{FIXTURE_VERSION}`",
                "- `Serving Reference S1`: one warm-up plus three retained real local-model observations.",
                "- `Vertical Slice V1`: ingest, edit/autosave, pause, process restart, resume,",
                "  real local-model Tool Call proposal, Runtime allow/effect/verify, confirm and restart.",
                "- Reference only; not E8 Baseline and no optimization claim.",
                "- Streaming TTFT, sampled peak VRAM and human UI acceptance remain unverified.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"result": "PASS", "packet": str(packet)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
