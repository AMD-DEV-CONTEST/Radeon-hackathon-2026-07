from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from agent_factory.local_inference.admission import (
    AdmissionQueueFull,
    AdmissionQueueTimeout,
    InferenceAdmissionScheduler,
    InferenceAdmissionSettings,
)
from agent_factory.local_inference.capacity import configured_chat_parallel_slots, inspect_chat_inference_capacity
from agent_factory.local_inference.config import load_local_inference_endpoint
from agent_factory.local_inference.http_client import create_private_async_http_client
from agent_factory.local_inference.context_allocation import resolve_llama_context_plan
from agent_factory.env import load_agentfactory_dotenv
from agent_factory.local_inference.memory_budget import (
    estimate_inference_memory,
    warm_inference_memory_metadata,
)
from agent_factory.local_inference.implementation import (
    activate_llama_implementation,
    inspect_llama_implementations,
)
from agent_factory.local_inference.node_control import (
    InferenceMemoryEstimateRequest,
    InferenceLlamaImplementationAction,
    InferenceNodeAction,
    InferenceOperatorAnalysisRequest,
    InferenceNodeProfileConfiguration,
)
from agent_factory.local_inference.operator_analysis import run_llama_operator_analysis
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.local_inference.runtime_manager import LocalInferenceRuntimeManager
from agent_factory.model_pool.schema import (
    LlamaCppInferenceConfig,
    LocalModelArtifact,
    ModelPoolProfile,
    StableDiffusionCppInferenceConfig,
    TransformersInferenceConfig,
)
from agent_factory.model_pool.store import ModelPoolStore


