from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import time
from typing import Any, Callable, Protocol

from .runtime import CancellationToken


class ProviderState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class VideoRequest:
    shot_id: str
    image_path: Path
    prompt: str
    negative_prompt: str
    duration_seconds: float
    output_directory: Path
    seed: int


@dataclass(frozen=True, slots=True)
class ProviderJob:
    provider_job_id: str
    state: ProviderState
    output_path: Path | None = None
    safe_error_code: str | None = None


class VideoProvider(Protocol):
    name: str

    def submit(self, request: VideoRequest, *, gpu_index: int) -> ProviderJob: ...

    def poll(self, provider_job_id: str) -> ProviderJob: ...

    def cancel(self, provider_job_id: str) -> None: ...

    def fetch(self, provider_job_id: str, destination: Path) -> Path: ...


class ProviderNotConfigured(RuntimeError):
    pass


class SeedanceClient(Protocol):
    def submit(self, request: VideoRequest) -> str | ProviderJob: ...

    def poll(self, provider_job_id: str) -> dict[str, Any] | ProviderJob: ...

    def cancel(self, provider_job_id: str) -> None: ...

    def fetch(self, provider_job_id: str, destination: Path) -> Path: ...


class SeedanceProvider:
    """Contract-only Seedance provider until a real, reviewed client is supplied."""

    name = "seedance"

    def __init__(self, client: SeedanceClient | None = None) -> None:
        self._client = client

    def _configured(self) -> SeedanceClient:
        if self._client is None:
            raise ProviderNotConfigured("Seedance provider is not configured")
        return self._client

    def submit(self, request: VideoRequest, *, gpu_index: int) -> ProviderJob:
        submitted = self._configured().submit(request)
        if isinstance(submitted, ProviderJob):
            return submitted
        if not isinstance(submitted, str) or not submitted:
            raise RuntimeError("Seedance submit response is invalid")
        return ProviderJob(submitted, ProviderState.QUEUED)

    def poll(self, provider_job_id: str) -> ProviderJob:
        value = self._configured().poll(provider_job_id)
        if isinstance(value, ProviderJob):
            return value
        if not isinstance(value, dict):
            raise RuntimeError("Seedance poll response is invalid")
        raw_state = str(value.get("status", "")).casefold()
        state = {
            "pending": ProviderState.QUEUED,
            "queued": ProviderState.QUEUED,
            "processing": ProviderState.RUNNING,
            "running": ProviderState.RUNNING,
            "completed": ProviderState.SUCCEEDED,
            "succeeded": ProviderState.SUCCEEDED,
            "error": ProviderState.FAILED,
            "failed": ProviderState.FAILED,
            "canceled": ProviderState.CANCELLED,
            "cancelled": ProviderState.CANCELLED,
        }.get(raw_state)
        if state is None:
            raise RuntimeError("Seedance status is invalid")
        error_code = value.get("error_code")
        return ProviderJob(
            provider_job_id,
            state,
            safe_error_code=(
                str(error_code)[:128] if isinstance(error_code, str) else None
            ),
        )

    def cancel(self, provider_job_id: str) -> None:
        self._configured().cancel(provider_job_id)

    def fetch(self, provider_job_id: str, destination: Path) -> Path:
        return self._configured().fetch(provider_job_id, destination)


class ComfyWanProvider:
    """Adapter around the existing blocking Comfy/Wan generation callback."""

    name = "comfy_wan"

    def __init__(
        self,
        generator: Callable[[VideoRequest, int], Path],
    ) -> None:
        self._generator = generator
        self._jobs: dict[str, ProviderJob] = {}

    def submit(self, request: VideoRequest, *, gpu_index: int) -> ProviderJob:
        job_id = f"{request.shot_id}-{time.time_ns()}"
        self._jobs[job_id] = ProviderJob(job_id, ProviderState.RUNNING)
        try:
            output = self._generator(request, gpu_index)
            job = ProviderJob(job_id, ProviderState.SUCCEEDED, output_path=output)
        except BaseException:
            job = ProviderJob(job_id, ProviderState.FAILED, safe_error_code="generation_failed")
            self._jobs[job_id] = job
            raise
        self._jobs[job_id] = job
        return job

    def poll(self, provider_job_id: str) -> ProviderJob:
        return self._jobs[provider_job_id]

    def cancel(self, provider_job_id: str) -> None:
        current = self._jobs[provider_job_id]
        if current.state not in {ProviderState.SUCCEEDED, ProviderState.FAILED}:
            self._jobs[provider_job_id] = ProviderJob(
                provider_job_id,
                ProviderState.CANCELLED,
            )

    def fetch(self, provider_job_id: str, destination: Path) -> Path:
        job = self._jobs[provider_job_id]
        if job.state is not ProviderState.SUCCEEDED or job.output_path is None:
            raise RuntimeError("provider output is not ready")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if job.output_path.resolve() != destination.resolve():
            destination.write_bytes(job.output_path.read_bytes())
        return destination


def wait_for_provider(
    provider: VideoProvider,
    provider_job_id: str,
    cancellation: CancellationToken,
    *,
    poll_interval: float = 1.0,
) -> ProviderJob:
    while True:
        cancellation.check()
        job = provider.poll(provider_job_id)
        if job.state in {
            ProviderState.SUCCEEDED,
            ProviderState.FAILED,
            ProviderState.CANCELLED,
        }:
            return job
        time.sleep(poll_interval)
