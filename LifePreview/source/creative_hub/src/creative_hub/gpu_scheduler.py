from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import floor
from uuid import UUID

from shared_contracts import ResourceRequirement


class GpuResourceClass(StrEnum):
    INTERACTIVE_GENERATION = "interactive_generation"
    CONTINUITY_GENERATION = "continuity_generation"
    USER_ANALYSIS = "user_analysis"
    MODEL_WARMUP = "model_warmup"
    BACKGROUND_LEARNING = "background_learning"


DEFAULT_PRIORITY = {
    GpuResourceClass.INTERACTIVE_GENERATION: 500,
    GpuResourceClass.CONTINUITY_GENERATION: 400,
    GpuResourceClass.USER_ANALYSIS: 300,
    GpuResourceClass.MODEL_WARMUP: 200,
    GpuResourceClass.BACKGROUND_LEARNING: 100,
}


@dataclass(frozen=True, slots=True)
class GpuTaskRequest:
    request_id: UUID
    resource_class: GpuResourceClass
    model_id: str
    estimated_vram_mib: int
    enqueued_at: datetime
    max_runtime_seconds: int
    priority_override: int | None = None
    project_id: UUID | None = None
    scene_id: UUID | None = None
    dependency_request_ids: tuple[UUID, ...] = ()
    pinned_gpu_index: int | None = None
    warm_affinity_wait_seconds: int = 30
    resource_requirement: ResourceRequirement | None = None
    implementation_manifest_digest: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.model_id
            or self.estimated_vram_mib <= 0
            or self.max_runtime_seconds <= 0
            or self.warm_affinity_wait_seconds < 0
            or (
                self.priority_override is not None
                and not 0 <= self.priority_override <= 1000
            )
            or (
                self.pinned_gpu_index is not None
                and self.pinned_gpu_index < 0
            )
            or (
                self.implementation_manifest_digest is not None
                and (
                    len(self.implementation_manifest_digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in self.implementation_manifest_digest
                    )
                )
            )
        ):
            raise ValueError("invalid GPU task request")
        if len(self.dependency_request_ids) != len(
            set(self.dependency_request_ids)
        ):
            raise ValueError("GPU task dependencies must be unique")
        if (
            self.resource_requirement is not None
            and self.implementation_manifest_digest is None
        ):
            raise ValueError(
                "structured GPU request requires an implementation manifest"
            )
        if (
            self.resource_requirement is not None
            and self.pinned_gpu_index is not None
            and self.resource_requirement.gpu_pin is not None
            and self.resource_requirement.gpu_pin
            not in {
                str(self.pinned_gpu_index),
                f"gpu-{self.pinned_gpu_index}",
                f"cuda:{self.pinned_gpu_index}",
            }
        ):
            raise ValueError("legacy and structured GPU pins conflict")


@dataclass(frozen=True, slots=True)
class GpuObservation:
    gpu_index: int
    total_vram_mib: int
    free_vram_mib: int
    active_lease_id: UUID | None = None
    warm_model_id: str | None = None
    device_type: str = "cuda"
    model_digests: tuple[str, ...] = ()
    workflow_digests: tuple[str, ...] = ()
    custom_node_environment_digest: str | None = None
    custom_node_environment_digests: tuple[str, ...] = ()
    implementation_manifest_digests: tuple[str, ...] = ()
    worker_id: str | None = None

    def __post_init__(self) -> None:
        if (
            self.gpu_index < 0
            or self.total_vram_mib <= 0
            or self.free_vram_mib < 0
            or self.free_vram_mib > self.total_vram_mib
            or not self.device_type
        ):
            raise ValueError("invalid GPU observation")
        for digest in (
            *self.model_digests,
            *self.workflow_digests,
            *self.custom_node_environment_digests,
            *self.implementation_manifest_digests,
        ):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("invalid GPU observation digest")
        if (
            self.custom_node_environment_digest is not None
            and (
                len(self.custom_node_environment_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in self.custom_node_environment_digest
                )
            )
        ):
            raise ValueError("invalid GPU observation environment digest")


@dataclass(frozen=True, slots=True)
class GpuScheduleDecision:
    request_id: UUID
    gpu_index: int
    effective_priority: int
    affinity: str
    required_vram_mib: int
    requirement_match: str = "legacy"


