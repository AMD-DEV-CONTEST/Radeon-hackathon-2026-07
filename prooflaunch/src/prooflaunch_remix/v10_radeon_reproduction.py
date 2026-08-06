from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError


_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONTAINER_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SHELL_CONTROL = re.compile(r"(?:&&|\|\||[;|<>`\n\r])")


def stable_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class MemoryOptimizationPolicy:
    maximum_resident_heavy_models: int
    release_sequence: tuple[str, ...]
    cpu_offload_enabled: bool
    cpu_offload_target: str
    vae_tiling_enabled: bool
    vae_tile_size: tuple[int, int]
    vae_overlap: int
    attention_slicing_enabled: bool
    attention_slice_size: int | str

    def __post_init__(self) -> None:
        if self.maximum_resident_heavy_models != 1:
            raise V10ContractError("exactly one heavy model may be resident")
        required_release = (
            "drop_model_references",
            "gc_collect",
            "empty_device_cache",
            "synchronize_device",
            "measure_free_memory",
        )
        if self.release_sequence != required_release:
            raise V10ContractError("memory release sequence is incomplete or reordered")
        if not self.cpu_offload_enabled or self.cpu_offload_target != "cpu":
            raise V10ContractError("explicit CPU offload is required")
        width, height = self.vae_tile_size
        if (
            not self.vae_tiling_enabled
            or min(width, height) < 256
            or max(width, height) > 2048
            or not 0 < self.vae_overlap < min(width, height)
        ):
            raise V10ContractError("VAE tiling bounds are invalid")
        if (
            not self.attention_slicing_enabled
            or not (
                self.attention_slice_size == "auto"
                or isinstance(self.attention_slice_size, int)
                and self.attention_slice_size > 0
            )
        ):
            raise V10ContractError("attention slicing must be explicitly bounded")

    @property
    def content_sha256(self) -> str:
        return stable_sha256(self.__dict__)


class CacheLayer(str, Enum):
    PROMPT = "prompt"
    EMBEDDING = "embedding"
    KV = "kv"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class CacheKey:
    layer: CacheLayer
    model_revision: str
    adapter_sha256: str
    input_sha256: str
    policy_sha256: str
    runtime_fingerprint: str

    def __post_init__(self) -> None:
        if not self.model_revision.strip() or not self.runtime_fingerprint.strip():
            raise V10ContractError("cache identity is incomplete")
        for value in (
            self.adapter_sha256,
            self.input_sha256,
            self.policy_sha256,
        ):
            if not _SHA256.fullmatch(value):
                raise V10ContractError("cache hashes must be lowercase SHA-256")

    @property
    def digest(self) -> str:
        return stable_sha256(
            {
                "layer": self.layer.value,
                "model_revision": self.model_revision,
                "adapter_sha256": self.adapter_sha256,
                "input_sha256": self.input_sha256,
                "policy_sha256": self.policy_sha256,
                "runtime_fingerprint": self.runtime_fingerprint,
            }
        )


@dataclass(frozen=True)
class CacheValue:
    payload: bytes
    payload_sha256: str

    @classmethod
    def from_bytes(cls, payload: bytes) -> "CacheValue":
        return cls(payload, hashlib.sha256(payload).hexdigest())

    def __post_init__(self) -> None:
        if hashlib.sha256(self.payload).hexdigest() != self.payload_sha256:
            raise V10ContractError("cache value hash does not match payload")


