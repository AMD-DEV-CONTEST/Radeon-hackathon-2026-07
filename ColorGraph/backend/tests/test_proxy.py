import subprocess
from pathlib import Path

import numpy as np

from colorgraph.config import settings
from colorgraph.domain.grade_graph import ColorSpace, MediaInfo
from colorgraph.media.probe import probe_media
from colorgraph.media.proxy import (
    BROWSER_PROXY_PRESETS,
    DEFAULT_BROWSER_PROXY_QUALITY,
    _encoder_arguments,
    browser_proxy_filename,
    create_browser_proxy,
    needs_browser_proxy,
    scaled_proxy_dimensions,
)


def _media(*, codec: str, width: int, height: int, fps: float, pixel_format: str) -> MediaInfo:
    return MediaInfo(
        path="source.mov",
        duration_seconds=1,
        width=width,
        height=height,
        fps=fps,
        frame_count=max(1, round(fps)),
        codec=codec,
        pixel_format=pixel_format,
        input_color_space=ColorSpace.BT709_OETF,
    )


def test_proxy_requirement_keeps_small_browser_h264() -> None:
    assert not needs_browser_proxy(
        _media(
            codec="h264",
            width=1280,
            height=720,
            fps=30,
            pixel_format="yuv420p",
        )
    )
    assert needs_browser_proxy(
        _media(
            codec="prores",
            width=3840,
            height=2160,
            fps=59.94,
            pixel_format="yuv422p10le",
        )
    )


def test_1080p_proxy_preset_prioritizes_still_quality() -> None:
    preset = BROWSER_PROXY_PRESETS[DEFAULT_BROWSER_PROXY_QUALITY]

    assert DEFAULT_BROWSER_PROXY_QUALITY == "1080p"
    assert preset.maximum_width == 1920
    assert preset.maximum_height == 1080
    assert preset.target_fps == 30
    assert preset.high_quality
    assert _encoder_arguments("h264_nvenc", high_quality=True) == [
        "-preset",
        "p5",
        "-tune",
        "hq",
        "-cq",
        "17",
        "-b:v",
        "0",
        "-profile:v",
        "high",
    ]
    assert BROWSER_PROXY_PRESETS["1440p"].maximum_width == 2560
    assert BROWSER_PROXY_PRESETS["2160p"].maximum_width == 3840
    assert browser_proxy_filename("2160p", "hevc", 10).endswith(
        "hevc-main10-10bit-bt709-limited.mp4"
    )


def test_proxy_dimensions_never_upscale_source() -> None:
    assert scaled_proxy_dimensions(
        1280,
        720,
        maximum_width=3840,
        maximum_height=2160,
    ) == (1280, 720)
    assert scaled_proxy_dimensions(
        4096,
        2160,
        maximum_width=3840,
        maximum_height=2160,
    ) == (3840, 2024)


def test_create_browser_proxy_is_h264_mp4(tmp_path) -> None:
    source = Path(__file__).parents[1] / "data" / "test" / "synthetic_landscape.mp4"
    media = probe_media(source)
    forced_media = media.model_copy(update={"codec": "prores"})
    destination = tmp_path / "browser-proxy.mp4"

    result = create_browser_proxy(
        source,
        destination,
        forced_media,
        preferred_encoder="libx264",
        maximum_width=320,
        target_fps=5,
    )
    proxy_media = probe_media(destination)

    assert result.created
    assert result.encoder == "libx264"
    assert result.codec == "h264"
    assert result.bit_depth == 8
    assert proxy_media.codec == "h264"
    assert proxy_media.width == 320
    assert proxy_media.fps == 5
    assert proxy_media.color_range == "limited"
    assert proxy_media.color_primaries == "bt709"

    cached = create_browser_proxy(
        source,
        destination,
        forced_media,
        preferred_encoder="libx264",
        maximum_width=320,
        target_fps=5,
    )
    assert cached.created
    assert cached.encoder == "cached"
    assert cached.path == destination.resolve()


def test_create_browser_proxy_supports_hevc_main10_with_color_tags(tmp_path) -> None:
    source = Path(__file__).parents[1] / "data" / "test" / "synthetic_landscape.mp4"
    media = probe_media(source)
    forced_media = media.model_copy(update={"codec": "prores"})
    destination = tmp_path / "browser-proxy-hevc-main10.mp4"

    result = create_browser_proxy(
        source,
        destination,
        forced_media,
        preferred_encoder="libx265",
        maximum_width=320,
        maximum_height=180,
        target_fps=5,
        high_quality=True,
        codec="hevc",
        bit_depth=10,
    )
    proxy_media = probe_media(destination)

    assert result.created
    assert result.encoder == "libx265"
    assert result.codec == "hevc"
    assert result.codec_profile == "main10"
    assert result.bit_depth == 10
    assert proxy_media.codec == "hevc"
    assert proxy_media.pixel_format == "yuv420p10le"
    assert proxy_media.bit_depth == 10
    assert proxy_media.width == 320
    assert proxy_media.height == 180
    assert proxy_media.color_range == "limited"
    assert proxy_media.color_primaries == "bt709"
    assert proxy_media.color_transfer == "bt709"
    assert proxy_media.color_matrix == "bt709"

    cached = create_browser_proxy(
        source,
        destination,
        forced_media,
        preferred_encoder="libx265",
        maximum_width=320,
        maximum_height=180,
        target_fps=5,
        high_quality=True,
        codec="hevc",
        bit_depth=10,
    )
    assert cached.encoder == "cached"
    assert cached.cache_key == result.cache_key


def test_main10_ramp_has_no_additional_banding_over_8_bit_proxy(tmp_path) -> None:
    source = tmp_path / "ramp-source.mkv"
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
            (
                "nullsrc=s=1024x64:d=0.2:r=5,format=yuv420p10le,"
                "geq=lum='64+876*X/(W-1)':cb='512':cr='512'"
            ),
            "-c:v",
            "ffv1",
            str(source),
        ],
        check=True,
    )
    media = probe_media(source)
    proxy_8 = tmp_path / "ramp-8.mp4"
    proxy_10 = tmp_path / "ramp-10.mp4"
    create_browser_proxy(
        source,
        proxy_8,
        media,
        preferred_encoder="libx264",
        maximum_width=1024,
        maximum_height=64,
        target_fps=5,
        high_quality=True,
        codec="h264",
        bit_depth=8,
    )
    create_browser_proxy(
        source,
        proxy_10,
        media,
        preferred_encoder="libx265",
        maximum_width=1024,
        maximum_height=64,
        target_fps=5,
        high_quality=True,
        codec="hevc",
        bit_depth=10,
    )

    def decoded_ramp(path: Path) -> np.ndarray:
        raw = subprocess.run(
            [
                settings.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray16le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout
        return np.frombuffer(raw, dtype="<u2").reshape(64, 1024)[32].astype(np.int32)

    ramp_8 = decoded_ramp(proxy_8)
    ramp_10 = decoded_ramp(proxy_10)
    assert len(np.unique(ramp_10)) > len(np.unique(ramp_8))
    assert np.max(np.diff(ramp_10)) < np.max(np.diff(ramp_8))
