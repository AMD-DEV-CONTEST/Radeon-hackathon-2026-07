from __future__ import annotations

import hashlib
import json
from pathlib import Path

from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    FakeCreativeModelProvider,
    ProviderBoundary,
    ProviderCapabilities,
    ProviderImage,
    ProviderUsage,
    RawProviderResponse,
    RuntimePolicy,
)
from colorgraph.agent.creative_shadow import (
    build_provider_shadow_request,
    run_provider_shadow,
)
from colorgraph.evaluation.creative_agent_readiness import (
    CREATIVE_AGENT_TASK_IDS,
    CreativeAgentReadinessReport,
    CreativeRuntimeSafetySnapshot,
    audit_creative_agent_readiness,
    audit_creative_agent_readiness_file,
)


def _runtime_snapshot() -> CreativeRuntimeSafetySnapshot:
    return CreativeRuntimeSafetySnapshot(
        network_enabled=False,
        provider_feature_enabled=False,
        provider_model_configured=False,
        provider_image_input_declared=False,
        provider_strict_output_declared=False,
        provider_maximum_context_tokens=0,
        provider_maximum_images=0,
        credential_present=False,
        knowledge_corpus_feature_enabled=False,
        knowledge_corpus_path_configured=False,
        critic_calibration_feature_enabled=False,
        critic_calibration_path_configured=False,
        current_runtime_fail_closed=True,
    )


def test_readiness_without_external_evidence_is_explicitly_fail_closed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "readiness.json"

    report = audit_creative_agent_readiness_file(
        output_path=output,
        runtime=_runtime_snapshot(),
    )
    restored = CreativeAgentReadinessReport.model_validate_json(
        output.read_text(encoding="utf-8")
    )

    assert restored == report
    assert set(report.task_gates) == set(CREATIVE_AGENT_TASK_IDS)
    assert not report.all_tasks_eligible_to_archive
    assert not report.formal_release_gates_passed
    assert report.configuration_changed is False
    assert all(
        not gate.eligible_to_archive for gate in report.task_gates.values()
    )
    assert report.checks["current_runtime_fail_closed"]
    assert "OPENAI_API_KEY" not in report.model_dump_json()
    assert "sk-" not in report.model_dump_json()


async def test_real_adapter_contract_shadow_can_only_unlock_runtime_task(
    tmp_path: Path,
) -> None:
    content = b"frozen representative frame"
    image = ProviderImage(
        asset_id="frame:scene-001",
        sha256=hashlib.sha256(content).hexdigest(),
        media_type="image/png",
        content=content,
    )
    provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(
                text=json.dumps(
                    {
                        "scene_summary": "Muted snow and a bright ridge.",
                        "observed_visual_cues": ["diffuse sky", "warm ridge"],
                        "uncertainties": ["weather evolution"],
                    }
                ),
                usage=ProviderUsage(
                    input_tokens=100,
                    output_tokens=30,
                    total_tokens=130,
                ),
                response_id="response:provider-contract",
            )
        ],
        provider_id="openai-responses",
        model_id="real-provider-model",
        model_revision="2026-07-30",
        boundary=ProviderBoundary.OPENAI,
        capabilities=ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=32_768,
            maximum_images=18,
            batch_requests=False,
        ),
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=True,
            cloud_provider_enabled=True,
            maximum_retries=0,
        ),
    )
    request = build_provider_shadow_request(
        scene_id="scene-001",
        role=CreativeRole.DIRECTOR,
        prompt="Describe observable evidence only.",
        prompt_version="provider-shadow/v1",
        input_asset_digests=(hashlib.sha256(b"context").hexdigest(),),
        images=(image,),
        cloud_upload_consent=True,
    )
    provider_report = await run_provider_shadow(
        runtime,
        scene_id="scene-001",
        request=request,
    )
    provider_path = tmp_path / "provider-shadow.json"
    provider_path.write_text(
        provider_report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    report = audit_creative_agent_readiness(
        runtime=_runtime_snapshot(),
        provider_shadow_path=provider_path,
    )

    assert report.task_gates["CG-AGENT-012"].eligible_to_archive
    assert not report.task_gates["CG-CREATIVE-010"].eligible_to_archive
    assert not report.task_gates["CG-RAG-010"].eligible_to_archive
    assert not report.task_gates["CG-CRITIC-010"].eligible_to_archive
    assert not report.task_gates["CG-AGENT-EVAL-010"].eligible_to_archive
    assert report.checks["provider_image_exercised"]
    assert report.checks["provider_cloud_consent"]
    assert report.checks["provider_audit_bound"]
    assert report.checks["provider_response_receipt"]


async def test_digest_pinned_local_adapter_can_unlock_runtime_task(
    tmp_path: Path,
) -> None:
    content = b"local representative frame"
    image = ProviderImage(
        asset_id="frame:scene-local",
        sha256=hashlib.sha256(content).hexdigest(),
        media_type="image/png",
        content=content,
    )
    provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(
                text=json.dumps(
                    {
                        "scene_summary": "Snow, rock, and a river are visible.",
                        "observed_visual_cues": ["snow", "rock", "river"],
                        "uncertainties": ["location"],
                    }
                ),
                response_id="resp_local_receipt",
            )
        ],
        provider_id="ollama-generate-structural-local",
        model_id="qwen3.5:9b",
        model_revision=f"ollama-0.20.6/sha256:{'6' * 64}",
        boundary=ProviderBoundary.LOCAL,
        capabilities=ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=262_144,
            maximum_images=18,
            batch_requests=False,
        ),
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
        ),
    )
    request = build_provider_shadow_request(
        scene_id="scene-local",
        role=CreativeRole.DIRECTOR,
        prompt="Describe directly observable evidence only.",
        prompt_version="ollama-shadow/v1",
        input_asset_digests=(hashlib.sha256(b"context").hexdigest(),),
        images=(image,),
        cloud_upload_consent=False,
    )
    provider_report = await run_provider_shadow(
        runtime,
        scene_id="scene-local",
        request=request,
    )
    provider_path = tmp_path / "ollama-shadow.json"
    provider_path.write_text(
        provider_report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    report = audit_creative_agent_readiness(
        runtime=_runtime_snapshot(),
        provider_shadow_path=provider_path,
    )

    assert report.checks["provider_real_adapter"]
    assert report.checks["provider_cloud_consent"]
    assert report.task_gates["CG-AGENT-012"].eligible_to_archive


async def test_fake_provider_identity_remains_blocked(
    tmp_path: Path,
) -> None:
    provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(
                text=json.dumps(
                    {
                        "scene_summary": "Fixture.",
                        "observed_visual_cues": [],
                        "uncertainties": [],
                    }
                ),
                response_id="fixture-response",
            )
        ],
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
    )
    request = build_provider_shadow_request(
        scene_id="fixture",
        role=CreativeRole.DIRECTOR,
        prompt="Fixture.",
        prompt_version="fixture/v1",
        input_asset_digests=(hashlib.sha256(b"fixture").hexdigest(),),
    )
    provider_report = await run_provider_shadow(
        runtime,
        scene_id="fixture",
        request=request,
    )
    provider_path = tmp_path / "fake-shadow.json"
    provider_path.write_text(
        provider_report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    report = audit_creative_agent_readiness(
        runtime=_runtime_snapshot(),
        provider_shadow_path=provider_path,
    )

    assert not report.checks["provider_real_adapter"]
    assert not report.checks["provider_image_exercised"]
    assert not report.task_gates["CG-AGENT-012"].eligible_to_archive
