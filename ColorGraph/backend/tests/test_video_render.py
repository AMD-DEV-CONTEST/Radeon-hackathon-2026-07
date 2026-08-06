import json
import subprocess
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION,
    LINEAR_REC709_RENDERER_VERSION,
    ColorSpace,
    GradeGraph,
    GradeNode,
    MediaInfo,
    NodeType,
    ScopeLevel,
    TemporalScope,
    TimeRange,
)
from colorgraph.grading import video as video_module
from colorgraph.grading.precision import (
    MASTER_PRECISION_BUDGET,
    PREVIEW_PRECISION_BUDGET,
)
from colorgraph.grading.video import (
    RenderAcceleratorEvidence,
    VideoRenderer,
    _ffconcat_manifest,
    _is_variable_frame_rate,
    _nearest_timestamp_index,
    _read_exact,
    _scaled_preview_dimensions,
    _tensor_to_raw_bytes,
    _write_all,
    require_amd_gpu_render,
    select_encoder,
)
from colorgraph.media.metadata import apply_color_management_override
from colorgraph.media.probe import probe_frame_timings, probe_media
from colorgraph.services.graph_builder import build_initial_graph


def _backend(runtime: str) -> SimpleNamespace:
    return SimpleNamespace(info=SimpleNamespace(runtime=runtime))


def test_encoder_selection_keeps_proxy_8_bit_and_uses_main10_for_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COLORGRAPH_VIDEO_ENCODER", raising=False)
    monkeypatch.delenv("COLORGRAPH_VIDEO_ENCODER_10BIT", raising=False)

    proxy_encoder, _ = select_encoder(_backend("cuda"))
    master_encoder, master_arguments = select_encoder(_backend("cuda"), bit_depth=10)
    software_encoder, software_arguments = select_encoder(_backend("cpu"), bit_depth=10)

    assert proxy_encoder == "h264_nvenc"
    assert master_encoder == "hevc_nvenc"
    assert "main10" in master_arguments
    assert software_encoder == "libx265"
    assert "main10" in software_arguments


def test_8_bit_and_10_bit_encoder_overrides_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER", "libx264")
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER_10BIT", "libx265")

    proxy_encoder, _ = select_encoder(_backend("cuda"))
    master_encoder, master_arguments = select_encoder(_backend("cuda"), bit_depth=10)

    assert proxy_encoder == "libx264"
    assert master_encoder == "libx265"
    assert "main10" in master_arguments


def test_vaapi_overrides_are_hardware_encoders_with_main10_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER", "h264_vaapi")
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER_10BIT", "hevc_vaapi")

    proxy_encoder, proxy_arguments = select_encoder(
        _backend("rocm"),
        require_hardware=True,
    )
    master_encoder, master_arguments = select_encoder(
        _backend("rocm"),
        bit_depth=10,
        require_hardware=True,
    )

    assert proxy_encoder == "h264_vaapi"
    assert "high" in proxy_arguments
    assert master_encoder == "hevc_vaapi"
    assert "main10" in master_arguments


def test_10_bit_raw_pipe_keeps_every_code_value() -> None:
    levels = torch.linspace(0, 1, 1024, dtype=torch.float32)
    image = levels.view(1, 1, 1, 1024).expand(1, 3, 1, 1024)

    raw_10_bit = _tensor_to_raw_bytes(image, 10)
    raw_8_bit = _tensor_to_raw_bytes(image, 8)
    values_10_bit = np.frombuffer(raw_10_bit, dtype="<u2").reshape(1, 1, 1024, 3)[0, 0, :, 0]
    values_8_bit = np.frombuffer(raw_8_bit, dtype=np.uint8).reshape(1, 1, 1024, 3)[0, 0, :, 0]
    projected_10_bit_codes = np.rint(values_10_bit.astype(np.float64) / 65535 * 1023).astype(
        np.uint16
    )

    assert len(np.unique(values_10_bit)) == 1024
    assert len(np.unique(projected_10_bit_codes)) == 1024
    assert len(np.unique(values_8_bit)) == 256
    assert values_10_bit[0] == 0
    assert values_10_bit[-1] == 65535


