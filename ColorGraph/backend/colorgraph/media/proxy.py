from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from colorgraph.config import settings
from colorgraph.domain.grade_graph import MediaInfo
from colorgraph.media.probe import probe_media

BrowserProxyQuality = Literal["540p", "1080p", "1440p", "2160p"]
BrowserProxyCodec = Literal["h264", "hevc"]
PROXY_COLOR_RANGE = "limited"
PROXY_FFMPEG_COLOR_RANGE = "tv"
PROXY_COLOR_PRIMARIES = "bt709"
PROXY_COLOR_TRANSFER = "bt709"
PROXY_COLOR_MATRIX = "bt709"
PROXY_CACHE_SCHEMA = "colorgraph.browser-proxy-cache/v2"


class ProxyCreationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserProxy:
    path: Path
    created: bool
    encoder: str | None
    codec: str | None = None
    codec_profile: str | None = None
    bit_depth: int | None = None
    pixel_format: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    cache_key: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserProxyPreset:
    maximum_width: int
    maximum_height: int
    target_fps: float
    high_quality: bool


BROWSER_PROXY_PRESETS: dict[BrowserProxyQuality, BrowserProxyPreset] = {
    "540p": BrowserProxyPreset(
        maximum_width=960,
        maximum_height=540,
        target_fps=15.0,
        high_quality=False,
    ),
    "1080p": BrowserProxyPreset(
        maximum_width=1920,
        maximum_height=1080,
        target_fps=30.0,
        high_quality=True,
    ),
    "1440p": BrowserProxyPreset(
        maximum_width=2560,
        maximum_height=1440,
        target_fps=30.0,
        high_quality=True,
    ),
    "2160p": BrowserProxyPreset(
        maximum_width=3840,
        maximum_height=2160,
        target_fps=30.0,
        high_quality=True,
    ),
}
DEFAULT_BROWSER_PROXY_QUALITY: BrowserProxyQuality = "1080p"


def validate_proxy_encoding(codec: str, bit_depth: int) -> tuple[BrowserProxyCodec, int]:
    if codec not in {"h264", "hevc"}:
        raise ValueError("preview codec must be h264 or hevc")
    if (codec, bit_depth) not in {("h264", 8), ("hevc", 10)}:
        raise ValueError("H.264 preview must be 8-bit and HEVC preview must be 10-bit")
    return codec, bit_depth  # type: ignore[return-value]


def proxy_codec_profile(codec: str, bit_depth: int) -> str:
    validate_proxy_encoding(codec, bit_depth)
    return "main10" if codec == "hevc" else "high"


def browser_proxy_filename(
    quality: BrowserProxyQuality,
    codec: BrowserProxyCodec,
    bit_depth: int,
) -> str:
    profile = proxy_codec_profile(codec, bit_depth)
    return (
        f"browser-proxy-{quality}-{codec}-{profile}-{bit_depth}bit-"
        f"{PROXY_COLOR_PRIMARIES}-{PROXY_COLOR_RANGE}.mp4"
    )


