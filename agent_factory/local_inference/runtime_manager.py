from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import signal
import sys
from typing import Any, Literal, cast
from urllib.parse import urlparse

import httpx

from agent_factory.local_inference.context_allocation import resolve_llama_context_allocation
from agent_factory.local_inference.config import (
    LocalInferenceEndpoint,
    load_local_embedding_endpoint,
    load_local_image_endpoint,
    load_local_inference_endpoint,
)
from agent_factory.local_inference.http_client import create_private_async_http_client
from agent_factory.local_inference.node_control import InferenceNodeClient, RuntimeAction
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    LlamaCppInferenceConfig,
    ModelPoolProfile,
    StableDiffusionCppInferenceConfig,
    utc_now_text,
)
from agent_factory.model_pool.store import ModelPoolStore


RuntimeKind = Literal["chat", "embedding", "image_generation"]
RuntimePhase = Literal["idle", "starting", "loading", "ready", "stopping", "failed"]

_RUNTIME_KINDS: tuple[RuntimeKind, ...] = ("chat", "embedding", "image_generation")
_LOAD_TIMEOUT_SECONDS: dict[RuntimeKind, float] = {
    "chat": 900.0,
    "embedding": 300.0,
    "image_generation": 900.0,
}
_LOG_LIMIT = 80
_PERCENT_PATTERN = re.compile(r"(?<!\d)(\d{1,3})%")


@dataclass(slots=True)
class _RuntimeSlot:
    kind: RuntimeKind
    mode: str = "managed"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    process: asyncio.subprocess.Process | None = None
    readiness_task: asyncio.Task[None] | None = None
    output_task: asyncio.Task[None] | None = None
    profile_id: str = ""
    phase: RuntimePhase = "idle"
    stage: str = "idle"
    progress_percent: int | None = None
    error: str = ""
    started_at: str = ""
    updated_at: str = field(default_factory=utc_now_text)
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=_LOG_LIMIT))

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mode": self.mode,
            "profile_id": self.profile_id,
            "phase": self.phase,
            "stage": self.stage,
            "progress_percent": self.progress_percent,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "error": self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "logs": list(self.logs),
        }