def test_raw_frame_reader_rejects_partial_frame() -> None:
    assert _read_exact(BytesIO(b"abcdef"), 6) == b"abcdef"
    assert _read_exact(BytesIO(), 6) is None
    with pytest.raises(RuntimeError, match="partial raw frame"):
        _read_exact(BytesIO(b"abc"), 6)


class _PartialWriter:
    def __init__(self, maximum_write: int) -> None:
        self.maximum_write = maximum_write
        self.payload = bytearray()
        self.write_sizes: list[int] = []

    def write(self, payload: bytes | memoryview) -> int:
        size = min(len(payload), self.maximum_write)
        self.write_sizes.append(len(payload))
        self.payload.extend(payload[:size])
        return size


def test_write_all_chunks_large_pipe_payload_and_handles_partial_writes() -> None:
    payload = b"x" * ((1 << 20) * 2 + 37)
    writer = _PartialWriter(maximum_write=65537)

    _write_all(writer, payload)

    assert bytes(writer.payload) == payload
    assert max(writer.write_sizes) <= 1 << 20


def test_video_render_rejects_unsupported_output_depth() -> None:
    with pytest.raises(ValueError, match="8 or 10"):
        select_encoder(_backend("cpu"), bit_depth=12)


def test_hardware_encoder_gate_rejects_software_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COLORGRAPH_VIDEO_ENCODER_10BIT", raising=False)

    with pytest.raises(RuntimeError, match="hardware video encoding"):
        select_encoder(
            _backend("cpu"),
            bit_depth=10,
            require_hardware=True,
        )


def test_ffmpeg_encoder_parser_accepts_direct_rendering_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_module.ffmpeg_encoder_names.cache_clear()
    monkeypatch.setattr(
        video_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                "Encoders:\n"
                " V....D h264_amf             AMD AMF H.264 Encoder (codec h264)\n"
                " V..... libx264              libx264 H.264 (codec h264)\n"
            ),
        ),
    )

    names = video_module.ffmpeg_encoder_names("ffmpeg-test")

    assert names == frozenset({"h264_amf", "libx264"})
    video_module.ffmpeg_encoder_names.cache_clear()


def test_amd_render_gate_requires_rocm_tensor_and_hardware_encoder_evidence() -> None:
    passed = SimpleNamespace(
        encoder="hevc_amf",
        encoder_available_verified=True,
        accelerator_evidence=RenderAcceleratorEvidence(
            schema_version="colorgraph.render-accelerator-evidence/v1",
            runtime="rocm",
            vendor="AMD",
            device_name="AMD Radeon RX 7900 XTX",
            torch_device="cuda:0",
            hip_version="7.2.1",
            batch_count=4,
            all_batches_accelerator_verified=True,
            peak_allocated_memory_mb=512,
            peak_reserved_memory_mb=768,
            batch_evidence_sha256="a" * 64,
        ),
    )
    require_amd_gpu_render(passed)

    failed = SimpleNamespace(
        encoder="libx265",
        encoder_available_verified=False,
        accelerator_evidence=passed.accelerator_evidence,
    )
    with pytest.raises(RuntimeError, match="encoder=libx265"):
        require_amd_gpu_render(failed)


def test_preview_scaling_preserves_aspect_and_even_encoder_dimensions() -> None:
    assert _scaled_preview_dimensions(3840, 2160, 1920) == (1920, 1080)
    assert _scaled_preview_dimensions(1921, 1081, 960) == (960, 540)
    assert _scaled_preview_dimensions(1279, 719, 1920) == (1278, 718)
    assert _scaled_preview_dimensions(1279, 719, None) == (1279, 719)


def test_nearest_timestamp_index_tracks_downsampled_frames_to_source() -> None:
    timestamps = [0.0, 0.04, 0.08, 0.12]

    assert _nearest_timestamp_index(timestamps, 0.0) == 0
    assert _nearest_timestamp_index(timestamps, 0.055) == 1
    assert _nearest_timestamp_index(timestamps, 0.065) == 2
    assert _nearest_timestamp_index(timestamps, 1.0) == 3


def test_variable_frame_rate_detection_and_manifest_keep_frame_durations(
    tmp_path: Path,
) -> None:
    paths = [tmp_path / f"frame-{index}.ppm" for index in range(4)]
    timestamps = [0.0, 0.04, 0.12, 0.20]

    manifest = _ffconcat_manifest(paths, timestamps).decode()

    assert _is_variable_frame_rate(timestamps)
    assert not _is_variable_frame_rate([0.0, 0.04, 0.08, 0.12])
    assert "duration 0.040000000000" in manifest
    assert manifest.count("duration 0.080000000000") == 2