class LayeredContentCache:
    def __init__(self, maximum_bytes: int) -> None:
        if maximum_bytes < 1:
            raise V10ContractError("cache byte budget must be positive")
        self.maximum_bytes = maximum_bytes
        self._items: OrderedDict[str, tuple[CacheKey, CacheValue]] = OrderedDict()
        self._resident_bytes = 0

    @property
    def resident_bytes(self) -> int:
        return self._resident_bytes

    def put(self, key: CacheKey, value: CacheValue) -> None:
        if len(value.payload) > self.maximum_bytes:
            raise V10ContractError("cache value exceeds the total byte budget")
        digest = key.digest
        if digest in self._items:
            _, previous = self._items.pop(digest)
            self._resident_bytes -= len(previous.payload)
        while self._items and self._resident_bytes + len(value.payload) > self.maximum_bytes:
            _, (_, evicted) = self._items.popitem(last=False)
            self._resident_bytes -= len(evicted.payload)
        self._items[digest] = (key, value)
        self._resident_bytes += len(value.payload)

    def get(self, key: CacheKey) -> bytes | None:
        item = self._items.get(key.digest)
        if item is None:
            return None
        stored_key, value = item
        if stored_key != key or hashlib.sha256(value.payload).hexdigest() != value.payload_sha256:
            self._items.pop(key.digest, None)
            self._resident_bytes -= len(value.payload)
            return None
        self._items.move_to_end(key.digest)
        return value.payload


class FailureKind(str, Enum):
    OOM = "oom"
    KERNEL = "kernel"
    DOWNLOAD = "download"


@dataclass(frozen=True)
class RecoveryPlan:
    kind: FailureKind
    attempt: int
    maximum_attempts: int
    actions: tuple[str, ...]
    checkpoint_required: bool
    exact_hash_required: bool
    atomic_commit_required: bool
    replay_successful_work: bool

    def __post_init__(self) -> None:
        if not 1 <= self.attempt <= self.maximum_attempts <= 2:
            raise V10ContractError("recovery attempts must be positive and capped at two")
        if not self.actions or self.replay_successful_work:
            raise V10ContractError("recovery cannot replay already successful work")
        if self.kind in {FailureKind.KERNEL, FailureKind.DOWNLOAD} and not self.exact_hash_required:
            raise V10ContractError("kernel and download recovery require exact hashes")


def build_recovery_plan(kind: FailureKind, attempt: int) -> RecoveryPlan:
    actions = {
        FailureKind.OOM: (
            "persist_checkpoint",
            "release_resident_model",
            "empty_device_cache",
            "halve_microbatch_or_tile",
            "resume_unfinished_unit",
        ),
        FailureKind.KERNEL: (
            "verify_last_committed_checkpoint",
            "start_clean_kernel",
            "restore_rng_optimizer_scheduler",
            "resume_unfinished_unit",
        ),
        FailureKind.DOWNLOAD: (
            "retain_partial_temp_file",
            "resume_with_http_range",
            "verify_expected_sha256",
            "atomic_rename_after_verification",
        ),
    }[kind]
    return RecoveryPlan(
        kind=kind,
        attempt=attempt,
        maximum_attempts=2,
        actions=actions,
        checkpoint_required=kind in {FailureKind.OOM, FailureKind.KERNEL},
        exact_hash_required=True,
        atomic_commit_required=True,
        replay_successful_work=False,
    )


@dataclass(frozen=True)
class OfflineArtifact:
    relative_path: str
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not self.relative_path.strip()
            or not _SHA256.fullmatch(self.sha256)
            or self.byte_size < 1
        ):
            raise V10ContractError("offline artifact identity is invalid")


@dataclass(frozen=True)
class OfflineBundleManifest:
    artifacts: tuple[OfflineArtifact, ...]
    network_allowed: bool
    local_files_only: bool
    dependency_lock_sha256: str

    def __post_init__(self) -> None:
        if not self.artifacts or len({item.relative_path for item in self.artifacts}) != len(self.artifacts):
            raise V10ContractError("offline manifest requires unique artifacts")
        if self.network_allowed or not self.local_files_only:
            raise V10ContractError("offline execution must fail closed on network access")
        if not _SHA256.fullmatch(self.dependency_lock_sha256):
            raise V10ContractError("offline dependency lock must be hash-bound")

    @property
    def content_sha256(self) -> str:
        return stable_sha256(
            {
                "artifacts": [item.__dict__ for item in self.artifacts],
                "network_allowed": self.network_allowed,
                "local_files_only": self.local_files_only,
                "dependency_lock_sha256": self.dependency_lock_sha256,
            }
        )


