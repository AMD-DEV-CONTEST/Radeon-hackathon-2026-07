from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

import torch

from colorgraph.config import settings
from colorgraph.devices.base import ComputeBackend


@dataclass(frozen=True, slots=True)
class ModelCacheKey:
    family: str
    model_id: str
    device: str
    dtype: str


@dataclass(slots=True)
class TorchModelResource:
    processor: Any
    model: Any
    model_revision: str | None = None
    checkpoint_sha256: str | None = None
    checkpoint_hash_kind: str | None = None
    auxiliary_tensors: dict[str, torch.Tensor] = field(default_factory=dict)
    auxiliary_lock: RLock = field(default_factory=RLock)


@dataclass(slots=True)
class _ModelEntry[ResourceT]:
    resource: ResourceT
    estimated_bytes: int
    unload: Callable[[ResourceT], None]
    leases: int = 0
    hits: int = 0
    loaded_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)


class ModelLease[ResourceT]:
    def __init__(
        self,
        cache: ModelLifecycleCache[ResourceT],
        key: ModelCacheKey,
        resource: ResourceT,
    ) -> None:
        self._cache = cache
        self._key = key
        self._resource = resource
        self._closed = False

    def __enter__(self) -> ResourceT:
        return self._resource

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cache._release(self._key)


class ModelLifecycleCache[ResourceT]:
    """Lease-aware LRU for device models with an estimated parameter budget."""

    def __init__(
        self,
        *,
        maximum_entries: int,
        maximum_estimated_bytes: int,
    ) -> None:
        if maximum_entries <= 0:
            raise ValueError("maximum_entries must be positive")
        if maximum_estimated_bytes < 0:
            raise ValueError("maximum_estimated_bytes must be non-negative")
        self.maximum_entries = maximum_entries
        self.maximum_estimated_bytes = maximum_estimated_bytes
        self._entries: OrderedDict[ModelCacheKey, _ModelEntry[ResourceT]] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._releases = 0

    def acquire(
        self,
        key: ModelCacheKey,
        *,
        loader: Callable[[], ResourceT],
        estimate_bytes: Callable[[ResourceT], int],
        unload: Callable[[ResourceT], None],
    ) -> ModelLease[ResourceT]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                resource = loader()
                estimated_bytes = estimate_bytes(resource)
                if estimated_bytes < 0:
                    unload(resource)
                    raise ValueError("estimated model bytes must be non-negative")
                entry = _ModelEntry(
                    resource=resource,
                    estimated_bytes=estimated_bytes,
                    unload=unload,
                )
                self._entries[key] = entry
            else:
                self._hits += 1
                entry.hits += 1
                entry.last_used_at = time.monotonic()
                self._entries.move_to_end(key)
            entry.leases += 1
            self._evict_to_limits(protected_key=key)
            return ModelLease(self, key, entry.resource)

    def _release(self, key: ModelCacheKey) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.leases <= 0:
                raise RuntimeError("model lease release does not match an active entry")
            entry.leases -= 1
            entry.last_used_at = time.monotonic()
            self._entries.move_to_end(key)
            self._evict_to_limits()

    def _over_limits(self) -> bool:
        estimated_bytes = sum(entry.estimated_bytes for entry in self._entries.values())
        return len(self._entries) > self.maximum_entries or (
            self.maximum_estimated_bytes > 0
            and estimated_bytes > self.maximum_estimated_bytes
        )

    def _evict_to_limits(self, *, protected_key: ModelCacheKey | None = None) -> None:
        while self._over_limits():
            victim_key = next(
                (
                    key
                    for key, entry in self._entries.items()
                    if entry.leases == 0 and key != protected_key
                ),
                None,
            )
            if victim_key is None:
                return
            victim = self._entries.pop(victim_key)
            victim.unload(victim.resource)
            self._evictions += 1

    def release_idle(self, *, family: str | None = None) -> int:
        released = 0
        with self._lock:
            victims = [
                key
                for key, entry in self._entries.items()
                if entry.leases == 0 and (family is None or key.family == family)
            ]
            for key in victims:
                entry = self._entries.pop(key)
                entry.unload(entry.resource)
                released += 1
                self._releases += 1
        return released

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "active_leases": sum(entry.leases for entry in self._entries.values()),
                "estimated_bytes": sum(
                    entry.estimated_bytes for entry in self._entries.values()
                ),
                "maximum_entries": self.maximum_entries,
                "maximum_estimated_bytes": self.maximum_estimated_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "releases": self._releases,
            }