def create_app() -> FastAPI:
    runtime_manager = LocalInferenceRuntimeManager(
        allow_external_control=False,
        restore_enabled_fallback=False,
    )
    chat_maintenance_lock = asyncio.Lock()
    chat_endpoint = load_local_inference_endpoint()
    admission = InferenceAdmissionScheduler(
        InferenceAdmissionSettings.from_environment(
            total_slots=configured_chat_parallel_slots() or 1,
        )
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        await asyncio.to_thread(_warm_enabled_model_metadata)
        await runtime_manager.restore()
        try:
            yield
        finally:
            await runtime_manager.shutdown()

    app = FastAPI(title="FastAgentFactory Inference Node", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/inference/admission")
    async def inference_admission() -> dict[str, object]:
        return admission.snapshot()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")
        identity = _admission_identity(request)
        lease = admission.admit(**identity)
        try:
            ticket = await _acquire_admission(request, lease)
        except AdmissionQueueFull as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except AdmissionQueueTimeout as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        if bool(payload.get("stream")):
            client = create_private_async_http_client(chat_endpoint)
            upstream_context = client.stream(
                "POST",
                chat_endpoint.endpoint("/chat/completions"),
                json=payload,
            )
            try:
                upstream = await upstream_context.__aenter__()
            except BaseException:
                await client.aclose()
                await lease.__aexit__(*sys.exc_info())
                raise

            async def stream_body():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    await upstream_context.__aexit__(None, None, None)
                    await client.aclose()
                    await lease.__aexit__(None, None, None)

            return StreamingResponse(
                stream_body(),
                status_code=upstream.status_code,
                headers={
                    "content-type": upstream.headers.get("content-type", "text/event-stream"),
                    "x-agentfactory-queue-wait-ms": str(round(ticket.queue_wait_seconds * 1000)),
                },
            )
        try:
            async with create_private_async_http_client(chat_endpoint) as client:
                upstream = await client.post(chat_endpoint.endpoint("/chat/completions"), json=payload)
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                headers={
                    "content-type": upstream.headers.get("content-type", "application/json"),
                    "x-agentfactory-queue-wait-ms": str(round(ticket.queue_wait_seconds * 1000)),
                },
            )
        finally:
            await lease.__aexit__(None, None, None)

    @app.post("/tokenize")
    async def tokenize(request: Request) -> Response:
        return await _proxy_request(request, chat_endpoint.server_endpoint("/tokenize"))

    @app.get("/slots")
    async def slots(request: Request) -> Response:
        return await _proxy_request(request, chat_endpoint.server_endpoint("/slots"))

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        return await _proxy_request(request, chat_endpoint.server_endpoint("/metrics"))

    @app.get("/runtime/rocm")
    async def rocm_runtime() -> dict[str, Any]:
        return inspect_rocm_runtime(require_available=False).payload()

    @app.get("/runtime/software")
    async def runtime_software() -> dict[str, Any]:
        return _software_payload()

    @app.get("/runtime/llama")
    async def llama_runtime() -> dict[str, Any]:
        return inspect_llama_implementations().model_dump(mode="json")

    @app.post("/runtime/llama/activate")
    async def activate_llama_runtime(
        request: InferenceLlamaImplementationAction,
    ) -> dict[str, Any]:
        if chat_maintenance_lock.locked():
            raise HTTPException(
                status_code=409,
                detail="another chat runtime maintenance operation is already running",
            )
        async with chat_maintenance_lock:
            return await _execute_implementation_activation(runtime_manager, request)

    @app.get("/runtimes")
    async def runtimes() -> dict[str, Any]:
        return {"runtimes": [_runtime_payload(item) for item in runtime_manager.states()]}

    @app.get("/models")
    async def models() -> dict[str, Any]:
        store = ModelPoolStore()
        rocm = inspect_rocm_runtime(require_available=False)
        device = rocm.devices[0] if rocm.devices else None
        runtime_by_profile = {
            str(item.get("profile_id") or ""): item
            for item in runtime_manager.states()
            if str(item.get("profile_id") or "")
        }
        result: list[dict[str, Any]] = []
        for profile in store.list_profiles(enabled=True):
            artifact = store.require_artifact(profile.artifact_id)
            runtime = runtime_by_profile.get(profile.profile_id, {})
            size_bytes = None
            if artifact.local_path:
                path = artifact.resolved_path()
                size_bytes = path.stat().st_size if path.is_file() else None
            capabilities = (
                ["embedding"]
                if profile.kind == "embedding"
                else ["image_generation"]
                if profile.kind == "image_generation"
                else ["completion"]
            )
            if "image" in profile.capabilities.input_modalities:
                capabilities.append("multimodal")
            model_payload = {
                    "model_id": profile.served_model_name,
                    "kind": profile.kind,
                    "format": artifact.model_format,
                    "context_length": artifact.native_context_tokens,
                    "native_context_tokens": artifact.native_context_tokens,
                    "context_extension": (
                        artifact.context_extension.model_dump(mode="json")
                        if artifact.context_extension is not None
                        else None
                    ),
                    "parameter_count": None,
                    "size_bytes": size_bytes,
                    "embedding_dimensions": profile.embedding_dimensions,
                    "capabilities": capabilities,
                    "phase": str(runtime.get("phase") or "idle"),
                    "profile_id": profile.profile_id,
                    "engine": profile.engine,
                    "revision": artifact.revision,
                    "checksum": artifact.checksum,
                    "runtime_configuration": _runtime_configuration(profile, artifact),
                }
            if profile.kind == "chat":
                model_payload["memory_estimate"] = estimate_inference_memory(
                    profile=profile,
                    artifact=artifact,
                    requested=InferenceNodeProfileConfiguration.from_profile(profile),
                    runtime=runtime,
                    device=device,
                ).payload()
            result.append(model_payload)
        return {"models": result}

    @app.post("/models/memory-estimate")
    async def memory_estimate(request: InferenceMemoryEstimateRequest) -> dict[str, Any]:
        profile = _resolve_profile_identity(request.kind, request.model_id)
        artifact = ModelPoolStore().require_artifact(profile.artifact_id)
        runtime = runtime_manager.state_for_profile(profile.profile_id)
        rocm = inspect_rocm_runtime(require_available=False)
        device = rocm.devices[0] if rocm.devices else None
        estimate = estimate_inference_memory(
            profile=profile,
            artifact=artifact,
            requested=request.profile,
            runtime=runtime,
            device=device,
        )
        return {"estimate": estimate.payload()}

    @app.post("/runtimes/load")
    async def load_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        _reject_chat_runtime_action_during_maintenance(request, chat_maintenance_lock)
        profile = _resolve_profile(request, apply_configuration=True)
        runtime = await runtime_manager.load(profile.profile_id)
        if request.kind == "chat":
            await admission.configure_total_slots(configured_chat_parallel_slots() or 1)
        return {"runtime": _runtime_payload(runtime)}

    @app.post("/runtimes/unload")
    async def unload_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        _reject_chat_runtime_action_during_maintenance(request, chat_maintenance_lock)
        profile = _resolve_profile(request)
        return {"runtime": _runtime_payload(await runtime_manager.unload(profile.profile_id), profile=profile)}

    @app.post("/runtimes/restart")
    async def restart_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        _reject_chat_runtime_action_during_maintenance(request, chat_maintenance_lock)
        profile = _resolve_profile(request, apply_configuration=True)
        runtime = await runtime_manager.restart(profile.profile_id)
        if request.kind == "chat":
            await admission.configure_total_slots(configured_chat_parallel_slots() or 1)
        return {"runtime": _runtime_payload(runtime)}

    @app.post("/benchmarks/operator-analysis")
    async def operator_analysis(request: InferenceOperatorAnalysisRequest) -> dict[str, Any]:
        if chat_maintenance_lock.locked():
            raise HTTPException(
                status_code=409,
                detail="another operator analysis is already running",
            )
        async with chat_maintenance_lock:
            return await _execute_operator_analysis(runtime_manager, request)

    return app


def _admission_identity(request: Request) -> dict[str, str]:
    priority = str(request.headers.get("x-agentfactory-priority") or "foreground").strip().lower()
    if priority not in {"foreground", "normal", "background"}:
        raise HTTPException(status_code=400, detail="invalid inference admission priority")
    session_id = str(request.headers.get("x-agentfactory-session-id") or "").strip()
    if not session_id:
        client_host = request.client.host if request.client is not None else "unknown"
        session_id = f"anonymous:{client_host}"
    return {
        "session_id": session_id,
        "request_id": str(request.headers.get("x-agentfactory-request-id") or "").strip(),
        "priority": priority,
    }


async def _proxy_request(request: Request, url: str) -> Response:
    body = await request.body()
    endpoint = load_local_inference_endpoint()
    async with create_private_async_http_client(endpoint) as client:
        upstream = await client.request(request.method, url, content=body or None)
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"content-type": upstream.headers.get("content-type", "application/octet-stream")},
    )