class LocalInferenceRuntimeManager:
    def __init__(
        self,
        *,
        allow_external_control: bool = True,
        restore_enabled_fallback: bool = True,
    ) -> None:
        self._slots = {kind: _RuntimeSlot(kind=kind) for kind in _RUNTIME_KINDS}
        self._project_root = Path(__file__).resolve().parents[2]
        self._node_client = InferenceNodeClient() if allow_external_control else None
        self._restore_enabled_fallback = restore_enabled_fallback

    def states(self) -> list[dict[str, Any]]:
        return [self._slots[kind].payload() for kind in _RUNTIME_KINDS]

    def state_for_profile(self, profile_id: str) -> dict[str, Any] | None:
        for slot in self._slots.values():
            if slot.profile_id == profile_id:
                return slot.payload()
        return None

    def is_ready(self, profile_id: str) -> bool:
        state = self.state_for_profile(profile_id)
        return bool(state and state["phase"] == "ready")

    async def restore(self) -> None:
        store = ModelPoolStore()
        for kind in _RUNTIME_KINDS:
            profile_id = store.active_profile_id(kind)
            profile = store.get_profile(profile_id) if profile_id else None
            if profile is None or not profile.enabled:
                if profile_id:
                    store.set_active_profile_id(kind, None)
                profile_id = None
            if not profile_id and self._restore_enabled_fallback:
                candidates = store.list_profiles(kind=kind, enabled=True)
                profile_id = candidates[0].profile_id if candidates else None
            if profile_id:
                try:
                    await self.load(profile_id)
                except Exception as exc:
                    slot = self._slots[kind]
                    slot.profile_id = profile_id
                    self._fail(slot, exc)

    async def load(self, profile_id: str) -> dict[str, Any]:
        store = ModelPoolStore()
        profile = store.require_profile(profile_id)
        artifact = store.require_artifact(profile.artifact_id)
        if not profile.enabled or not artifact.enabled:
            raise ValueError("profile and model artifact must be enabled before loading")
        self._assert_residency_allowed(profile)
        slot = self._slots[profile.kind]
        async with slot.lock:
            if slot.profile_id == profile.profile_id and slot.phase in {"starting", "loading", "ready"}:
                return slot.payload()
            return await self._start_locked(slot, profile, external_action="load")

    async def restart(self, profile_id: str) -> dict[str, Any]:
        store = ModelPoolStore()
        profile = store.require_profile(profile_id)
        artifact = store.require_artifact(profile.artifact_id)
        if not profile.enabled or not artifact.enabled:
            raise ValueError("profile and model artifact must be enabled before restarting")
        self._assert_residency_allowed(profile)
        slot = self._slots[profile.kind]
        async with slot.lock:
            return await self._start_locked(slot, profile, external_action="restart")

    async def unload(self, profile_id: str) -> dict[str, Any]:
        state = self.state_for_profile(profile_id)
        if state is None:
            profile = ModelPoolStore().get_profile(profile_id)
            kind: RuntimeKind = profile.kind if profile else "chat"
            return _idle_runtime_payload(kind, profile_id)
        slot = self._slots[state["kind"]]
        async with slot.lock:
            profile = ModelPoolStore().get_profile(profile_id)
            if slot.mode == "external" and profile is not None:
                if self._node_client is None:
                    raise ValueError("external inference control is disabled")
                remote = await self._node_client.action(
                    "unload",
                    kind=profile.kind,
                    model_id=profile.served_model_name,
                )
                await self._stop_locked(slot, clear_active=True)
                return _external_runtime_payload(remote, profile)
            await self._stop_locked(slot, clear_active=True)
            return slot.payload()

    async def shutdown(self) -> None:
        for slot in self._slots.values():
            async with slot.lock:
                await self._stop_locked(slot, clear_active=False)

    def _assert_residency_allowed(self, profile: ModelPoolProfile) -> None:
        image_profile = profile if profile.kind == "image_generation" else _active_image_profile(self._slots)
        if image_profile is None or _image_residency_policy(image_profile) != "exclusive":
            return
        conflicting_kind = "chat" if profile.kind == "image_generation" else "image_generation"
        conflict = self._slots[conflicting_kind]
        if conflict.phase in {"starting", "loading", "ready"}:
            raise ValueError(
                "exclusive image generation profile cannot share GPU residency with the chat runtime; "
                f"unload the active {conflicting_kind} model first"
            )

    def _endpoint(self, kind: RuntimeKind) -> LocalInferenceEndpoint:
        if kind == "chat":
            return load_local_inference_endpoint(timeout_seconds=2.0)
        if kind == "embedding":
            return load_local_embedding_endpoint(timeout_seconds=2.0)
        return load_local_image_endpoint(timeout_seconds=2.0)

    def _command(self, profile: ModelPoolProfile, endpoint: LocalInferenceEndpoint) -> list[str]:
        if profile.engine == "external":
            raise ValueError("external inference profiles do not start a local process")
        host, port = _local_binding(endpoint)
        if profile.kind == "chat":
            module = "agent_factory.local_inference.run_llama_server"
        elif profile.kind == "embedding":
            module = "agent_factory.local_inference.embedding_server"
        else:
            module = "agent_factory.local_inference.run_sd_server"
        return [
            sys.executable,
            "-m",
            module,
            "--profile-id",
            profile.profile_id,
            "--host",
            host,
            "--port",
            str(port),
        ]

    async def _wait_until_ready(
        self,
        slot: _RuntimeSlot,
        profile: ModelPoolProfile,
        endpoint: LocalInferenceEndpoint,
        *,
        require_process: bool,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + _LOAD_TIMEOUT_SECONDS[slot.kind]
        readiness_error: Exception | None = None
        async with create_private_async_http_client(endpoint) as client:
            while asyncio.get_running_loop().time() < deadline:
                if require_process and (slot.process is None or slot.process.returncode is not None):
                    return
                try:
                    ready = await _runtime_is_ready(client, endpoint, profile)
                except (httpx.HTTPError, ValueError) as exc:
                    readiness_error = exc
                    ready = False
                if ready:
                    self._update(slot, phase="ready", stage="ready", progress_percent=100)
                    return
                await asyncio.sleep(1.0)
        failure = readiness_error or TimeoutError(f"{slot.kind} model loading timed out")
        self._fail(slot, failure)
        if require_process:
            await self._terminate(slot)

    async def _watch_output(self, slot: _RuntimeSlot) -> None:
        process = slot.process
        if process is None or process.stdout is None:
            return
        buffer = ""
        while chunk := await process.stdout.read(4096):
            buffer += chunk.decode("utf-8", errors="replace")
            lines = re.split(r"[\r\n]+", buffer)
            buffer = lines.pop()
            for line in lines:
                _observe_log_line(slot, line)
        _observe_log_line(slot, buffer)
        return_code = await process.wait()
        if slot.phase not in {"idle", "stopping"}:
            detail = slot.logs[-1] if slot.logs else "no process output"
            self._fail(slot, RuntimeError(f"inference process exited with code {return_code}: {detail}"))

    async def _stop_locked(self, slot: _RuntimeSlot, *, clear_active: bool) -> None:
        if slot.process is not None and slot.process.returncode is None:
            self._update(slot, phase="stopping", stage="stopping", progress_percent=None)
            await self._terminate(slot)
        for task in (slot.readiness_task, slot.output_task):
            if task and not task.done():
                task.cancel()
        if clear_active:
            ModelPoolStore().set_active_profile_id(slot.kind, None)
        slot.process = None
        slot.readiness_task = None
        slot.output_task = None
        slot.profile_id = ""
        slot.mode = "managed"
        slot.phase = "idle"
        slot.stage = "idle"
        slot.progress_percent = None
        slot.error = ""
        slot.started_at = ""
        slot.updated_at = utc_now_text()
        slot.logs.clear()

    async def _start_locked(
        self,
        slot: _RuntimeSlot,
        profile: ModelPoolProfile,
        *,
        external_action: RuntimeAction,
    ) -> dict[str, Any]:
        await self._stop_locked(slot, clear_active=False)
        slot.profile_id = profile.profile_id
        slot.mode = "external" if profile.engine == "external" else "managed"
        slot.phase = "starting"
        slot.stage = "validating_runtime"
        slot.progress_percent = 0
        slot.error = ""
        slot.started_at = utc_now_text()
        slot.updated_at = slot.started_at
        slot.logs.clear()
        try:
            endpoint = self._endpoint(profile.kind)
            if profile.engine == "external":
                if self._node_client is None:
                    raise ValueError("external inference control is disabled")
                remote = await self._node_client.action(
                    external_action,
                    kind=profile.kind,
                    model_id=profile.served_model_name,
                    profile=profile,
                    artifact=ModelPoolStore().require_artifact(profile.artifact_id),
                )
                ModelPoolStore().set_active_profile_id(profile.kind, profile.profile_id)
                _apply_external_runtime(slot, remote, profile)
                if slot.phase in {"starting", "loading", "stopping"}:
                    slot.readiness_task = asyncio.create_task(self._sync_external_runtime(slot, profile))
                return slot.payload()
            await asyncio.to_thread(inspect_rocm_runtime, require_available=True)
            command = self._command(profile, endpoint)
            environment = dict(os.environ)
            environment["PYTHONUNBUFFERED"] = "1"
            slot.process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._project_root,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            ModelPoolStore().set_active_profile_id(profile.kind, profile.profile_id)
            self._update(slot, phase="loading", stage="process_started", progress_percent=5)
            slot.output_task = asyncio.create_task(self._watch_output(slot))
            slot.readiness_task = asyncio.create_task(
                self._wait_until_ready(slot, profile, endpoint, require_process=True)
            )
        except Exception as exc:
            self._fail(slot, exc)
        return slot.payload()

    async def _sync_external_runtime(self, slot: _RuntimeSlot, profile: ModelPoolProfile) -> None:
        if self._node_client is None:
            self._fail(slot, ValueError("external inference control is disabled"))
            return
        deadline = asyncio.get_running_loop().time() + _LOAD_TIMEOUT_SECONDS[slot.kind]
        while asyncio.get_running_loop().time() < deadline:
            try:
                runtimes = await self._node_client.runtimes()
                remote = next(
                    (
                        item
                        for item in runtimes
                        if str(item.get("kind") or "") == profile.kind
                        and str(item.get("served_model_name") or "") == profile.served_model_name
                    ),
                    None,
                )
                if remote is not None:
                    _apply_external_runtime(slot, remote, profile)
                    if slot.phase in {"ready", "failed", "idle"}:
                        return
            except (httpx.HTTPError, ValueError) as exc:
                slot.error = f"{type(exc).__name__}: {exc}"
                slot.updated_at = utc_now_text()
            await asyncio.sleep(1.0)
        self._fail(slot, TimeoutError(f"external {slot.kind} model loading timed out"))

    async def _terminate(self, slot: _RuntimeSlot) -> None:
        process = slot.process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=20.0)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()

    @staticmethod
    def _update(
        slot: _RuntimeSlot,
        *,
        phase: RuntimePhase,
        stage: str,
        progress_percent: int | None,
    ) -> None:
        slot.phase = phase
        slot.stage = stage
        slot.progress_percent = progress_percent
        slot.updated_at = utc_now_text()

    @staticmethod
    def _fail(slot: _RuntimeSlot, exc: Exception) -> None:
        slot.phase = "failed"
        slot.stage = "failed"
        slot.progress_percent = None
        slot.error = f"{type(exc).__name__}: {exc}"
        slot.updated_at = utc_now_text()