class ContentTensorCache:
    """Bounded CPU tensor cache keyed by immutable content/model digests."""

    def __init__(self, maximum_entries: int) -> None:
        if maximum_entries <= 0:
            raise ValueError("maximum_entries must be positive")
        self.maximum_entries = maximum_entries
        self._entries: OrderedDict[str, torch.Tensor] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> torch.Tensor | None:
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                self._misses += 1
                return None
            self._hits += 1
            self._entries.move_to_end(key)
            return value.clone()

    def put(self, key: str, value: torch.Tensor) -> None:
        stable = value.detach().to(device="cpu", dtype=torch.float32).contiguous().clone()
        with self._lock:
            self._entries[key] = stable
            self._entries.move_to_end(key)
            while len(self._entries) > self.maximum_entries:
                self._entries.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "maximum_entries": self.maximum_entries,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }


def estimate_torch_model_bytes(resource: TorchModelResource) -> int:
    model = resource.model
    parameter_bytes = sum(
        parameter.numel() * parameter.element_size()
        for parameter in model.parameters()
    )
    buffer_bytes = sum(
        buffer.numel() * buffer.element_size()
        for buffer in model.buffers()
    )
    return parameter_bytes + buffer_bytes


def torch_state_dict_sha256(state: Any) -> str:
    """Hash tensor state independently of checkpoint packaging."""
    digest = hashlib.sha256()
    digest.update(b"colorgraph.torch-state-dict/v1\0")
    for name in sorted(state):
        value = state[name]
        if not isinstance(value, torch.Tensor):
            raise TypeError(f"model state entry {name!r} is not a tensor")
        tensor = value.detach().cpu()
        if tensor.is_quantized:
            tensor = tensor.dequantize()
        if tensor.layout != torch.strided:
            tensor = tensor.to_dense()
        tensor = tensor.contiguous()
        name_bytes = name.encode("utf-8")
        dtype_bytes = str(tensor.dtype).encode("ascii")
        digest.update(len(name_bytes).to_bytes(8, "big"))
        digest.update(name_bytes)
        digest.update(len(dtype_bytes).to_bytes(8, "big"))
        digest.update(dtype_bytes)
        digest.update(len(tensor.shape).to_bytes(8, "big"))
        for dimension in tensor.shape:
            digest.update(int(dimension).to_bytes(8, "big", signed=True))
        raw = tensor.reshape(-1).view(torch.uint8).numpy()
        digest.update(int(raw.nbytes).to_bytes(8, "big"))
        digest.update(memoryview(raw))
    return digest.hexdigest()


def torch_model_state_sha256(model: Any) -> str:
    """Hash the exact loaded tensor state independently of checkpoint packaging."""
    return torch_state_dict_sha256(model.state_dict())


def torch_model_cache_key(
    *,
    family: str,
    model_id: str,
    backend: ComputeBackend,
) -> ModelCacheKey:
    dtype = "float16" if backend.info.runtime in {"cuda", "rocm"} else "float32"
    return ModelCacheKey(
        family=family,
        model_id=model_id,
        device=str(backend.torch_device),
        dtype=dtype,
    )


def unload_torch_resource(
    resource: TorchModelResource,
    *,
    backend: ComputeBackend,
) -> None:
    resource.auxiliary_tensors.clear()
    resource.model.to(device="cpu")
    backend.empty_cache()


MODEL_LIFECYCLE_CACHE = ModelLifecycleCache[TorchModelResource](
    maximum_entries=settings.model_cache_max_entries,
    maximum_estimated_bytes=settings.model_vram_budget_mb * 1024**2,
)
IMAGE_EMBEDDING_CACHE = ContentTensorCache(settings.embedding_cache_max_entries)


def release_inference_models(*, family: str | None = None) -> int:
    return MODEL_LIFECYCLE_CACHE.release_idle(family=family)


def inference_cache_stats() -> dict[str, dict[str, int]]:
    return {
        "models": MODEL_LIFECYCLE_CACHE.stats(),
        "image_embeddings": IMAGE_EMBEDDING_CACHE.stats(),
    }


def clear_inference_caches() -> None:
    MODEL_LIFECYCLE_CACHE.release_idle()
    IMAGE_EMBEDDING_CACHE.clear()
