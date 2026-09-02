from __future__ import annotations

import hashlib
import json
import math
import subprocess
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

try:
    import requests
except ImportError:  # pragma: no cover - guarded by RequestsComfyTransport
    requests = None
from shared_contracts import ComponentName, VideoResolution, stable_json_sha256

from .domain import (
    FactoryProjectState,
    GenerationRunStatus,
    ProviderCheckpoint,
    TakeEligibility,
    VisualTake,
)
from .durable_provider import ProviderRejected, ProviderResponseLost
from .state_store import FactoryStateError, FactoryStateStore


class ComfyRuntimeError(RuntimeError):
    pass


class ComfySubmitRejected(ComfyRuntimeError, ProviderRejected):
    pass


class ComfySubmissionOutcomeUnknown(ComfyRuntimeError, ProviderResponseLost):
    pass


class ComfyOutputInvalid(ComfyRuntimeError):
    pass


class ComfyCancellationForbidden(ComfyRuntimeError):
    pass


class ComfyObservation(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    LOST = "lost"
    CANCELLED = "cancelled"


class ComfyTransport(Protocol):
    def submit(
        self,
        workflow: dict[str, Any],
        *,
        client_id: str,
        extra_data: dict[str, Any],
    ) -> str: ...

    def find_submission(
        self,
        *,
        client_id: str,
        submission_nonce: str,
        required_extra_data: Mapping[str, object] | None = None,
    ) -> str | None: ...

    def observe(self, prompt_id: str) -> tuple[ComfyObservation, dict[str, Any]]: ...

    def cancel(self, prompt_id: str) -> None: ...

    def download(self, prompt_id: str, destination: Path) -> Path: ...


def _safe_response_detail(response: requests.Response) -> str:
    try:
        value = response.json()
        return json.dumps(value, ensure_ascii=False)[:1000]
    except (ValueError, TypeError):
        return (response.text or "")[:1000]


def _prompt_nodes(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in workflow.items()
        if isinstance(value, dict)
    }


def _contains_all(value: Any, tokens: tuple[str, ...]) -> bool:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return all(token in serialized for token in tokens)


def _find_prompt_id(value: Any, tokens: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and _contains_all(item, tokens):
                if len(key) >= 8:
                    return key
            found = _find_prompt_id(item, tokens)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        if _contains_all(value, tokens):
            for item in value:
                if isinstance(item, str) and len(item) >= 8:
                    return item
        for item in value:
            found = _find_prompt_id(item, tokens)
            if found:
                return found
    return None


def _validated_required_extra_data(
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not value:
        raise ComfyRuntimeError(
            "required Comfy submission metadata must be a non-empty object"
        )
    validated: dict[str, object] = {}
    for key, item in value.items():
        if (
            type(key) is not str
            or not key
            or key != key.strip()
            or len(key) > 128
            or any(
                not (character.isalnum() or character in {"_", "-", "."})
                for character in key
            )
        ):
            raise ComfyRuntimeError(
                "required Comfy submission metadata key is unsafe"
            )
        if type(item) is str:
            if (
                not item
                or item != item.strip()
                or len(item) > 1_000
                or any(
                    unicodedata.category(character) == "Cc"
                    for character in item
                )
            ):
                raise ComfyRuntimeError(
                    "required Comfy submission metadata value is unsafe"
                )
        elif type(item) is float:
            if not math.isfinite(item):
                raise ComfyRuntimeError(
                    "required Comfy submission metadata value is unsafe"
                )
        elif type(item) not in {bool, int}:
            raise ComfyRuntimeError(
                "required Comfy submission metadata value must be a JSON scalar"
            )
        validated[key] = item
    return validated


def _same_json_scalar(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _contains_exact_scalar(value: object, expected: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_exact_scalar(item, expected)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_exact_scalar(item, expected) for item in value)
    return _same_json_scalar(value, expected)


def _contains_exact_mapping(
    value: object,
    required: Mapping[str, object],
) -> bool:
    if isinstance(value, Mapping):
        if all(
            key in value and _same_json_scalar(value[key], expected)
            for key, expected in required.items()
        ):
            return True
        return any(
            _contains_exact_mapping(item, required)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_exact_mapping(item, required) for item in value)
    return False


def _looks_like_prompt_candidate(value: Mapping[str, object]) -> bool:
    return any(
        key in value
        for key in ("client_id", "extra_data", "prompt", "status", "outputs")
    )


def _find_prompt_id_with_metadata(
    value: object,
    *,
    tokens: tuple[str, ...],
    required: Mapping[str, object],
) -> str | None:
    def matches(candidate: object) -> bool:
        return all(
            _contains_exact_scalar(candidate, token) for token in tokens
        ) and _contains_exact_mapping(candidate, required)

    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                isinstance(key, str)
                and len(key) >= 8
                and isinstance(item, Mapping)
                and _looks_like_prompt_candidate(item)
                and matches(item)
            ):
                return key
            found = _find_prompt_id_with_metadata(
                item,
                tokens=tokens,
                required=required,
            )
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        if matches(value):
            excluded = {*tokens, *(str(item) for item in required.values())}
            for item in value:
                if (
                    isinstance(item, str)
                    and len(item) >= 8
                    and item not in excluded
                ):
                    return item
        for item in value:
            found = _find_prompt_id_with_metadata(
                item,
                tokens=tokens,
                required=required,
            )
            if found is not None:
                return found
    return None


def _queue_contains(queue: dict[str, Any], prompt_id: str) -> ComfyObservation | None:
    running = queue.get("queue_running", ())
    pending = queue.get("queue_pending", ())
    if _contains_all(running, (prompt_id,)):
        return ComfyObservation.RUNNING
    if _contains_all(pending, (prompt_id,)):
        return ComfyObservation.QUEUED
    return None


def _history_state(entry: dict[str, Any]) -> ComfyObservation:
    status = entry.get("status") or {}
    status_text = str(status.get("status_str", "")).casefold()
    if status_text in {"error", "failed"}:
        return ComfyObservation.ERROR
    if status_text in {"cancelled", "canceled"}:
        return ComfyObservation.CANCELLED
    if status.get("completed") is True or entry.get("outputs"):
        return ComfyObservation.SUCCESS
    return ComfyObservation.RUNNING


def _video_output_descriptor(entry: dict[str, Any]) -> dict[str, Any]:
    for output in (entry.get("outputs") or {}).values():
        if not isinstance(output, dict):
            continue
        for key in ("videos", "gifs", "images"):
            for item in output.get(key, ()):
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename", ""))
                if Path(filename).suffix.casefold() in {
                    ".mp4",
                    ".webm",
                    ".mov",
                    ".mkv",
                }:
                    return item
    raise ComfyOutputInvalid("Comfy history has no video output")


class RequestsComfyTransport:
    """Small HTTP adapter; durable state remains in FactoryStateStore."""

    def __init__(
        self,
        base_url: str,
        *,
        session: requests.Session | None = None,
        submit_timeout_seconds: float = 60,
        read_timeout_seconds: float = 30,
    ) -> None:
        if requests is None:
            raise ComfyRuntimeError("requests is required for Comfy HTTP transport")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.submit_timeout_seconds = submit_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds

    def _get_json(self, path: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}",
            timeout=self.read_timeout_seconds,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ComfyRuntimeError("Comfy returned a non-object response")
        return value

    def submit(
        self,
        workflow: dict[str, Any],
        *,
        client_id: str,
        extra_data: dict[str, Any],
    ) -> str:
        try:
            response = self.session.post(
                f"{self.base_url}/prompt",
                json={
                    "prompt": _prompt_nodes(workflow),
                    "client_id": client_id,
                    "extra_data": extra_data,
                },
                timeout=self.submit_timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise ComfySubmissionOutcomeUnknown(
                "Comfy submission response was not observed"
            ) from exc
        if response.status_code >= 400:
            raise ComfySubmitRejected(
                f"Comfy rejected prompt: {_safe_response_detail(response)}"
            )
        try:
            value = response.json()
        except (TypeError, ValueError) as exc:
            raise ComfySubmissionOutcomeUnknown(
                "Comfy submission returned an ambiguous success response"
            ) from exc
        prompt_id = value.get("prompt_id") if isinstance(value, dict) else None
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfySubmissionOutcomeUnknown(
                "Comfy submission returned an ambiguous success response"
            )
        return prompt_id

    def find_submission(
        self,
        *,
        client_id: str,
        submission_nonce: str,
        required_extra_data: Mapping[str, object] | None = None,
    ) -> str | None:
        required = _validated_required_extra_data(required_extra_data)
        tokens = (client_id, submission_nonce)
        queue = self._get_json("/queue")
        found = (
            _find_prompt_id(queue, tokens)
            if required is None
            else _find_prompt_id_with_metadata(
                queue,
                tokens=tokens,
                required=required,
            )
        )
        if found:
            return found
        history = self._get_json("/history")
        if required is None:
            return _find_prompt_id(history, tokens)
        return _find_prompt_id_with_metadata(
            history,
            tokens=tokens,
            required=required,
        )

    def observe(self, prompt_id: str) -> tuple[ComfyObservation, dict[str, Any]]:
        history = self._get_json(f"/history/{prompt_id}")
        entry = history.get(prompt_id)
        if isinstance(entry, dict):
            status = _history_state(entry)
            progress = {"status": entry.get("status", {})}
            return status, progress
        queue = self._get_json("/queue")
        queue_state = _queue_contains(queue, prompt_id)
        if queue_state is not None:
            return queue_state, {}
        return ComfyObservation.LOST, {}

    def cancel(self, prompt_id: str) -> None:
        queue = self._get_json("/queue")
        state = _queue_contains(queue, prompt_id)
        if state is ComfyObservation.RUNNING:
            response = self.session.post(
                f"{self.base_url}/interrupt",
                json={},
                timeout=self.read_timeout_seconds,
            )
            response.raise_for_status()
        elif state is ComfyObservation.QUEUED:
            response = self.session.post(
                f"{self.base_url}/queue",
                json={"delete": [prompt_id]},
                timeout=self.read_timeout_seconds,
            )
            response.raise_for_status()

    def download(self, prompt_id: str, destination: Path) -> Path:
        history = self._get_json(f"/history/{prompt_id}")
        entry = history.get(prompt_id)
        if not isinstance(entry, dict) or _history_state(entry) is not ComfyObservation.SUCCESS:
            raise ComfyRuntimeError("Comfy output is not ready")
        descriptor = _video_output_descriptor(entry)
        response = self.session.get(
            f"{self.base_url}/view",
            params={
                "filename": descriptor["filename"],
                "subfolder": descriptor.get("subfolder", ""),
                "type": descriptor.get("type", "output"),
            },
            timeout=max(self.read_timeout_seconds, 300),
        )
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
        return destination


@dataclass(frozen=True, slots=True)
class VideoProbe:
    width: int
    height: int
    duration_seconds: float
    codec_type: str
    format_name: str


class VideoProbeBackend(Protocol):
    def probe(self, path: Path) -> VideoProbe: ...


class FfprobeBackend:
    def __init__(self, executable: str = "ffprobe") -> None:
        self.executable = executable

    def probe(self, path: Path) -> VideoProbe:
        completed = subprocess.run(
            [
                self.executable,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_type:format=duration,format_name",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if completed.returncode != 0:
            raise ComfyOutputInvalid("ffprobe rejected generated video")
        try:
            payload = json.loads(completed.stdout)
            stream = payload["streams"][0]
            format_data = payload["format"]
            return VideoProbe(
                width=int(stream["width"]),
                height=int(stream["height"]),
                duration_seconds=float(format_data["duration"]),
                codec_type=str(stream["codec_type"]),
                format_name=str(format_data["format_name"]),
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ComfyOutputInvalid("ffprobe output is incomplete") from exc


@dataclass(frozen=True, slots=True)
class VerifiedVideo:
    artifact_sha256: str
    artifact_bytes: int
    mime: str
    probe: VideoProbe
    manifest_sha256: str


class ComfyOutputVerifier:
    MIME_BY_SUFFIX = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
    }

    def __init__(
        self,
        probe_backend: VideoProbeBackend | None = None,
        *,
        duration_tolerance_seconds: float = 1.0,
    ) -> None:
        self.probe_backend = probe_backend or FfprobeBackend()
        self.duration_tolerance_seconds = duration_tolerance_seconds

    def verify(
        self,
        path: Path,
        *,
        expected_resolution: VideoResolution,
        expected_duration_seconds: float,
    ) -> VerifiedVideo:
        if not path.is_file():
            raise ComfyOutputInvalid("generated video does not exist")
        size = path.stat().st_size
        if size <= 0:
            raise ComfyOutputInvalid("generated video is empty")
        mime = self.MIME_BY_SUFFIX.get(path.suffix.casefold())
        if mime is None:
            raise ComfyOutputInvalid("generated artifact is not a supported video type")
        probe = self.probe_backend.probe(path)
        if probe.codec_type != "video":
            raise ComfyOutputInvalid("generated artifact has no video stream")
        if (
            probe.width != expected_resolution.width
            or probe.height != expected_resolution.height
        ):
            raise ComfyOutputInvalid("generated video resolution does not match request")
        tolerance = max(
            self.duration_tolerance_seconds,
            expected_duration_seconds * 0.2,
        )
        if abs(probe.duration_seconds - expected_duration_seconds) > tolerance:
            raise ComfyOutputInvalid("generated video duration does not match request")

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        manifest = {
            "artifact_sha256": sha256,
            "artifact_bytes": size,
            "mime": mime,
            "width": probe.width,
            "height": probe.height,
            "duration_seconds": probe.duration_seconds,
            "format_name": probe.format_name,
        }
        return VerifiedVideo(
            artifact_sha256=sha256,
            artifact_bytes=size,
            mime=mime,
            probe=probe,
            manifest_sha256=stable_json_sha256(manifest),
        )


def _checkpoint(state: FactoryProjectState, run_id: UUID) -> ProviderCheckpoint:
    for checkpoint in state.checkpoints:
        if checkpoint.run_id == run_id:
            return checkpoint
    raise FactoryStateError("provider checkpoint is unavailable")


class DurableComfyCoordinator:
    """Crash-safe coordinator with file state as the single provider authority."""

    def __init__(
        self,
        *,
        store: FactoryStateStore,
        transport: ComfyTransport,
        verifier: ComfyOutputVerifier | None = None,
    ) -> None:
        self.store = store
        self.transport = transport
        self.verifier = verifier or ComfyOutputVerifier()

    @staticmethod
    def workflow_hash(workflow: dict[str, Any]) -> str:
        return stable_json_sha256(_prompt_nodes(workflow))

    def submit(
        self,
        run_id: UUID,
        *,
        workflow: dict[str, Any],
        instance_id: str,
        gpu_id: str,
        gpu_lease_id: UUID,
        hub_job_lease_id: UUID,
        expected_state_version: int,
        submission_nonce: str | None = None,
        client_id: str | None = None,
    ) -> FactoryProjectState:
        state = self.store.prepare_submission(
            run_id,
            instance_id=instance_id,
            gpu_id=gpu_id,
            gpu_lease_id=gpu_lease_id,
            hub_job_lease_id=hub_job_lease_id,
            workflow_hash=self.workflow_hash(workflow),
            submission_nonce=submission_nonce,
            client_id=client_id,
            expected_state_version=expected_state_version,
        )
        checkpoint = _checkpoint(state, run_id)
        if checkpoint.prompt_id is not None:
            return state
        extra_data = {
            "factory_run_id": str(run_id),
            "submission_nonce": checkpoint.submission_nonce,
        }
        prompt_id = self.transport.find_submission(
            client_id=checkpoint.client_id,
            submission_nonce=checkpoint.submission_nonce,
        )
        try:
            if prompt_id is None:
                prompt_id = self.transport.submit(
                    workflow,
                    client_id=checkpoint.client_id,
                    extra_data=extra_data,
                )
        except ComfySubmissionOutcomeUnknown:
            prompt_id = self.transport.find_submission(
                client_id=checkpoint.client_id,
                submission_nonce=checkpoint.submission_nonce,
            )
            if prompt_id is None:
                raise
        except ComfySubmitRejected:
            return self.store.transition_run(
                run_id,
                GenerationRunStatus.FAILED,
                safe_error_code="provider_submit_rejected",
                expected_state_version=state.state_version,
            )
        return self.store.confirm_submission(
            run_id,
            prompt_id=prompt_id,
            expected_state_version=state.state_version,
        )

    def recover_prepared(
        self,
        run_id: UUID,
        *,
        workflow: dict[str, Any],
        expected_state_version: int,
        resubmit_after_confirmed_absence: bool = False,
    ) -> FactoryProjectState:
        state = self.store.load()
        if state.state_version != expected_state_version:
            raise FactoryStateError("factory state version changed during recovery")
        checkpoint = _checkpoint(state, run_id)
        if checkpoint.prompt_id is not None:
            return state
        if checkpoint.workflow_hash != self.workflow_hash(workflow):
            raise FactoryStateError("prepared workflow hash does not match recovery input")
        prompt_id = self.transport.find_submission(
            client_id=checkpoint.client_id,
            submission_nonce=checkpoint.submission_nonce,
        )
        if prompt_id is None and resubmit_after_confirmed_absence:
            prompt_id = self.transport.submit(
                workflow,
                client_id=checkpoint.client_id,
                extra_data={
                    "factory_run_id": str(run_id),
                    "submission_nonce": checkpoint.submission_nonce,
                },
            )
        if prompt_id is None:
            raise ComfySubmissionOutcomeUnknown(
                "prepared submission is absent; explicit resubmit approval is required"
            )
        return self.store.confirm_submission(
            run_id,
            prompt_id=prompt_id,
            expected_state_version=state.state_version,
        )

    def observe(
        self,
        run_id: UUID,
        *,
        expected_state_version: int,
    ) -> FactoryProjectState:
        state = self.store.load()
        if state.state_version != expected_state_version:
            raise FactoryStateError("factory state version changed during provider poll")
        checkpoint = _checkpoint(state, run_id)
        if checkpoint.prompt_id is None:
            raise FactoryStateError("provider prompt id is not persisted")
        observation, progress = self.transport.observe(checkpoint.prompt_id)
        run = next(item for item in state.runs if item.run_id == run_id)
        if (
            checkpoint.last_observed_state == observation.value
            and checkpoint.progress == progress
        ):
            return state
        if (
            run.status is GenerationRunStatus.RUNNING
            and observation is ComfyObservation.QUEUED
        ):
            return state
        return self.store.observe_provider(
            run_id,
            observed_state=observation.value,
            progress=progress,
            expected_state_version=state.state_version,
        )

    def cancel(
        self,
        run_id: UUID,
        *,
        gpu_lease_id: UUID,
        hub_job_lease_id: UUID,
        expected_state_version: int,
    ) -> FactoryProjectState:
        state = self.store.load()
        if state.state_version != expected_state_version:
            raise FactoryStateError("factory state version changed during cancellation")
        checkpoint = _checkpoint(state, run_id)
        if (
            checkpoint.gpu_lease_id != gpu_lease_id
            or checkpoint.hub_job_lease_id != hub_job_lease_id
        ):
            raise ComfyCancellationForbidden(
                "cancel requester does not own both durable leases"
            )
        if checkpoint.prompt_id is None:
            raise FactoryStateError("provider prompt id is not persisted")
        self.transport.cancel(checkpoint.prompt_id)
        return self.store.observe_provider(
            run_id,
            observed_state=ComfyObservation.CANCELLED.value,
            progress={},
            expected_state_version=state.state_version,
        )

    def materialize(
        self,
        run_id: UUID,
        *,
        destination: Path,
        observed_state: dict[str, Any],
        expected_state_version: int,
    ) -> FactoryProjectState:
        state = self.store.load()
        if state.state_version != expected_state_version:
            raise FactoryStateError("factory state version changed during materialization")
        run = next(item for item in state.runs if item.run_id == run_id)
        if run.status is not GenerationRunStatus.MATERIALIZING:
            raise FactoryStateError("generation run is not ready to materialize")
        checkpoint = _checkpoint(state, run_id)
        if checkpoint.prompt_id is None:
            raise FactoryStateError("provider prompt id is not persisted")
        output = self.transport.download(checkpoint.prompt_id, destination)
        verified = self.verifier.verify(
            output,
            expected_resolution=run.request.resolution,
            expected_duration_seconds=run.request.duration_seconds,
        )
        from shared_contracts import ArtifactRef

        take = VisualTake(
            visual_take_id=uuid4(),
            run_id=run_id,
            raw_video_ref=ArtifactRef(
                owner=ComponentName.DRAMA_FACTORY,
                artifact_id=uuid4(),
                sha256=verified.artifact_sha256,
                bytes=verified.artifact_bytes,
                mime=verified.mime,
                version=1,
            ),
            manifest_hash=verified.manifest_sha256,
            observed_state=observed_state,
            eligibility=TakeEligibility.CANDIDATE,
            created_at=state.updated_at,
        )
        return self.store.record_visual_take(
            take,
            expected_state_version=state.state_version,
        )
