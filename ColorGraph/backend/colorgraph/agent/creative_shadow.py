from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent.creative_provider import (
    CreativeModelRequest,
    CreativeModelResult,
    CreativeProviderRuntime,
    CreativeRole,
    FallbackDecision,
    ProviderAuditRecord,
    ProviderBoundary,
    ProviderCapabilities,
    ProviderFailureType,
    ProviderImage,
    provider_runtime_configuration_digest,
    request_digest,
)

PROVIDER_SHADOW_REPORT_VERSION = "colorgraph.creative-provider-shadow/v1"


class ProviderShadowSceneOutput(BaseModel):
    """Minimal transport probe output; it is never compiled into a Grade Graph."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scene_summary: str = Field(min_length=1)
    observed_visual_cues: list[str]
    uncertainties: list[str]


class ProviderShadowRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["colorgraph.creative-provider-shadow/v1"] = (
        PROVIDER_SHADOW_REPORT_VERSION
    )
    created_at: datetime
    scene_id: str = Field(min_length=1)
    role: CreativeRole
    provider_id: str = Field(min_length=1)
    provider_boundary: ProviderBoundary
    model_id: str = Field(min_length=1)
    configured_model_revision: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    provider_capabilities: ProviderCapabilities
    runtime_configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_asset_digests: list[str]
    image_digests: list[str]
    cloud_upload_consent: bool
    project_state_mutated: Literal[False] = False
    status: Literal["completed", "fallback"]
    output: ProviderShadowSceneOutput | None = None
    audit: ProviderAuditRecord | None = None
    fallback_reason: ProviderFailureType | None = None
    fallback_detail: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ProviderShadowRunReport:
        if self.status == "completed":
            if self.output is None or self.audit is None:
                raise ValueError("completed shadow reports require output and audit")
            if self.fallback_reason is not None or self.fallback_detail is not None:
                raise ValueError("completed shadow reports cannot contain fallback fields")
            if (
                self.audit.request_digest != self.request_digest
                or self.audit.provider_id != self.provider_id
                or self.audit.boundary != self.provider_boundary
                or self.audit.model_id != self.model_id
                or self.audit.model_revision != self.model_revision
                or self.audit.role != self.role
                or not self.audit.success
            ):
                raise ValueError(
                    "completed shadow report identity does not match its provider audit"
                )
        else:
            if self.output is not None or self.audit is not None:
                raise ValueError("fallback shadow reports cannot contain provider output")
            if self.fallback_reason is None or self.fallback_detail is None:
                raise ValueError("fallback shadow reports require a reason and detail")
        return self


def build_provider_shadow_request(
    *,
    scene_id: str,
    role: CreativeRole,
    prompt: str,
    prompt_version: str,
    input_asset_digests: tuple[str, ...],
    images: tuple[ProviderImage, ...] = (),
    max_output_tokens: int = 1_024,
    estimated_input_tokens: int = 0,
    cloud_upload_consent: bool = False,
) -> CreativeModelRequest[ProviderShadowSceneOutput]:
    if not scene_id.strip():
        raise ValueError("scene_id must not be empty")
    return CreativeModelRequest(
        role=role,
        prompt=prompt,
        prompt_version=prompt_version,
        schema_version=PROVIDER_SHADOW_REPORT_VERSION,
        output_model=ProviderShadowSceneOutput,
        input_asset_digests=input_asset_digests,
        images=images,
        max_output_tokens=max_output_tokens,
        estimated_input_tokens=estimated_input_tokens,
        cloud_upload_consent=cloud_upload_consent,
        request_id=f"shadow:{scene_id}",
    )


async def run_provider_shadow(
    runtime: CreativeProviderRuntime,
    *,
    scene_id: str,
    request: CreativeModelRequest[ProviderShadowSceneOutput],
) -> ProviderShadowRunReport:
    """Run a transport-only scene probe without exposing a graph mutation path."""

    provider = runtime.providers[request.role]
    outcome = await runtime.run_or_fallback(request)
    common = {
        "created_at": datetime.now(UTC),
        "scene_id": scene_id,
        "role": request.role,
        "provider_id": provider.provider_id,
        "provider_boundary": provider.boundary,
        "model_id": provider.model_id,
        "configured_model_revision": provider.model_revision,
        "provider_capabilities": provider.capabilities,
        "runtime_configuration_digest": provider_runtime_configuration_digest(
            runtime
        ),
        "request_digest": request_digest(request),
        "input_asset_digests": list(request.input_asset_digests),
        "image_digests": [image.sha256 for image in request.images],
        "cloud_upload_consent": request.cloud_upload_consent,
    }
    if isinstance(outcome, FallbackDecision):
        return ProviderShadowRunReport(
            **common,
            model_revision=provider.model_revision,
            status="fallback",
            fallback_reason=outcome.reason,
            fallback_detail=outcome.detail,
        )
    if not isinstance(outcome, CreativeModelResult):
        raise TypeError("creative provider returned an unknown shadow outcome")
    return ProviderShadowRunReport(
        **common,
        model_revision=outcome.audit.model_revision,
        status="completed",
        output=outcome.output,
        audit=outcome.audit,
    )
