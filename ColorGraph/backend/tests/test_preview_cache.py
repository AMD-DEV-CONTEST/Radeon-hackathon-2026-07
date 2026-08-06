from pathlib import Path

import pytest
from fastapi import HTTPException

from colorgraph.api.routes import operations
from colorgraph.api.routes.operations import _decodable_preview_timestamp
from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, NodeType, TimeRange
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.services.preview_cache import (
    build_preview_cache_entry,
    build_preview_video_cache_entry,
    build_preview_video_segment_cache_entry,
    save_cached_preview_video,
)
from colorgraph.storage import ProjectStore


def _graph(
    project_id: str = "cache_test",
    media_path: str = "source.mp4",
):
    media = MediaInfo(
        path=media_path,
        duration_seconds=8,
        width=640,
        height=360,
        fps=25,
        frame_count=200,
        codec="h264",
        input_color_space=ColorSpace.BT709_OETF,
    )
    return build_initial_graph(
        project_id=project_id,
        project_name="Cache Test",
        media=media,
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=4),
            TimeRange(start_seconds=4, end_seconds=8),
        ],
        representative_frames=[Path("one.jpg"), Path("two.jpg")],
    )


def _entry(tmp_path: Path, graph, time_seconds: float):
    source = tmp_path / "source.mp4"
    if not source.is_file():
        source.write_bytes(b"source")
    return build_preview_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        frame_index=round(time_seconds * graph.media.fps),
        time_seconds=time_seconds,
    )


def test_preview_cache_only_invalidates_active_temporal_scope(tmp_path: Path) -> None:
    graph = _graph()
    before_first = _entry(tmp_path, graph, 1)
    before_second = _entry(tmp_path, graph, 5)
    second_balance = next(
        node
        for node in graph.nodes
        if node.type == NodeType.BALANCE and node.temporal_scope.shot_id == "shot_002"
    )
    second_balance.parameters["exposure"] = 0.75

    after_first = _entry(tmp_path, graph, 1)
    after_second = _entry(tmp_path, graph, 5)

    assert after_first.key == before_first.key
    assert after_second.key != before_second.key


def test_preview_cache_global_look_invalidates_all_ranges(tmp_path: Path) -> None:
    graph = _graph()
    before = _entry(tmp_path, graph, 1)
    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters["strength"] = 0.42
    after = _entry(tmp_path, graph, 1)
    assert after.key != before.key


def test_exact_preview_cache_uses_lossless_rgb_png(tmp_path: Path) -> None:
    entry = _entry(tmp_path, _graph(), 1)

    assert entry.source_frame.suffix == ".png"
    assert entry.output_frame.suffix == ".png"


def test_preview_timestamp_uses_last_decodable_frame_at_media_end() -> None:
    assert _decodable_preview_timestamp(
        8.0,
        duration_seconds=8.0,
        fps=25.0,
        frame_count=200,
    ) == pytest.approx(7.96)
    assert _decodable_preview_timestamp(
        -2.0,
        duration_seconds=8.0,
        fps=25.0,
        frame_count=200,
    ) == 0.0


def test_preview_video_cache_tracks_full_graph_and_quality(tmp_path: Path) -> None:
    graph = _graph()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    before = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
    )

    graph.updated_at = graph.updated_at.replace(microsecond=123456)
    timestamp_only = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
    )
    assert timestamp_only.key == before.key

    look = next(node for node in graph.nodes if node.type == NodeType.LOOK)
    look.parameters["strength"] = 0.42
    changed_graph = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
    )
    changed_quality = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="1080p",
        maximum_width=1920,
        maximum_height=1080,
        target_fps=30,
    )
    changed_encoding = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="1080p",
        codec="hevc",
        codec_profile="main10",
        bit_depth=10,
        pixel_format="yuv420p10le",
        maximum_width=1920,
        maximum_height=1080,
        target_fps=30,
    )
    changed_fps = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=12,
    )
    normalized_fps = build_preview_video_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15.0,
    )

    assert changed_graph.key != before.key
    assert changed_quality.key != changed_graph.key
    assert changed_encoding.key != changed_quality.key
    assert "-hevc-10bit-" in changed_encoding.key
    assert changed_fps.key != changed_graph.key
    assert normalized_fps.key == changed_graph.key


