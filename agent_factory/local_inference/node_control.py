from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.local_inference.config import load_inference_telemetry_endpoint
from agent_factory.local_inference.http_client import create_private_async_http_client
from agent_factory.local_inference.implementation import (
    LlamaImplementationId,
    LlamaImplementationStatus,
)
from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    LlamaCppInferenceConfig,
    LocalModelArtifact,
    ModelContextExtensionCapability,
    ModelPoolCapabilities,
    ModelPoolLimits,
    ModelPoolProfile,
    StableDiffusionCppInferenceConfig,
    TransformersInferenceConfig,
)


RuntimeKind = Literal["chat", "embedding", "image_generation"]
RuntimeAction = Literal["load", "unload", "restart"]


class InferenceNodeHTTPError(RuntimeError):
    def __init__(self, *, status_code: int, operation: str, detail: str) -> None:
        suffix = f": {detail}" if detail else ""
        super().__init__(
            f"inference node {operation} failed with HTTP {status_code}{suffix}"
        )
        self.status_code = status_code
        self.detail = detail


class InferenceNodeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuntimeKind
    model_id: str
    profile: "InferenceNodeProfileConfiguration | None" = None


class InferenceNodeProfileConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limits: ModelPoolLimits
    capabilities: ModelPoolCapabilities
    inference: LlamaCppInferenceConfig | TransformersInferenceConfig | StableDiffusionCppInferenceConfig | None = None
    embedding_dimensions: int | None = None
    normalize_embeddings: bool = True
    native_context_tokens: int | None = Field(default=None, ge=1)
    context_extension: ModelContextExtensionCapability | None = None

    @classmethod
    def from_profile(
        cls,
        profile: ModelPoolProfile,
        artifact: LocalModelArtifact | None = None,
    ) -> "InferenceNodeProfileConfiguration":
        inference = profile.inference
        remote_inference = (
            inference.remote_inference
            if isinstance(inference, ExternalInferenceConfig)
            else inference
        )
        return cls(
            limits=profile.limits,
            capabilities=profile.capabilities,
            inference=remote_inference,
            embedding_dimensions=profile.embedding_dimensions,
            normalize_embeddings=profile.normalize_embeddings,
            native_context_tokens=artifact.native_context_tokens if artifact is not None else None,
            context_extension=artifact.context_extension if artifact is not None else None,
        )


class InferenceMemoryEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuntimeKind
    model_id: str
    profile: InferenceNodeProfileConfiguration


class InferenceOperatorAnalysisOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefill_tokens: int = Field(ge=32, le=32768)
    decode_tokens: int = Field(ge=1, le=4096)
    repetitions: int = Field(ge=1, le=20)
    top_kernels: int = Field(ge=5, le=100)


class InferenceOperatorAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    profile: InferenceNodeProfileConfiguration
    analysis_id: str
    options: InferenceOperatorAnalysisOptions


class InferenceLlamaImplementationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    implementation: LlamaImplementationId


class InferenceNodeClient:
    async def software(self) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint("/runtime/software"))
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("inference node response does not contain software metadata")
        return payload

    async def llama_implementation(self) -> LlamaImplementationStatus:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint("/runtime/llama"))
            if response.status_code == 404:
                response = await client.get(endpoint.endpoint("/runtime/software"))
                response.raise_for_status()
                software = response.json()
                payload = software.get("llama_implementation") if isinstance(software, dict) else None
            else:
                response.raise_for_status()
                payload = response.json()
        if not isinstance(payload, dict):
            return LlamaImplementationStatus(
                error="inference node does not report llama.cpp implementation metadata",
            )
        return LlamaImplementationStatus.model_validate(payload)

    async def runtimes(self) -> list[dict[str, Any]]:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint("/runtimes"))
            response.raise_for_status()
            payload = response.json()
        runtimes = payload.get("runtimes") if isinstance(payload, dict) else None
        if not isinstance(runtimes, list):
            raise ValueError("inference node response does not contain runtimes")
        return [item for item in runtimes if isinstance(item, dict)]

    async def action(
        self,
        action: RuntimeAction,
        *,
        kind: RuntimeKind,
        model_id: str,
        profile: ModelPoolProfile | None = None,
        artifact: LocalModelArtifact | None = None,
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint()
        request = InferenceNodeAction(
            kind=kind,
            model_id=model_id,
            profile=(
                InferenceNodeProfileConfiguration.from_profile(profile, artifact)
                if profile
                else None
            ),
        )
        async with create_private_async_http_client(endpoint) as client:
            response = await client.post(
                endpoint.endpoint(f"/runtimes/{action}"),
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            payload = response.json()
        runtime = payload.get("runtime") if isinstance(payload, dict) else None
        if not isinstance(runtime, dict):
            raise ValueError("inference node response does not contain a runtime")
        return runtime

    async def memory_estimate(
        self,
        request: InferenceMemoryEstimateRequest,
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.post(
                endpoint.endpoint("/models/memory-estimate"),
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            payload = response.json()
        estimate = payload.get("estimate") if isinstance(payload, dict) else None
        if not isinstance(estimate, dict):
            raise ValueError("inference node response does not contain a memory estimate")
        return estimate

    async def operator_analysis(
        self,
        request: InferenceOperatorAnalysisRequest,
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint(timeout_seconds=7200.0)
        async with create_private_async_http_client(endpoint) as client:
            response = await client.post(
                endpoint.endpoint("/benchmarks/operator-analysis"),
                json=request.model_dump(mode="json"),
            )
            _raise_for_inference_node_error(response, operation="operator analysis")
            payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise ValueError("inference node response does not contain operator analysis results")
        return result

    async def activate_llama_implementation(
        self,
        implementation: LlamaImplementationId,
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint(timeout_seconds=1200.0)
        request = InferenceLlamaImplementationAction(implementation=implementation)
        async with create_private_async_http_client(endpoint) as client:
            response = await client.post(
                endpoint.endpoint("/runtime/llama/activate"),
                json=request.model_dump(mode="json"),
            )
            _raise_for_inference_node_error(
                response,
                operation="llama.cpp implementation activation",
            )
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("inference node response does not contain activation status")
        return payload


def _raise_for_inference_node_error(
    response: httpx.Response,
    *,
    operation: str,
) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _inference_node_error_detail(response)
        raise InferenceNodeHTTPError(
            status_code=response.status_code,
            operation=operation,
            detail=detail,
        ) from exc


def _inference_node_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return response.text.strip()
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or "").strip()
    return str(payload.get("detail") or payload.get("message") or "").strip()
