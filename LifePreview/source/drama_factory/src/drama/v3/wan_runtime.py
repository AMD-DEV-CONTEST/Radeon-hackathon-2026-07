from __future__ import annotations

import time
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from shared_contracts import FirstLastFrameRequest, ImageToVideoRequest

from .artifact_catalog import FactoryArtifactCatalog
from .domain import FactoryProjectState, GenerationRunStatus
from .durable_comfy import (
    ComfyRuntimeError,
    DurableComfyCoordinator,
    RequestsComfyTransport,
)
from .model_registry import (
    LocalModelRegistry,
    ModelSelectionBlocked,
)
from .prompt_compiler import CompiledWanPrompt
from .state_store import (
    FactoryStateConflict,
    FactoryStateError,
    FactoryStateStore,
)
from .workflows import WanQualityProfile, WanWorkflowBuilder


class WanExecutionError(RuntimeError):
    pass


class WanRequestsComfyTransport(RequestsComfyTransport):
    def upload_image(
        self,
        path: Path,
        *,
        subfolder: str,
    ) -> str:
        if not path.is_file():
            raise WanExecutionError("Comfy input artifact is unavailable")
        with path.open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}/upload/image",
                files={
                    "image": (
                        path.name,
                        handle,
                        "application/octet-stream",
                    )
                },
                data={
                    "overwrite": "false",
                    "subfolder": subfolder,
                    "type": "input",
                },
                timeout=max(self.submit_timeout_seconds, 120),
            )
        response.raise_for_status()
        payload = response.json()
        name = payload.get("name") if isinstance(payload, dict) else None
        actual_subfolder = (
            payload.get("subfolder", subfolder)
            if isinstance(payload, dict)
            else subfolder
        )
        if not isinstance(name, str) or not name:
            raise WanExecutionError("Comfy upload response is incomplete")
        if actual_subfolder:
            normalized_subfolder = str(actual_subfolder).replace("\\", "/")
            return f"{normalized_subfolder}/{name}"
        return name