async def _acquire_admission(request: Request, lease: Any) -> Any:
    acquire_task = asyncio.create_task(lease.__aenter__())
    disconnect_task = asyncio.create_task(_wait_for_disconnect(request))
    done, _pending = await asyncio.wait(
        {acquire_task, disconnect_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if disconnect_task in done:
        acquire_task.cancel()
        lease_acquired = False
        try:
            await acquire_task
            lease_acquired = True
        except asyncio.CancelledError:
            pass
        if lease_acquired:
            await lease.__aexit__(None, None, None)
        raise HTTPException(status_code=499, detail="client disconnected while waiting for inference")

    ticket = await acquire_task
    disconnect_task.cancel()
    with suppress(asyncio.CancelledError):
        await disconnect_task
    return ticket


async def _wait_for_disconnect(request: Request) -> None:
    while True:
        message = await request.receive()
        if message.get("type") == "http.disconnect":
            return


def _reject_chat_runtime_action_during_maintenance(
    request: InferenceNodeAction,
    lock: asyncio.Lock,
) -> None:
    if request.kind == "chat" and lock.locked():
        raise HTTPException(
            status_code=409,
            detail="chat runtime control is unavailable during maintenance",
        )


async def _execute_implementation_activation(
    runtime_manager: LocalInferenceRuntimeManager,
    request: InferenceLlamaImplementationAction,
) -> dict[str, Any]:
    current = inspect_llama_implementations()
    if current.active == request.implementation and current.available:
        return {
            "implementation": current.model_dump(mode="json"),
            "runtime": _chat_runtime_state(runtime_manager),
        }
    chat_state = _chat_runtime_state(runtime_manager)
    phase = str(chat_state.get("phase") or "idle")
    if phase not in {"idle", "ready"}:
        raise HTTPException(
            status_code=409,
            detail=f"chat runtime must be idle or ready before switching implementation: {phase}",
        )
    if phase == "ready":
        capacity = await asyncio.to_thread(
            inspect_chat_inference_capacity,
            timeout_seconds=2.0,
        )
        if not capacity.live:
            raise HTTPException(
                status_code=409,
                detail=(
                    "cannot switch llama.cpp implementation because chat slot activity "
                    f"could not be verified: {capacity.detail or capacity.source}"
                ),
            )
        if capacity.busy_slots or capacity.deferred_requests:
            raise HTTPException(
                status_code=409,
                detail=(
                    "cannot switch llama.cpp implementation while chat inference is active: "
                    f"busy_slots={capacity.busy_slots}, "
                    f"deferred_requests={capacity.deferred_requests}"
                ),
            )
    profile_id = str(chat_state.get("profile_id") or "") if phase == "ready" else ""
    if profile_id:
        await runtime_manager.unload(profile_id)
    try:
        activated = activate_llama_implementation(request.implementation)
        if profile_id:
            await runtime_manager.load(profile_id)
            await _wait_runtime_ready(runtime_manager, profile_id)
    except Exception as activation_error:
        rollback_error: Exception | None = None
        if current.active is not None:
            try:
                active_state = _chat_runtime_state(runtime_manager)
                active_profile_id = str(active_state.get("profile_id") or "")
                if active_profile_id:
                    await runtime_manager.unload(active_profile_id)
                activate_llama_implementation(current.active)
                if profile_id:
                    await runtime_manager.load(profile_id)
                    await _wait_runtime_ready(runtime_manager, profile_id)
            except Exception as exc:
                rollback_error = exc
        detail = f"{type(activation_error).__name__}: {activation_error}"
        if rollback_error is not None:
            detail += f"; rollback failed: {type(rollback_error).__name__}: {rollback_error}"
        raise HTTPException(status_code=500, detail=detail) from activation_error
    return {
        "implementation": activated.model_dump(mode="json"),
        "runtime": _chat_runtime_state(runtime_manager),
    }


def _chat_runtime_state(runtime_manager: LocalInferenceRuntimeManager) -> dict[str, Any]:
    return next(
        (
            state
            for state in runtime_manager.states()
            if str(state.get("kind") or "") == "chat"
        ),
        {"kind": "chat", "phase": "idle", "profile_id": ""},
    )


async def _execute_operator_analysis(
    runtime_manager: LocalInferenceRuntimeManager,
    request: InferenceOperatorAnalysisRequest,
) -> dict[str, Any]:
    profile = _resolve_profile(
        InferenceNodeAction(
            kind="chat",
            model_id=request.model_id,
            profile=request.profile,
        ),
        apply_configuration=True,
    )
    state = runtime_manager.state_for_profile(profile.profile_id)
    if state is None or state.get("phase") != "ready":
        raise HTTPException(
            status_code=409,
            detail="operator analysis requires the selected chat runtime to be ready",
        )
    implementation = inspect_llama_implementations()
    if not implementation.available or implementation.active_build is None:
        raise HTTPException(
            status_code=409,
            detail=implementation.error or "active llama.cpp implementation is unavailable",
        )
    artifact = ModelPoolStore().require_artifact(profile.artifact_id)
    await runtime_manager.unload(profile.profile_id)
    result: dict[str, Any] | None = None
    analysis_error: Exception | None = None
    restore_error: Exception | None = None
    try:
        result = await run_llama_operator_analysis(
            profile=profile,
            artifact=artifact,
            build=implementation.active_build,
            analysis_id=request.analysis_id,
            options=request.options,
        )
    except Exception as exc:
        analysis_error = exc
    finally:
        try:
            await runtime_manager.load(profile.profile_id)
            await _wait_runtime_ready(runtime_manager, profile.profile_id)
        except Exception as exc:
            restore_error = exc
    if analysis_error is not None:
        detail = f"{type(analysis_error).__name__}: {analysis_error}"
        if restore_error is not None:
            detail += f"; runtime restore failed: {type(restore_error).__name__}: {restore_error}"
        raise HTTPException(status_code=500, detail=detail)
    if result is None:
        raise HTTPException(status_code=500, detail="operator analysis did not produce a result")
    result.update(
        {
            "runtime_was_paused": True,
            "runtime_restored": restore_error is None,
        }
    )
    if restore_error is not None:
        result.setdefault("warnings", []).append(
            f"runtime restore failed: {type(restore_error).__name__}: {restore_error}"
        )
    return {"result": result}


async def _wait_runtime_ready(
    runtime_manager: LocalInferenceRuntimeManager,
    profile_id: str,
    *,
    timeout_seconds: float = 900.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        state = runtime_manager.state_for_profile(profile_id)
        phase = str(state.get("phase") or "") if state else ""
        if phase == "ready":
            return
        if phase == "failed":
            raise RuntimeError(str(state.get("error") or "runtime restore failed"))
        await asyncio.sleep(1.0)
    raise TimeoutError("chat runtime restore timed out after operator analysis")


def _resolve_profile(
    request: InferenceNodeAction,
    *,
    apply_configuration: bool = False,
) -> ModelPoolProfile:
    profile = _resolve_profile_identity(request.kind, request.model_id)
    if apply_configuration and request.profile is not None:
        profile = _apply_profile_configuration(profile, request.profile)
    return profile


def _resolve_profile_identity(kind: str, model_id: str) -> ModelPoolProfile:
    profiles = [
        profile
        for profile in ModelPoolStore().list_profiles(kind=kind, enabled=True)
        if profile.served_model_name == model_id
    ]
    if len(profiles) != 1:
        raise HTTPException(
            status_code=404,
            detail=f"enabled {kind} model is not registered on the inference node: {model_id}",
        )
    return profiles[0]


def _apply_profile_configuration(
    profile: ModelPoolProfile,
    configuration: InferenceNodeProfileConfiguration,
) -> ModelPoolProfile:
    inference = configuration.inference
    if profile.kind == "chat" and inference is not None and not isinstance(
        inference,
        LlamaCppInferenceConfig,
    ):
        raise ValueError("chat inference nodes require llama.cpp settings")
    if profile.kind == "embedding" and inference is not None and not isinstance(
        inference,
        TransformersInferenceConfig,
    ):
        raise ValueError("embedding inference nodes require Transformers settings")
    if profile.kind == "image_generation" and inference is not None and not isinstance(
        inference,
        StableDiffusionCppInferenceConfig,
    ):
        raise ValueError("image generation inference nodes require stable-diffusion.cpp settings")

    payload = profile.model_dump(mode="json")
    payload.update(
        {
            "limits": configuration.limits.model_dump(mode="json"),
            "capabilities": configuration.capabilities.model_dump(mode="json"),
            "embedding_dimensions": configuration.embedding_dimensions,
            "normalize_embeddings": configuration.normalize_embeddings,
        }
    )
    if inference is not None:
        payload["inference"] = {
            **profile.inference.model_dump(mode="json"),
            **inference.model_dump(mode="json", exclude_none=True),
        }
    if profile.kind == "chat" and configuration.native_context_tokens is not None:
        store = ModelPoolStore()
        artifact = store.require_artifact(profile.artifact_id)
        artifact_payload = artifact.model_dump(mode="json")
        artifact_payload.update(
            {
                "native_context_tokens": configuration.native_context_tokens,
                "context_extension": (
                    configuration.context_extension.model_dump(mode="json")
                    if configuration.context_extension is not None
                    else None
                ),
            }
        )
        store.upsert_artifact(LocalModelArtifact.model_validate(artifact_payload))
    updated = ModelPoolProfile.model_validate(payload)
    return ModelPoolStore().upsert_profile(updated)


def _runtime_payload(
    runtime: dict[str, Any],
    *,
    profile: ModelPoolProfile | None = None,
) -> dict[str, Any]:
    profile_id = str(runtime.get("profile_id") or "")
    resolved = profile or (ModelPoolStore().get_profile(profile_id) if profile_id else None)
    return {
        **runtime,
        "served_model_name": resolved.served_model_name if resolved else "",
    }


def _runtime_configuration(
    profile: ModelPoolProfile,
    artifact: LocalModelArtifact,
) -> dict[str, Any]:
    configuration = profile.inference.model_dump(mode="json")
    mmproj_path = configuration.pop("mmproj_path", None)
    if mmproj_path is not None:
        configuration["multimodal_projector"] = bool(mmproj_path)
    if isinstance(profile.inference, LlamaCppInferenceConfig):
        try:
            context_plan = resolve_llama_context_plan(artifact, profile.limits, profile.inference)
        except ValueError as exc:
            configuration["context_configuration_error"] = str(exc)
            return configuration
        if context_plan is not None:
            configuration["per_slot_context_tokens"] = context_plan.allocation.per_slot_tokens
            configuration["server_context_tokens"] = context_plan.allocation.server_context_tokens
            if context_plan.rope_scaling is not None:
                configuration["rope_scaling"] = asdict(context_plan.rope_scaling)
    return configuration


def _software_payload() -> dict[str, Any]:
    configured_binary = str(os.environ.get("AGENTFACTORY_LLAMA_SERVER_PATH") or "llama-server").strip()
    binary = shutil.which(configured_binary)
    configured_sd_binary = str(os.environ.get("AGENTFACTORY_SD_SERVER_PATH") or "sd-server").strip()
    sd_binary = shutil.which(configured_sd_binary)
    implementation = inspect_llama_implementations()
    return {
        "python_version": sys.version.split()[0],
        "project_revision": _command_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
        ),
        "llama_server_version": _command_output([binary, "--version"]) if binary else "",
        "llama_implementation": implementation.model_dump(mode="json"),
        "sd_server_version": _command_output([sd_binary, "--version"]) if sd_binary else "",
    }


def _warm_enabled_model_metadata() -> None:
    store = ModelPoolStore()
    for profile in store.list_profiles(kind="chat", enabled=True):
        warm_inference_memory_metadata(store.require_artifact(profile.artifact_id))


def _command_output(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Radeon inference node control service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8004)
    args = parser.parse_args()
    load_agentfactory_dotenv()
    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