class UnifiedGpuScheduler:
    """Pure scheduling policy used by the local broker and its DB mirror."""

    def __init__(
        self,
        *,
        safety_margin_ratio: float = 0.08,
        minimum_safety_margin_mib: int = 1024,
        aging_interval_seconds: int = 30,
        aging_points: int = 10,
        maximum_priority: int = 1000,
    ) -> None:
        if (
            safety_margin_ratio < 0
            or safety_margin_ratio >= 1
            or minimum_safety_margin_mib < 0
            or aging_interval_seconds <= 0
            or aging_points <= 0
            or maximum_priority <= 0
        ):
            raise ValueError("invalid GPU scheduler policy")
        self.safety_margin_ratio = safety_margin_ratio
        self.minimum_safety_margin_mib = minimum_safety_margin_mib
        self.aging_interval_seconds = aging_interval_seconds
        self.aging_points = aging_points
        self.maximum_priority = maximum_priority

    def effective_priority(
        self,
        request: GpuTaskRequest,
        *,
        now: datetime,
    ) -> int:
        waited = max((now - request.enqueued_at).total_seconds(), 0)
        base = (
            request.priority_override
            if request.priority_override is not None
            else DEFAULT_PRIORITY[request.resource_class]
        )
        aged = floor(waited / self.aging_interval_seconds) * self.aging_points
        return min(base + aged, self.maximum_priority)

    def required_vram(self, request: GpuTaskRequest) -> int:
        base = (
            request.resource_requirement.minimum_vram_mb
            if request.resource_requirement is not None
            else request.estimated_vram_mib
        )
        return base + max(
            round(base * self.safety_margin_ratio),
            self.minimum_safety_margin_mib,
        )

    @staticmethod
    def _pin_matches(
        pin: str,
        observation: GpuObservation,
    ) -> bool:
        return pin in {
            str(observation.gpu_index),
            f"gpu-{observation.gpu_index}",
            f"cuda:{observation.gpu_index}",
            observation.worker_id,
        }

    def requirement_matches(
        self,
        request: GpuTaskRequest,
        observation: GpuObservation,
    ) -> bool:
        requirement = request.resource_requirement
        if requirement is None:
            return True
        return (
            observation.device_type == requirement.device_type
            and requirement.model_digest in observation.model_digests
            and requirement.workflow_digest in observation.workflow_digests
            and requirement.custom_node_environment_digest
            in {
                observation.custom_node_environment_digest,
                *observation.custom_node_environment_digests,
            }
            and (
                requirement.gpu_pin is None
                or self._pin_matches(requirement.gpu_pin, observation)
            )
            and (
                request.implementation_manifest_digest is None
                or request.implementation_manifest_digest
                in observation.implementation_manifest_digests
            )
        )

    def choose(
        self,
        requests: tuple[GpuTaskRequest, ...],
        observations: tuple[GpuObservation, ...],
        *,
        completed_dependencies: frozenset[UUID],
        now: datetime,
    ) -> GpuScheduleDecision | None:
        runnable = [
            request
            for request in requests
            if set(request.dependency_request_ids).issubset(
                completed_dependencies
            )
        ]
        runnable.sort(
            key=lambda request: (
                -self.effective_priority(request, now=now),
                request.enqueued_at,
                str(request.request_id),
            )
        )
        for request in runnable:
            decision = self._place(request, observations, now=now)
            if decision is not None:
                return decision
        return None

    def _place(
        self,
        request: GpuTaskRequest,
        observations: tuple[GpuObservation, ...],
        *,
        now: datetime,
    ) -> GpuScheduleDecision | None:
        required = self.required_vram(request)
        free = [
            gpu
            for gpu in observations
            if (
                gpu.active_lease_id is None
                and gpu.free_vram_mib >= required
                and self.requirement_matches(request, gpu)
            )
        ]
        if request.pinned_gpu_index is not None:
            free = [
                gpu
                for gpu in free
                if gpu.gpu_index == request.pinned_gpu_index
            ]
        if not free:
            return None

        affinity_ids = (
            request.resource_requirement.warm_model_affinity
            if request.resource_requirement is not None
            else ()
        )
        warm = [
            gpu
            for gpu in free
            if gpu.warm_model_id in {request.model_id, *affinity_ids}
        ]
        if warm:
            target = (
                request.resource_requirement.target_vram_mb
                if request.resource_requirement is not None
                else request.estimated_vram_mib
            )
            selected = max(
                warm,
                key=lambda gpu: (
                    gpu.free_vram_mib >= target,
                    gpu.free_vram_mib,
                    -gpu.gpu_index,
                ),
            )
            affinity = "warm_model"
        else:
            warm_busy_exists = any(
                gpu.warm_model_id in {request.model_id, *affinity_ids}
                and gpu.active_lease_id is not None
                for gpu in observations
                if self.requirement_matches(request, gpu)
            )
            waited = max((now - request.enqueued_at).total_seconds(), 0)
            if (
                warm_busy_exists
                and waited < request.warm_affinity_wait_seconds
                and request.pinned_gpu_index is None
            ):
                return None
            selected = max(free, key=lambda gpu: gpu.free_vram_mib)
            affinity = (
                "manual_pin"
                if request.pinned_gpu_index is not None
                else "overflow"
            )
        return GpuScheduleDecision(
            request_id=request.request_id,
            gpu_index=selected.gpu_index,
            effective_priority=self.effective_priority(request, now=now),
            affinity=affinity,
            required_vram_mib=required,
            requirement_match=(
                "exact"
                if request.resource_requirement is not None
                else "legacy"
            ),
        )