def scaled_proxy_dimensions(
    width: int,
    height: int,
    *,
    maximum_width: int,
    maximum_height: int,
) -> tuple[int, int]:
    if min(width, height, maximum_width, maximum_height) < 2:
        raise ValueError("preview dimensions must be at least two pixels")
    scale = min(
        1.0,
        maximum_width / max(width, 1),
        maximum_height / max(height, 1),
    )
    scaled_width = max(2, int(width * scale) // 2 * 2)
    scaled_height = max(2, int(height * scale) // 2 * 2)
    return scaled_width, scaled_height


def _media_bit_depth(media: MediaInfo) -> int:
    if media.bit_depth is not None:
        return media.bit_depth
    pixel_format = (media.pixel_format or "").lower()
    return 10 if "10" in pixel_format or "p010" in pixel_format else 8


def needs_browser_proxy(
    media: MediaInfo,
    *,
    codec: BrowserProxyCodec = "h264",
    bit_depth: int = 8,
    maximum_width: int = 1280,
    maximum_height: int = 720,
    target_fps: float = 30.01,
    require_color_tags: bool = False,
) -> bool:
    validate_proxy_encoding(codec, bit_depth)
    target_width, target_height = scaled_proxy_dimensions(
        media.width,
        media.height,
        maximum_width=maximum_width,
        maximum_height=maximum_height,
    )
    expected_codec = "hevc" if codec == "hevc" else "h264"
    pixel_format = (media.pixel_format or "").lower()
    pixel_format_matches = (
        ("10" in pixel_format or "p010" in pixel_format)
        if bit_depth == 10
        else pixel_format.startswith("yuv420p") and "10" not in pixel_format
    )
    color_tags_match = (
        not require_color_tags
        or (
            media.color_range == PROXY_COLOR_RANGE
            and media.color_primaries == PROXY_COLOR_PRIMARIES
            and media.color_transfer == PROXY_COLOR_TRANSFER
            and media.color_matrix == PROXY_COLOR_MATRIX
        )
    )
    return not (
        media.codec == expected_codec
        and media.width == target_width
        and media.height == target_height
        and media.fps <= min(target_fps, media.fps) + 0.05
        and _media_bit_depth(media) == bit_depth
        and pixel_format_matches
        and color_tags_match
    )


def _encoder_arguments(
    encoder: str,
    *,
    high_quality: bool,
    bit_depth: int = 8,
) -> list[str]:
    if bit_depth == 10:
        if encoder == "hevc_nvenc":
            return [
                "-preset",
                "p5" if high_quality else "p3",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                "18" if high_quality else "21",
                "-b:v",
                "0",
                "-profile:v",
                "main10",
            ]
        if encoder == "hevc_amf":
            return [
                "-quality",
                "quality" if high_quality else "balanced",
                "-rc",
                "cqp",
                "-qp_i",
                "18" if high_quality else "21",
                "-qp_p",
                "20" if high_quality else "23",
                "-profile:v",
                "main10",
            ]
        if encoder == "libx265":
            return [
                "-preset",
                "medium" if high_quality else "fast",
                "-crf",
                "18" if high_quality else "21",
                "-profile:v",
                "main10",
            ]
        return []
    if encoder == "h264_nvenc":
        if high_quality:
            return [
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
        return [
            "-preset",
            "p1",
            "-tune",
            "ll",
            "-cq",
            "20",
            "-b:v",
            "0",
            "-profile:v",
            "high",
        ]
    if encoder == "h264_amf":
        if high_quality:
            return [
                "-quality",
                "quality",
                "-rc",
                "cqp",
                "-qp_i",
                "16",
                "-qp_p",
                "18",
                "-profile:v",
                "high",
            ]
        return [
            "-quality",
            "speed",
            "-rc",
            "cqp",
            "-qp_i",
            "18",
            "-qp_p",
            "20",
            "-profile:v",
            "high",
        ]
    if high_quality:
        return ["-preset", "medium", "-crf", "16", "-profile:v", "high"]
    return ["-preset", "veryfast", "-crf", "18", "-profile:v", "high"]


def _proxy_pixel_format(encoder: str, bit_depth: int) -> str:
    if bit_depth == 8:
        return "yuv420p"
    if encoder in {"hevc_nvenc", "hevc_amf"}:
        return "p010le"
    return "yuv420p10le"


def _file_fingerprint(path: Path) -> dict[str, int | str | None]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "size": None, "mtime_ns": None}
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _proxy_cache_payload(
    source_path: Path,
    *,
    codec: BrowserProxyCodec,
    codec_profile: str,
    bit_depth: int,
    width: int,
    height: int,
    target_fps: float,
) -> dict:
    return {
        "schema": PROXY_CACHE_SCHEMA,
        "source": _file_fingerprint(source_path),
        "container": "mp4",
        "codec": codec,
        "codec_profile": codec_profile,
        "bit_depth": bit_depth,
        "width": width,
        "height": height,
        "target_fps": round(target_fps, 6),
        "color_range": PROXY_COLOR_RANGE,
        "color_primaries": PROXY_COLOR_PRIMARIES,
        "color_transfer": PROXY_COLOR_TRANSFER,
        "color_matrix": PROXY_COLOR_MATRIX,
        "mov_tag": "hvc1" if codec == "hevc" else "avc1",
    }


def _cache_key(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _proxy_metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".json")


def _cached_proxy_is_usable(
    path: Path,
    source_media: MediaInfo,
    *,
    expected_payload: dict,
    expected_cache_key: str,
    target_fps: float,
    target_width: int,
    target_height: int,
) -> MediaInfo | None:
    metadata_path = _proxy_metadata_path(path)
    if not path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(metadata, dict)
        or metadata.get("cache_key") != expected_cache_key
        or metadata.get("profile") != expected_payload
    ):
        return None
    try:
        if metadata.get("output_size") != path.stat().st_size:
            return None
    except OSError:
        return None
    try:
        cached = probe_media(path)
    except (OSError, RuntimeError, ValueError):
        return None
    duration_tolerance = max(1.0, 3.0 / max(target_fps, 1.0))
    expected_codec = "hevc" if expected_payload["codec"] == "hevc" else "h264"
    pixel_format = (cached.pixel_format or "").lower()
    expected_bit_depth = int(expected_payload["bit_depth"])
    pixel_format_matches = (
        ("10" in pixel_format or "p010" in pixel_format)
        if expected_bit_depth == 10
        else pixel_format.startswith("yuv420p") and "10" not in pixel_format
    )
    usable = (
        cached.codec == expected_codec
        and cached.width == target_width
        and cached.height == target_height
        and cached.fps <= target_fps + 0.05
        and _media_bit_depth(cached) == expected_bit_depth
        and pixel_format_matches
        and cached.color_range == PROXY_COLOR_RANGE
        and cached.color_primaries == PROXY_COLOR_PRIMARIES
        and cached.color_transfer == PROXY_COLOR_TRANSFER
        and cached.color_matrix == PROXY_COLOR_MATRIX
        and abs(cached.duration_seconds - source_media.duration_seconds) <= duration_tolerance
    )
    return cached if usable else None


def _write_proxy_metadata(
    path: Path,
    *,
    cache_key: str,
    profile: dict,
    media: MediaInfo,
) -> None:
    payload = {
        "schema": PROXY_CACHE_SCHEMA,
        "cache_key": cache_key,
        "profile": profile,
        "output_size": path.stat().st_size,
        "output": {
            "codec": media.codec,
            "pixel_format": media.pixel_format,
            "bit_depth": media.bit_depth,
            "width": media.width,
            "height": media.height,
            "fps": media.fps,
            "color_range": media.color_range,
            "color_primaries": media.color_primaries,
            "color_transfer": media.color_transfer,
            "color_matrix": media.color_matrix,
        },
    }
    destination = _proxy_metadata_path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _browser_proxy_result(
    path: Path,
    *,
    created: bool,
    encoder: str | None,
    codec_profile: str,
    media: MediaInfo,
    cache_key: str | None,
) -> BrowserProxy:
    return BrowserProxy(
        path=path,
        created=created,
        encoder=encoder,
        codec=media.codec,
        codec_profile=codec_profile,
        bit_depth=_media_bit_depth(media),
        pixel_format=media.pixel_format,
        width=media.width,
        height=media.height,
        fps=media.fps,
        cache_key=cache_key,
    )


def create_browser_proxy(
    source: str | Path,
    destination: str | Path,
    media: MediaInfo,
    *,
    preferred_encoder: str = "libx264",
    maximum_width: int = 960,
    maximum_height: int = 540,
    target_fps: float = 15.0,
    high_quality: bool = False,
    codec: BrowserProxyCodec = "h264",
    bit_depth: int = 8,
) -> BrowserProxy:
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    validate_proxy_encoding(codec, bit_depth)
    codec_profile = proxy_codec_profile(codec, bit_depth)
    target_width, target_height = scaled_proxy_dimensions(
        media.width,
        media.height,
        maximum_width=maximum_width,
        maximum_height=maximum_height,
    )
    actual_target_fps = min(media.fps, target_fps)
    if not needs_browser_proxy(
        media,
        codec=codec,
        bit_depth=bit_depth,
        maximum_width=maximum_width,
        maximum_height=maximum_height,
        target_fps=target_fps,
        require_color_tags=True,
    ):
        return _browser_proxy_result(
            source_path,
            created=False,
            encoder=None,
            codec_profile=codec_profile,
            media=media,
            cache_key=None,
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    profile_payload = _proxy_cache_payload(
        source_path,
        codec=codec,
        codec_profile=codec_profile,
        bit_depth=bit_depth,
        width=target_width,
        height=target_height,
        target_fps=actual_target_fps,
    )
    expected_cache_key = _cache_key(profile_payload)
    cached_media = _cached_proxy_is_usable(
        destination_path,
        media,
        expected_payload=profile_payload,
        expected_cache_key=expected_cache_key,
        target_fps=actual_target_fps,
        target_width=target_width,
        target_height=target_height,
    )
    if cached_media is not None:
        return _browser_proxy_result(
            destination_path,
            created=True,
            encoder="cached",
            codec_profile=codec_profile,
            media=cached_media,
            cache_key=expected_cache_key,
        )
    temporary_path = destination_path.with_name(f"{destination_path.stem}.tmp.mp4")
    if codec == "hevc":
        selected_encoder = (
            preferred_encoder
            if preferred_encoder in {"hevc_nvenc", "hevc_amf", "libx265"}
            else "libx265"
        )
        encoders = [selected_encoder]
        if selected_encoder != "libx265":
            encoders.append("libx265")
    else:
        selected_encoder = (
            preferred_encoder
            if preferred_encoder in {"h264_nvenc", "h264_amf", "libx264"}
            else "libx264"
        )
        encoders = [selected_encoder]
        if selected_encoder != "libx264":
            encoders.append("libx264")
    errors: list[str] = []

    for encoder in encoders:
        temporary_path.unlink(missing_ok=True)
        pixel_format = _proxy_pixel_format(encoder, bit_depth)
        command = [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            (
                f"fps={actual_target_fps:.6f},"
                f"scale={target_width}:{target_height}:"
                f"flags={'lanczos' if high_quality else 'fast_bilinear'}:"
                f"sws_dither=ed,format={pixel_format},"
                "setparams=range=limited:color_primaries=bt709:"
                "color_trc=bt709:colorspace=bt709"
            ),
            "-c:v",
            encoder,
            *_encoder_arguments(
                encoder,
                high_quality=high_quality,
                bit_depth=bit_depth,
            ),
            "-pix_fmt",
            pixel_format,
            "-color_range",
            PROXY_FFMPEG_COLOR_RANGE,
            "-color_primaries",
            PROXY_COLOR_PRIMARIES,
            "-color_trc",
            PROXY_COLOR_TRANSFER,
            "-colorspace",
            PROXY_COLOR_MATRIX,
            "-movflags",
            "+faststart",
        ]
        if codec == "hevc":
            command.extend(["-tag:v", "hvc1"])
        command.append(str(temporary_path))
        try:
            subprocess.run(command, check=True, capture_output=True)
            temporary_path.replace(destination_path)
            encoded_media = probe_media(destination_path)
            _write_proxy_metadata(
                destination_path,
                cache_key=expected_cache_key,
                profile=profile_payload,
                media=encoded_media,
            )
            usable = _cached_proxy_is_usable(
                destination_path,
                media,
                expected_payload=profile_payload,
                expected_cache_key=expected_cache_key,
                target_fps=actual_target_fps,
                target_width=target_width,
                target_height=target_height,
            )
            if usable is None:
                raise ProxyCreationError(
                    f"{encoder} produced a proxy that failed codec, bit-depth, "
                    "resolution, or color-tag validation"
                )
            return _browser_proxy_result(
                destination_path,
                created=True,
                encoder=encoder,
                codec_profile=codec_profile,
                media=usable,
                cache_key=expected_cache_key,
            )
        except FileNotFoundError as exc:
            raise ProxyCreationError(f"FFmpeg is unavailable: {settings.ffmpeg_binary}") from exc
        except ProxyCreationError as exc:
            errors.append(str(exc))
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
            errors.append(f"{encoder}: {stderr or 'encoding failed'}")

    temporary_path.unlink(missing_ok=True)
    raise ProxyCreationError("; ".join(errors))
