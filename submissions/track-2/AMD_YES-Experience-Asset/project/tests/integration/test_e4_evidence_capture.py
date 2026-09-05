from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.experience_asset.inference import FakeModelClient
from app.experience_asset.inference.models import ModelMetadata
from scripts.capture_e4_m3_evidence import _assert_ledger_evidence, capture
from scripts.capture_e4_m3_negative_evidence import (
    _proposal,
    _result,
)
from scripts.capture_e4_m3_negative_evidence import (
    capture as capture_negative,
)
from scripts.finalize_e4_w7900_packet import PUBLIC_ARTIFACTS, finalize
from scripts.run_e4_m3_local_evidence_server import E4PublicFixtureModel
from scripts.run_e4_w7900_gate import _validate_agent_python, build_steps

COMMIT = "0" * 40


class EvidenceLocalModelClient(FakeModelClient):
    model_id = "Qwen2.5-14B-Instruct"
    base_url = "http://127.0.0.1:8000/v1"

    async def generate_m3_ledger(self, request):
        result = _result(_proposal(request))
        return result.model_copy(
            update={
                "metadata": ModelMetadata(
                    server_kind="vllm",
                    server_base_url=self.base_url,
                    model_id=self.model_id,
                    response_id="fixture-response",
                    prompt_tokens=10,
                    completion_tokens=20,
                    elapsed_ms=3,
                    received_at=datetime.now(UTC),
                )
            }
        )


def _evidence_workspace(moment_ids: list[str], evidence_id: str) -> dict:
    roles = ["ALTERNATIVE", "REASON", "DECISION", "ACTION", "OBSERVED_RESULT"]
    return {
        "artifact": {
            "entries": [
                {
                    "statements": [
                        {
                            "role": role,
                            "source_moment_ids": moment_ids,
                            "source_statement_ids": (
                                [evidence_id] if role != "OBSERVED_RESULT" else []
                            ),
                            "derived_from_statement_ids": (
                                [evidence_id] if role == "OBSERVED_RESULT" else []
                            ),
                        }
                        for role in roles
                    ]
                }
            ]
        }
    }


def test_ledger_evidence_accepts_reference_from_union_of_declared_moments() -> None:
    first_moment, second_moment = str(uuid4()), str(uuid4())
    first_evidence, second_evidence = str(uuid4()), str(uuid4())
    m2 = {
        "moments": [
            {
                "moment_id": first_moment,
                "source_statement_ids": [first_evidence],
            },
            {
                "moment_id": second_moment,
                "source_statement_ids": [second_evidence],
            },
        ]
    }

    _assert_ledger_evidence(
        _evidence_workspace(
            [first_moment, second_moment],
            second_evidence,
        ),
        m2,
    )


def test_ledger_evidence_rejects_reference_outside_declared_moment_union() -> None:
    moment_id, valid_evidence = str(uuid4()), str(uuid4())
    m2 = {
        "moments": [
            {
                "moment_id": moment_id,
                "source_statement_ids": [valid_evidence],
            }
        ]
    }

    with pytest.raises(RuntimeError, match="outside its declared M2 moments"):
        _assert_ledger_evidence(
            _evidence_workspace([moment_id], str(uuid4())),
            m2,
        )


def test_public_browser_fixture_covers_m2_semantic_roles() -> None:
    statement_ids = [uuid4(), uuid4(), uuid4()]

    result = asyncio.run(
        E4PublicFixtureModel().generate_m2_roles(
            SimpleNamespace(
                canonical_context={
                    "statement_ids": [str(statement_id) for statement_id in statement_ids]
                }
            )
        )
    )

    assert [item.statement_id for item in result.proposal.assignments] == statement_ids
    assert result.proposal.assignments[0].roles == ["CUE", "CHANGE", "SURPRISE"]
    assert all(not item.roles for item in result.proposal.assignments[1:])
    assert result.metadata.server_kind == "fake"