def _identity_graph(media: MediaInfo) -> GradeGraph:
    project_id = "vfr-roundtrip"
    scope = TemporalScope(level=ScopeLevel.PROJECT, project_id=project_id)
    return GradeGraph(
        schema_version=LINEAR_REC709_GRADE_GRAPH_SCHEMA_VERSION,
        renderer_version=LINEAR_REC709_RENDERER_VERSION,
        id="graph_vfr_roundtrip",
        project_id=project_id,
        project_name="VFR roundtrip",
        working_color_space=ColorSpace.LINEAR_REC709,
        output_color_space=ColorSpace.BT709_OETF,
        media=media,
        nodes=[
            GradeNode(
                id="input_transform",
                type=NodeType.INPUT_TRANSFORM,
                label="Input transform",
                order=0,
                temporal_scope=scope,
                parameters={
                    "input_space": ColorSpace.BT709_OETF.value,
                    "working_space": ColorSpace.LINEAR_REC709.value,
                },
            ),
            GradeNode(
                id="output_transform",
                type=NodeType.OUTPUT_TRANSFORM,
                label="Output transform",
                order=1,
                temporal_scope=scope,
                parameters={
                    "working_space": ColorSpace.LINEAR_REC709.value,
                    "output_space": ColorSpace.BT709_OETF.value,
                },
            ),
        ],
    )


def _aces_graph(media: MediaInfo) -> GradeGraph:
    graph = build_initial_graph(
        project_id="aces-video",
        project_name="ACES video",
        media=media,
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=media.duration_seconds),
        ],
        representative_frames=[Path("frame.jpg")],
    )
    for node in graph.nodes:
        if node.type not in {NodeType.INPUT_TRANSFORM, NodeType.OUTPUT_TRANSFORM}:
            node.enabled = False
    return graph


def _create_vfr_source(path: Path) -> None:
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=32x24:rate=25:duration=0.16",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.30",
            "-vf",
            (
                r"setpts=if(eq(N\,0)\,0/TB\,"
                r"if(eq(N\,1)\,0.04/TB\,"
                r"if(eq(N\,2)\,0.12/TB\,0.20/TB)))"
            ),
            "-fps_mode",
            "vfr",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "yuv444p10le",
            "-color_range",
            "tv",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _create_cfr_source(path: Path) -> None:
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=32x24:rate=25:duration=0.16",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.16",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "yuv444p10le",
            "-color_range",
            "tv",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_cfr_8bit_delivery_still_uses_16bit_fp32_formal_pipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source-cfr.mkv"
    destination = tmp_path / "rendered-cfr.mp4"
    _create_cfr_source(source)
    media = apply_color_management_override(
        probe_media(source),
        ColorSpace.BT709_OETF,
        None,
    )
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER", "libx264")

    result = VideoRenderer(TorchComputeBackend("cpu")).render(
        source,
        destination,
        _aces_graph(media),
        batch_size=2,
        bit_depth=8,
        maximum_width=16,
        target_fps=12.5,
    )

    rendered_media = probe_media(destination)
    assert result.timing_mode == "cfr"
    assert result.frame_count == 2
    assert result.decode_pixel_format == "rgb48le"
    assert result.encode_input_pixel_format == "rgb48le"
    assert result.compute_precision == "fp32"
    assert result.precision_budget == PREVIEW_PRECISION_BUDGET.name
    assert not result.meets_master_precision
    assert result.max_timestamp_error_seconds <= 5e-4
    assert rendered_media.bit_depth == 8
    assert (rendered_media.width, rendered_media.height) == (16, 12)
    assert rendered_media.fps == pytest.approx(12.5, abs=0.05)
    assert result.accelerator_evidence.batch_count == 1
    assert not result.accelerator_evidence.all_batches_accelerator_verified
    assert len(result.accelerator_evidence.batch_evidence_sha256) == 64