def test_preview_video_segments_share_graph_group_but_not_segment_key(
    tmp_path: Path,
) -> None:
    graph = _graph()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    first = build_preview_video_segment_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
        start_seconds=0,
        end_seconds=4,
    )
    second = build_preview_video_segment_cache_entry(
        previews_dir=tmp_path,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
        start_seconds=4,
        end_seconds=8,
    )

    assert first.group_key == second.group_key
    assert first.key != second.key
    assert operations._preview_segment_bounds(0.5, 8) == (0, 4)
    assert operations._preview_segment_bounds(4, 8) == (4, 8)
    assert operations._preview_segment_bounds(8, 8) == (4, 8)


@pytest.mark.asyncio
async def test_prepare_preview_video_reuses_completed_true_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("True Preview")
    source = project.input_dir / "source.mp4"
    source.write_bytes(b"source")
    graph = _graph(project.id, str(source))
    store.save_graph(project, graph)
    cache = build_preview_video_cache_entry(
        previews_dir=project.previews_dir,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
    )
    cache.output_video.write_bytes(b"rendered-video")
    save_cached_preview_video(cache, render={"frame_count": graph.media.frame_count})
    monkeypatch.setattr(operations, "project_store", lambda: store)

    prepared = await operations.prepare_preview_video(
        project.id,
        operations.PreviewVideoRequest(quality="540p", graph=graph),
    )

    assert prepared.status == "ready"
    assert prepared.cache_hit
    assert prepared.job_id is None
    assert prepared.cache_key == cache.key
    assert prepared.url == (
        f"/api/projects/{project.id}/preview-videos/{cache.output_video.name}"
    )
    assert prepared.profile.quality == "540p"
    assert prepared.profile.codec == "h264"
    assert prepared.profile.bit_depth == 8
    assert prepared.profile.width == 640
    assert prepared.profile.height == 360
    response = await operations.get_preview_video(project.id, cache.output_video.name)
    assert Path(response.path) == cache.output_video
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"


@pytest.mark.asyncio
async def test_exact_preview_response_serves_png_with_immutable_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Exact Preview")
    preview = project.previews_dir / "graded-frame.png"
    preview.write_bytes(b"png")
    monkeypatch.setattr(operations, "project_store", lambda: store)

    response = await operations.get_preview(project.id, preview.name)

    assert Path(response.path) == preview
    assert response.media_type == "image/png"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"


@pytest.mark.asyncio
async def test_prepare_preview_video_segment_reuses_completed_segment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Segment Preview")
    source = project.input_dir / "source.mp4"
    source.write_bytes(b"source")
    graph = _graph(project.id, str(source))
    store.save_graph(project, graph)
    cache = build_preview_video_segment_cache_entry(
        previews_dir=project.previews_dir,
        source=source,
        graph=graph,
        quality="540p",
        maximum_width=960,
        maximum_height=540,
        target_fps=15,
        start_seconds=4,
        end_seconds=8,
    )
    cache.output_video.write_bytes(b"rendered-segment")
    save_cached_preview_video(cache, render={"frame_count": 60})
    monkeypatch.setattr(operations, "project_store", lambda: store)

    prepared = await operations.prepare_preview_video_segment(
        project.id,
        operations.PreviewVideoSegmentRequest(
            quality="540p",
            graph=graph,
            time_seconds=6,
        ),
    )

    assert prepared.status == "ready"
    assert prepared.cache_hit
    assert prepared.cache_key == cache.key
    assert prepared.group_key == cache.group_key
    assert (prepared.start_seconds, prepared.end_seconds) == (4, 8)
    assert prepared.url == (
        f"/api/projects/{project.id}/preview-videos/{cache.output_video.name}"
    )
    with pytest.raises(HTTPException) as stale:
        await operations.prepare_preview_video_segment(
            project.id,
            operations.PreviewVideoSegmentRequest(
                quality="540p",
                graph=graph,
                time_seconds=2,
                priority=False,
                group_key="stale-group",
            ),
        )
    assert stale.value.status_code == 409


def test_preview_request_rejects_mismatched_codec_and_bit_depth() -> None:
    with pytest.raises(ValueError, match="H.264 preview must be 8-bit"):
        operations.PreviewVideoRequest(
            quality="2160p",
            codec="h264",
            bit_depth=10,
        )
