#!/usr/bin/env python3
"""Crash-safe controller for the user-clicked AMD three-second vertical slice.

The controller owns ordering and durable evidence, while every side effect is an
explicit dependency: cgroup admission, process lifecycle, Comfy transport,
targeted page-cache advice, and ffprobe.  Production wiring can use the existing
loopback Comfy transports; tests never start a process or touch the network.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Protocol

from drama.flux2_reference.workflows import compile_flux2_workflow
from drama.h3.workflows import build_h3_comfy_api_workflow


REQUESTED_DURATION_SECONDS = 3.0
H3_FRAME_COUNT = 73
H3_FPS = 24
H3_DURATION_SECONDS = H3_FRAME_COUNT / H3_FPS
COMPETITION_MEDIA_DURATION_MIN_SECONDS = 2.8
COMPETITION_MEDIA_DURATION_MAX_SECONDS = 3.5
COMPETITION_MEDIA_FRAME_COUNT_MIN = 65
COMPETITION_MEDIA_FRAME_COUNT_MAX = 90
COMPETITION_MEDIA_FPS_MIN = 20.0
COMPETITION_MEDIA_FPS_MAX = 30.0
FRAME_COUNT_WARNING = "ACTUAL_FRAME_COUNT_DEVIATES_FROM_REQUESTED_73"
FPS_WARNING = "ACTUAL_FPS_DEVIATES_FROM_REQUESTED_24"
DURATION_WARNING = "ACTUAL_DURATION_DEVIATES_FROM_EXPECTED_73_OVER_24"
VIEW_ORDER = ("front_three_quarter",)
FLUX_ARGUMENTS = ("--highvram", "--cache-none", "--reserve-vram", "2")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{32,128}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class VerticalSliceError(RuntimeError):
    """The persisted authority or a runtime boundary failed closed."""


class UnknownSubmissionOutcome(VerticalSliceError):
    """Comfy may have accepted a prompt but did not return its prompt id."""


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise VerticalSliceError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: object) -> None:
    _atomic_bytes(
        path,
        (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
    )


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerticalSliceError(f"{label} is unavailable or invalid JSON") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise VerticalSliceError(f"{label} must be a JSON object")
    return value


def _resolve_persistent_file(value: object, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise VerticalSliceError(f"{label} must be an absolute persistent path")
    candidate = Path(value)
    if candidate.is_symlink():
        raise VerticalSliceError(f"{label} symlinks are forbidden")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise VerticalSliceError(f"{label} is outside persistent authority") from exc
    if not resolved.is_file():
        raise VerticalSliceError(f"{label} must be a regular file")
    return resolved


@dataclass(frozen=True, slots=True)
class VerticalSliceRuntimeInputs:
    persistent_root: Path
    click_authority_path: Path
    checkpoint_path: Path
    evidence_root: Path
    output_path: Path

    def __post_init__(self) -> None:
        root = self.persistent_root.resolve()
        if not root.is_absolute():
            raise VerticalSliceError("persistent_root must be absolute")
        object.__setattr__(self, "persistent_root", root)
        for field in ("click_authority_path", "checkpoint_path", "evidence_root", "output_path"):
            value = getattr(self, field)
            if not isinstance(value, Path) or not value.is_absolute():
                raise VerticalSliceError(f"{field} must be an absolute path")
            try:
                value.resolve().relative_to(root)
            except ValueError as exc:
                raise VerticalSliceError(f"{field} must stay inside persistent_root") from exc


@dataclass(frozen=True, slots=True)
class FluxExecutionAuthority:
    capability: Any
    templates: Any
    model_root: str
    reference_profile: str
    source_mode: str
    required_images: int
    view: str
    prompt: str
    prompt_sha256: str
    seed: int
    workflow_sha256: str
    generation_invocation_count: int
    technical_retry_limit: int

    def __post_init__(self) -> None:
        root = PurePosixPath(self.model_root)
        if (
            not root.is_absolute()
            or not self.model_root.startswith("/persistent/")
            or "\\" in self.model_root
        ):
            raise VerticalSliceError("FLUX model_root must be an absolute PVC path")
        if (
            self.reference_profile != "competition-prompt-single-view-v1"
            or self.source_mode != "prompt_synthesized"
            or self.required_images != 1
            or self.view != "front_three_quarter"
            or type(self.prompt) is not str
            or not self.prompt.strip()
            or hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()
            != self.prompt_sha256
            or isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed < 2**64
            or _SHA256_RE.fullmatch(self.workflow_sha256) is None
            or self.generation_invocation_count != 1
            or self.technical_retry_limit != 1
        ):
            raise VerticalSliceError("FLUX competition prompt authority is invalid")

    def exact_weight_authority(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("diffusion_models", self.capability.diffusion_model),
            ("text_encoders", self.capability.text_encoder),
            ("vae", self.capability.vae),
        )
        result: list[tuple[str, str]] = []
        for folder, revision in values:
            digest = _require_sha256(revision.sha256, f"FLUX {folder} SHA")
            path = (PurePosixPath(self.model_root) / folder / revision.filename).as_posix()
            if (
                not path.endswith(".safetensors")
                or ".." in PurePosixPath(path).parts
                or any(mark in path for mark in "*?[]{}")
            ):
                raise VerticalSliceError("FLUX reclaim authority contains an unsafe weight path")
            result.append((path, digest))
        return tuple(result)


@dataclass(frozen=True, slots=True)
class H3BuildAuthority:
    compiled: Any
    plan: Any
    rendered: Any
    binding: Any
    capability: Any
    template_path: Path
    staged_references: tuple[Any, ...]
    seed: int
    reference_profile: str = "production-three-view-v1"
    concrete: Any | None = None


@dataclass(frozen=True, slots=True)
class GeneratedReferenceAsset:
    view_name: str
    path: Path
    sha256: str
    prompt_id: str
    prompt_sha256: str
    seed: int
    workflow_sha256: str
    compiled_workflow_sha256: str
    generation_attempt_ordinal: int
    technical_failure_receipt_sha256: str | None
    source_mode: str = "generated_by_current_flux"
    generated_by_current_flux: bool = True
    flux_output_used: bool = True
    import_authority_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class MediaProbeSummary:
    duration_seconds: float
    fps: float
    frame_count: int
    video_streams: int
    audio_streams: int
    subtitle_streams: int
    format_name: str


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    requested_duration_seconds: float
    frame_count: int
    fps: int
    native_audio: bool
    subtitles: bool
    prompt_id: str
    submission_nonce: str
    workflow_sha256: str
    output_path: Path
    output_sha256: str
    ffprobe: MediaProbeSummary
    media_warnings: tuple[str, ...]


class ProcessController(Protocol):
    def assert_gpu_idle(self, phase: str) -> None: ...

    def start(self, kind: str, arguments: tuple[str, ...]) -> Any: ...

    def stop(self, handle: Any) -> None: ...

    def wait_exited(self, handle: Any) -> None: ...

    def assert_vram_idle(self) -> None: ...

    def wait_for_gpu_activity(
        self, handle: Any, *, kind: str, prompt_id: str
    ) -> dict[str, object]: ...


class ComfySession(Protocol):
    def stage_input(self, local_path: Path, remote_name: str, sha256: str) -> None: ...

    def recover_submission(
        self,
        *,
        prompt_id: str | None,
        client_id: str,
        submission_nonce: str,
        required_metadata: dict[str, object],
    ) -> str | None: ...

    def submit(
        self,
        workflow: dict[str, Any],
        *,
        client_id: str,
        submission_nonce: str,
        extra_data: dict[str, object],
    ) -> str: ...

    def submit_runtime_proof(
        self,
        workflow: dict[str, Any],
        *,
        client_id: str,
        submission_nonce: str,
        extra_data: dict[str, object],
    ) -> dict[str, object]: ...

    def queue_id_for_prompt(self, prompt_id: str) -> int: ...

    def wait_success(self, prompt_id: str) -> None: ...

    def download(self, prompt_id: str, destination: Path) -> Path: ...

    def unload_models(self) -> None: ...


class ComfySessionFactory(Protocol):
    def create(self, kind: str, process_handle: Any) -> ComfySession: ...


class MemoryAdmissionGate(Protocol):
    def capture_and_require_go(self, phase: str) -> dict[str, object]: ...


class PageCacheReclaimer(Protocol):
    def reclaim(self, exact_weights: tuple[tuple[str, str], ...]) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class _ClickContext:
    authority_sha256: str
    logical_prompt_id: str
    submission_nonce: str
    workflow_sha256: str
    assets_manifest_sha256: str
    prompt_sha256: str
    seed: int
    prepared_reference: dict[str, object] | None


class VerticalSliceRunner:
    def __init__(
        self,
        *,
        runtime_inputs: VerticalSliceRuntimeInputs,
        flux_authority: FluxExecutionAuthority,
        h3_authority_factory: Callable[[tuple[GeneratedReferenceAsset, ...]], H3BuildAuthority],
        processes: ProcessController,
        session_factory: ComfySessionFactory,
        memory_gate: MemoryAdmissionGate,
        page_cache_reclaimer: PageCacheReclaimer,
        media_probe: Callable[[Path], MediaProbeSummary],
    ) -> None:
        self.runtime_inputs = runtime_inputs
        self.flux_authority = flux_authority
        self._h3_authority_factory = h3_authority_factory
        self._processes = processes
        self._session_factory = session_factory
        self._memory_gate = memory_gate
        self._page_cache_reclaimer = page_cache_reclaimer
        self._media_probe = media_probe

    def run(self) -> VerticalSliceResult:
        click = self._load_click_context()
        if click.prepared_reference is not None:
            raise VerticalSliceError(
                "imported-reference jobs require the staged FLUX proof then H3 flow"
            )
        checkpoint = self._load_or_create_checkpoint(click)
        succeeded = self._result_from_succeeded_checkpoint(checkpoint)
        if succeeded is not None:
            return succeeded

        references = self._run_flux(click, checkpoint)
        self._perform_flux_to_h3_cutover(checkpoint)
        checkpoint["status"] = "flux_ready"
        self._save_checkpoint(checkpoint)
        return self._complete_h3(click, checkpoint, references)

    def run_flux_stage(self) -> tuple[GeneratedReferenceAsset, ...]:
        """Finish FLUX, process exit, exact reclaim, and the H3 admission gate."""

        click = self._load_click_context(allow_reference_preparation=True)
        if click.prepared_reference is not None:
            raise VerticalSliceError(
                "imported-reference jobs cannot use the legacy FLUX output path"
            )
        checkpoint = self._load_or_create_checkpoint(click)
        if checkpoint.get("status") == "succeeded":
            return self._verified_reference_assets(
                checkpoint["flux"]["views"], require_all=True
            )
        references = self._verified_reference_assets(
            checkpoint["flux"]["views"]
        )
        if len(references) != len(VIEW_ORDER):
            references = self._run_flux(click, checkpoint)
        self._perform_flux_to_h3_cutover(checkpoint)
        checkpoint["status"] = "flux_ready"
        self._save_checkpoint(checkpoint)
        return references

    def adopt_prepared_flux_stage(
        self,
        references: tuple[GeneratedReferenceAsset, ...],
        *,
        preparation_request_id: str,
        preparation_checkpoint_sha256: str,
    ) -> tuple[GeneratedReferenceAsset, ...]:
        """Bind one already generated reference to the user's clicked H3 run.

        This method never starts ComfyUI.  The prepared asset has already
        crossed the FLUX process-exit, VRAM-idle, targeted page-cache reclaim,
        and H3 memory-admission boundary.  A fresh clicked runner checkpoint is
        still created so the later H3 submission remains bound to the user's
        own click authority rather than to the preparation request.
        """

        if (
            tuple(item.view_name for item in references) != VIEW_ORDER
            or not isinstance(preparation_request_id, str)
            or _UUID_RE.fullmatch(preparation_request_id) is None
            or _SHA256_RE.fullmatch(preparation_checkpoint_sha256) is None
        ):
            raise VerticalSliceError("prepared FLUX cache authority is invalid")
        click = self._load_click_context()
        checkpoint = self._load_or_create_checkpoint(click)
        existing = self._verified_reference_assets(checkpoint["flux"]["views"])
        if existing:
            if existing != references:
                raise VerticalSliceError("clicked runner already binds another FLUX asset")
            return existing
        item = references[0]
        prepared = click.prepared_reference
        if prepared is not None and (
            prepared.get("requestId") != preparation_request_id
            or prepared.get("artifactSha256") != item.sha256
            or prepared.get("promptSha256") != item.prompt_sha256
            or prepared.get("seed") != item.seed
            or prepared.get("workflowSha256") != item.workflow_sha256
            or prepared.get("compiledWorkflowSha256")
            != item.compiled_workflow_sha256
        ):
            raise VerticalSliceError(
                "prepared FLUX asset diverges from the clicked manifest"
            )
        checkpoint["flux"]["views"][item.view_name] = {
            "status": "succeeded",
            "promptId": item.prompt_id,
            "submissionNonce": self._stage_nonce(
                click.submission_nonce, "flux:prepared-cache"
            ),
            "workflowSha256": item.compiled_workflow_sha256,
            "assetsSha256": click.assets_manifest_sha256,
            "outputPath": str(item.path),
            "outputSha256": item.sha256,
            "viewName": item.view_name,
            "promptSha256": item.prompt_sha256,
            "seed": item.seed,
            "generationAttemptOrdinal": item.generation_attempt_ordinal,
            "technicalFailureReceiptSha256": (
                item.technical_failure_receipt_sha256
            ),
        }
        checkpoint["flux"]["processExited"] = True
        checkpoint["flux"]["cutoverComplete"] = True
        checkpoint["flux"]["preparedCache"] = {
            "requestId": preparation_request_id,
            "checkpointSha256": preparation_checkpoint_sha256,
        }
        checkpoint["status"] = "flux_ready"
        self._save_checkpoint(checkpoint)
        return self._verified_reference_assets(
            checkpoint["flux"]["views"], require_all=True
        )

    def run_flux_runtime_proof_stage(
        self, imported_reference: Mapping[str, object]
    ) -> tuple[GeneratedReferenceAsset, ...]:
        """Prove real FLUX GPU execution, discard its output, then bind an import.

        The imported image is never described as a FLUX output.  The FLUX
        submission receipt and GPU telemetry live under ``flux.runtimeProof``;
        the H3 reference lineage lives under ``flux.views`` with explicit
        ``preuploaded_imported`` flags.
        """

        click = self._load_click_context()
        checkpoint = self._load_or_create_checkpoint(click)
        reference = dict(imported_reference)
        expected_fields = {
            "requestId",
            "path",
            "sha256",
            "mimeType",
            "width",
            "height",
            "byteSize",
            "importAuthoritySha256",
        }
        if set(reference) != expected_fields:
            raise VerticalSliceError("imported reference authority fields are invalid")
        prepared = click.prepared_reference
        if (
            prepared is None
            or prepared.get("sourceMode") != "preuploaded_imported"
            or prepared.get("requestId") != reference["requestId"]
            or prepared.get("artifactSha256") != reference["sha256"]
            or prepared.get("importAuthoritySha256")
            != reference["importAuthoritySha256"]
        ):
            raise VerticalSliceError(
                "clicked imported reference diverges from the runtime authority"
            )
        path = _resolve_persistent_file(
            reference["path"], self.runtime_inputs.persistent_root, "imported reference"
        )
        digest = _require_sha256(reference["sha256"], "imported reference SHA")
        if (
            _sha256_file(path) != digest
            or path.stat().st_size != reference["byteSize"]
            or reference["mimeType"] != "image/png"
            or reference["width"] != 880
            or reference["height"] != 1168
        ):
            raise VerticalSliceError("imported reference bytes changed")

        compiled = compile_flux2_workflow(
            role="text_to_image",
            templates=self.flux_authority.templates,
            capability=self.flux_authority.capability,
            prompt=self.flux_authority.prompt,
            width=512,
            height=768,
            seed=self.flux_authority.seed,
            reference_images=(),
            filename_prefix=(
                f"vertical-slice/{click.logical_prompt_id}/flux-runtime-proof/discarded"
            ),
        )
        self._validate_flux_workflow(compiled)
        workflow_path = self._persist_workflow("flux-runtime-proof", compiled)
        nonce = self._stage_nonce(click.submission_nonce, "flux:runtime-proof")

        existing = self._verified_reference_assets(checkpoint["flux"]["views"])
        proof = checkpoint["flux"].get("runtimeProof")
        proof_entry: dict[str, object]
        if proof is None:
            proof_entry = {
                "schemaVersion": "amd.flux-runtime-proof.v1",
                "status": "prepared",
                "promptId": None,
                "queueId": None,
                "submissionNonce": nonce,
                "workflowSha256": compiled.workflow_digest,
                "workflowPath": str(workflow_path),
                "promptSha256": self.flux_authority.prompt_sha256,
                "seed": self.flux_authority.seed,
                "gpuActivity": None,
                "outputUsedByH3": False,
                "processExited": False,
                "vramIdleAfterStop": False,
            }
            checkpoint["flux"]["runtimeProof"] = proof_entry
            self._save_checkpoint(checkpoint)
        elif isinstance(proof, dict):
            proof_entry = proof
            status = proof_entry.get("status")
            prompt_id = proof_entry.get("promptId")
            queue_id = proof_entry.get("queueId")
            activity = proof_entry.get("gpuActivity")
            if (
                set(proof_entry)
                != {
                    "schemaVersion",
                    "status",
                    "promptId",
                    "queueId",
                    "submissionNonce",
                    "workflowSha256",
                    "workflowPath",
                    "promptSha256",
                    "seed",
                    "gpuActivity",
                    "outputUsedByH3",
                    "processExited",
                    "vramIdleAfterStop",
                }
                or proof_entry.get("schemaVersion")
                != "amd.flux-runtime-proof.v1"
                or status
                not in {
                    "prepared",
                    "queued",
                    "gpu_activity_observed",
                    "stopped_after_gpu_activity",
                }
                or proof_entry.get("submissionNonce") != nonce
                or proof_entry.get("workflowSha256") != compiled.workflow_digest
                or proof_entry.get("workflowPath") != str(workflow_path)
                or proof_entry.get("promptSha256")
                != self.flux_authority.prompt_sha256
                or proof_entry.get("seed") != self.flux_authority.seed
                or proof_entry.get("outputUsedByH3") is not False
                or (
                    status == "prepared"
                    and (prompt_id is not None or queue_id is not None or activity is not None)
                )
                or (
                    status != "prepared"
                    and (
                        type(prompt_id) is not str
                        or not prompt_id
                        or isinstance(queue_id, bool)
                        or type(queue_id) is not int
                        or queue_id < 0
                    )
                )
                or (
                    status in {"gpu_activity_observed", "stopped_after_gpu_activity"}
                    and (
                        not isinstance(activity, dict)
                        or activity.get("gpuActivityObserved") is not True
                    )
                )
                or (
                    status == "stopped_after_gpu_activity"
                    and (
                        proof_entry.get("processExited") is not True
                        or proof_entry.get("vramIdleAfterStop") is not True
                    )
                )
            ):
                raise VerticalSliceError("persisted FLUX runtime proof is invalid")
        else:
            raise VerticalSliceError("persisted FLUX runtime proof is invalid")

        if existing:
            if proof_entry.get("status") != "stopped_after_gpu_activity":
                raise VerticalSliceError("imported reference lacks FLUX runtime proof")
            return existing

        if proof_entry.get("status") in {
            "gpu_activity_observed",
            "stopped_after_gpu_activity",
        }:
            self._processes.assert_gpu_idle("recover-after-flux-proof")
            self._processes.assert_vram_idle()
            proof_entry["processExited"] = True
            proof_entry["vramIdleAfterStop"] = True
            proof_entry["status"] = "stopped_after_gpu_activity"
            checkpoint["flux"]["processExited"] = True
            self._save_checkpoint(checkpoint)
            self._perform_flux_to_h3_cutover(checkpoint)
            return self._bind_imported_reference_after_flux_proof(
                click=click,
                checkpoint=checkpoint,
                reference=reference,
                path=path,
                digest=digest,
                proof_entry=proof_entry,
                compiled_workflow_sha256=compiled.workflow_digest,
                nonce=nonce,
            )

        self._processes.assert_gpu_idle("before-flux")
        gate = self._memory_gate.capture_and_require_go("flux")
        checkpoint["admissionEvidence"]["beforeFlux"] = gate
        process = self._processes.start("flux", FLUX_ARGUMENTS)
        session: ComfySession | None = None
        try:
            session = self._session_factory.create("flux", process)
            submit_runtime_proof = getattr(session, "submit_runtime_proof", None)
            if not callable(submit_runtime_proof):
                raise VerticalSliceError("Comfy runtime-proof submission is unavailable")
            client_id = f"{click.logical_prompt_id}.flux.runtime-proof"
            required_metadata = {
                "submission_nonce": nonce,
                "workflow_sha256": compiled.workflow_digest,
                "assets_sha256": click.assets_manifest_sha256,
                "runtime_proof_only": True,
            }
            persisted_prompt_id = proof_entry.get("promptId")
            if persisted_prompt_id is None:
                submission = submit_runtime_proof(
                    compiled.workflow,
                    client_id=client_id,
                    submission_nonce=nonce,
                    extra_data=required_metadata,
                )
            else:
                recovered_prompt_id = session.recover_submission(
                    prompt_id=str(persisted_prompt_id),
                    client_id=client_id,
                    submission_nonce=nonce,
                    required_metadata=required_metadata,
                )
                if recovered_prompt_id != persisted_prompt_id:
                    raise UnknownSubmissionOutcome(
                        "persisted FLUX runtime-proof prompt is absent"
                    )
                recovered_queue_id = session.queue_id_for_prompt(
                    str(persisted_prompt_id)
                )
                if recovered_queue_id != proof_entry.get("queueId"):
                    raise VerticalSliceError(
                        "persisted FLUX runtime-proof queue identity changed"
                    )
                submission = {
                    "promptId": persisted_prompt_id,
                    "queueId": recovered_queue_id,
                }
            if (
                not isinstance(submission, dict)
                or set(submission) != {"promptId", "queueId"}
                or not isinstance(submission.get("promptId"), str)
                or not submission["promptId"]
                or isinstance(submission.get("queueId"), bool)
                or not isinstance(submission.get("queueId"), int)
            ):
                raise VerticalSliceError("FLUX runtime-proof queue receipt is invalid")
            proof_entry["promptId"] = submission["promptId"]
            proof_entry["queueId"] = submission["queueId"]
            proof_entry["status"] = "queued"
            self._save_checkpoint(checkpoint)
            wait_for_gpu = getattr(self._processes, "wait_for_gpu_activity", None)
            if not callable(wait_for_gpu):
                raise VerticalSliceError("GPU runtime-proof telemetry is unavailable")
            activity = wait_for_gpu(
                process,
                kind="flux",
                prompt_id=str(submission["promptId"]),
            )
            if not isinstance(activity, dict) or activity.get("gpuActivityObserved") is not True:
                raise VerticalSliceError("FLUX GPU activity was not observed")
            proof_entry["gpuActivity"] = activity
            proof_entry["status"] = "gpu_activity_observed"
            self._save_checkpoint(checkpoint)
        finally:
            if session is not None:
                try:
                    session.unload_models()
                except Exception:
                    pass
            self._processes.stop(process)
            self._processes.wait_exited(process)
        proof_entry["processExited"] = True
        checkpoint["flux"]["processExited"] = True
        self._save_checkpoint(checkpoint)
        self._processes.assert_vram_idle()
        proof_entry["vramIdleAfterStop"] = True
        proof_entry["status"] = "stopped_after_gpu_activity"
        self._save_checkpoint(checkpoint)
        self._perform_flux_to_h3_cutover(checkpoint)
        return self._bind_imported_reference_after_flux_proof(
            click=click,
            checkpoint=checkpoint,
            reference=reference,
            path=path,
            digest=digest,
            proof_entry=proof_entry,
            compiled_workflow_sha256=compiled.workflow_digest,
            nonce=nonce,
        )

    def _bind_imported_reference_after_flux_proof(
        self,
        *,
        click: _ClickContext,
        checkpoint: dict[str, Any],
        reference: Mapping[str, object],
        path: Path,
        digest: str,
        proof_entry: Mapping[str, object],
        compiled_workflow_sha256: str,
        nonce: str,
    ) -> tuple[GeneratedReferenceAsset, ...]:
        if (
            proof_entry.get("status") != "stopped_after_gpu_activity"
            or proof_entry.get("processExited") is not True
            or proof_entry.get("vramIdleAfterStop") is not True
            or proof_entry.get("outputUsedByH3") is not False
            or type(proof_entry.get("promptId")) is not str
            or not proof_entry["promptId"]
            or isinstance(proof_entry.get("queueId"), bool)
            or type(proof_entry.get("queueId")) is not int
            or proof_entry["queueId"] < 0
        ):
            raise VerticalSliceError(
                "imported reference cannot bind before FLUX proof shutdown"
            )
        checkpoint["flux"]["views"]["front_three_quarter"] = {
            "status": "succeeded",
            "promptId": proof_entry["promptId"],
            "submissionNonce": nonce,
            "workflowSha256": compiled_workflow_sha256,
            "assetsSha256": click.assets_manifest_sha256,
            "outputPath": str(path),
            "outputSha256": digest,
            "viewName": "front_three_quarter",
            "promptSha256": self.flux_authority.prompt_sha256,
            "seed": self.flux_authority.seed,
            "generationAttemptOrdinal": 0,
            "technicalFailureReceiptSha256": None,
            "sourceMode": "preuploaded_imported",
            "generatedByCurrentFlux": False,
            "fluxOutputUsed": False,
            "importAuthoritySha256": reference["importAuthoritySha256"],
        }
        checkpoint["status"] = "flux_ready"
        self._save_checkpoint(checkpoint)
        return self._verified_reference_assets(
            checkpoint["flux"]["views"], require_all=True
        )

    def run_h3_stage(self) -> VerticalSliceResult:
        """Resume from persisted FLUX assets without ever rerunning FLUX."""

        click = self._load_click_context()
        checkpoint = self._load_or_create_checkpoint(click)
        succeeded = self._result_from_succeeded_checkpoint(checkpoint)
        if succeeded is not None:
            return succeeded
        references = self._verified_reference_assets(
            checkpoint["flux"]["views"],
            require_all=True,
        )
        if not checkpoint["flux"].get("cutoverComplete"):
            raise VerticalSliceError(
                "resume-h3 requires a completed FLUX exit and page-cache cutover"
            )
        self._perform_flux_to_h3_cutover(checkpoint)
        return self._complete_h3(click, checkpoint, references)

    def _complete_h3(
        self,
        click: _ClickContext,
        checkpoint: dict[str, Any],
        references: tuple[GeneratedReferenceAsset, ...],
    ) -> VerticalSliceResult:
        result = self._run_h3(click, checkpoint, references)
        checkpoint["status"] = "succeeded"
        checkpoint["result"] = self._result_payload(result)
        self._save_checkpoint(checkpoint)
        return result

    def _load_click_context(
        self, *, allow_reference_preparation: bool = False
    ) -> _ClickContext:
        inputs = self.runtime_inputs
        click_path = _resolve_persistent_file(
            str(inputs.click_authority_path), inputs.persistent_root, "click authority"
        )
        authority = _load_json(click_path, "click authority")
        expected_fields = {
            "schemaVersion",
            "userClick",
            "action",
            "promptId",
            "submissionNonce",
            "workflowPath",
            "workflowSha256",
            "assetsManifestPath",
            "assetsManifestSha256",
            "statePath",
            "stateSha256",
        }
        if set(authority) != expected_fields:
            raise VerticalSliceError("click authority fields are not frozen")
        clicked = (
            authority["schemaVersion"] == "amd.user-gpu-click.v1"
            and authority["userClick"] is True
            and authority["action"] == "start_generation"
        )
        prepared = (
            allow_reference_preparation
            and authority["schemaVersion"]
            == "amd.reference-preparation-request.v1"
            and authority["userClick"] is False
            and authority["action"] == "prepare_reference"
        )
        if not (clicked or prepared):
            raise VerticalSliceError("generation requires an explicit persisted user click")
        prompt_id = authority["promptId"]
        nonce = authority["submissionNonce"]
        if not isinstance(prompt_id, str) or _UUID_RE.fullmatch(prompt_id) is None:
            raise VerticalSliceError("click logical prompt id is invalid")
        if not isinstance(nonce, str) or _NONCE_RE.fullmatch(nonce) is None:
            raise VerticalSliceError("click submission nonce is invalid")

        workflow_path = _resolve_persistent_file(
            authority["workflowPath"], inputs.persistent_root, "click workflow"
        )
        assets_path = _resolve_persistent_file(
            authority["assetsManifestPath"], inputs.persistent_root, "asset manifest"
        )
        prepared_state_path = _resolve_persistent_file(
            authority["statePath"], inputs.persistent_root, "prepared state"
        )
        workflow_sha = _require_sha256(authority["workflowSha256"], "workflowSha256")
        assets_sha = _require_sha256(
            authority["assetsManifestSha256"], "assetsManifestSha256"
        )
        state_sha = _require_sha256(authority["stateSha256"], "stateSha256")
        if _sha256_file(workflow_path) != workflow_sha:
            raise VerticalSliceError("click workflow SHA does not match authority")
        if _sha256_file(assets_path) != assets_sha:
            raise VerticalSliceError("asset manifest SHA does not match authority")
        if _sha256_file(prepared_state_path) != state_sha:
            raise VerticalSliceError("prepared state SHA does not match authority")

        workflow = _load_json(workflow_path, "vertical-slice workflow authority")
        prepared = _load_json(prepared_state_path, "prepared submission state")
        for source in (workflow, prepared):
            self._require_video_contract(source)
        expected_prepared = {
            "promptId": prompt_id,
            "submissionNonce": nonce,
            "workflowSha256": workflow_sha,
            "assetsManifestSha256": assets_sha,
        }
        if any(prepared.get(key) != value for key, value in expected_prepared.items()):
            raise VerticalSliceError("prepared state does not match click authority")
        if prepared.get("status") not in {"prepared", "queued", "running", "succeeded"}:
            raise VerticalSliceError("prepared state status is not recoverable")

        generation = workflow.get("fluxReferenceGeneration")
        if not isinstance(generation, dict):
            raise VerticalSliceError("FLUX prompt authority is unavailable")
        generation_identity = dict(generation)
        generation_digest = generation_identity.pop("authoritySha256", None)
        expected_generation = {
            "schemaVersion": "amd.flux-prompt-single-reference-generation.v1",
            "referenceProfile": self.flux_authority.reference_profile,
            "sourceMode": self.flux_authority.source_mode,
            "requiredImages": self.flux_authority.required_images,
            "view": self.flux_authority.view,
            "prompt": self.flux_authority.prompt,
            "promptSha256": self.flux_authority.prompt_sha256,
            "seed": self.flux_authority.seed,
            "workflowSha256": self.flux_authority.workflow_sha256,
            "generationInvocationCount": 1,
            "technicalRetryLimit": 1,
        }
        if (
            generation_identity != expected_generation
            or generation_digest != canonical_sha256(expected_generation)
        ):
            raise VerticalSliceError("FLUX prompt authority diverges from runtime")
        assets = _load_json(assets_path, "vertical-slice asset manifest")
        expected_assets: dict[str, object] = {
            "schemaVersion": "amd.prompt-single-reference-assets.v1",
            "referenceProfile": self.flux_authority.reference_profile,
            "sourceMode": self.flux_authority.source_mode,
            "requiredImages": 1,
            "view": self.flux_authority.view,
            "promptSha256": self.flux_authority.prompt_sha256,
            "seed": self.flux_authority.seed,
            "workflowSha256": self.flux_authority.workflow_sha256,
        }
        prepared_reference = assets.get("preparedReference")
        if prepared_reference is not None:
            if (
                not isinstance(prepared_reference, dict)
                or set(prepared_reference) != {
                    "requestId",
                    "artifactSha256",
                    "sourceMode",
                    "importAuthoritySha256",
                }
                or _UUID_RE.fullmatch(str(prepared_reference.get("requestId")))
                is None
                or prepared_reference.get("sourceMode")
                != "preuploaded_imported"
                or any(
                    _SHA256_RE.fullmatch(str(prepared_reference.get(field)))
                    is None
                    for field in (
                        "artifactSha256",
                        "importAuthoritySha256",
                    )
                )
            ):
                raise VerticalSliceError(
                    "clicked prepared reference authority is invalid"
                )
            expected_assets["preparedReference"] = prepared_reference
        if assets != expected_assets:
            raise VerticalSliceError("prompt single-reference asset authority is invalid")
        return _ClickContext(
            authority_sha256=_sha256_file(click_path),
            logical_prompt_id=prompt_id,
            submission_nonce=nonce,
            workflow_sha256=workflow_sha,
            assets_manifest_sha256=assets_sha,
            prompt_sha256=self.flux_authority.prompt_sha256,
            seed=self.flux_authority.seed,
            prepared_reference=prepared_reference,
        )

    @staticmethod
    def _require_video_contract(value: Mapping[str, object]) -> None:
        if value.get("requestedDurationSeconds") != REQUESTED_DURATION_SECONDS:
            raise VerticalSliceError("requested duration must be exactly 3.0 seconds")
        if value.get("frameCount") != H3_FRAME_COUNT or value.get("fps") != H3_FPS:
            raise VerticalSliceError("H3 execution must use exactly 73 frames at 24 fps")
        if value.get("nativeAudio") is not True:
            raise VerticalSliceError("H3 native audio is required")
        if value.get("subtitles") is not False:
            raise VerticalSliceError("subtitles must be disabled")

    def _load_or_create_checkpoint(self, click: _ClickContext) -> dict[str, Any]:
        path = self.runtime_inputs.checkpoint_path
        if path.exists():
            checkpoint = _load_json(path, "vertical-slice checkpoint")
            if (
                checkpoint.get("schemaVersion") != "amd.three-second-runner.v1"
                or checkpoint.get("clickAuthoritySha256") != click.authority_sha256
                or checkpoint.get("promptSha256") != click.prompt_sha256
                or checkpoint.get("seed") != click.seed
                or checkpoint.get("requestedDurationSeconds") != REQUESTED_DURATION_SECONDS
                or checkpoint.get("frameCount") != H3_FRAME_COUNT
                or checkpoint.get("fps") != H3_FPS
                or checkpoint.get("nativeAudio") is not True
                or checkpoint.get("subtitles") is not False
            ):
                raise VerticalSliceError("persisted checkpoint diverges from click authority")
            if not isinstance(checkpoint.get("flux"), dict) or not isinstance(
                checkpoint.get("h3"), dict
            ):
                raise VerticalSliceError("persisted checkpoint stages are invalid")
            return checkpoint
        checkpoint: dict[str, Any] = {
            "schemaVersion": "amd.three-second-runner.v1",
            "status": "prepared",
            "clickAuthoritySha256": click.authority_sha256,
            "logicalPromptId": click.logical_prompt_id,
            "clickSubmissionNonce": click.submission_nonce,
            "logicalWorkflowSha256": click.workflow_sha256,
            "assetsManifestSha256": click.assets_manifest_sha256,
            "referenceProfile": (
                "competition-imported-single-view-v1"
                if click.prepared_reference is not None
                else "competition-prompt-single-view-v1"
            ),
            "sourceMode": (
                "preuploaded_imported"
                if click.prepared_reference is not None
                else "prompt_synthesized"
            ),
            "requiredImages": 1,
            "view": "front_three_quarter",
            "promptSha256": click.prompt_sha256,
            "seed": click.seed,
            "requestedDurationSeconds": REQUESTED_DURATION_SECONDS,
            "frameCount": H3_FRAME_COUNT,
            "fps": H3_FPS,
            "nativeAudio": True,
            "subtitles": False,
            "admissionEvidence": {},
            "flux": {
                "views": {},
                "technicalFailures": {},
                "cutoverComplete": False,
            },
            "h3": {},
            "result": None,
        }
        self._save_checkpoint(checkpoint)
        return checkpoint

    def _save_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        _atomic_json(self.runtime_inputs.checkpoint_path, checkpoint)

    def _result_from_succeeded_checkpoint(
        self, checkpoint: dict[str, Any]
    ) -> VerticalSliceResult | None:
        if checkpoint.get("status") != "succeeded":
            return None
        payload = checkpoint.get("result")
        if not isinstance(payload, dict):
            raise VerticalSliceError("succeeded checkpoint has no result authority")
        expected_fields = {
            "requestedDurationSeconds",
            "frameCount",
            "fps",
            "nativeAudio",
            "subtitles",
            "promptId",
            "submissionNonce",
            "workflowSha256",
            "outputPath",
            "outputSha256",
            "ffprobe",
            "mediaWarnings",
        }
        h3 = checkpoint.get("h3")
        if (
            set(payload) != expected_fields
            or payload.get("requestedDurationSeconds") != REQUESTED_DURATION_SECONDS
            or payload.get("frameCount") != H3_FRAME_COUNT
            or payload.get("fps") != H3_FPS
            or payload.get("nativeAudio") is not True
            or payload.get("subtitles") is not False
            or not isinstance(h3, dict)
            or h3.get("status") != "succeeded"
            or payload.get("promptId") != h3.get("promptId")
            or payload.get("submissionNonce") != h3.get("submissionNonce")
            or payload.get("workflowSha256") != h3.get("workflowSha256")
            or payload.get("outputPath") != h3.get("outputPath")
            or payload.get("outputSha256") != h3.get("outputSha256")
        ):
            raise VerticalSliceError(
                "succeeded result diverges from the persisted H3 authority"
            )
        _require_sha256(payload.get("workflowSha256"), "workflowSha256")
        if payload.get("submissionNonce") != checkpoint.get("clickSubmissionNonce"):
            raise VerticalSliceError(
                "succeeded result nonce diverges from the user click"
            )
        path = Path(str(payload.get("outputPath", "")))
        try:
            path.resolve(strict=True).relative_to(self.runtime_inputs.persistent_root)
        except (OSError, ValueError) as exc:
            raise VerticalSliceError("succeeded output path is unavailable") from exc
        digest = _require_sha256(payload.get("outputSha256"), "outputSha256")
        if _sha256_file(path) != digest:
            raise VerticalSliceError("succeeded output SHA mismatch")
        probe_value = payload.get("ffprobe")
        if not isinstance(probe_value, dict):
            raise VerticalSliceError("succeeded ffprobe evidence is invalid")
        probe = MediaProbeSummary(**probe_value)
        media_warnings = self._validate_probe(probe)
        if payload.get("mediaWarnings") != list(media_warnings):
            raise VerticalSliceError("succeeded media warnings diverge from ffprobe")
        return VerticalSliceResult(
            requested_duration_seconds=REQUESTED_DURATION_SECONDS,
            frame_count=H3_FRAME_COUNT,
            fps=H3_FPS,
            native_audio=True,
            subtitles=False,
            prompt_id=str(payload["promptId"]),
            submission_nonce=str(payload["submissionNonce"]),
            workflow_sha256=str(payload["workflowSha256"]),
            output_path=path,
            output_sha256=digest,
            ffprobe=probe,
            media_warnings=media_warnings,
        )

    def _run_flux(
        self,
        click: _ClickContext,
        checkpoint: dict[str, Any],
    ) -> tuple[GeneratedReferenceAsset, ...]:
        flux_stage = checkpoint["flux"]
        views = flux_stage["views"]
        failures = flux_stage.setdefault("technicalFailures", {})
        if not isinstance(failures, dict):
            raise VerticalSliceError("FLUX technical failure authority is invalid")
        existing = self._verified_reference_assets(views)
        if len(existing) == len(VIEW_ORDER):
            return existing
        self._processes.assert_gpu_idle("before-flux")
        gate = self._memory_gate.capture_and_require_go("flux")
        checkpoint["admissionEvidence"]["beforeFlux"] = gate
        self._save_checkpoint(checkpoint)
        process = self._processes.start("flux", FLUX_ARGUMENTS)
        session: ComfySession | None = None
        try:
            session = self._session_factory.create("flux", process)
            for view in VIEW_ORDER:
                current = views.get(view)
                if isinstance(current, dict) and current.get("status") == "succeeded":
                    continue
                history = failures.setdefault(view, [])
                if not isinstance(history, list) or len(history) > 1:
                    raise VerticalSliceError("FLUX technical retry budget is exhausted")
                for attempt_ordinal in range(len(history), 2):
                    compiled = compile_flux2_workflow(
                        role="text_to_image",
                        templates=self.flux_authority.templates,
                        capability=self.flux_authority.capability,
                        prompt=self.flux_authority.prompt,
                        width=512,
                        height=768,
                        seed=self.flux_authority.seed,
                        reference_images=(),
                        filename_prefix=(
                            f"vertical-slice/{click.logical_prompt_id}/{view}/"
                            f"attempt-{attempt_ordinal}"
                        ),
                    )
                    self._validate_flux_workflow(compiled)
                    workflow_path = self._persist_workflow(
                        f"flux-{view}-attempt-{attempt_ordinal}", compiled
                    )
                    output_path = (
                        self.runtime_inputs.evidence_root
                        / "references"
                        / f"{view}.png"
                    )
                    submission_nonce = self._stage_nonce(
                        click.submission_nonce,
                        f"flux:{view}:attempt:{attempt_ordinal}",
                    )
                    try:
                        entry = self._run_submission(
                            checkpoint=checkpoint,
                            stage=views,
                            stage_key=view,
                            session=session,
                            workflow=compiled.workflow,
                            workflow_sha256=compiled.workflow_digest,
                            workflow_path=workflow_path,
                            client_id=(
                                f"{click.logical_prompt_id}.flux.{view}."
                                f"attempt-{attempt_ordinal}"
                            ),
                            submission_nonce=submission_nonce,
                            assets_sha256=click.assets_manifest_sha256,
                            output_path=output_path,
                        )
                    except Exception as exc:
                        if getattr(exc, "known_terminal", False) is not True:
                            raise
                        receipt_sha = self._record_flux_terminal_failure(
                            checkpoint=checkpoint,
                            view=view,
                            attempt_ordinal=attempt_ordinal,
                            submission_nonce=submission_nonce,
                            workflow_sha256=compiled.workflow_digest,
                        )
                        history.append(
                            {
                                "attemptOrdinal": attempt_ordinal,
                                "receiptSha256": receipt_sha,
                            }
                        )
                        if attempt_ordinal >= self.flux_authority.technical_retry_limit:
                            flux_stage["status"] = "failed"
                            self._save_checkpoint(checkpoint)
                            raise VerticalSliceError(
                                "FLUX technical retry also failed; no reference was accepted"
                            ) from exc
                        views[view] = {}
                        self._save_checkpoint(checkpoint)
                        continue
                    entry["viewName"] = view
                    entry["promptSha256"] = self.flux_authority.prompt_sha256
                    entry["seed"] = self.flux_authority.seed
                    entry["generationAttemptOrdinal"] = attempt_ordinal
                    entry["technicalFailureReceiptSha256"] = (
                        None if attempt_ordinal == 0 else history[0]["receiptSha256"]
                    )
                    self._save_checkpoint(checkpoint)
                    break
        finally:
            if session is not None:
                try:
                    session.unload_models()
                except Exception:
                    pass
            self._processes.stop(process)
            self._processes.wait_exited(process)
        checkpoint["flux"]["processExited"] = True
        self._save_checkpoint(checkpoint)
        return self._verified_reference_assets(views, require_all=True)

    def _record_flux_terminal_failure(
        self,
        *,
        checkpoint: dict[str, Any],
        view: str,
        attempt_ordinal: int,
        submission_nonce: str,
        workflow_sha256: str,
    ) -> str:
        entry = checkpoint["flux"]["views"].get(view)
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in {"queued", "prepared"}
            or not isinstance(entry.get("promptId"), str)
            or not entry["promptId"]
            or entry.get("submissionNonce") != submission_nonce
            or entry.get("workflowSha256") != workflow_sha256
        ):
            raise VerticalSliceError(
                "terminal FLUX failure lacks a persisted submission authority"
            )
        identity = {
            "schemaVersion": "amd.flux-technical-failure-receipt.v1",
            "viewName": view,
            "attemptOrdinal": attempt_ordinal,
            "promptId": entry["promptId"],
            "submissionNonce": submission_nonce,
            "workflowSha256": workflow_sha256,
            "assetsSha256": entry.get("assetsSha256"),
            "failureCode": "COMFY_TERMINAL_WORKFLOW_FAILURE",
            "terminal": True,
        }
        receipt_sha = canonical_sha256(identity)
        path = (
            self.runtime_inputs.evidence_root
            / "failures"
            / f"flux-{view}-attempt-{attempt_ordinal}.json"
        )
        _atomic_json(path, {**identity, "receiptSha256": receipt_sha})
        return receipt_sha

    @staticmethod
    def _validate_flux_workflow(compiled: Any) -> None:
        if getattr(compiled, "role", "text_to_image") != "text_to_image":
            raise VerticalSliceError("competition FLUX reference must use T2I")
        graph = compiled.workflow
        batch_sizes = [
            inputs["batch_size"]
            for node in graph.values()
            if isinstance(node, dict)
            and isinstance((inputs := node.get("inputs")), dict)
            and "batch_size" in inputs
        ]
        if batch_sizes != [1]:
            raise VerticalSliceError("FLUX single-reference generation requires batch_size=1")
        if any(
            isinstance(node, dict) and node.get("class_type") == "SaveVideo"
            for node in graph.values()
        ):
            raise VerticalSliceError("FLUX reference workflow cannot emit video")

    def _verified_reference_assets(
        self,
        views: Mapping[str, object],
        *,
        require_all: bool = False,
    ) -> tuple[GeneratedReferenceAsset, ...]:
        result: list[GeneratedReferenceAsset] = []
        for view in VIEW_ORDER:
            entry = views.get(view)
            if not isinstance(entry, dict) or entry.get("status") != "succeeded":
                if require_all:
                    raise VerticalSliceError("FLUX reference set is incomplete")
                continue
            path = Path(str(entry.get("outputPath", "")))
            digest = _require_sha256(entry.get("outputSha256"), f"{view} output SHA")
            try:
                path.resolve(strict=True).relative_to(self.runtime_inputs.persistent_root)
            except (OSError, ValueError) as exc:
                raise VerticalSliceError(f"{view} reference output is unavailable") from exc
            if _sha256_file(path) != digest:
                raise VerticalSliceError(f"{view} reference output SHA mismatch")
            ordinal = entry.get("generationAttemptOrdinal")
            failure_receipt = entry.get("technicalFailureReceiptSha256")
            imported = entry.get("sourceMode") == "preuploaded_imported"
            if (
                entry.get("promptSha256") != self.flux_authority.prompt_sha256
                or entry.get("seed") != self.flux_authority.seed
                or ordinal not in {0, 1}
                or (ordinal == 0 and failure_receipt is not None)
                or (
                    ordinal == 1
                    and _SHA256_RE.fullmatch(str(failure_receipt)) is None
                )
                or _SHA256_RE.fullmatch(str(entry.get("workflowSha256", ""))) is None
                or (
                    imported
                    and (
                        entry.get("generatedByCurrentFlux") is not False
                        or entry.get("fluxOutputUsed") is not False
                        or _SHA256_RE.fullmatch(
                            str(entry.get("importAuthoritySha256", ""))
                        )
                        is None
                    )
                )
            ):
                raise VerticalSliceError(
                    f"{view} generation authority is invalid"
                )
            result.append(
                GeneratedReferenceAsset(
                    view_name=view,
                    path=path,
                    sha256=digest,
                    prompt_id=str(entry["promptId"]),
                    prompt_sha256=_require_sha256(
                        entry.get("promptSha256"), f"{view} prompt SHA"
                    ),
                    seed=self.flux_authority.seed,
                    workflow_sha256=self.flux_authority.workflow_sha256,
                    compiled_workflow_sha256=_require_sha256(
                        entry.get("workflowSha256"),
                        f"{view} compiled workflow SHA",
                    ),
                    generation_attempt_ordinal=ordinal,
                    technical_failure_receipt_sha256=failure_receipt,
                    source_mode=str(
                        entry.get("sourceMode", "generated_by_current_flux")
                    ),
                    generated_by_current_flux=entry.get(
                        "generatedByCurrentFlux", True
                    ) is True,
                    flux_output_used=entry.get("fluxOutputUsed", True) is True,
                    import_authority_sha256=(
                        _require_sha256(
                            entry.get("importAuthoritySha256"),
                            f"{view} import authority SHA",
                        )
                        if entry.get("sourceMode") == "preuploaded_imported"
                        else None
                    ),
                )
            )
        return tuple(result)

    def _perform_flux_to_h3_cutover(self, checkpoint: dict[str, Any]) -> None:
        flux = checkpoint["flux"]
        self._processes.assert_gpu_idle("after-flux")
        self._processes.assert_vram_idle()
        if not flux.get("cutoverComplete"):
            reclaim = self._page_cache_reclaimer.reclaim(
                self.flux_authority.exact_weight_authority()
            )
            flux["pageCacheReclaim"] = reclaim
            flux["cutoverComplete"] = True
            self._save_checkpoint(checkpoint)
        gate = self._memory_gate.capture_and_require_go("h3")
        checkpoint["admissionEvidence"]["beforeH3"] = gate
        self._save_checkpoint(checkpoint)

    def _run_h3(
        self,
        click: _ClickContext,
        checkpoint: dict[str, Any],
        references: tuple[GeneratedReferenceAsset, ...],
    ) -> VerticalSliceResult:
        if tuple(item.view_name for item in references) != VIEW_ORDER:
            raise VerticalSliceError("H3 requires the canonical three-view reference set")
        authority = self._h3_authority_factory(references)
        self._validate_h3_authority(authority, references)
        if authority.reference_profile in {
            "competition-imported-single-view-v1",
            "competition-prompt-single-view-v1",
        }:
            concrete = authority.concrete
            if concrete is None:
                raise VerticalSliceError(
                    "competition single-reference authority lacks a concrete workflow"
                )
        else:
            concrete = build_h3_comfy_api_workflow(
                authority.compiled,
                plan=authority.plan,
                rendered=authority.rendered,
                binding=authority.binding,
                capability=authority.capability,
                template_path=authority.template_path,
                staged_references=authority.staged_references,
                seed=authority.seed,
            )
        self._validate_h3_workflow(concrete)
        workflow_path = self._persist_workflow("h3-73-frames", concrete)
        assets_sha = canonical_sha256(
            [
                {"viewName": item.view_name, "sha256": item.sha256}
                for item in references
            ]
        )
        self._processes.assert_gpu_idle("before-h3-process")
        process = self._processes.start("h3", ())
        session: ComfySession | None = None
        try:
            session = self._session_factory.create("h3", process)
            for asset, staged in zip(references, authority.staged_references):
                session.stage_input(asset.path, staged.remote_name, asset.sha256)
            entry = self._run_submission(
                checkpoint=checkpoint,
                stage=checkpoint,
                stage_key="h3",
                session=session,
                workflow=concrete.workflow,
                workflow_sha256=concrete.workflow_digest,
                workflow_path=workflow_path,
                client_id=click.logical_prompt_id,
                submission_nonce=click.submission_nonce,
                assets_sha256=assets_sha,
                output_path=self.runtime_inputs.output_path,
            )
        finally:
            if session is not None:
                try:
                    session.unload_models()
                except Exception:
                    pass
            self._processes.stop(process)
            self._processes.wait_exited(process)
        probe = self._media_probe(self.runtime_inputs.output_path)
        media_warnings = self._validate_probe(probe)
        result = VerticalSliceResult(
            requested_duration_seconds=REQUESTED_DURATION_SECONDS,
            frame_count=H3_FRAME_COUNT,
            fps=H3_FPS,
            native_audio=True,
            subtitles=False,
            prompt_id=str(entry["promptId"]),
            submission_nonce=str(entry["submissionNonce"]),
            workflow_sha256=str(entry["workflowSha256"]),
            output_path=self.runtime_inputs.output_path,
            output_sha256=str(entry["outputSha256"]),
            ffprobe=probe,
            media_warnings=media_warnings,
        )
        return result

    @staticmethod
    def _validate_h3_authority(
        authority: H3BuildAuthority,
        references: tuple[GeneratedReferenceAsset, ...],
    ) -> None:
        plan = authority.plan
        if authority.reference_profile in {
            "competition-imported-single-view-v1",
            "competition-prompt-single-view-v1",
        }:
            imported = authority.reference_profile == "competition-imported-single-view-v1"
            if (
                not isinstance(plan, Mapping)
                or plan.get("schemaVersion")
                != "amd.competition-single-reference-h3-plan.v1"
                or plan.get("referenceProfile")
                != authority.reference_profile
                or plan.get("sourceMode")
                != ("preuploaded_imported" if imported else "prompt_synthesized")
                or plan.get("requiredImages") != 1
                or plan.get("view") != "front_three_quarter"
                or plan.get("requestedDurationSeconds") != REQUESTED_DURATION_SECONDS
                or plan.get("frameCount") != H3_FRAME_COUNT
                or plan.get("fps") != H3_FPS
                or len(references) != 1
                or references[0].view_name != "front_three_quarter"
                or (
                    imported
                    and (
                        references[0].source_mode != "preuploaded_imported"
                        or references[0].generated_by_current_flux is not False
                        or references[0].flux_output_used is not False
                    )
                )
                or len(authority.staged_references) != 1
                or authority.staged_references[0].sha256 != references[0].sha256
                or authority.concrete is None
            ):
                raise VerticalSliceError(
                    "competition H3 authority must bind one approved image"
                )
            return
        if getattr(plan, "requested_duration_seconds", None) != REQUESTED_DURATION_SECONDS:
            raise VerticalSliceError("H3 plan requested duration must be exactly 3.0 seconds")
        if getattr(plan, "frame_count", None) != H3_FRAME_COUNT:
            raise VerticalSliceError("H3 plan must contain exactly 73 frames")
        if getattr(plan, "fps", None) != H3_FPS:
            raise VerticalSliceError("H3 plan must run at exactly 24 fps")
        if len(authority.staged_references) != len(VIEW_ORDER):
            raise VerticalSliceError("H3 plan requires exactly three staged references")
        staged_digests = tuple(item.sha256 for item in authority.staged_references)
        if staged_digests != tuple(item.sha256 for item in references):
            raise VerticalSliceError("H3 staged references diverge from FLUX outputs")

    @staticmethod
    def _validate_h3_workflow(concrete: Any) -> None:
        graph = concrete.workflow
        serialized = json.dumps(graph, ensure_ascii=False, allow_nan=False).casefold()
        nodes = [node for node in graph.values() if isinstance(node, dict)]
        h3_nodes = [
            node for node in nodes if node.get("class_type") == "MiniMaxH3ReferenceToVideo"
        ]
        audio_nodes = [node for node in nodes if node.get("class_type") == "VAEDecodeAudio"]
        create_nodes = [node for node in nodes if node.get("class_type") == "CreateVideo"]
        save_nodes = [node for node in nodes if node.get("class_type") == "SaveVideo"]
        if (
            len(h3_nodes) != 1
            or len(audio_nodes) != 1
            or len(create_nodes) != 1
            or len(save_nodes) != 1
        ):
            raise VerticalSliceError("compiled H3 workflow lacks native audio/video nodes")
        h3_inputs = h3_nodes[0].get("inputs")
        create_inputs = create_nodes[0].get("inputs")
        save_inputs = save_nodes[0].get("inputs")
        if not isinstance(h3_inputs, dict) or h3_inputs.get("length") != H3_FRAME_COUNT:
            raise VerticalSliceError("MiniMax H3 workflow must contain exactly 73 frames")
        if (
            not isinstance(save_inputs, dict)
            or str(save_inputs.get("format", "")).casefold() != "mp4"
            or not isinstance(create_inputs, dict)
            or create_inputs.get("fps") not in {H3_FPS, float(H3_FPS)}
        ):
            raise VerticalSliceError("CreateVideo/SaveVideo must encode MP4 at 24 fps")
        if any(token in serialized for token in ("subtitle", ".srt", ".vtt")):
            raise VerticalSliceError("compiled H3 workflow must not contain subtitles")

    def _run_submission(
        self,
        *,
        checkpoint: dict[str, Any],
        stage: dict[str, Any],
        stage_key: str,
        session: ComfySession,
        workflow: dict[str, Any],
        workflow_sha256: str,
        workflow_path: Path,
        client_id: str,
        submission_nonce: str,
        assets_sha256: str,
        output_path: Path,
    ) -> dict[str, Any]:
        _require_sha256(workflow_sha256, "compiled workflow SHA")
        _require_sha256(assets_sha256, "submission assets SHA")
        current = stage.get(stage_key)
        if current is None or current == {}:
            current = {
                "status": "prepared",
                "submissionNonce": submission_nonce,
                "workflowSha256": workflow_sha256,
                "workflowPath": str(workflow_path),
                "assetsSha256": assets_sha256,
                "promptId": None,
                "queueId": None,
                "outputPath": str(output_path),
                "outputSha256": None,
            }
            stage[stage_key] = current
            self._save_checkpoint(checkpoint)
        if not isinstance(current, dict) or any(
            current.get(key) != value
            for key, value in {
                "submissionNonce": submission_nonce,
                "workflowSha256": workflow_sha256,
                "workflowPath": str(workflow_path),
                "assetsSha256": assets_sha256,
                "outputPath": str(output_path),
            }.items()
        ):
            raise VerticalSliceError(f"persisted {stage_key} submission diverges")
        required_metadata = {
            "submission_nonce": submission_nonce,
            "workflow_sha256": workflow_sha256,
            "assets_sha256": assets_sha256,
        }
        persisted_prompt = current.get("promptId")
        if persisted_prompt is not None and not isinstance(persisted_prompt, str):
            raise VerticalSliceError(f"persisted {stage_key} prompt id is invalid")
        recovered = session.recover_submission(
            prompt_id=persisted_prompt,
            client_id=client_id,
            submission_nonce=submission_nonce,
            required_metadata=required_metadata,
        )
        if persisted_prompt is not None and recovered != persisted_prompt:
            raise UnknownSubmissionOutcome(
                f"persisted {stage_key} prompt is absent from Comfy history and queue"
            )
        prompt_id = recovered
        if prompt_id is None:
            try:
                prompt_id = session.submit(
                    workflow,
                    client_id=client_id,
                    submission_nonce=submission_nonce,
                    extra_data=required_metadata,
                )
            except UnknownSubmissionOutcome:
                prompt_id = session.recover_submission(
                    prompt_id=None,
                    client_id=client_id,
                    submission_nonce=submission_nonce,
                    required_metadata=required_metadata,
                )
                if prompt_id is None:
                    raise
            if not isinstance(prompt_id, str) or not prompt_id:
                raise UnknownSubmissionOutcome("Comfy returned no durable prompt id")
            current["promptId"] = prompt_id
            queue_id = session.queue_id_for_prompt(prompt_id)
            if (
                isinstance(queue_id, bool)
                or not isinstance(queue_id, int)
                or queue_id < 0
            ):
                raise VerticalSliceError(
                    f"persisted {stage_key} queue id is invalid"
                )
            current["queueId"] = queue_id
            current["status"] = "queued"
            self._save_checkpoint(checkpoint)
        elif current.get("queueId") is None:
            queue_id = session.queue_id_for_prompt(prompt_id)
            if (
                isinstance(queue_id, bool)
                or not isinstance(queue_id, int)
                or queue_id < 0
            ):
                raise VerticalSliceError(
                    f"persisted {stage_key} queue id is invalid"
                )
            current["queueId"] = queue_id
            self._save_checkpoint(checkpoint)
        if current.get("status") != "succeeded":
            session.wait_success(prompt_id)
            partial = output_path.with_name(output_path.name + ".partial")
            partial.parent.mkdir(parents=True, exist_ok=True)
            returned = session.download(prompt_id, partial)
            if returned != partial or not partial.is_file() or partial.stat().st_size <= 0:
                raise VerticalSliceError(f"Comfy {stage_key} output is unavailable")
            output_sha = _sha256_file(partial)
            with partial.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            output_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(partial, output_path)
            current["outputSha256"] = output_sha
            current["status"] = "succeeded"
            self._save_checkpoint(checkpoint)
        else:
            output_sha = _require_sha256(current.get("outputSha256"), "output SHA")
            if not output_path.is_file() or _sha256_file(output_path) != output_sha:
                raise VerticalSliceError(f"persisted {stage_key} output SHA mismatch")
        return current

    def _persist_workflow(self, name: str, compiled: Any) -> Path:
        graph = compiled.workflow
        digest = canonical_sha256(graph)
        if digest != compiled.workflow_digest:
            raise VerticalSliceError(f"{name} workflow digest is inconsistent")
        path = self.runtime_inputs.evidence_root / "workflows" / f"{name}.json"
        payload = json.dumps(
            graph,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if path.exists() and _sha256_file(path) != digest:
            raise VerticalSliceError(f"persisted {name} workflow was altered")
        if not path.exists():
            _atomic_bytes(path, payload)
        return path

    @staticmethod
    def _stage_nonce(click_nonce: str, stage: str) -> str:
        return hashlib.sha256(f"{click_nonce}:{stage}".encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _validate_probe(value: MediaProbeSummary) -> tuple[str, ...]:
        if not isinstance(value, MediaProbeSummary):
            raise VerticalSliceError("ffprobe must return MediaProbeSummary")
        if value.video_streams != 1 or value.audio_streams < 1:
            raise VerticalSliceError("H3 MP4 must contain video and native audio")
        if value.subtitle_streams != 0:
            raise VerticalSliceError("H3 MP4 must not contain subtitle streams")
        if "mp4" not in value.format_name.casefold():
            raise VerticalSliceError("H3 output must be an MP4 container")
        if not (
            COMPETITION_MEDIA_DURATION_MIN_SECONDS
            <= value.duration_seconds
            <= COMPETITION_MEDIA_DURATION_MAX_SECONDS
        ):
            raise VerticalSliceError("H3 MP4 is outside the 2.8-3.5 second competition duration")
        if not (
            COMPETITION_MEDIA_FRAME_COUNT_MIN
            <= value.frame_count
            <= COMPETITION_MEDIA_FRAME_COUNT_MAX
        ):
            raise VerticalSliceError("H3 MP4 frame count seriously diverges from the 73-frame request")
        if not COMPETITION_MEDIA_FPS_MIN <= value.fps <= COMPETITION_MEDIA_FPS_MAX:
            raise VerticalSliceError("H3 MP4 frame rate seriously diverges from 24 fps")
        if not math.isclose(
            value.frame_count / value.fps,
            value.duration_seconds,
            rel_tol=0.0,
            abs_tol=0.35,
        ):
            raise VerticalSliceError("H3 MP4 frame metadata seriously diverges from duration")

        warnings: list[str] = []
        if value.frame_count != H3_FRAME_COUNT:
            warnings.append(FRAME_COUNT_WARNING)
        if not math.isclose(value.fps, H3_FPS, rel_tol=0.0, abs_tol=0.01):
            warnings.append(FPS_WARNING)
        if not math.isclose(
            value.duration_seconds,
            H3_DURATION_SECONDS,
            rel_tol=0.0,
            abs_tol=0.25,
        ):
            warnings.append(DURATION_WARNING)
        return tuple(warnings)

    @staticmethod
    def _result_payload(result: VerticalSliceResult) -> dict[str, object]:
        return {
            "requestedDurationSeconds": result.requested_duration_seconds,
            "frameCount": result.frame_count,
            "fps": result.fps,
            "nativeAudio": result.native_audio,
            "subtitles": result.subtitles,
            "promptId": result.prompt_id,
            "submissionNonce": result.submission_nonce,
            "workflowSha256": result.workflow_sha256,
            "outputPath": str(result.output_path),
            "outputSha256": result.output_sha256,
            "ffprobe": asdict(result.ffprobe),
            "mediaWarnings": list(result.media_warnings),
        }


def _load_wired_runner(specification: str, arguments: argparse.Namespace) -> VerticalSliceRunner:
    if ":" not in specification:
        raise VerticalSliceError("--wiring must use module:function syntax")
    module_name, factory_name = specification.split(":", 1)
    factory = getattr(importlib.import_module(module_name), factory_name, None)
    if not callable(factory):
        raise VerticalSliceError("runtime wiring factory is unavailable")
    runner = factory(arguments)
    if not isinstance(runner, VerticalSliceRunner):
        raise VerticalSliceError("runtime wiring factory returned the wrong type")
    return runner


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the persisted user-clicked 3.0s AMD FLUX-to-H3 vertical slice"
    )
    parser.add_argument(
        "--wiring",
        required=True,
        help="trusted module:function factory for loopback Comfy/process/gate wiring",
    )
    parser.add_argument("--persistent-root", type=Path, required=True)
    parser.add_argument("--click-authority", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--flux-manifest", type=Path, required=True)
    parser.add_argument("--flux-workflow-root", type=Path, required=True)
    parser.add_argument("--h3-manifest", type=Path, required=True)
    parser.add_argument("--h3-template", type=Path, required=True)
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument(
        "--stop-after-flux",
        action="store_true",
        help="persist the three FLUX assets and safe cutover, then exit",
    )
    phase.add_argument(
        "--resume-h3",
        action="store_true",
        help="require a flux_ready checkpoint and execute only H3",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    runner = _load_wired_runner(arguments.wiring, arguments)
    if arguments.stop_after_flux:
        references = runner.run_flux_stage()
        print(
            json.dumps(
                {
                    "status": "flux_ready",
                    "references": [
                        {
                            "viewName": item.view_name,
                            "path": str(item.path),
                            "sha256": item.sha256,
                            "promptId": item.prompt_id,
                            "workflowSha256": item.workflow_sha256,
                            "compiledWorkflowSha256": item.compiled_workflow_sha256,
                        }
                        for item in references
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    result = runner.run_h3_stage() if arguments.resume_h3 else runner.run()
    print(
        json.dumps(
            VerticalSliceRunner._result_payload(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