def test_segment_render_starts_at_project_time_and_omits_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source-segment.mkv"
    destination = tmp_path / "rendered-segment.mp4"
    _create_cfr_source(source)
    media = apply_color_management_override(
        probe_media(source),
        ColorSpace.BT709_OETF,
        None,
    )
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER", "libx264")
    renderer = VideoRenderer(TorchComputeBackend("cpu"))
    captured_timestamps: list[float] = []
    probed_timing_paths: list[Path] = []
    mask_storage_verification: list[bool] = []
    render_batch = renderer.engine.render_output_batch
    probe_timings = video_module.probe_frame_timings
    graph_mask_resolver = video_module.GraphMaskResolver

    def capture_timestamps(*args, **kwargs):
        captured_timestamps.extend(kwargs["timestamps"])
        return render_batch(*args, **kwargs)

    def track_timing_probe(path):
        probed_timing_paths.append(Path(path).resolve())
        return probe_timings(path)

    def track_mask_resolver(*args, **kwargs):
        mask_storage_verification.append(kwargs.get("verify_storage", True))
        return graph_mask_resolver(*args, **kwargs)

    monkeypatch.setattr(renderer.engine, "render_output_batch", capture_timestamps)
    monkeypatch.setattr(video_module, "probe_frame_timings", track_timing_probe)
    monkeypatch.setattr(video_module, "GraphMaskResolver", track_mask_resolver)
    result = renderer.render(
        source,
        destination,
        _aces_graph(media),
        batch_size=2,
        bit_depth=8,
        maximum_width=16,
        target_fps=25,
        start_time_seconds=0.04,
        end_time_seconds=0.12,
        include_audio=False,
        verify_mask_storage=False,
    )

    rendered_media = probe_media(destination)
    audio_streams = subprocess.run(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result.frame_count == 2
    assert result.source_start_time_seconds == pytest.approx(0.04, abs=5e-4)
    assert captured_timestamps == pytest.approx([0.04, 0.08], abs=5e-4)
    assert rendered_media.duration_seconds == pytest.approx(0.08, abs=0.01)
    assert audio_streams == ""
    assert source.resolve() not in probed_timing_paths
    assert mask_storage_verification == [False]


def test_vfr_main10_render_round_trips_pts_audio_and_color_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source-vfr.mkv"
    destination = tmp_path / "rendered-vfr.mp4"
    _create_vfr_source(source)
    media = apply_color_management_override(
        probe_media(source),
        ColorSpace.BT709_OETF,
        None,
    )
    monkeypatch.setenv("COLORGRAPH_VIDEO_ENCODER_10BIT", "libx265")

    result = VideoRenderer(TorchComputeBackend("cpu")).render(
        source,
        destination,
        _identity_graph(media),
        batch_size=2,
        bit_depth=10,
    )

    source_timestamps = probe_frame_timings(source)
    output_timestamps = probe_frame_timings(destination)
    source_start = source_timestamps[0].pts_seconds
    output_start = output_timestamps[0].pts_seconds
    assert [timing.pts_seconds - output_start for timing in output_timestamps] == pytest.approx(
        [timing.pts_seconds - source_start for timing in source_timestamps],
        abs=5e-4,
    )
    rendered_media = probe_media(destination)
    assert result.timing_mode == "vfr"
    assert result.frame_count == 4
    assert result.max_timestamp_error_seconds <= 5e-4
    assert result.decode_pixel_format == "rgb48le"
    assert result.encode_input_pixel_format == "rgb48le"
    assert result.compute_precision == "fp32"
    assert result.precision_budget == MASTER_PRECISION_BUDGET.name
    assert result.meets_master_precision
    assert rendered_media.bit_depth == 10
    assert rendered_media.color_range == "limited"
    assert rendered_media.color_primaries == "bt709"
    assert rendered_media.color_transfer == "bt709"
    assert rendered_media.color_matrix == "bt709"

    streams = json.loads(
        subprocess.run(
            [
                settings.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,start_time,duration",
                "-of",
                "json",
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )["streams"]
    assert {stream["codec_type"] for stream in streams} == {"video", "audio"}
    streams_by_type = {stream["codec_type"]: stream for stream in streams}
    video_start = float(streams_by_type["video"].get("start_time", 0))
    audio_start = float(streams_by_type["audio"].get("start_time", 0))
    assert abs(video_start - audio_start) <= 0.05
