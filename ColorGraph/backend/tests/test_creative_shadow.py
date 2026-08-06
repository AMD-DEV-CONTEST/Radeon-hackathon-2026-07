from __future__ import annotations

import argparse
import hashlib
import json
from types import SimpleNamespace

import colorgraph.cli as cli
from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    FakeCreativeModelProvider,
    ProviderBoundary,
    ProviderFailureType,
    ProviderUsage,
    RawProviderResponse,
    RuntimePolicy,
)
from colorgraph.agent.creative_shadow import (
    PROVIDER_SHADOW_REPORT_VERSION,
    ProviderShadowRunReport,
    build_provider_shadow_request,
    run_provider_shadow,
)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _providers(provider: FakeCreativeModelProvider):
    return {role: provider for role in CreativeRole}


async def test_shadow_probe_persists_auditable_output_without_graph_mutation() -> None:
    provider = FakeCreativeModelProvider(
        responses=[
            RawProviderResponse(
                text=json.dumps(
                    {
                        "scene_summary": "A bright snow field under a muted sky.",
                        "observed_visual_cues": ["cool diffuse light", "warm ridge"],
                        "uncertainties": ["cloud motion is ambiguous"],
                    }
                ),
                usage=ProviderUsage(
                    input_tokens=120,
                    output_tokens=40,
                    total_tokens=160,
                ),
                response_id="response:shadow",
            )
        ]
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(maximum_retries=0),
    )
    request = build_provider_shadow_request(
        scene_id="scene_001",
        role=CreativeRole.DIRECTOR,
        prompt="Describe only observable scene evidence.",
        prompt_version="provider-shadow/v1",
        input_asset_digests=(_digest(b"frozen-scene-context"),),
        estimated_input_tokens=256,
    )

    report = await run_provider_shadow(
        runtime,
        scene_id="scene_001",
        request=request,
    )
    restored = ProviderShadowRunReport.model_validate_json(report.model_dump_json())

    assert restored.schema_version == PROVIDER_SHADOW_REPORT_VERSION
    assert restored.status == "completed"
    assert restored.project_state_mutated is False
    assert restored.output is not None
    assert restored.output.observed_visual_cues == [
        "cool diffuse light",
        "warm ridge",
    ]
    assert restored.audit is not None
    assert restored.audit.request_id == "shadow:scene_001"


async def test_shadow_probe_reports_offline_fallback_without_calling_cloud() -> None:
    provider = FakeCreativeModelProvider(
        responses=[],
        boundary=ProviderBoundary.OPENAI,
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
        ),
    )
    request = build_provider_shadow_request(
        scene_id="scene_002",
        role=CreativeRole.CRITIC,
        prompt="Describe only observable scene evidence.",
        prompt_version="provider-shadow/v1",
        input_asset_digests=(_digest(b"frozen-scene-context"),),
    )

    report = await run_provider_shadow(
        runtime,
        scene_id="scene_002",
        request=request,
    )

    assert report.status == "fallback"
    assert report.project_state_mutated is False
    assert report.fallback_reason == ProviderFailureType.OFFLINE
    assert report.audit is None
    assert provider.calls == 0


def test_shadow_cli_offline_mode_writes_fallback_and_audit(
    tmp_path,
    monkeypatch,
) -> None:
    prompt = tmp_path / "scene-prompt.txt"
    prompt.write_text("Describe only observable scene evidence.", encoding="utf-8")
    output = tmp_path / "shadow-report.json"
    monkeypatch.setattr(
        cli,
        "settings",
        SimpleNamespace(
            cache_dir=tmp_path / "cache",
            creative_network_enabled=False,
            enable_openai_creative_provider=False,
            openai_creative_model="configured-test-model",
            openai_creative_model_revision="test-revision",
            openai_creative_base_url="https://api.openai.com/v1",
            openai_creative_image_input=True,
            openai_creative_strict_structured_output=True,
            openai_creative_max_context_tokens=8_192,
            openai_creative_max_images=4,
            openai_creative_input_cost_per_million=0,
            openai_creative_output_cost_per_million=0,
        ),
    )
    arguments = argparse.Namespace(
        scene_id="scene_003",
        role="director",
        prompt_file=str(prompt),
        prompt_version="provider-shadow/v1",
        image=[],
        image_detail="low",
        estimated_input_tokens=128,
        max_output_tokens=256,
        input_token_budget=4_096,
        output_token_budget=1_024,
        maximum_cost_usd=0,
        timeout=1,
        maximum_retries=0,
        requests_per_minute=10,
        consent_cloud_upload=False,
        confirm_cloud_run=False,
        output=str(output),
    )

    exit_code = cli._creative_provider_shadow(arguments)
    payload = json.loads(output.read_text(encoding="utf-8"))
    audit_path = output.with_suffix(".json.audit.jsonl")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert payload["status"] == "fallback"
    assert payload["fallback_reason"] == ProviderFailureType.OFFLINE
    assert payload["project_state_mutated"] is False
    assert audit["failure_type"] == ProviderFailureType.OFFLINE
    assert "credential" not in audit
