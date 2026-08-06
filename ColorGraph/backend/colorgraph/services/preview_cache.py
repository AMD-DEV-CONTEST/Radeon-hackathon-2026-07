from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from colorgraph.domain.grade_graph import GradeGraph, GradeNode, MaskAsset
from colorgraph.grading.engine import RenderMetrics
from colorgraph.grading.masks import mask_expression_operands

PREVIEW_IMAGE_PROFILE = "png-rgb24-1080p-video-signal-v3"
PREVIEW_VIDEO_PROFILE = "browser-playback-full-graph-v2"
PREVIEW_VIDEO_SEGMENT_PROFILE = "browser-playback-segment-v1"


@dataclass(frozen=True, slots=True)
class PreviewCacheEntry:
    key: str
    source_frame: Path
    output_frame: Path
    metrics_path: Path


@dataclass(frozen=True, slots=True)
class PreviewVideoCacheEntry:
    key: str
    output_video: Path
    metadata_path: Path


@dataclass(frozen=True, slots=True)
class PreviewVideoSegmentCacheEntry:
    key: str
    group_key: str
    start_seconds: float
    end_seconds: float
    output_video: Path
    metadata_path: Path


def _active_at(node: GradeNode, time_seconds: float) -> bool:
    time_range = node.temporal_scope.time_range
    return node.enabled and (
        time_range is None or time_range.start_seconds <= time_seconds < time_range.end_seconds
    )


def _path_fingerprint(path: Path) -> dict[str, int | str | None]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "size": None, "mtime_ns": None}
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _mask_fingerprint(asset: MaskAsset, frame_index: int) -> dict:
    video_path = Path(str(asset.metadata.get("video_path", "")))
    if video_path.is_file():
        storage = _path_fingerprint(video_path)
    else:
        pattern = str(asset.metadata.get("file_pattern", "{frame_index:06d}.png"))
        try:
            frame_path = Path(asset.path) / pattern.format(frame_index=frame_index)
        except (IndexError, KeyError, ValueError):
            frame_path = Path(asset.path)
        storage = _path_fingerprint(frame_path)
    return {
        "id": asset.id,
        "target": asset.target,
        "confidence": asset.confidence,
        "storage": storage,
    }