class WanGenerationExecutor:
    """Execute one already-queued immutable GenerationRun on one Comfy GPU."""

    def __init__(
        self,
        *,
        store: FactoryStateStore,
        catalog: FactoryArtifactCatalog,
        registry: LocalModelRegistry,
        transport: WanRequestsComfyTransport,
        poll_interval_seconds: float = 2,
        maximum_runtime_seconds: int = 3600,
    ) -> None:
        if poll_interval_seconds <= 0 or maximum_runtime_seconds <= 0:
            raise ValueError("Wan execution timing must be positive")
        self.store = store
        self.catalog = catalog
        self.registry = registry
        self.transport = transport
        self.poll_interval_seconds = poll_interval_seconds
        self.maximum_runtime_seconds = maximum_runtime_seconds
        self.coordinator = DurableComfyCoordinator(
            store=store,
            transport=transport,
        )

    def _with_fresh_state(
        self,
        operation: Callable[[int], FactoryProjectState],
        *,
        attempts: int = 30,
    ) -> FactoryProjectState:
        """Retry a run-scoped mutation when another GPU advances the project."""
        for attempt in range(attempts):
            version = self.store.load().state_version
            try:
                return operation(version)
            except FactoryStateConflict:
                pass
            except FactoryStateError as exc:
                if "state version changed" not in str(exc):
                    raise
            if attempt + 1 == attempts:
                break
            time.sleep(min(0.01 * (attempt + 1), 0.2))
        raise WanExecutionError(
            "factory project remained busy while updating this generation run"
        )

    def execute(
        self,
        run_id: UUID,
        *,
        instance_id: str,
        gpu_id: str,
        gpu_lease_id: UUID,
        hub_job_lease_id: UUID,
        quality: WanQualityProfile = WanQualityProfile.QUALITY,
        allow_hash_verified_bootstrap: bool = False,
        heartbeat: Callable[[], None] | None = None,
    ) -> FactoryProjectState:
        state = self.store.load()
        run = next(
            (item for item in state.runs if item.run_id == run_id),
            None,
        )
        if run is None:
            raise WanExecutionError("generation run is unavailable")
        if run.status is not GenerationRunStatus.QUEUED:
            raise WanExecutionError("generation run is not queued")
        registered = next(
            (
                item
                for item in self.registry.list_models()
                if item.entry.model_id == run.request.model_id
            ),
            None,
        )
        if registered is None:
            raise ModelSelectionBlocked("generation model is not registered")
        verification = registered.entry.verification_status.value
        if verification != "load_verified" and not (
            allow_hash_verified_bootstrap
            and verification == "hash_verified"
        ):
            raise ModelSelectionBlocked(
                "generation model is not load-verified"
            )
        capability = self.registry.capability(
            model_id=run.request.model_id,
            mode=run.request.mode,
        )
        if (
            run.request.resolution not in capability.supported_resolutions
            or run.request.duration_seconds
            not in capability.supported_durations_seconds
        ):
            raise ModelSelectionBlocked(
                "generation request exceeds model capability"
            )

        compiled = self._load_prompt(run.request.prompt_snapshot_id)
        first_name = None
        last_name = None
        subfolder = f"factory/{run.run_id}"
        if isinstance(run.request, ImageToVideoRequest):
            first_name = self.transport.upload_image(
                self.catalog.resolve(run.request.first_image),
                subfolder=subfolder,
            )
        elif isinstance(run.request, FirstLastFrameRequest):
            first_name = self.transport.upload_image(
                self.catalog.resolve(run.request.first_image),
                subfolder=subfolder,
            )
            last_name = self.transport.upload_image(
                self.catalog.resolve(run.request.last_image),
                subfolder=subfolder,
            )

        build = WanWorkflowBuilder().build(
            request=run.request,
            compiled=compiled,
            quality=quality,
            first_image_filename=first_name,
            last_image_filename=last_name,
        )
        submission_nonce = uuid4().hex
        client_id = f"drama-{uuid4().hex}"
        state = self._with_fresh_state(
            lambda version: self.coordinator.submit(
                run_id,
                workflow=build.workflow,
                instance_id=instance_id,
                gpu_id=gpu_id,
                gpu_lease_id=gpu_lease_id,
                hub_job_lease_id=hub_job_lease_id,
                expected_state_version=version,
                submission_nonce=submission_nonce,
                client_id=client_id,
            )
        )
        deadline = time.monotonic() + self.maximum_runtime_seconds
        while True:
            if heartbeat is not None:
                heartbeat()
            run = next(item for item in state.runs if item.run_id == run_id)
            if run.status is GenerationRunStatus.MATERIALIZING:
                break
            if run.status in {
                GenerationRunStatus.FAILED,
                GenerationRunStatus.CANCELLED,
                GenerationRunStatus.NEEDS_HUMAN,
            }:
                raise WanExecutionError(
                    f"Wan generation stopped with {run.status.value}: "
                    f"{run.safe_error_code or 'unknown'}"
                )
            if time.monotonic() >= deadline:
                raise WanExecutionError("Wan generation exceeded runtime limit")
            time.sleep(self.poll_interval_seconds)
            state = self._with_fresh_state(
                lambda version: self.coordinator.observe(
                    run_id,
                    expected_state_version=version,
                )
            )

        destination = (
            self.store.root
            / "artifacts"
            / "generated"
            / f"{run_id}.mp4"
        )
        observed_state = {
            "workflow_id": build.workflow_id,
            "workflow_version": build.workflow_version,
            "workflow_sha256": build.workflow_sha256,
            "quality_profile": quality.value,
            "instance_id": instance_id,
            "gpu_id": gpu_id,
            "frame_count": build.frame_count,
            "fps": build.fps,
            "model_files": list(build.model_files),
        }
        state = self._with_fresh_state(
            lambda version: self.coordinator.materialize(
                run_id,
                destination=destination,
                observed_state=observed_state,
                expected_state_version=version,
            )
        )
        take = next(item for item in state.visual_takes if item.run_id == run_id)
        self.catalog.bind(
            take.raw_video_ref,
            destination,
            role="generated_visual_take",
            created_at=take.created_at,
        )
        return state

    def _load_prompt(self, prompt_snapshot_id: UUID) -> CompiledWanPrompt:
        path = self.store.root / "prompts" / f"{prompt_snapshot_id}.json"
        if not path.is_file():
            raise FactoryStateError("compiled prompt snapshot is unavailable")
        return CompiledWanPrompt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
