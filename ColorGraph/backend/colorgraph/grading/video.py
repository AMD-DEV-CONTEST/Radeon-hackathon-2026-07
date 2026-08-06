from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from bisect import bisect_left
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import numpy as np
import torch

from colorgraph.config import settings
from colorgraph.devices.base import ComputeBackend
from colorgraph.domain.grade_graph import GradeGraph
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.masks import GraphMaskResolver
from colorgraph.grading.precision import (
    MASTER_PRECISION_BUDGET,
    PREVIEW_PRECISION_BUDGET,
)
from colorgraph.media.probe import VideoFrameTiming, probe_frame_timings, probe_media

_DECODE_PIXEL_FORMAT = "rgb48le"
_DECODE_SAMPLE_MAX = float((1 << MASTER_PRECISION_BUDGET.minimum_decode_bits) - 1)
_PIPE_WRITE_CHUNK_BYTES = 1 << 20
_SUPPORTED_OUTPUT_BIT_DEPTHS = {8, 10}
_HARDWARE_ENCODERS = frozenset(
    {
        "h264_amf",
        "hevc_amf",
        "h264_nvenc",
        "hevc_nvenc",
        "h264_vaapi",
        "hevc_vaapi",
    }
)
_VAAPI_ENCODERS = frozenset({"h264_vaapi", "hevc_vaapi"})
RenderProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class RenderAcceleratorEvidence:
    schema_version: str
    runtime: str
    vendor: str
    device_name: str
    torch_device: str
    hip_version: str | None
    batch_count: int
    all_batches_accelerator_verified: bool
    peak_allocated_memory_mb: float | None
    peak_reserved_memory_mb: float | None
    batch_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class VideoRenderResult:
    output_path: str
    frame_count: int
    elapsed_seconds: float
    processing_fps: float
    encoder: str
    codec: str
    pixel_format: str
    bit_depth: int
    decode_pixel_format: str
    encode_input_pixel_format: str
    compute_precision: str
    precision_budget: str
    meets_master_precision: bool
    timing_mode: str
    source_start_time_seconds: float
    max_timestamp_error_seconds: float
    device_runtime: str
    device_name: str
    encoder_hardware_accelerated: bool
    encoder_available_verified: bool
    accelerator_evidence: RenderAcceleratorEvidence


def _validate_bit_depth(bit_depth: int) -> None:
    if bit_depth not in _SUPPORTED_OUTPUT_BIT_DEPTHS:
        raise ValueError("output bit depth must be 8 or 10")


@lru_cache(maxsize=8)
def ffmpeg_encoder_names(binary: str) -> frozenset[str]:
    try:
        result = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return frozenset()
    if result.returncode:
        return frozenset()
    names: set[str] = set()
    for line in result.stdout.splitlines():
        # Newer FFmpeg builds may add flags such as D (direct rendering) to
        # the six capability columns.
        match = re.match(r"^\s*[A-Z\.]{6}\s+(\S+)", line)
        if match is not None:
            names.add(match.group(1))
    return frozenset(names)


def _vaapi_device_path() -> str | None:
    override = os.getenv("COLORGRAPH_VAAPI_DEVICE", "").strip()
    if override:
        return str(Path(override).expanduser())
    render_nodes = sorted(Path("/dev/dri").glob("renderD*"))
    if len(render_nodes) == 1:
        return str(render_nodes[0])
    return None


