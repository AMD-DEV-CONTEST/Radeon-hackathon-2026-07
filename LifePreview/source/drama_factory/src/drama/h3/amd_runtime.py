from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import tempfile
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol
from urllib.parse import urlsplit

import yaml

from drama.v3.durable_comfy import (
    ComfyObservation,
    ComfyRuntimeError,
    RequestsComfyTransport,
)
from drama.v3.durable_provider import (
    DurableProviderTransport,
    ProviderCapabilities,
    ProviderObservation,
    ProviderObservationState,
)


class H3AmdRuntimeError(RuntimeError):
    """An AMD H3 runtime boundary received untrusted or inconsistent data."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PERSISTENT_ROOT = "/persistent/douyin-amd"
_RUNTIME_ROOT = "/workspace/amd-runtime-cache"
_H3_MODEL_ROOT = f"{_PERSISTENT_ROOT}/models/minimax-h3/h3-amd-local-v1"
_FLUX2_MODEL_ROOT = (
    f"{_PERSISTENT_ROOT}/models/flux2-dev/flux2-dev-fp8mixed-v1"
)
_COMFY_BASE_URL = "http://127.0.0.1:18188"


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown {', '.join(unknown)}")
        raise H3AmdRuntimeError(f"{label} fields are not pinned: {'; '.join(details)}")


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise H3AmdRuntimeError(f"{label} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class AmdDeviceIdentity:
    vendor: str
    backend: str
    arch: str
    framework_device: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            for value in (
                self.vendor,
                self.backend,
                self.arch,
                self.framework_device,
            )
        ):
            raise H3AmdRuntimeError("AMD device identity fields must be strings")


def validate_amd_device_identity(identity: AmdDeviceIdentity) -> AmdDeviceIdentity:
    if type(identity) is not AmdDeviceIdentity:
        raise H3AmdRuntimeError("AMD device identity has an invalid type")
    if identity.vendor != "amd":
        raise H3AmdRuntimeError("AMD runtime requires the AMD vendor")
    if identity.backend != "rocm":
        raise H3AmdRuntimeError("AMD runtime requires the ROCm backend")
    if identity.arch != "gfx1100":
        raise H3AmdRuntimeError("AMD runtime requires the gfx1100 architecture")
    if identity.framework_device != "cuda:0":
        raise H3AmdRuntimeError(
            "AMD ROCm runtime must expose its only GPU as framework device cuda:0"
        )
    return identity


@dataclass(frozen=True, slots=True)
class H3AmdRuntimeConfig:
    schema_version: str
    comfy_base_url: str
    persistent_root: str
    runtime_root: str
    h3_model_root: str
    flux2_model_root: str
    gpu_count: int
    comfyui_count: int
    video_worker_count: int
    serial_model_execution: bool
    device: AmdDeviceIdentity

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            for value in (
                self.schema_version,
                self.comfy_base_url,
                self.persistent_root,
                self.runtime_root,
                self.h3_model_root,
                self.flux2_model_root,
            )
        ):
            raise H3AmdRuntimeError("H3 AMD runtime paths must be strings")
        if any(
            type(value) is not int
            for value in (
                self.gpu_count,
                self.comfyui_count,
                self.video_worker_count,
            )
        ):
            raise H3AmdRuntimeError("H3 AMD service counts must be integers")
        if type(self.serial_model_execution) is not bool:
            raise H3AmdRuntimeError("serial_model_execution must be a boolean")
        if self.schema_version != "h3-amd-runtime.v1":
            raise H3AmdRuntimeError("H3 AMD runtime schema is not pinned")
        if self.comfy_base_url != _COMFY_BASE_URL:
            raise H3AmdRuntimeError("H3 ComfyUI endpoint must use the pinned loopback URL")
        if (
            self.persistent_root != _PERSISTENT_ROOT
            or self.runtime_root != _RUNTIME_ROOT
            or self.h3_model_root != _H3_MODEL_ROOT
            or self.flux2_model_root != _FLUX2_MODEL_ROOT
        ):
            raise H3AmdRuntimeError(
                "H3 AMD persistent model roots or workspace runtime root are not pinned"
            )
        if (
            self.gpu_count != 1
            or self.comfyui_count != 1
            or self.video_worker_count != 1
        ):
            raise H3AmdRuntimeError(
                "H3 AMD first release requires one GPU, one ComfyUI, and one video worker"
            )
        if self.serial_model_execution is not True:
            raise H3AmdRuntimeError("FLUX.2 and H3 must execute serially on the AMD GPU")
        validate_amd_device_identity(self.device)


def load_h3_amd_runtime_config(source: Path | str) -> H3AmdRuntimeConfig:
    try:
        path = Path(source)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        root = _require_mapping(payload, "H3 AMD runtime config")
        _exact_keys(
            root,
            {
                "schema_version",
                "comfy_base_url",
                "persistent_root",
                "runtime_root",
                "h3_model_root",
                "flux2_model_root",
                "gpu_count",
                "comfyui_count",
                "video_worker_count",
                "serial_model_execution",
                "device",
            },
            "H3 AMD runtime config",
        )
        device_data = _require_mapping(root["device"], "H3 AMD device")
        _exact_keys(
            device_data,
            {"vendor", "backend", "arch", "framework_device"},
            "H3 AMD device",
        )
        if any(
            isinstance(root[key], bool) or not isinstance(root[key], int)
            for key in ("gpu_count", "comfyui_count", "video_worker_count")
        ):
            raise H3AmdRuntimeError("H3 AMD service counts must be integers")
        if not all(
            isinstance(root[key], str)
            for key in (
                "schema_version",
                "comfy_base_url",
                "persistent_root",
                "runtime_root",
                "h3_model_root",
                "flux2_model_root",
            )
        ):
            raise H3AmdRuntimeError("H3 AMD runtime paths and identity must be strings")
        if not all(isinstance(device_data[key], str) for key in device_data):
            raise H3AmdRuntimeError("H3 AMD device fields must be strings")
        if not isinstance(root["serial_model_execution"], bool):
            raise H3AmdRuntimeError("serial_model_execution must be a boolean")
        return H3AmdRuntimeConfig(
            schema_version=root["schema_version"],
            comfy_base_url=root["comfy_base_url"],
            persistent_root=root["persistent_root"],
            runtime_root=root["runtime_root"],
            h3_model_root=root["h3_model_root"],
            flux2_model_root=root["flux2_model_root"],
            gpu_count=root["gpu_count"],
            comfyui_count=root["comfyui_count"],
            video_worker_count=root["video_worker_count"],
            serial_model_execution=root["serial_model_execution"],
            device=AmdDeviceIdentity(
                vendor=device_data["vendor"],
                backend=device_data["backend"],
                arch=device_data["arch"],
                framework_device=device_data["framework_device"],
            ),
        )
    except H3AmdRuntimeError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise H3AmdRuntimeError(f"invalid H3 AMD runtime config: {exc}") from exc


def _sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return _sha256_handle(handle)


def _sha256_handle(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validate_loopback_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        is_loopback = bool(host) and (
            host == "localhost" or ipaddress.ip_address(host).is_loopback
        )
    except ValueError as exc:
        raise H3AmdRuntimeError("ComfyUI URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or not is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise H3AmdRuntimeError("ComfyUI URL must be a credential-free loopback HTTP URL")
    return value.rstrip("/")


def _safe_subfolder(value: str) -> str:
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise H3AmdRuntimeError("H3 upload subfolder is unsafe")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) < 2
        or path.parts[0] != "h3"
        or any(
            part in {"", ".", ".."} or not _SAFE_SEGMENT_RE.fullmatch(part)
            for part in path.parts
        )
    ):
        raise H3AmdRuntimeError("H3 upload subfolder is unsafe")
    return path.as_posix()


def _safe_upload_name(value: object) -> str:
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise H3AmdRuntimeError("Comfy upload returned an unsafe name")
    path = PurePosixPath(value)
    if (
        path.name != value
        or value in {"", ".", ".."}
        or not _SAFE_SEGMENT_RE.fullmatch(value)
        or path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}
    ):
        raise H3AmdRuntimeError("Comfy upload returned an unsafe name")
    return value


def _safe_prompt_id(value: object) -> str:
    if (
        type(value) is not str
        or not 8 <= len(value) <= 200
        or _SAFE_SEGMENT_RE.fullmatch(value) is None
        or any(character.isspace() or ord(character) < 33 for character in value)
    ):
        raise H3AmdRuntimeError("Comfy returned an unsafe prompt id")
    return value


def _safe_output_subfolder(value: object) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise H3AmdRuntimeError("Comfy output location is unsafe")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(
            segment in {"", ".", ".."}
            or _SAFE_SEGMENT_RE.fullmatch(segment) is None
            for segment in path.parts
        )
    ):
        raise H3AmdRuntimeError("Comfy output location is unsafe")
    return value


def _safe_output_name(value: object) -> str:
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise H3AmdRuntimeError("Comfy output filename is unsafe")
    path = PurePosixPath(value)
    if (
        path.name != value
        or value in {"", ".", ".."}
        or _SAFE_SEGMENT_RE.fullmatch(value) is None
        or path.suffix.casefold() != ".mp4"
    ):
        raise H3AmdRuntimeError("Comfy output filename is unsafe")
    return value


class H3RequestsComfyTransport(RequestsComfyTransport):
    """Loopback Comfy adapter for digest-bound H3 reference staging."""

    def __init__(self, base_url: str, **kwargs: object) -> None:
        output_root = kwargs.pop("output_root", None)
        try:
            super().__init__(_validate_loopback_url(base_url), **kwargs)
        except H3AmdRuntimeError:
            raise
        except (ComfyRuntimeError, TypeError, ValueError) as exc:
            raise H3AmdRuntimeError(f"cannot initialize H3 Comfy transport: {exc}") from exc
        if output_root is None:
            self.output_root: Path | None = None
            self.resolved_output_root: Path | None = None
            return
        if (
            not isinstance(output_root, Path)
            or not output_root.is_absolute()
            or not output_root.is_dir()
            or output_root.is_symlink()
            or bool(getattr(output_root, "is_junction", lambda: False)())
        ):
            raise H3AmdRuntimeError("H3 output root is unsafe")
        try:
            resolved_output_root = output_root.resolve(strict=True)
        except OSError as exc:
            raise H3AmdRuntimeError("H3 output root is unsafe") from exc
        self.output_root = output_root.absolute()
        self.resolved_output_root = resolved_output_root

    @staticmethod
    def _is_linklike(path: Path) -> bool:
        try:
            return path.is_symlink() or bool(
                getattr(path, "is_junction", lambda: False)()
            )
        except OSError:
            return True

    def _validate_output_destination(self, destination: object) -> Path:
        output_root = self.output_root
        resolved_output_root = self.resolved_output_root
        if (
            output_root is None
            or resolved_output_root is None
            or not isinstance(destination, Path)
            or not destination.is_absolute()
            or any(part in {"", ".", ".."} for part in destination.parts[1:])
        ):
            raise H3AmdRuntimeError("H3 output destination is unsafe")
        try:
            relative = destination.absolute().relative_to(output_root)
            resolved_parent = destination.parent.resolve(strict=True)
            resolved_parent.relative_to(resolved_output_root)
        except (OSError, ValueError) as exc:
            raise H3AmdRuntimeError("H3 output destination is unsafe") from exc
        current = output_root
        for segment in relative.parts[:-1]:
            current /= segment
            if self._is_linklike(current):
                raise H3AmdRuntimeError("H3 output destination is unsafe")
        if (
            destination.suffix.casefold() != ".mp4"
            or _SAFE_SEGMENT_RE.fullmatch(destination.name) is None
            or destination.exists()
            or destination.is_symlink()
            or not destination.parent.is_dir()
            or self._is_linklike(destination.parent)
        ):
            raise H3AmdRuntimeError("H3 output destination is unsafe")
        return destination

    def upload_reference(
        self,
        source: Path,
        *,
        expected_sha256: str,
        subfolder: str,
    ) -> str:
        if not isinstance(source, Path) or not source.is_file():
            raise H3AmdRuntimeError("approved H3 reference is unavailable")
        if type(expected_sha256) is not str or not _SHA256_RE.fullmatch(
            expected_sha256
        ):
            raise H3AmdRuntimeError("approved H3 reference digest is invalid")
        safe_subfolder = _safe_subfolder(subfolder)
        local_name = _safe_upload_name(source.name)
        try:
            with tempfile.TemporaryDirectory(
                prefix="h3-reference-upload-",
                dir=source.parent,
            ) as directory:
                snapshot_path = Path(directory) / "reference.snapshot"
                snapshot_digest = hashlib.sha256()
                snapshot_size = 0
                with source.open("rb") as source_handle, snapshot_path.open(
                    "xb"
                ) as snapshot_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        snapshot_handle.write(chunk)
                        snapshot_digest.update(chunk)
                        snapshot_size += len(chunk)
                if snapshot_digest.hexdigest() != expected_sha256:
                    raise H3AmdRuntimeError(
                        "approved H3 reference digest does not match local bytes"
                    )
                with snapshot_path.open("rb") as upload_handle:
                    if _sha256_handle(upload_handle) != expected_sha256:
                        raise H3AmdRuntimeError(
                            "approved H3 reference snapshot is inconsistent"
                        )
                    upload_handle.seek(0)
                    response = self.session.post(
                        f"{self.base_url}/upload/image",
                        files={
                            "image": (
                                local_name,
                                upload_handle,
                                "application/octet-stream",
                            )
                        },
                        data={
                            "overwrite": "false",
                            "subfolder": safe_subfolder,
                            "type": "input",
                        },
                        timeout=max(self.submit_timeout_seconds, 120),
                    )
                    upload_handle.seek(0)
                    uploaded_snapshot_digest = _sha256_handle(upload_handle)
                snapshot_final_stat = snapshot_path.stat()
                with snapshot_path.open("rb") as snapshot_handle:
                    final_path_digest = _sha256_handle(snapshot_handle)
                if (
                    snapshot_final_stat.st_size != snapshot_size
                    or uploaded_snapshot_digest != expected_sha256
                    or final_path_digest != expected_sha256
                ):
                    raise H3AmdRuntimeError(
                        "approved H3 reference snapshot changed while it was uploaded"
                    )
            response.raise_for_status()
            payload = response.json()
        except H3AmdRuntimeError:
            raise
        except Exception as exc:
            raise H3AmdRuntimeError("Comfy reference upload failed") from exc
        if not isinstance(payload, Mapping):
            raise H3AmdRuntimeError("Comfy upload response is incomplete")
        actual_name = _safe_upload_name(payload.get("name"))
        actual_subfolder = payload.get("subfolder")
        actual_type = payload.get("type")
        if (
            actual_name != local_name
            or actual_subfolder != safe_subfolder
            or actual_type != "input"
        ):
            raise H3AmdRuntimeError("Comfy upload response did not exactly echo its location")
        return f"{safe_subfolder}/{actual_name}"

    def download(self, prompt_id: str, destination: Path) -> Path:
        safe_prompt_id = _safe_prompt_id(prompt_id)
        destination = self._validate_output_destination(destination)
        partial = destination.with_suffix(destination.suffix + ".partial")
        if partial.exists() or partial.is_symlink():
            if self._is_linklike(partial) or not partial.is_file():
                raise H3AmdRuntimeError("H3 output destination is unsafe")
            try:
                partial.unlink()
            except OSError as exc:
                raise H3AmdRuntimeError(
                    "H3 stale output fragment cannot be recovered"
                ) from exc
        try:
            history = self._get_json(f"/history/{safe_prompt_id}")
            entry = history.get(safe_prompt_id)
            if not isinstance(entry, Mapping):
                raise H3AmdRuntimeError("Comfy output is not ready")
            status = entry.get("status")
            status_text = (
                str(status.get("status_str", "")).casefold()
                if isinstance(status, Mapping)
                else ""
            )
            if (
                not isinstance(status, Mapping)
                or status_text in {
                    "error",
                    "failed",
                    "cancelled",
                    "canceled",
                }
                or status.get("completed") is not True
            ):
                raise H3AmdRuntimeError("Comfy output is not ready")
            outputs = entry.get("outputs")
            if not isinstance(outputs, Mapping) or set(outputs) != {"15"}:
                raise H3AmdRuntimeError("Comfy output node is not pinned")
            save_video = outputs.get("15")
            if not isinstance(save_video, Mapping) or save_video.get("images"):
                raise H3AmdRuntimeError("Comfy output descriptor is invalid")
            descriptors: list[object] = []
            for key in ("videos", "gifs"):
                values = save_video.get(key, ())
                if not isinstance(values, (list, tuple)):
                    raise H3AmdRuntimeError("Comfy output descriptor is invalid")
                descriptors.extend(values)
            if len(descriptors) != 1 or not isinstance(descriptors[0], Mapping):
                raise H3AmdRuntimeError("Comfy output descriptor is invalid")
            descriptor = descriptors[0]
            filename = _safe_output_name(descriptor.get("filename"))
            subfolder = _safe_output_subfolder(descriptor.get("subfolder", ""))
            if descriptor.get("type") != "output":
                raise H3AmdRuntimeError("Comfy output location is unsafe")
            response = self.session.get(
                f"{self.base_url}/view",
                params={
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": "output",
                },
                timeout=max(self.read_timeout_seconds, 300),
            )
            response.raise_for_status()
            payload = response.content
            if not isinstance(payload, (bytes, bytearray)) or not payload:
                raise H3AmdRuntimeError("Comfy output payload is invalid")
            with partial.open("xb") as handle:
                handle.write(bytes(payload))
                handle.flush()
            partial.replace(destination)
        except H3AmdRuntimeError:
            partial.unlink(missing_ok=True)
            raise
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise H3AmdRuntimeError("Comfy output download failed") from exc
        return destination


@dataclass(frozen=True, slots=True)
class H3MediaProbe:
    width: int
    height: int
    fps_numerator: int
    fps_denominator: int
    frame_count: int
    duration_seconds: float
    video_codec: str
    audio_codec: str | None
    audio_channels: int


class H3MediaProbeBackend(Protocol):
    def probe(self, path: Path) -> H3MediaProbe: ...


def _positive_int(value: object, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise H3AmdRuntimeError(f"ffprobe {label} is invalid") from exc
    if result <= 0:
        raise H3AmdRuntimeError(f"ffprobe {label} must be positive")
    return result


def _frame_rate(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or "/" not in value:
        raise H3AmdRuntimeError("ffprobe frame rate is invalid")
    numerator, denominator = value.split("/", 1)
    return _positive_int(numerator, "frame-rate numerator"), _positive_int(
        denominator, "frame-rate denominator"
    )


class H3FfprobeBackend:
    """Extract the exact video and native-audio properties used for H3 QC."""

    def __init__(self, executable: str = "ffprobe") -> None:
        if not executable.strip():
            raise H3AmdRuntimeError("ffprobe executable must not be empty")
        self.executable = executable

    def probe(self, path: Path) -> H3MediaProbe:
        try:
            completed = subprocess.run(
                [
                    self.executable,
                    "-v",
                    "error",
                    "-count_frames",
                    "-show_entries",
                    (
                        "stream=codec_type,codec_name,width,height,avg_frame_rate,"
                        "nb_frames,nb_read_frames,channels:format=duration"
                    ),
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
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise H3AmdRuntimeError("ffprobe could not inspect H3 output") from exc
        if completed.returncode != 0:
            raise H3AmdRuntimeError("ffprobe rejected H3 output")
        try:
            payload = json.loads(completed.stdout)
            streams = payload["streams"]
            if not isinstance(streams, list) or any(
                not isinstance(item, Mapping) for item in streams
            ):
                raise H3AmdRuntimeError("ffprobe stream list is invalid")
            video_streams = [item for item in streams if item.get("codec_type") == "video"]
            audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
            if (
                len(streams) != 2
                or len(video_streams) != 1
                or len(audio_streams) != 1
            ):
                raise H3AmdRuntimeError(
                    "H3 output must contain exactly one video and one native-audio stream"
                )
            video = video_streams[0]
            audio = audio_streams[0]
            numerator, denominator = _frame_rate(video.get("avg_frame_rate"))
            raw_frames = video.get("nb_read_frames") or video.get("nb_frames")
            return H3MediaProbe(
                width=_positive_int(video.get("width"), "width"),
                height=_positive_int(video.get("height"), "height"),
                fps_numerator=numerator,
                fps_denominator=denominator,
                frame_count=_positive_int(raw_frames, "frame count"),
                duration_seconds=float(payload["format"]["duration"]),
                video_codec=str(video.get("codec_name") or ""),
                audio_codec=str(audio.get("codec_name") or "") or None,
                audio_channels=_positive_int(audio.get("channels"), "audio channels"),
            )
        except H3AmdRuntimeError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise H3AmdRuntimeError("ffprobe output is incomplete") from exc


@dataclass(frozen=True, slots=True)
class H3VerifiedOutput:
    artifact_sha256: str
    artifact_bytes: int
    probe: H3MediaProbe


class H3OutputVerifier:
    def __init__(
        self,
        probe_backend: H3MediaProbeBackend | None = None,
        *,
        duration_tolerance_seconds: float = 0.1,
    ) -> None:
        if (
            not math.isfinite(duration_tolerance_seconds)
            or duration_tolerance_seconds < 0
        ):
            raise H3AmdRuntimeError("H3 duration tolerance must be finite and non-negative")
        self.probe_backend = probe_backend or H3FfprobeBackend()
        self.duration_tolerance_seconds = duration_tolerance_seconds

    def verify(
        self,
        path: Path,
        *,
        expected_frame_count: int,
        expected_fps: int,
        expected_width: int,
        expected_height: int,
    ) -> H3VerifiedOutput:
        if not isinstance(path, Path) or not path.is_file():
            raise H3AmdRuntimeError("H3 output does not exist")
        try:
            initial_stat = path.stat()
        except OSError as exc:
            raise H3AmdRuntimeError("H3 output cannot be inspected") from exc
        if initial_stat.st_size <= 0 or path.suffix.casefold() != ".mp4":
            raise H3AmdRuntimeError("H3 output must be a non-empty MP4")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (
                expected_frame_count,
                expected_fps,
                expected_width,
                expected_height,
            )
        ):
            raise H3AmdRuntimeError("expected H3 media values must be positive integers")
        if (
            expected_width != 1344
            or expected_height != 768
            or expected_fps != 24
            or not 73 <= expected_frame_count <= 362
            or expected_frame_count % 17 != 5
        ):
            raise H3AmdRuntimeError(
                "expected media does not match the pinned H3 AMD execution profile"
            )
        try:
            with tempfile.TemporaryDirectory(
                prefix="h3-media-verify-",
                dir=path.parent,
            ) as directory:
                snapshot_path = Path(directory) / "artifact.mp4"
                snapshot_digest = hashlib.sha256()
                snapshot_size = 0
                with path.open("rb") as source, snapshot_path.open("xb") as destination:
                    while chunk := source.read(1024 * 1024):
                        destination.write(chunk)
                        snapshot_digest.update(chunk)
                        snapshot_size += len(chunk)
                artifact_sha256 = snapshot_digest.hexdigest()
                if (
                    snapshot_size != initial_stat.st_size
                    or _sha256_file(path) != artifact_sha256
                ):
                    raise H3AmdRuntimeError(
                        "H3 output changed while its immutable snapshot was created"
                    )
                probe = self.probe_backend.probe(snapshot_path)
                snapshot_final_stat = snapshot_path.stat()
                if (
                    snapshot_final_stat.st_size != snapshot_size
                    or _sha256_file(snapshot_path) != artifact_sha256
                ):
                    raise H3AmdRuntimeError(
                        "H3 immutable media snapshot changed while it was probed"
                    )
                final_stat = path.stat()
                if (
                    final_stat.st_size != snapshot_size
                    or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
                    or _sha256_file(path) != artifact_sha256
                ):
                    raise H3AmdRuntimeError(
                        "H3 output changed while its media snapshot was verified"
                    )
        except H3AmdRuntimeError:
            raise
        except OSError as exc:
            raise H3AmdRuntimeError("H3 output snapshot could not be verified") from exc
        if not isinstance(probe, H3MediaProbe):
            raise H3AmdRuntimeError("H3 probe backend returned an invalid result")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                probe.width,
                probe.height,
                probe.fps_numerator,
                probe.fps_denominator,
                probe.frame_count,
                probe.audio_channels,
            )
        ) or not isinstance(probe.duration_seconds, (int, float)):
            raise H3AmdRuntimeError("H3 probe returned invalid numeric media fields")
        if not isinstance(probe.video_codec, str) or (
            probe.audio_codec is not None and not isinstance(probe.audio_codec, str)
        ):
            raise H3AmdRuntimeError("H3 probe returned invalid codec fields")
        if probe.width != expected_width or probe.height != expected_height:
            raise H3AmdRuntimeError("H3 output resolution does not match the request")
        if (
            probe.fps_denominator <= 0
            or probe.fps_numerator != expected_fps * probe.fps_denominator
        ):
            raise H3AmdRuntimeError("H3 output frame rate does not match the request")
        if probe.frame_count != expected_frame_count:
            raise H3AmdRuntimeError("H3 output frame count does not match the request")
        if probe.video_codec.casefold() != "h264":
            raise H3AmdRuntimeError("H3 output video codec must be H.264")
        if probe.audio_codec is None or probe.audio_codec.casefold() != "aac":
            raise H3AmdRuntimeError("H3 output must contain native AAC audio")
        if probe.audio_channels <= 0:
            raise H3AmdRuntimeError("H3 output native audio has no channels")
        expected_duration = expected_frame_count / expected_fps
        tolerance = max(self.duration_tolerance_seconds, 2 / expected_fps)
        if (
            not math.isfinite(probe.duration_seconds)
            or probe.duration_seconds <= 0
            or abs(probe.duration_seconds - expected_duration) > tolerance
        ):
            raise H3AmdRuntimeError("H3 output duration is inconsistent with its frame grid")
        return H3VerifiedOutput(
            artifact_sha256=artifact_sha256,
            artifact_bytes=snapshot_size,
            probe=probe,
        )


@dataclass(frozen=True, slots=True, init=False)
class H3DurableComfyTransport(DurableProviderTransport):
    """Adapt local Comfy to the generic crash-safe provider protocol."""

    comfy: object = field(repr=False)
    _workflow_json: str = field(repr=False)
    workflow_digest: str
    submission_nonce: str = field(repr=False)
    attempt_stage: str
    provider_name: str

    capabilities = ProviderCapabilities(
        idempotent_submit=False,
        query_by_client_token=True,
        query_by_task_id=True,
    )

    def __init__(
        self,
        *,
        comfy: object,
        workflow: Mapping[str, Any],
        workflow_digest: str,
        submission_nonce: str,
        attempt_stage: str,
    ) -> None:
        if type(attempt_stage) is not str or attempt_stage not in {
            "initial",
            "repair",
        }:
            raise H3AmdRuntimeError(
                "H3 attempt stage must be exactly initial or repair"
            )
        if not isinstance(workflow, Mapping) or not workflow:
            raise H3AmdRuntimeError("H3 Comfy workflow must be a non-empty object")
        if type(workflow_digest) is not str or not _SHA256_RE.fullmatch(
            workflow_digest
        ):
            raise H3AmdRuntimeError("H3 workflow digest is invalid")
        if type(submission_nonce) is not str or not _NONCE_RE.fullmatch(
            submission_nonce
        ):
            raise H3AmdRuntimeError("H3 submission nonce is invalid")
        try:
            workflow_json = _canonical_json(dict(workflow))
            snapshot = json.loads(workflow_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise H3AmdRuntimeError("H3 Comfy workflow is not canonical JSON") from exc
        if not isinstance(snapshot, dict) or _stable_digest(snapshot) != workflow_digest:
            raise H3AmdRuntimeError("H3 workflow digest does not match its snapshot")
        output = snapshot.get("15")
        if (
            not isinstance(output, Mapping)
            or output.get("class_type") != "SaveVideo"
            or not isinstance(output.get("inputs"), Mapping)
        ):
            raise H3AmdRuntimeError("H3 workflow must end at pinned SaveVideo node 15")
        for method in ("submit", "find_submission", "observe"):
            if not callable(getattr(comfy, method, None)):
                raise H3AmdRuntimeError(f"H3 Comfy adapter does not implement {method}")
        object.__setattr__(self, "comfy", comfy)
        object.__setattr__(self, "_workflow_json", workflow_json)
        object.__setattr__(self, "workflow_digest", workflow_digest)
        object.__setattr__(self, "submission_nonce", submission_nonce)
        object.__setattr__(self, "attempt_stage", attempt_stage)
        object.__setattr__(
            self,
            "provider_name",
            f"local-minimax-h3-comfy.{attempt_stage}",
        )

    @property
    def workflow(self) -> dict[str, Any]:
        value = json.loads(self._workflow_json)
        if not isinstance(value, dict):  # pragma: no cover - guarded in __init__
            raise H3AmdRuntimeError("H3 Comfy workflow snapshot is invalid")
        return value

    def _validate_request(self, request: Mapping[str, Any]) -> None:
        if not isinstance(request, Mapping):
            raise H3AmdRuntimeError("H3 provider request must be an object")
        if set(request) != {"workflow_digest", "submission_nonce"}:
            raise H3AmdRuntimeError("H3 provider request fields are not pinned")
        if request.get("workflow_digest") != self.workflow_digest:
            raise H3AmdRuntimeError("H3 request workflow_digest does not match transport")
        if request.get("submission_nonce") != self.submission_nonce:
            raise H3AmdRuntimeError("H3 request submission nonce does not match transport")

    @staticmethod
    def _validate_client_token(value: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) < 16
            or len(value) > 200
            or any(character.isspace() or ord(character) < 33 for character in value)
        ):
            raise H3AmdRuntimeError("H3 durable client token is unsafe")
        return value

    @staticmethod
    def _validate_prompt_id(value: object) -> str:
        if (
            not isinstance(value, str)
            or len(value) < 8
            or len(value) > 200
            or not _SAFE_SEGMENT_RE.fullmatch(value)
            or any(character.isspace() or ord(character) < 33 for character in value)
        ):
            raise H3AmdRuntimeError("Comfy returned an unsafe prompt id")
        return value

    def submit(
        self,
        request: Mapping[str, Any],
        *,
        client_token: str,
    ) -> str:
        self._validate_request(request)
        token = self._validate_client_token(client_token)
        prompt_id = self.comfy.submit(
            self.workflow,
            client_id=token,
            extra_data={
                "provider": self.provider_name,
                "submission_nonce": self.submission_nonce,
                "workflow_digest": self.workflow_digest,
            },
        )
        return self._validate_prompt_id(prompt_id)

    def query(
        self,
        *,
        client_token: str,
        provider_task_id: str | None,
    ) -> ProviderObservation:
        token = self._validate_client_token(client_token)
        if provider_task_id is None:
            found = self.comfy.find_submission(
                client_id=token,
                submission_nonce=self.submission_nonce,
                required_extra_data={
                    "provider": self.provider_name,
                    "workflow_digest": self.workflow_digest,
                },
            )
            if found is None:
                return ProviderObservation(state=ProviderObservationState.ABSENT)
            prompt_id = self._validate_prompt_id(found)
        else:
            prompt_id = self._validate_prompt_id(provider_task_id)
        observed = self.comfy.observe(prompt_id)
        if (
            not isinstance(observed, tuple)
            or len(observed) != 2
            or not isinstance(observed[0], ComfyObservation)
            or not isinstance(observed[1], Mapping)
        ):
            raise H3AmdRuntimeError("Comfy returned an invalid H3 observation")
        state, detail = observed
        mapped = {
            ComfyObservation.QUEUED: ProviderObservationState.PENDING,
            ComfyObservation.RUNNING: ProviderObservationState.RUNNING,
            ComfyObservation.SUCCESS: ProviderObservationState.SUCCEEDED,
            ComfyObservation.ERROR: ProviderObservationState.FAILED,
            ComfyObservation.CANCELLED: ProviderObservationState.CANCELLED,
            ComfyObservation.LOST: ProviderObservationState.UNKNOWN,
        }[state]
        result = None
        if mapped in {
            ProviderObservationState.SUCCEEDED,
            ProviderObservationState.FAILED,
            ProviderObservationState.CANCELLED,
        }:
            try:
                observation_digest = _stable_digest(dict(detail))
            except (TypeError, ValueError) as exc:
                raise H3AmdRuntimeError(
                    "Comfy returned an invalid H3 observation detail"
                ) from exc
            result = {
                "prompt_id": prompt_id,
                "observation_digest": observation_digest,
            }
        return ProviderObservation(
            state=mapped,
            provider_task_id=prompt_id,
            result=result,
        )


__all__ = [
    "AmdDeviceIdentity",
    "H3AmdRuntimeConfig",
    "H3AmdRuntimeError",
    "H3DurableComfyTransport",
    "H3FfprobeBackend",
    "H3MediaProbe",
    "H3MediaProbeBackend",
    "H3OutputVerifier",
    "H3RequestsComfyTransport",
    "H3VerifiedOutput",
    "load_h3_amd_runtime_config",
    "validate_amd_device_identity",
]