def build_preview_cache_entry(
    *,
    previews_dir: Path,
    source: Path,
    graph: GradeGraph,
    frame_index: int,
    time_seconds: float,
) -> PreviewCacheEntry:
    """Build a content-addressed key from only the nodes active at this time.

    Editing a shot or sub-shot does not invalidate cached previews outside its
    temporal scope. Global and scene changes naturally produce a new digest.
    """

    active_nodes = [
        node.model_dump(mode="json")
        for node in graph.ordered_nodes()
        if _active_at(node, time_seconds)
    ]
    referenced_mask_ids = {
        node.spatial_scope.mask_asset_id
        for node in graph.ordered_nodes()
        if _active_at(node, time_seconds) and node.spatial_scope.mask_asset_id
    }
    expression_operands: set[str] = set()
    for node in graph.ordered_nodes():
        if _active_at(node, time_seconds) and node.spatial_scope.expression:
            expression_operands.update(mask_expression_operands(node.spatial_scope.expression))
    active_masks = [
        _mask_fingerprint(asset, frame_index)
        for asset in graph.masks
        if asset.id in referenced_mask_ids
        or asset.id in expression_operands
        or asset.target in expression_operands
    ]
    source_fingerprint = _path_fingerprint(source)
    source_digest = hashlib.sha256(
        json.dumps(
            {
                "source": source_fingerprint,
                "image_profile": PREVIEW_IMAGE_PROFILE,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    payload = {
        "schema": "colorgraph.preview-cache/v2",
        "image_profile": PREVIEW_IMAGE_PROFILE,
        "grade_graph_schema": graph.schema_version,
        "renderer_version": graph.renderer_version,
        "frame_index": frame_index,
        "time_seconds": round(time_seconds, 6),
        "source": source_fingerprint,
        "input_color_space": graph.media.input_color_space,
        "source_log_profile": graph.media.source_log_profile,
        "working_color_space": graph.working_color_space,
        "output_color_space": graph.output_color_space,
        "nodes": active_nodes,
        "masks": active_masks,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:20]
    key = f"{frame_index:08d}-{digest}"
    return PreviewCacheEntry(
        key=key,
        source_frame=previews_dir / f"source-{frame_index:08d}-{source_digest}.png",
        output_frame=previews_dir / f"graded-{key}.png",
        metrics_path=previews_dir / f"graded-{key}.metrics.json",
    )


def build_preview_video_cache_entry(
    *,
    previews_dir: Path,
    source: Path,
    graph: GradeGraph,
    quality: str,
    codec: str = "h264",
    codec_profile: str = "high",
    bit_depth: int = 8,
    pixel_format: str = "yuv420p",
    maximum_width: int,
    maximum_height: int | None = None,
    target_fps: float,
    color_range: str = "limited",
    color_primaries: str = "bt709",
    color_transfer: str = "bt709",
    color_matrix: str = "bt709",
) -> PreviewVideoCacheEntry:
    """Build a cache key for a fully rendered browser-playable preview video."""

    graph_payload = graph.model_dump(mode="json")
    graph_payload.pop("created_at", None)
    graph_payload.pop("updated_at", None)
    payload = {
        "schema": "colorgraph.preview-video-cache/v2",
        "video_profile": PREVIEW_VIDEO_PROFILE,
        "quality": quality,
        "container": "mp4",
        "codec": codec,
        "codec_profile": codec_profile,
        "bit_depth": bit_depth,
        "pixel_format": pixel_format,
        "maximum_width": maximum_width,
        "maximum_height": maximum_height,
        "target_fps": round(float(target_fps), 6),
        "color_range": color_range,
        "color_primaries": color_primaries,
        "color_transfer": color_transfer,
        "color_matrix": color_matrix,
        "mov_tag": "hvc1" if codec == "hevc" else "avc1",
        "source": _path_fingerprint(source),
        "graph": graph_payload,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:24]
    key = f"{quality}-{codec}-{bit_depth}bit-{digest}"
    return PreviewVideoCacheEntry(
        key=key,
        output_video=previews_dir / f"graded-playback-{key}.mp4",
        metadata_path=previews_dir / f"graded-playback-{key}.json",
    )


def build_preview_video_segment_cache_entry(
    *,
    previews_dir: Path,
    source: Path,
    graph: GradeGraph,
    quality: str,
    start_seconds: float,
    end_seconds: float,
    codec: str = "h264",
    codec_profile: str = "high",
    bit_depth: int = 8,
    pixel_format: str = "yuv420p",
    maximum_width: int,
    maximum_height: int | None = None,
    target_fps: float,
    color_range: str = "limited",
    color_primaries: str = "bt709",
    color_transfer: str = "bt709",
    color_matrix: str = "bt709",
) -> PreviewVideoSegmentCacheEntry:
    """Build one content-addressed true-grade playback segment cache entry."""

    if start_seconds < 0 or end_seconds <= start_seconds:
        raise ValueError("preview segment range must be positive and increasing")
    group = build_preview_video_cache_entry(
        previews_dir=previews_dir,
        source=source,
        graph=graph,
        quality=quality,
        codec=codec,
        codec_profile=codec_profile,
        bit_depth=bit_depth,
        pixel_format=pixel_format,
        maximum_width=maximum_width,
        maximum_height=maximum_height,
        target_fps=target_fps,
        color_range=color_range,
        color_primaries=color_primaries,
        color_transfer=color_transfer,
        color_matrix=color_matrix,
    )
    payload = {
        "schema": "colorgraph.preview-video-segment-cache/v1",
        "segment_profile": PREVIEW_VIDEO_SEGMENT_PROFILE,
        "group_key": group.key,
        "start_seconds": round(float(start_seconds), 6),
        "end_seconds": round(float(end_seconds), 6),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    key = f"{quality}-{codec}-{bit_depth}bit-{digest}"
    return PreviewVideoSegmentCacheEntry(
        key=key,
        group_key=group.key,
        start_seconds=float(start_seconds),
        end_seconds=float(end_seconds),
        output_video=previews_dir / f"graded-playback-{key}.mp4",
        metadata_path=previews_dir / f"graded-playback-{key}.json",
    )


def load_cached_metrics(path: Path) -> RenderMetrics | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RenderMetrics(**payload)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_cached_metrics(path: Path, metrics: RenderMetrics) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(metrics), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_cached_preview_video(
    entry: PreviewVideoCacheEntry | PreviewVideoSegmentCacheEntry,
) -> dict | None:
    if not entry.output_video.is_file() or not entry.metadata_path.is_file():
        return None
    try:
        payload = json.loads(entry.metadata_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("cache_key") != entry.key:
        return None
    try:
        output_size = entry.output_video.stat().st_size
    except OSError:
        return None
    if output_size <= 0 or payload.get("output_size") != output_size:
        return None
    return payload


def save_cached_preview_video(
    entry: PreviewVideoCacheEntry | PreviewVideoSegmentCacheEntry,
    *,
    render: dict,
    profile: dict | None = None,
) -> None:
    payload = {
        "cache_key": entry.key,
        "video_profile": PREVIEW_VIDEO_PROFILE,
        "filename": entry.output_video.name,
        "output_size": entry.output_video.stat().st_size,
        "render": render,
        "profile": profile or {},
    }
    if isinstance(entry, PreviewVideoSegmentCacheEntry):
        payload.update(
            {
                "segment_profile": PREVIEW_VIDEO_SEGMENT_PROFILE,
                "group_key": entry.group_key,
                "start_seconds": entry.start_seconds,
                "end_seconds": entry.end_seconds,
            }
        )
    temporary = entry.metadata_path.with_suffix(entry.metadata_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(entry.metadata_path)