@lru_cache(maxsize=16)
def ffmpeg_encoder_available(
    binary: str,
    encoder: str,
    bit_depth: int,
    vaapi_device: str | None = None,
) -> bool:
    """Preflight a selected encoder, including a real VAAPI device init."""

    if encoder not in ffmpeg_encoder_names(binary):
        return False
    if encoder not in _VAAPI_ENCODERS:
        return True
    if not vaapi_device:
        return False
    device = Path(vaapi_device)
    if not device.exists() or not os.access(device, os.R_OK | os.W_OK):
        return False
    pixel_format = "p010le" if bit_depth == 10 else "nv12"
    try:
        completed = subprocess.run(
            [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-vaapi_device",
                str(device),
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=256x256:r=1:d=0.04",
                "-vf",
                f"format={pixel_format},hwupload",
                "-frames:v",
                "1",
                "-an",
                "-c:v",
                encoder,
                *_encoder_arguments(encoder, bit_depth),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _encoder_arguments(encoder: str, bit_depth: int) -> list[str]:
    if bit_depth == 10:
        if encoder == "hevc_nvenc":
            return [
                "-preset",
                "p5",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                "18",
                "-b:v",
                "0",
                "-profile:v",
                "main10",
            ]
        if encoder == "hevc_amf":
            return [
                "-quality",
                "balanced",
                "-rc",
                "cqp",
                "-qp_i",
                "18",
                "-qp_p",
                "20",
                "-profile:v",
                "main10",
            ]
        if encoder == "hevc_vaapi":
            return ["-profile:v", "main10", "-qp", "18"]
        if encoder == "libx265":
            return ["-preset", "medium", "-crf", "18", "-profile:v", "main10"]
        return []
    if encoder == "h264_nvenc":
        return ["-preset", "p4", "-tune", "hq", "-cq", "19", "-b:v", "0"]
    if encoder == "h264_amf":
        return ["-quality", "balanced", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20"]
    if encoder == "h264_vaapi":
        return ["-profile:v", "high", "-qp", "20"]
    if encoder == "libx264":
        return ["-preset", "medium", "-crf", "18"]
    return []


def select_encoder(
    backend: ComputeBackend,
    *,
    bit_depth: int = 8,
    require_hardware: bool = False,
    verify_available: bool = False,
) -> tuple[str, list[str]]:
    _validate_bit_depth(bit_depth)
    override = os.getenv(
        "COLORGRAPH_VIDEO_ENCODER_10BIT" if bit_depth == 10 else "COLORGRAPH_VIDEO_ENCODER"
    )
    if override:
        encoder = override
    else:
        runtime = backend.info.runtime
        if bit_depth == 10:
            if runtime == "cuda":
                encoder = "hevc_nvenc"
            elif runtime == "rocm" and os.name == "nt":
                encoder = "hevc_amf"
            elif runtime == "rocm" and os.name == "posix":
                encoder = "hevc_vaapi"
            else:
                encoder = "libx265"
        elif runtime == "cuda":
            encoder = "h264_nvenc"
        elif runtime == "rocm" and os.name == "nt":
            encoder = "h264_amf"
        elif runtime == "rocm" and os.name == "posix":
            encoder = "h264_vaapi"
        else:
            encoder = "libx264"
    if require_hardware and encoder not in _HARDWARE_ENCODERS:
        raise RuntimeError(
            f"hardware video encoding is required, but {encoder!r} is software"
        )
    vaapi_device = _vaapi_device_path() if encoder in _VAAPI_ENCODERS else None
    if verify_available and not ffmpeg_encoder_available(
        settings.ffmpeg_binary,
        encoder,
        bit_depth,
        vaapi_device,
    ):
        raise RuntimeError(
            f"FFmpeg could not initialize the selected encoder {encoder!r}"
        )
    return encoder, _encoder_arguments(encoder, bit_depth)


def _encoder_pixel_format(encoder: str, bit_depth: int) -> str:
    if bit_depth == 8:
        return "nv12" if encoder in _VAAPI_ENCODERS else "yuv420p"
    if encoder in {"hevc_nvenc", "hevc_amf", "hevc_vaapi"}:
        return "p010le"
    return "yuv420p10le"


def _is_hevc_encoder(encoder: str) -> bool:
    return encoder in {"hevc_nvenc", "hevc_amf", "hevc_vaapi", "libx265"}


def _scaled_preview_dimensions(
    width: int,
    height: int,
    maximum_width: int | None,
    maximum_height: int | None = None,
) -> tuple[int, int]:
    if maximum_width is None and maximum_height is None:
        return width, height
    if maximum_width is not None and maximum_width < 2:
        raise ValueError("maximum width must be at least two pixels")
    if maximum_height is not None and maximum_height < 2:
        raise ValueError("maximum height must be at least two pixels")
    width_scale = maximum_width / max(width, 1) if maximum_width is not None else 1.0
    height_scale = (
        maximum_height / max(height, 1) if maximum_height is not None else 1.0
    )
    scale = min(1.0, width_scale, height_scale)
    scaled_width = max(2, int(width * scale) // 2 * 2)
    scaled_height = max(2, int(height * scale) // 2 * 2)
    return scaled_width, scaled_height


def _nearest_timestamp_index(timestamps: list[float], timestamp: float) -> int:
    position = bisect_left(timestamps, timestamp)
    if position <= 0:
        return 0
    if position >= len(timestamps):
        return len(timestamps) - 1
    before = timestamps[position - 1]
    after = timestamps[position]
    return position - 1 if timestamp - before <= after - timestamp else position


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if remaining == size:
                return None
            received = size - remaining
            raise RuntimeError(
                f"FFmpeg decoder returned a partial raw frame ({received}/{size} bytes)"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_all(stream: BinaryIO, payload: bytes) -> None:
    """Write a large raw-video payload without exceeding Windows pipe limits."""

    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        end = min(offset + _PIPE_WRITE_CHUNK_BYTES, len(view))
        written = stream.write(view[offset:end])
        if written is None:
            written = end - offset
        if written <= 0:
            raise BrokenPipeError("FFmpeg encoder pipe stopped accepting raw video")
        offset += written


def _tensor_to_raw_bytes(output: torch.Tensor, bit_depth: int) -> bytes:
    _validate_bit_depth(bit_depth)
    maximum = 65535 if bit_depth == 10 else 255
    dtype = torch.uint16 if bit_depth == 10 else torch.uint8
    quantized = output.detach().mul(maximum).round().clamp(0, maximum).to(dtype)
    array = quantized.permute(0, 2, 3, 1).contiguous().cpu().numpy()
    if bit_depth == 10:
        array = array.astype("<u2", copy=False)
    return array.tobytes()


def _relative_timestamps(timings: list[VideoFrameTiming]) -> list[float]:
    start = timings[0].pts_seconds
    return [timing.pts_seconds - start for timing in timings]


def _is_variable_frame_rate(timestamps: list[float]) -> bool:
    if len(timestamps) < 3:
        return False
    intervals = np.diff(np.asarray(timestamps, dtype=np.float64))
    median = float(np.median(intervals))
    tolerance = max(1e-6, abs(median) * 1e-3)
    return bool(np.max(np.abs(intervals - median)) > tolerance)


def _ffconcat_quote(path: Path) -> str:
    resolved = path.resolve()
    value = (resolved.as_posix() if os.name == "nt" else resolved.as_uri()).replace(
        "'", "'\\''"
    )
    return f"'{value}'"


def _ffconcat_manifest(frame_paths: list[Path], timestamps: list[float]) -> bytes:
    if len(frame_paths) != len(timestamps) or not frame_paths:
        raise ValueError("VFR frame paths and timestamps must have the same non-zero length")
    lines = ["ffconcat version 1.0"]
    for index, frame_path in enumerate(frame_paths):
        lines.append(f"file {_ffconcat_quote(frame_path)}")
        if index + 1 < len(timestamps):
            duration = timestamps[index + 1] - timestamps[index]
            if duration <= 0:
                raise ValueError("VFR timestamps must be strictly increasing")
            lines.append(f"duration {duration:.12f}")
    return ("\n".join(lines) + "\n").encode()


def _write_ppm_batch(
    output: torch.Tensor,
    directory: Path,
    start_index: int,
) -> list[Path]:
    quantized = output.detach().mul(65535).round().clamp(0, 65535).to(torch.uint16)
    frames = quantized.permute(0, 2, 3, 1).contiguous().cpu().numpy()
    height, width = frames.shape[1:3]
    header = f"P6\n{width} {height}\n65535\n".encode()
    paths: list[Path] = []
    for offset, frame in enumerate(frames):
        path = directory / f"frame-{start_index + offset:09d}.ppm"
        path.write_bytes(header + frame.astype(">u2", copy=False).tobytes())
        paths.append(path)
    return paths


def _verify_timestamp_roundtrip(
    source_timestamps: list[float],
    rendered_timings: list[VideoFrameTiming],
) -> float:
    rendered_timestamps = _relative_timestamps(rendered_timings)
    if len(rendered_timestamps) != len(source_timestamps):
        raise RuntimeError(
            "rendered frame count does not preserve source timing: "
            f"{len(rendered_timestamps)} != {len(source_timestamps)}"
        )
    maximum_error = max(
        abs(expected - actual)
        for expected, actual in zip(source_timestamps, rendered_timestamps, strict=True)
    )
    tolerance = MASTER_PRECISION_BUDGET.maximum_timestamp_error_seconds
    if maximum_error > tolerance:
        raise RuntimeError(
            "rendered presentation timestamps exceed tolerance: "
            f"{maximum_error:.9f}s > {tolerance:.9f}s"
        )
    return maximum_error


def _stop_process(process: subprocess.Popen[bytes] | None) -> str:
    if process is None:
        return ""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    stderr = process.stderr.read() if process.stderr else b""
    return stderr.decode("utf-8", errors="replace").strip()


class VideoRenderer:
    def __init__(self, backend: ComputeBackend) -> None:
        self.backend = backend
        self.engine = GradeRenderEngine(backend)

    def render(
        self,
        source: str | Path,
        destination: str | Path,
        graph: GradeGraph,
        *,
        batch_size: int = 4,
        bit_depth: int = 10,
        progress: RenderProgressCallback | None = None,
        validated_source_timings: list[VideoFrameTiming] | None = None,
        maximum_width: int | None = None,
        maximum_height: int | None = None,
        target_fps: float | None = None,
        start_time_seconds: float | None = None,
        end_time_seconds: float | None = None,
        include_audio: bool = True,
        verify_mask_storage: bool = True,
        require_hardware_encoder: bool = False,
    ) -> VideoRenderResult:
        _validate_bit_depth(bit_depth)
        if batch_size < 1:
            raise ValueError("batch size must be at least one")
        source_path = Path(source).resolve()
        output_path = Path(destination).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        media = probe_media(source_path)
        if target_fps is not None and target_fps <= 0:
            raise ValueError("target frame rate must be positive")
        segmented_render = start_time_seconds is not None or end_time_seconds is not None
        render_start = 0.0 if start_time_seconds is None else float(start_time_seconds)
        render_end = (
            media.duration_seconds
            if end_time_seconds is None
            else min(float(end_time_seconds), media.duration_seconds)
        )
        if render_start < 0 or render_start >= media.duration_seconds:
            raise ValueError("render start time must be inside the source duration")
        if render_end <= render_start:
            raise ValueError("render end time must be greater than render start time")
        render_duration = render_end - render_start
        frame_timings = (
            list(validated_source_timings)
            if validated_source_timings is not None
            else ([] if segmented_render else probe_frame_timings(source_path))
        )
        if validated_source_timings is not None and len(frame_timings) != media.frame_count:
            raise ValueError(
                "validated source timing count does not match probed frame count: "
                f"{len(frame_timings)} != {media.frame_count}"
            )
        if not segmented_render and not frame_timings:
            raise ValueError("source timings cannot be empty")
        source_timestamps = (
            _relative_timestamps(frame_timings) if frame_timings else []
        )
        if any(
            current <= previous
            for previous, current in zip(
                source_timestamps,
                source_timestamps[1:],
                strict=False,
            )
        ):
            raise ValueError("validated source timings must be strictly increasing")
        downsample_fps = (
            target_fps
            if target_fps is not None and target_fps < media.fps - 0.05
            else None
        )
        segment_fps = (
            min(target_fps or media.fps, media.fps) if segmented_render else None
        )
        constant_output_fps = segment_fps or downsample_fps
        variable_frame_rate = (
            False
            if constant_output_fps is not None
            else _is_variable_frame_rate(source_timestamps)
        )
        width, height = _scaled_preview_dimensions(
            media.width,
            media.height,
            maximum_width,
            maximum_height,
        )
        fps = constant_output_fps or media.fps
        progress_total = (
            max(1, round(render_duration * fps))
            if constant_output_fps is not None
            else len(source_timestamps)
        )
        frame_bytes = width * height * 3 * 2

        encoder, encoder_arguments = select_encoder(
            self.backend,
            bit_depth=bit_depth,
            require_hardware=require_hardware_encoder,
            verify_available=require_hardware_encoder,
        )
        encoder_pixel_format = _encoder_pixel_format(encoder, bit_depth)
        temporary_path = output_path.with_name(
            f"{output_path.stem}.{uuid4().hex}.rendering{output_path.suffix}"
        )
        scale_filter = (
            "scale=in_range=full:out_range=limited:out_color_matrix=bt709:"
            "flags=accurate_rnd+full_chroma_int:sws_dither=ed,"
            f"format={encoder_pixel_format},"
            "setparams=range=limited:color_primaries=bt709:"
            "color_trc=bt709:colorspace=bt709"
        )
        vaapi_device = _vaapi_device_path() if encoder in _VAAPI_ENCODERS else None
        if encoder in _VAAPI_ENCODERS:
            if not vaapi_device:
                raise RuntimeError(
                    "VAAPI encoding requires COLORGRAPH_VAAPI_DEVICE when zero or "
                    "multiple render nodes are visible"
                )
            scale_filter += ",hwupload"
        decoder_command = [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if segmented_render and render_start > 0:
            decoder_command.extend(["-ss", f"{render_start:.9f}"])
        decoder_command.extend(
            [
            "-i",
            str(source_path),
            ]
        )
        if segmented_render:
            decoder_command.extend(["-t", f"{render_duration:.9f}"])
        decoder_command.extend(
            [
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            ]
        )
        decoder_filters: list[str] = []
        if segmented_render:
            decoder_filters.append("setpts=PTS-STARTPTS")
        if constant_output_fps is not None:
            decoder_filters.append(f"fps={constant_output_fps:.8f}")
        if (width, height) != (media.width, media.height):
            decoder_filters.append(f"scale={width}:{height}:flags=lanczos")
        if decoder_filters:
            decoder_command.extend(
                [
                    "-vf",
                    ",".join(decoder_filters),
                ]
            )
        decoder_command.extend(
            [
                "-fps_mode",
                "passthrough",
                "-f",
                "rawvideo",
                "-pix_fmt",
                _DECODE_PIXEL_FORMAT,
                "pipe:1",
            ]
        )
        if variable_frame_rate:
            primary_input = [
                "-f",
                "concat",
                "-safe",
                "0",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                "pipe:0",
            ]
        else:
            primary_input = [
                "-f",
                "rawvideo",
                "-pixel_format",
                _DECODE_PIXEL_FORMAT,
                "-video_size",
                f"{width}x{height}",
                "-framerate",
                f"{fps:.8f}",
                "-i",
                "pipe:0",
            ]
        encoder_command = [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
        ]
        if vaapi_device:
            encoder_command.extend(["-vaapi_device", vaapi_device])
        encoder_command.extend(primary_input)
        if include_audio:
            encoder_command.extend(["-i", str(source_path)])
        encoder_command.extend(["-map", "0:v:0"])
        if include_audio:
            encoder_command.extend(
                [
                    "-map",
                    "1:a?",
                    "-map_metadata",
                    "1",
                    "-map_chapters",
                    "1",
                ]
            )
        encoder_command.extend(
            [
            "-c:v",
            encoder,
            *encoder_arguments,
            "-vf",
            scale_filter,
            "-fps_mode",
            "passthrough",
            "-color_range",
            "tv",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-movflags",
            "+faststart",
            ]
        )
        if include_audio:
            encoder_command.extend(["-c:a", "aac", "-b:a", "192k"])
        if _is_hevc_encoder(encoder):
            encoder_command.extend(["-tag:v", "hvc1"])
        encoder_command.append(str(temporary_path))

        decoder_process: subprocess.Popen[bytes] | None = None
        encoder_process: subprocess.Popen[bytes] | None = None
        staging_directory = (
            tempfile.TemporaryDirectory(
                prefix=f".{output_path.stem}.vfr-",
                dir=output_path.parent,
            )
            if variable_frame_rate
            else None
        )
        staging_path = Path(staging_directory.name) if staging_directory is not None else None
        staged_frame_paths: list[Path] = []
        max_timestamp_error = 0.0
        started = time.perf_counter()
        frame_index = 0
        batch_frames: list[np.ndarray] = []
        batch_frame_indices: list[int] = []
        batch_timestamps: list[float] = []
        rendered_timestamps: list[float] = []
        render_batch_count = 0
        all_batches_accelerator_verified = True
        evidence_digest = hashlib.sha256()
        peak_allocated_bytes: int | None = None
        peak_reserved_bytes: int | None = None
        mask_resolver = GraphMaskResolver(
            graph,
            verify_storage=verify_mask_storage,
        )
        if progress is not None:
            progress(0, progress_total)

        try:
            decoder_process = subprocess.Popen(
                decoder_command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if not variable_frame_rate:
                encoder_process = subprocess.Popen(
                    encoder_command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            if decoder_process.stdout is None:
                raise RuntimeError("failed to open FFmpeg decode pipe")
            if not variable_frame_rate and (
                encoder_process is None or encoder_process.stdin is None
            ):
                raise RuntimeError("failed to open FFmpeg encode pipe")

            def flush_batch() -> None:
                nonlocal batch_frames
                nonlocal batch_frame_indices
                nonlocal batch_timestamps
                nonlocal render_batch_count
                nonlocal all_batches_accelerator_verified
                nonlocal peak_allocated_bytes
                nonlocal peak_reserved_bytes
                if not batch_frames:
                    return
                frames = batch_frames
                frame_indices = batch_frame_indices
                timestamps = batch_timestamps
                batch_frames = []
                batch_frame_indices = []
                batch_timestamps = []

                array = np.stack(frames)
                tensor = (
                    torch.from_numpy(array)
                    .permute(0, 3, 1, 2)
                    .to(dtype=torch.float32)
                    .div_(_DECODE_SAMPLE_MAX)
                )
                masks = (
                    mask_resolver.load_batch(
                        frame_indices,
                        device=self.engine.backend.torch_device,
                    )
                    if mask_resolver.assets
                    else None
                )
                output, _ = self.engine.render_output_batch(
                    tensor,
                    graph,
                    timestamps=timestamps,
                    masks=masks,
                    mixed_precision=MASTER_PRECISION_BUDGET.mixed_precision_allowed,
                )
                stage_evidence = self.engine.last_output_evidence
                if stage_evidence is None:
                    raise RuntimeError("grade renderer did not emit device evidence")
                render_batch_count += 1
                all_batches_accelerator_verified = (
                    all_batches_accelerator_verified
                    and stage_evidence.accelerator_tensors_verified
                )
                if stage_evidence.peak_allocated_bytes is not None:
                    peak_allocated_bytes = max(
                        peak_allocated_bytes or 0,
                        stage_evidence.peak_allocated_bytes,
                    )
                if stage_evidence.peak_reserved_bytes is not None:
                    peak_reserved_bytes = max(
                        peak_reserved_bytes or 0,
                        stage_evidence.peak_reserved_bytes,
                    )
                evidence_digest.update(
                    json.dumps(
                        stage_evidence.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                if variable_frame_rate:
                    if staging_path is None:
                        raise RuntimeError("VFR staging directory is unavailable")
                    staged_frame_paths.extend(
                        _write_ppm_batch(output, staging_path, len(staged_frame_paths))
                    )
                else:
                    if encoder_process is None or encoder_process.stdin is None:
                        raise RuntimeError("FFmpeg encode pipe closed before render completed")
                    # The formal render pipe remains 16-bit even for an optional
                    # 8-bit deliverable; FFmpeg performs the final dithered reduction.
                    _write_all(
                        encoder_process.stdin,
                        _tensor_to_raw_bytes(output, 10),
                    )
                if progress is not None:
                    progress(frame_index, progress_total)

            while True:
                raw_frame = _read_exact(decoder_process.stdout, frame_bytes)
                if raw_frame is None:
                    break
                if constant_output_fps is None and frame_index >= len(source_timestamps):
                    raise RuntimeError(
                        "decoded more video frames than ffprobe reported presentation timestamps"
                    )
                frame = np.frombuffer(raw_frame, dtype="<u2").reshape(height, width, 3)
                output_timestamp = (
                    frame_index / constant_output_fps
                    if constant_output_fps is not None
                    else source_timestamps[frame_index]
                )
                graph_timestamp = (
                    render_start + output_timestamp
                    if segmented_render
                    else output_timestamp
                )
                source_frame_index = (
                    min(
                        max(0, round(graph_timestamp * media.fps)),
                        max(0, media.frame_count - 1),
                    )
                    if segmented_render
                    else (
                        _nearest_timestamp_index(source_timestamps, graph_timestamp)
                        if constant_output_fps is not None
                        else frame_index
                    )
                )
                batch_frames.append(frame)
                batch_frame_indices.append(source_frame_index)
                batch_timestamps.append(graph_timestamp)
                rendered_timestamps.append(output_timestamp)
                frame_index += 1
                if len(batch_frames) >= batch_size:
                    flush_batch()
            flush_batch()

            decoder_process.stdout.close()
            decoder_stderr = decoder_process.stderr.read() if decoder_process.stderr else b""
            decoder_return_code = decoder_process.wait()
            if decoder_return_code:
                raise RuntimeError(
                    f"FFmpeg decoder failed ({decoder_return_code}): "
                    f"{decoder_stderr.decode('utf-8', errors='replace').strip()}"
                )
            if constant_output_fps is None and frame_index != len(source_timestamps):
                raise RuntimeError(
                    "decoded frame count does not match ffprobe presentation timestamps: "
                    f"{frame_index} != {len(source_timestamps)}"
                )

            if variable_frame_rate:
                manifest = _ffconcat_manifest(staged_frame_paths, rendered_timestamps)
                encoder_result = subprocess.run(
                    encoder_command,
                    input=manifest,
                    capture_output=True,
                    check=False,
                )
                if encoder_result.returncode:
                    encoder_stderr = encoder_result.stderr.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()
                    raise RuntimeError(
                        f"FFmpeg VFR encoder failed ({encoder_result.returncode}): {encoder_stderr}"
                    )
            else:
                if encoder_process is None or encoder_process.stdin is None:
                    raise RuntimeError("FFmpeg encoder is unavailable")
                encoder_process.stdin.close()
                encoder_stderr = encoder_process.stderr.read() if encoder_process.stderr else b""
                encoder_return_code = encoder_process.wait()
                if encoder_return_code:
                    raise RuntimeError(
                        f"FFmpeg encoder failed ({encoder_return_code}): "
                        f"{encoder_stderr.decode('utf-8', errors='replace').strip()}"
                    )

            rendered_timings = probe_frame_timings(temporary_path)
            max_timestamp_error = _verify_timestamp_roundtrip(
                rendered_timestamps,
                rendered_timings,
            )
            temporary_path.replace(output_path)
        except FileNotFoundError as exc:
            _stop_process(decoder_process)
            _stop_process(encoder_process)
            temporary_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg is unavailable: {settings.ffmpeg_binary}") from exc
        except Exception as exc:
            if encoder_process and encoder_process.stdin:
                with suppress(OSError):
                    encoder_process.stdin.close()
            if decoder_process and decoder_process.stdout:
                decoder_process.stdout.close()
            decoder_error = _stop_process(decoder_process)
            encoder_error = _stop_process(encoder_process)
            temporary_path.unlink(missing_ok=True)
            if isinstance(exc, (BrokenPipeError, OSError)):
                details = encoder_error or decoder_error or str(exc)
                raise RuntimeError(f"FFmpeg render pipe failed: {details}") from exc
            raise
        finally:
            mask_resolver.close()
            if staging_directory is not None:
                staging_directory.cleanup()

        elapsed = max(time.perf_counter() - started, 1e-9)
        rendered_media = probe_media(output_path)
        info = self.backend.info
        precision_budget = MASTER_PRECISION_BUDGET if bit_depth >= 10 else PREVIEW_PRECISION_BUDGET
        accelerator_evidence = RenderAcceleratorEvidence(
            schema_version="colorgraph.render-accelerator-evidence/v1",
            runtime=info.runtime,
            vendor=info.vendor,
            device_name=info.name,
            torch_device=str(self.backend.torch_device),
            hip_version=str(torch.version.hip) if torch.version.hip else None,
            batch_count=render_batch_count,
            all_batches_accelerator_verified=(
                render_batch_count > 0 and all_batches_accelerator_verified
            ),
            peak_allocated_memory_mb=(
                peak_allocated_bytes / 1024**2
                if peak_allocated_bytes is not None
                else None
            ),
            peak_reserved_memory_mb=(
                peak_reserved_bytes / 1024**2
                if peak_reserved_bytes is not None
                else None
            ),
            batch_evidence_sha256=evidence_digest.hexdigest(),
        )
        return VideoRenderResult(
            output_path=str(output_path),
            frame_count=frame_index,
            elapsed_seconds=elapsed,
            processing_fps=frame_index / elapsed,
            encoder=encoder,
            codec=rendered_media.codec,
            pixel_format=rendered_media.pixel_format or encoder_pixel_format,
            bit_depth=bit_depth,
            decode_pixel_format=_DECODE_PIXEL_FORMAT,
            encode_input_pixel_format=_DECODE_PIXEL_FORMAT,
            compute_precision="fp32",
            precision_budget=precision_budget.name,
            meets_master_precision=bit_depth >= MASTER_PRECISION_BUDGET.minimum_output_bits,
            timing_mode="vfr" if variable_frame_rate else "cfr",
            source_start_time_seconds=(
                frame_timings[0].pts_seconds + render_start
                if frame_timings
                else render_start
            ),
            max_timestamp_error_seconds=max_timestamp_error,
            device_runtime=info.runtime,
            device_name=info.name,
            encoder_hardware_accelerated=encoder in _HARDWARE_ENCODERS,
            encoder_available_verified=(
                require_hardware_encoder
                and ffmpeg_encoder_available(
                    settings.ffmpeg_binary,
                    encoder,
                    bit_depth,
                    vaapi_device,
                )
            ),
            accelerator_evidence=accelerator_evidence,
        )


def require_amd_gpu_render(result: VideoRenderResult) -> None:
    evidence = result.accelerator_evidence
    failures: list[str] = []
    if evidence.runtime != "rocm":
        failures.append(f"runtime={evidence.runtime}")
    if evidence.vendor.casefold() != "amd":
        failures.append(f"vendor={evidence.vendor}")
    if evidence.hip_version is None:
        failures.append("torch.version.hip is empty")
    if not evidence.all_batches_accelerator_verified:
        failures.append("one or more grading batches did not prove accelerator tensors")
    if not evidence.peak_allocated_memory_mb:
        failures.append("peak accelerator allocation is empty")
    if result.encoder not in {"h264_amf", "hevc_amf", "h264_vaapi", "hevc_vaapi"}:
        failures.append(f"encoder={result.encoder}")
    if not result.encoder_available_verified:
        failures.append("AMD hardware encoder availability was not preflighted")
    if failures:
        raise RuntimeError("AMD GPU render gate failed: " + "; ".join(failures))