def test_capture_e4_m3_evidence_covers_real_path_restart_and_regeneration(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts"
    hashes = capture(
        output,
        code_commit=COMMIT,
        model_client=EvidenceLocalModelClient(),
    )
    assert set(hashes) == {
        "m3-correction-regeneration-trace.json",
        "m3-langgraph-node-trace.json",
        "m3-model-summary.json",
        "m3-restart-idempotency-summary.json",
        "m3-role-evidence-summary.json",
        "m3-workspace.public.json",
    }
    role_summary = json.loads(
        (output / "m3-role-evidence-summary.json").read_text(encoding="utf-8")
    )
    assert role_summary["all_required_roles_present"] is True
    assert role_summary["all_evidence_refs_validated_against_declared_moment"] is True
    correction = json.loads(
        (output / "m3-correction-regeneration-trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert correction["old_artifact_not_current"] is True
    assert correction["regenerated_artifact_current"] is True
    assert correction["affected_decision_identity_reused"] is True
    model = json.loads(
        (output / "m3-model-summary.json").read_text(encoding="utf-8")
    )
    assert len(model["runs"]) == 2
    assert all(run["proposal_metadata"] for run in model["runs"])
    assert all(
        metadata["server_kind"] == "vllm"
        for run in model["runs"]
        for metadata in run["proposal_metadata"]
    )


def test_capture_e4_negative_paths_are_zero_effect_and_bounded(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts"
    result = capture_negative(output, code_commit=COMMIT)
    assert result["result"] == "PASS"
    policy = json.loads(
        (output / "m3-policy-denial-trace.json").read_text(encoding="utf-8")
    )
    assert policy["status"]["terminal_state"] == "POLICY_BLOCKED"
    assert policy["tool_execution_effect_count"] == 0
    repair = json.loads(
        (output / "m3-invalid-output-recovery-trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert repair["terminal_state"] == "SUCCEEDED"
    assert repair["model_call_count"] == 2
    assert repair["structured_repairs_used"] == 1
    unsupported = json.loads(
        (output / "m3-unsupported-claim-trace.json").read_text(encoding="utf-8")
    )
    assert unsupported["persisted_m3_artifact"] is False


def test_e4_w7900_plan_is_complete_and_teammate_only_executes_it(
    tmp_path: Path,
) -> None:
    steps = build_steps(
        python="/workspace/amd-track2-agent/venvs/agent/bin/python",
        vllm_python="/workspace/amd-track2-agent/venvs/vllm/bin/python",
        base_url="http://127.0.0.1:8000/v1",
        model_id="Qwen2.5-14B-Instruct",
        model_path=Path("/workspace/amd-track2-agent/models/model"),
        model_manifest=Path("/workspace/amd-track2-agent/repo/config/model.json"),
        output_dir=tmp_path / "raw",
        code_commit=COMMIT,
    )
    assert [step.name for step in steps] == [
        "remote-environment",
        "rocm-environment",
        "w7900-environment-json",
        "model-snapshot-full-sha256",
        "vllm-health",
        "native-tool-call",
        "model-contract",
        "runtime-allow-deny-restart",
        "e4-contract-export-check",
        "e4-m3-regressions",
        "e4-negative-path-artifacts",
        "e4-real-model-artifacts",
        "finalize-sanitized-packet",
    ]
    assert steps[-2].argv[-1] == COMMIT
    snapshot_step = next(
        step for step in steps if step.name == "model-snapshot-full-sha256"
    )
    assert "--full-sha256" in snapshot_step.argv


def test_e4_w7900_gate_accepts_activated_venv_python_symlink(
    tmp_path: Path,
) -> None:
    persistent_root = tmp_path / "amd-track2-agent"
    agent_environment = persistent_root / "venvs" / "agent"
    python = agent_environment / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.symlink_to("/usr/bin/python3.12")

    _validate_agent_python(
        str(python),
        str(agent_environment),
        persistent_root=persistent_root,
    )


def test_e4_w7900_gate_rejects_system_python_even_with_spoofed_venv(
    tmp_path: Path,
) -> None:
    persistent_root = tmp_path / "amd-track2-agent"
    agent_environment = persistent_root / "venvs" / "agent"
    with pytest.raises(RuntimeError, match="activate"):
        _validate_agent_python(
            "/usr/bin/python3.12",
            str(agent_environment),
            persistent_root=persistent_root,
        )


def test_finalize_e4_packet_copies_only_allowlisted_sanitized_artifacts(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "run-1" / "raw"
    artifacts = raw / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "w7900-environment.json").write_text(
        json.dumps(
            {
                "schema_version": "w7900-environment/v1",
                "code_commit": COMMIT,
                "hardware": {"gpu": "AMD Radeon PRO W7900"},
                "software": {"hip": "test"},
            }
        ),
        encoding="utf-8",
    )
    capture_negative(artifacts, code_commit=COMMIT)
    capture(
        artifacts,
        code_commit=COMMIT,
        model_client=EvidenceLocalModelClient(),
    )
    (raw / "private-working.log").write_text("not for Git", encoding="utf-8")
    (raw / "run-result.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "finished_at": "2026-07-30T10:00:00+00:00",
                "source": {
                    "git_commit": COMMIT,
                    "branch": "codex/e4-test",
                    "dirty_tree": False,
                },
                "fixture": {
                    "id": "chair_public_complete",
                    "version": "0.1.0",
                    "data_class": "adapted_public_research",
                },
                "steps": [
                    {"name": "gate", "argv": ["test"], "exit_code": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    packet = finalize(raw, tmp_path / "packet")
    manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["git_commit"] == COMMIT
    assert (
        manifest["results"]["terminal_state"]
        == "W7900_COMPATIBILITY_READY_FOR_REVIEW"
    )
    assert not (packet / "private-working.log").exists()
    assert {path.name for path in (packet / "artifacts").iterdir()} == set(
        PUBLIC_ARTIFACTS
    )