def _local_binding(endpoint: LocalInferenceEndpoint) -> tuple[str, int]:
    parsed = urlparse(endpoint.base_url)
    hostname = str(parsed.hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("managed local inference endpoints must use a loopback host")
    host = "127.0.0.1" if hostname == "localhost" else hostname
    port = parsed.port or 80
    return host, port


def _apply_external_runtime(
    slot: _RuntimeSlot,
    remote: dict[str, Any],
    profile: ModelPoolProfile,
) -> None:
    phase = str(remote.get("phase") or "failed")
    if phase not in {"idle", "starting", "loading", "ready", "stopping", "failed"}:
        phase = "failed"
    progress = remote.get("progress_percent")
    slot.mode = "external"
    slot.profile_id = profile.profile_id
    slot.phase = cast(RuntimePhase, phase)
    slot.stage = str(remote.get("stage") or phase)
    slot.progress_percent = int(progress) if isinstance(progress, (int, float)) else None
    slot.error = str(remote.get("error") or "")
    slot.started_at = str(remote.get("started_at") or slot.started_at)
    slot.updated_at = str(remote.get("updated_at") or utc_now_text())
    logs = remote.get("logs")
    slot.logs.clear()
    if isinstance(logs, list):
        slot.logs.extend(str(item) for item in logs[-_LOG_LIMIT:])


def _external_runtime_payload(remote: dict[str, Any], profile: ModelPoolProfile) -> dict[str, Any]:
    payload = dict(remote)
    payload.update(
        {
            "kind": profile.kind,
            "mode": "external",
            "profile_id": profile.profile_id,
            "pid": None,
        }
    )
    return payload


async def _runtime_is_ready(
    client: httpx.AsyncClient,
    endpoint: LocalInferenceEndpoint,
    profile: ModelPoolProfile,
) -> bool:
    if profile.kind == "chat":
        health_response = await client.get(endpoint.server_endpoint("/health"))
        health_response.raise_for_status()
        response = await client.get(endpoint.endpoint("/models"))
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        model_ready = any(
            isinstance(item, dict) and str(item.get("id") or "") == profile.served_model_name
            for item in models or []
        )
        if not model_ready:
            return False
        inference = _llama_inference(profile)
        allocation = (
            resolve_llama_context_allocation(profile.limits, inference)
            if inference is not None
            else None
        )
        if allocation is None:
            return True
        slots_response = await client.get(endpoint.server_endpoint("/slots"))
        slots_response.raise_for_status()
        slots = slots_response.json()
        if not isinstance(slots, list) or len(slots) != allocation.parallel_slots:
            actual_slots = len(slots) if isinstance(slots, list) else 0
            raise ValueError(
                "llama-server parallel slot validation failed: "
                f"configured={allocation.parallel_slots}, actual={actual_slots}"
            )
        slot_contexts = [
            int(item.get("n_ctx") or 0)
            for item in slots
            if isinstance(item, dict)
        ]
        if len(slot_contexts) != allocation.parallel_slots or any(
            value < allocation.per_slot_tokens for value in slot_contexts
        ):
            raise ValueError(
                "llama-server per-slot context validation failed: "
                f"configured={allocation.per_slot_tokens}, actual={slot_contexts}"
            )
        if inference.speculative_decoding.method == "mtp":
            speculative_slots = [
                item.get("speculative") is True
                for item in slots
                if isinstance(item, dict)
            ]
            if len(speculative_slots) != allocation.parallel_slots or not all(speculative_slots):
                raise ValueError(
                    "llama-server MTP validation failed: the profile enables MTP but "
                    f"slot speculative states are {speculative_slots}"
                )
        return True
    if profile.kind == "image_generation":
        response = await client.get(endpoint.endpoint("/models"))
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        return bool(models and any(isinstance(item, dict) for item in models))
    response = await client.get(endpoint.endpoint("/health"))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return False
    if profile.engine == "external":
        remote_model_ids = {
            str(payload.get("model_id") or ""),
            str(payload.get("profile_id") or ""),
        }
        return profile.served_model_name in remote_model_ids
    return str(payload.get("profile_id") or "") == profile.profile_id


def _llama_inference(profile: ModelPoolProfile) -> LlamaCppInferenceConfig | None:
    inference = profile.inference
    if isinstance(inference, ExternalInferenceConfig):
        inference = inference.remote_inference
    return inference if isinstance(inference, LlamaCppInferenceConfig) else None


def _update_progress_from_log(slot: _RuntimeSlot, text: str) -> None:
    normalized = text.lower()
    if slot.kind == "chat" and any(
        token in normalized
        for token in ("load_model: loading model", "llama_model_loader", "loading model")
    ):
        slot.stage = "loading_weights"
        slot.progress_percent = None
    elif slot.kind == "chat" and "model loaded" in normalized:
        slot.stage = "initializing_service"
        slot.progress_percent = max(slot.progress_percent or 0, 90)
    elif "loading" in normalized and any(
        token in normalized for token in ("weight", "checkpoint", "safetensor")
    ):
        slot.stage = "loading_weights"
        match = _PERCENT_PATTERN.search(text)
        if match:
            progress = 10 + min(int(match.group(1)), 100) * 70 // 100
            slot.progress_percent = max(slot.progress_percent or 0, progress)
        elif (slot.progress_percent or 0) <= 10:
            slot.progress_percent = None
    elif any(token in normalized for token in ("torch.compile", "capturing", "engine core", "initialize")):
        slot.stage = "initializing_engine"
        slot.progress_percent = max(slot.progress_percent or 0, 85)
    elif "waiting for application startup" in normalized:
        if slot.kind == "embedding":
            slot.stage = "loading_weights"
            slot.progress_percent = None
        else:
            slot.stage = "initializing_service"
            slot.progress_percent = max(slot.progress_percent or 0, 90)
    slot.updated_at = utc_now_text()


def _observe_log_line(slot: _RuntimeSlot, line: str) -> None:
    text = line.strip()
    if not text:
        return
    slot.logs.append(text[-1000:])
    _update_progress_from_log(slot, text)


def _idle_runtime_payload(kind: RuntimeKind, profile_id: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "mode": "managed",
        "profile_id": profile_id,
        "phase": "idle",
        "stage": "idle",
        "progress_percent": None,
        "pid": None,
        "error": "",
        "started_at": "",
        "updated_at": utc_now_text(),
        "logs": [],
    }


def _active_image_profile(slots: dict[RuntimeKind, _RuntimeSlot]) -> ModelPoolProfile | None:
    slot = slots["image_generation"]
    if not slot.profile_id:
        return None
    return ModelPoolStore().get_profile(slot.profile_id)


def _image_residency_policy(profile: ModelPoolProfile) -> str:
    inference = profile.inference
    if isinstance(inference, ExternalInferenceConfig):
        inference = inference.remote_inference
    if isinstance(inference, StableDiffusionCppInferenceConfig):
        return inference.residency_policy
    return "coexist_if_fit"