@dataclass(frozen=True)
class CleanInstanceContract:
    container_image: str
    container_digest: str
    source_archive_sha256: str
    offline_manifest_sha256: str
    commands: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not self.container_image.strip() or not _CONTAINER_DIGEST.fullmatch(self.container_digest):
            raise V10ContractError("clean instance requires an immutable container digest")
        if not _SHA256.fullmatch(self.source_archive_sha256) or not _SHA256.fullmatch(self.offline_manifest_sha256):
            raise V10ContractError("clean instance inputs must be hash-bound")
        if not self.commands:
            raise V10ContractError("clean instance command sequence is empty")
        for argv in self.commands:
            if not argv or any(not value or _SHELL_CONTROL.search(value) for value in argv):
                raise V10ContractError("clean instance commands must be shell-free argv")

    @property
    def content_sha256(self) -> str:
        return stable_sha256(
            {
                "container_image": self.container_image,
                "container_digest": self.container_digest,
                "source_archive_sha256": self.source_archive_sha256,
                "offline_manifest_sha256": self.offline_manifest_sha256,
                "commands": self.commands,
            }
        )


@dataclass(frozen=True)
class RadeonRuntimeObservation:
    gpu_name: str | None
    total_vram_bytes: int | None
    free_vram_bytes: int | None
    rocm_version: str | None
    hip_version: str | None
    torch_version: str | None
    bf16_forward_passed: bool | None
    fp16_forward_passed: bool | None
    backward_passed: bool | None
    attention_passed: bool | None
    vae_passed: bool | None
    model_checks: Mapping[str, bool | None]
    execution_observed: bool

    def __post_init__(self) -> None:
        if self.execution_observed:
            if (
                self.total_vram_bytes is None
                or self.free_vram_bytes is None
                or self.total_vram_bytes < 1
                or not 0 <= self.free_vram_bytes <= self.total_vram_bytes
            ):
                raise V10ContractError("observed Radeon memory values are invalid")
            if not self.model_checks:
                raise V10ContractError("observed Radeon runtime requires model checks")

    @property
    def complete(self) -> bool:
        flags = (
            self.bf16_forward_passed,
            self.fp16_forward_passed,
            self.backward_passed,
            self.attention_passed,
            self.vae_passed,
        )
        return (
            self.execution_observed
            and all(
                value is not None
                for value in (
                    self.gpu_name,
                    self.total_vram_bytes,
                    self.free_vram_bytes,
                    self.rocm_version,
                    self.hip_version,
                    self.torch_version,
                )
            )
            and all(value is True for value in flags)
            and all(value is True for value in self.model_checks.values())
        )


@dataclass(frozen=True)
class RadeonPerformanceObservation:
    latency_ms: tuple[float, ...]
    peak_vram_bytes: int | None
    gpu_utilization_percent: float | None
    cpu_utilization_percent: float | None
    disk_read_bytes: int | None
    disk_write_bytes: int | None
    model_load_ms: float | None
    matched_baseline_sha256: str | None
    candidate_quality: float | None
    baseline_quality: float | None
    execution_observed: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("gpu_utilization_percent", self.gpu_utilization_percent),
            ("cpu_utilization_percent", self.cpu_utilization_percent),
        ):
            if value is not None and (
                not math.isfinite(value) or not 0 <= value <= 100
            ):
                raise V10ContractError(f"{name} must be between zero and 100")
        for value in (self.peak_vram_bytes, self.disk_read_bytes, self.disk_write_bytes):
            if value is not None and value < 0:
                raise V10ContractError("performance byte counters cannot be negative")

    @property
    def complete(self) -> bool:
        values = self.latency_ms
        return (
            self.execution_observed
            and bool(values)
            and all(math.isfinite(item) and item > 0 for item in values)
            and self.peak_vram_bytes is not None
            and self.gpu_utilization_percent is not None
            and self.cpu_utilization_percent is not None
            and self.disk_read_bytes is not None
            and self.disk_write_bytes is not None
            and self.model_load_ms is not None
            and self.matched_baseline_sha256 is not None
            and self.candidate_quality is not None
            and self.baseline_quality is not None
            and self.candidate_quality >= self.baseline_quality
        )
