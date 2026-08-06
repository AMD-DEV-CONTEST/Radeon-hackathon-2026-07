from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from agent_factory.local_inference.config import load_local_inference_endpoint
from agent_factory.local_inference.http_client import create_private_http_client
from agent_factory.model_pool.schema import ExternalInferenceConfig, LlamaCppInferenceConfig, ModelPoolProfile
from agent_factory.model_pool.store import ModelPoolStore


@dataclass(frozen=True, slots=True)
class ChatInferenceCapacity:
    profile_id: str
    total_slots: int
    busy_slots: int
    deferred_requests: int
    available_slots: int
    source: str
    live: bool
    detail: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "total_slots": self.total_slots,
            "busy_slots": self.busy_slots,
            "deferred_requests": self.deferred_requests,
            "available_slots": self.available_slots,
            "source": self.source,
            "live": self.live,
            "detail": self.detail,
        }


def inspect_chat_inference_capacity(
    *,
    store: ModelPoolStore | None = None,
    timeout_seconds: float = 2.0,
) -> ChatInferenceCapacity:
    model_store = store or ModelPoolStore(setup=False)
    profile = _active_chat_profile(model_store)
    configured_slots = _configured_parallel_slots(profile)
    profile_id = profile.profile_id if profile is not None else ""
    try:
        endpoint = load_local_inference_endpoint(timeout_seconds=timeout_seconds)
        with create_private_http_client(endpoint) as client:
            slots_response = client.get(endpoint.server_endpoint("/slots"))
            slots_response.raise_for_status()
            slots = _slot_payload(slots_response.json())
            deferred_requests = (
                _deferred_requests(client, endpoint.server_endpoint("/metrics"))
                + _admission_pending(client, endpoint.server_endpoint("/inference/admission"))
            )
        total_slots = len(slots)
        busy_slots = sum(1 for item in slots if item.get("is_processing") is True)
        idle_slots = max(0, total_slots - busy_slots)
        return ChatInferenceCapacity(
            profile_id=profile_id,
            total_slots=total_slots,
            busy_slots=busy_slots,
            deferred_requests=deferred_requests,
            available_slots=max(0, idle_slots - deferred_requests),
            source="llama_server",
            live=True,
        )
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return ChatInferenceCapacity(
            profile_id=profile_id,
            total_slots=configured_slots,
            busy_slots=0,
            deferred_requests=0,
            available_slots=configured_slots,
            source="model_profile" if configured_slots else "unavailable",
            live=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


def configured_chat_parallel_slots(*, store: ModelPoolStore | None = None) -> int:
    model_store = store or ModelPoolStore(setup=False)
    return _configured_parallel_slots(_active_chat_profile(model_store))


def _active_chat_profile(store: ModelPoolStore) -> ModelPoolProfile | None:
    profile_ids = [
        store.active_profile_id("chat"),
        store.resolve_default_profile_id("task"),
        store.resolve_default_profile_id("main"),
    ]
    for profile_id in profile_ids:
        profile = store.get_profile(profile_id) if profile_id else None
        if profile is not None and profile.kind == "chat" and profile.enabled:
            return profile
    return None


def _configured_parallel_slots(profile: ModelPoolProfile | None) -> int:
    if profile is None:
        return 0
    inference = profile.inference
    if isinstance(inference, ExternalInferenceConfig):
        inference = inference.remote_inference
    if not isinstance(inference, LlamaCppInferenceConfig):
        return 0
    return inference.parallel_slots


def _slot_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("llama-server slots response must be a non-empty array")
    slots = [item for item in value if isinstance(item, dict)]
    if len(slots) != len(value):
        raise ValueError("llama-server slots response contains a non-object item")
    if any("is_processing" not in item for item in slots):
        raise ValueError("llama-server slot does not contain is_processing")
    return slots


def _deferred_requests(client: httpx.Client, metrics_url: str) -> int:
    try:
        response = client.get(metrics_url)
        response.raise_for_status()
    except httpx.HTTPError:
        return 0
    for line in response.text.splitlines():
        if not line.startswith("llamacpp:requests_deferred "):
            continue
        _, raw_value = line.rsplit(" ", 1)
        try:
            return max(0, int(float(raw_value)))
        except ValueError:
            return 0
    return 0


def _admission_pending(client: httpx.Client, admission_url: str) -> int:
    try:
        response = client.get(admission_url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        return max(0, int(payload.get("pending") or 0))
    except (TypeError, ValueError):
        return 0
