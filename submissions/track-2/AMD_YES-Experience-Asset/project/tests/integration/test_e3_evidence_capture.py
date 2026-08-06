import json
from pathlib import Path
from uuid import UUID

from app.experience_asset.inference import (
    FakeModelClient,
    M2SemanticRoleAssignment,
    M2SemanticRoleProposal,
)
from scripts.capture_e3_m2_evidence import capture
from scripts.finalize_e3_w7900_packet import finalize
from scripts.run_e3_w7900_gate import build_steps

COMMIT = "0" * 40


class EvidenceFixtureModelClient(FakeModelClient):
    async def generate_m2_roles(self, request):
        statement_ids = [
            UUID(str(statement_id))
            for statement_id in request.canonical_context["statement_ids"]
        ]
        self.m2_role_proposal = M2SemanticRoleProposal(
            assignments=[
                M2SemanticRoleAssignment(
                    statement_id=statement_id,
                    roles=["CUE", "CHANGE", "SURPRISE"] if index == 0 else [],
                    reasoning="Configured sanitized evidence fixture.",
                )
                for index, statement_id in enumerate(statement_ids)
            ]
        )
        return await super().generate_m2_roles(request)


def test_capture_e3_m2_evidence_is_public_source_linked_and_restart_traced(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts"
    hashes = capture(
        output,
        code_commit=COMMIT,
        model_client=EvidenceFixtureModelClient(),
    )
    assert set(hashes) == {
        "correction-invalidation-trace.json",
        "langgraph-node-trace.json",
        "m2-workspace.public.json",
        "role-summary.json",
        "semantic-model-summary.json",
    }

    roles = json.loads((output / "role-summary.json").read_text(encoding="utf-8"))
    assert roles["all_roles_source_linked"] is True
    assert roles["initial_role_counts"]["cue"] > 0
    assert roles["initial_role_counts"]["change_or_turning"] > 0
    assert roles["initial_role_counts"]["surprise"] > 0

    correction = json.loads(
        (output / "correction-invalidation-trace.json").read_text(encoding="utf-8")
    )
    assert correction["old_artifact_not_current"] is True
    assert correction["regenerated_artifact_current"] is True
    assert (
        correction["regenerated_base_m1_version_id"]
        == correction["latest_m1_version_id"]
    )

    trace = json.loads(
        (output / "langgraph-node-trace.json").read_text(encoding="utf-8")
    )
    assert trace["code_commit"] == COMMIT
    assert trace["nodes"]
    model = json.loads(
        (output / "semantic-model-summary.json").read_text(encoding="utf-8")
    )
    assert model["model_call_count"] == 1
    assert model["server_base_url"].startswith("http://127.0.0.1")
    assert model["raw_prompt_or_response_retained"] is False


def test_w7900_plan_includes_environment_model_runtime_m2_and_artifacts(
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
    names = [step.name for step in steps]
    assert names == [
        "remote-environment",
        "rocm-environment",
        "w7900-environment-json",
        "model-snapshot-full-sha256",
        "vllm-health",
        "native-tool-call",
        "model-contract",
        "runtime-allow-deny-restart",
        "e3-m2-regressions",
        "e3-sanitized-artifacts",
        "finalize-sanitized-packet",
    ]
    capture_step = next(step for step in steps if step.name == "e3-sanitized-artifacts")
    assert capture_step.argv[-1] == COMMIT


def test_finalize_w7900_packet_copies_only_sanitized_artifacts(tmp_path: Path) -> None:
    raw = tmp_path / "run-1" / "raw"
    artifacts = raw / "artifacts"
    capture(
        artifacts,
        code_commit=COMMIT,
        model_client=EvidenceFixtureModelClient(),
    )
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
    (raw / "private-working.log").write_text("not for Git", encoding="utf-8")
    (raw / "run-result.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "finished_at": "2026-07-29T10:00:00+00:00",
                "source": {
                    "git_commit": COMMIT,
                    "branch": "codex/e3-test",
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
    assert manifest["results"]["terminal_state"] == (
        "W7900_COMPATIBILITY_READY_FOR_REVIEW"
    )
    assert "Performance Baseline/Candidate" in " ".join(
        manifest["results"]["unverified"]
    )
    assert not (packet / "private-working.log").exists()
    assert {path.name for path in (packet / "artifacts").iterdir()} == {
        "artifact-hashes.json",
        "correction-invalidation-trace.json",
        "langgraph-node-trace.json",
        "m2-workspace.public.json",
        "role-summary.json",
        "semantic-model-summary.json",
        "w7900-environment.json",
    }
