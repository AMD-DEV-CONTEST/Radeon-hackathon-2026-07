from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent import CommandContext, CommandPlan, GradeCommandPlanner
from colorgraph.agent.creative_ui import AgentUIStore
from colorgraph.api.dependencies import (
    compute_backend,
    project_store,
    scene_analyzer,
    video_mask_generator,
)
from colorgraph.domain.grade_graph import GradeGraph
from colorgraph.domain.jobs import JobRecord, JobStatus
from colorgraph.exports import export_grade_package
from colorgraph.grading.engine import GradeRenderEngine
from colorgraph.grading.looks import (
    LOOK_RECIPE_VERSION,
    LOOK_RECIPES,
    active_look_node,
    graph_digest,
    graph_with_look_recipe,
    look_instance_for_node,
    sync_look_instances,
)
from colorgraph.grading.masks import GraphMaskResolver
from colorgraph.grading.video import VideoRenderer
from colorgraph.media.frames import extract_frame
from colorgraph.media.proxy import (
    BROWSER_PROXY_PRESETS,
    PROXY_COLOR_MATRIX,
    PROXY_COLOR_PRIMARIES,
    PROXY_COLOR_RANGE,
    PROXY_COLOR_TRANSFER,
    BrowserProxyCodec,
    BrowserProxyQuality,
    proxy_codec_profile,
    scaled_proxy_dimensions,
)
from colorgraph.quality import (
    QualityReport,
    RepairAttemptDecision,
    RepairPolicy,
    analyze_video_quality,
    repairable_objective_ids,
    search_technical_repairs,
)
from colorgraph.services.candidates import generate_look_candidates
from colorgraph.services.jobs import job_manager
from colorgraph.services.mask_nodes import ensure_default_mask_nodes
from colorgraph.services.playback_metrics import record_playback_metrics
from colorgraph.services.preview_cache import (
    PreviewVideoCacheEntry,
    PreviewVideoSegmentCacheEntry,
    build_preview_cache_entry,
    build_preview_video_cache_entry,
    build_preview_video_segment_cache_entry,
    load_cached_metrics,
    load_cached_preview_video,
    save_cached_metrics,
    save_cached_preview_video,
)
from colorgraph.services.reference_supervision import fit_partial_video_reference
from colorgraph.vision import release_inference_models

router = APIRouter(prefix="/api/projects", tags=["operations"])
_PREVIEW_VIDEO_RENDER_LOCKS: dict[str, asyncio.Lock] = {}
_LATEST_PREVIEW_VIDEO_KEYS: dict[str, str] = {}
_LATEST_PREVIEW_SEGMENT_GROUP_KEYS: dict[str, str] = {}
_PREVIEW_SEGMENT_REQUEST_EPOCHS: dict[str, int] = {}
PREVIEW_SEGMENT_DURATION_SECONDS = 4.0


class PreviewVideoRenderSuperseded(RuntimeError):
    pass


def _decodable_preview_timestamp(
    requested_time: float,
    *,
    duration_seconds: float,
    fps: float,
    frame_count: int,
) -> float:
    safe_fps = max(fps, 1.0)
    last_frame_time = max(0.0, (frame_count - 1) / safe_fps)
    last_decodable_time = min(duration_seconds, last_frame_time)
    return min(max(0.0, requested_time), last_decodable_time)


class OperationAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    job_id: str
    status: JobStatus


class MaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[str] = Field(
        default_factory=lambda: [
            "sky",
            "vegetation",
            "water",
            "mountain",
            "depth_far",
        ]
    )
    inference_interval_seconds: float = Field(default=1.5, ge=0.5, le=10)
    maximum_edge: int = Field(default=640, ge=256, le=1280)


def _reusable_mask_targets(
    graph: GradeGraph,
    masks_root: Path,
    targets: list[str],
) -> set[str]:
    root = masks_root.resolve()
    reusable: set[str] = set()
    for target in targets:
        asset = next((item for item in graph.masks if item.target == target), None)
        if asset is None or asset.frame_count != graph.media.frame_count:
            continue
        metadata = asset.metadata
        sequence_root = Path(asset.path).resolve()
        video_value = metadata.get("video_path")
        if not isinstance(video_value, str):
            continue
        video_path = Path(video_value).resolve()
        common_integrity = (
            not sequence_root.is_relative_to(root)
            or not video_path.is_relative_to(root)
            or not sequence_root.is_dir()
            or not video_path.is_file()
            or metadata.get("frame_count") != graph.media.frame_count
            or metadata.get("decode_verified") is not True
            or len(str(metadata.get("video_sha256", ""))) != 64
        )
        if common_integrity:
            continue
        storage = metadata.get("storage")
        video_primary = (
            isinstance(storage, dict)
            and storage.get("preferred_decode") == "video_ffmpeg"
        )
        if video_primary:
            if metadata.get("file_count") != 0:
                continue
        elif (
            metadata.get("file_count") != graph.media.frame_count
            or len(str(metadata.get("sequence_sha256", ""))) != 64
        ):
            continue
        reusable.add(target)
    return reusable


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=1200)
    context: CommandContext = Field(default_factory=CommandContext)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_seconds: float = Field(default=0, ge=0)


class PreviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    source_url: str
    time_seconds: float
    metrics: dict
    cache_hit: bool
    cache_key: str


class PreviewVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: BrowserProxyQuality = "1080p"
    codec: BrowserProxyCodec = "h264"
    bit_depth: Literal[8, 10] = 8
    batch_size: int = Field(default=4, ge=1, le=24)
    graph: GradeGraph | None = None

    @model_validator(mode="after")
    def validate_encoding(self) -> PreviewVideoRequest:
        if (self.codec, self.bit_depth) not in {("h264", 8), ("hevc", 10)}:
            raise ValueError(
                "H.264 preview must be 8-bit and HEVC preview must be 10-bit"
            )
        return self


class PreviewPlaybackProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: BrowserProxyQuality
    codec: BrowserProxyCodec
    codec_profile: Literal["high", "main10"]
    bit_depth: Literal[8, 10]
    pixel_format: Literal["yuv420p", "yuv420p10le"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    color_range: Literal["limited"] = PROXY_COLOR_RANGE
    color_primaries: Literal["bt709"] = PROXY_COLOR_PRIMARIES
    color_transfer: Literal["bt709"] = PROXY_COLOR_TRANSFER
    color_matrix: Literal["bt709"] = PROXY_COLOR_MATRIX
    mov_tag: Literal["avc1", "hvc1"]


class PreviewVideoPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "rendering"]
    cache_key: str
    cache_hit: bool
    url: str | None = None
    job_id: str | None = None
    profile: PreviewPlaybackProfile


class PreviewVideoSegmentRequest(PreviewVideoRequest):
    time_seconds: float = Field(default=0, ge=0)
    priority: bool = True
    group_key: str | None = Field(default=None, min_length=1, max_length=128)


class PreviewVideoSegmentPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "rendering"]
    cache_key: str
    group_key: str
    cache_hit: bool
    start_seconds: float
    end_seconds: float
    url: str | None = None
    job_id: str | None = None
    profile: PreviewPlaybackProfile


class PreviewPlaybackTelemetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9._-]+$")
    cache_key: str = Field(
        pattern=(
            r"^(540p|1080p|1440p|2160p)-(h264|hevc)-(8|10)bit-[0-9a-f]{24}$"
        )
    )
    profile: PreviewPlaybackProfile
    first_frame_wait_ms: float | None = Field(default=None, ge=0, le=600_000)
    total_video_frames: int = Field(default=0, ge=0)
    dropped_video_frames: int = Field(default=0, ge=0)
    sync_error_ms: float = Field(default=0, ge=0, le=60_000)
    buffering_events: int = Field(default=0, ge=0)
    master_ready_state: int = Field(ge=0, le=4)
    graded_ready_state: int = Field(ge=0, le=4)
    playing: bool

    @model_validator(mode="after")
    def validate_frames_and_profile(self) -> PreviewPlaybackTelemetryRequest:
        if self.dropped_video_frames > self.total_video_frames:
            raise ValueError("dropped video frames cannot exceed total video frames")
        expected_prefix = (
            f"{self.profile.quality}-{self.profile.codec}-"
            f"{self.profile.bit_depth}bit-"
        )
        if not self.cache_key.startswith(expected_prefix):
            raise ValueError("cache key does not match the playback profile")
        return self


def _preview_playback_profile(
    graph: GradeGraph,
    request: PreviewVideoRequest,
) -> PreviewPlaybackProfile:
    preset = BROWSER_PROXY_PRESETS[request.quality]
    width, height = scaled_proxy_dimensions(
        graph.media.width,
        graph.media.height,
        maximum_width=preset.maximum_width,
        maximum_height=preset.maximum_height,
    )
    return PreviewPlaybackProfile(
        quality=request.quality,
        codec=request.codec,
        codec_profile=proxy_codec_profile(request.codec, request.bit_depth),
        bit_depth=request.bit_depth,
        pixel_format="yuv420p10le" if request.bit_depth == 10 else "yuv420p",
        width=width,
        height=height,
        fps=min(graph.media.fps, preset.target_fps),
        mov_tag="hvc1" if request.codec == "hevc" else "avc1",
    )


def _preview_segment_bounds(
    time_seconds: float,
    duration_seconds: float,
) -> tuple[float, float]:
    if duration_seconds <= 0:
        raise ValueError("preview source duration must be positive")
    safe_time = min(max(0.0, time_seconds), max(0.0, duration_seconds - 1e-6))
    start = int(safe_time / PREVIEW_SEGMENT_DURATION_SECONDS)
    start_seconds = start * PREVIEW_SEGMENT_DURATION_SECONDS
    end_seconds = min(
        duration_seconds,
        start_seconds + PREVIEW_SEGMENT_DURATION_SECONDS,
    )
    return round(start_seconds, 6), round(end_seconds, 6)


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_seconds: float = Field(default=0, ge=0)
    prompt: str = Field(
        default="自然、清晰、保留天空与植被层次",
        max_length=1200,
    )
    limit: int = Field(default=3, ge=2, le=4)


class LookApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=80)
    recipe_version: str = Field(min_length=1, max_length=80)
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    time_seconds: float = Field(default=0, ge=0)
    discard_overrides: bool = False


class LookRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_seconds: float = Field(default=0, ge=0)


class LookMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["applied", "restored", "unchanged"]
    recipe_id: str
    graph_digest: str
    graph: GradeGraph


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(default=4, ge=1, le=24)
    bit_depth: Literal[8, 10] = 10
    filename: str = Field(default="graded.mp4", pattern=r"^[a-zA-Z0-9_-]+\.mp4$")
    repair_evaluation_budget: int = Field(default=4, ge=0, le=12)
    repair_maximum_rounds: int = Field(default=3, ge=1, le=6)


class PartialReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_media_path: str = Field(min_length=1, max_length=4096)
    source_start_seconds: float = Field(ge=0)
    source_end_seconds: float = Field(gt=0)
    reference_start_seconds: float = Field(ge=0)
    reference_end_seconds: float = Field(gt=0)
    sample_count: int = Field(default=5, ge=3, le=9)
    fit_samples: int = Field(default=300_000, ge=10_000, le=1_000_000)
    optimization_steps: int = Field(default=500, ge=100, le=2_000)
    maximum_width: int = Field(default=1280, ge=640, le=1920)

    @model_validator(mode="after")
    def validate_ranges(self) -> PartialReferenceRequest:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("source_end_seconds must be greater than source_start_seconds")
        if self.reference_end_seconds <= self.reference_start_seconds:
            raise ValueError("reference_end_seconds must be greater than reference_start_seconds")
        return self


def _source_path(project_id: str) -> Path:
    store = project_store()
    project = store.get(project_id)
    return store.resolve_source(project)


async def _generate_masks_task(
    *,
    job_id: str,
    project_id: str,
    request: MaskRequest,
) -> None:
    loop = asyncio.get_running_loop()
    store = project_store()
    try:
        project = store.get(project_id)
        source = _source_path(project_id)
        graph = store.load_graph(project_id)
        backend = compute_backend()
        await job_manager.update(
            job_id,
            status=JobStatus.RUNNING,
            stage="models",
            progress=5,
            message="Loading local semantic segmentation and depth models",
            device=backend.info.runtime,
        )
        generator = video_mask_generator()
        release_inference_models(family="clip-scene")

        last_progress = -1

        def report(completed: int, total: int, message: str) -> None:
            nonlocal last_progress
            progress = 10 + round(completed / max(total, 1) * 80)
            if progress <= last_progress:
                return
            last_progress = progress
            coroutine = job_manager.update(
                job_id,
                stage="masks",
                progress=min(progress, 90),
                message=f"{message}: {completed}/{total}",
                device=backend.info.runtime,
            )
            loop.call_soon_threadsafe(asyncio.create_task, coroutine)

        result = await asyncio.to_thread(
            generator.generate,
            source,
            graph,
            project.masks_dir,
            targets=request.targets,
            inference_interval_seconds=request.inference_interval_seconds,
            maximum_edge=request.maximum_edge,
            progress=report,
        )
        graph_with_nodes = ensure_default_mask_nodes(result.graph)
        await asyncio.to_thread(store.save_graph, project, graph_with_nodes)
        await job_manager.complete(
            job_id,
            {
                "project_id": project_id,
                "targets": result.targets,
                "frame_count": result.frame_count,
                "inference_frames": result.inference_frames,
                "grade_graph_url": f"/api/projects/{project_id}/grade-graph",
            },
        )
    except Exception as exc:
        await job_manager.fail(job_id, exc)


@router.post("/{project_id}/masks", response_model=OperationAccepted, status_code=202)
async def generate_masks(
    project_id: str,
    request: MaskRequest,
) -> OperationAccepted:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    job, created = await job_manager.create_unique(
        kind="masks",
        project_id=project_id,
    )
    if created:
        reusable = _reusable_mask_targets(
            graph,
            project.masks_dir,
            request.targets,
        )
        missing_targets = [
            target for target in request.targets if target not in reusable
        ]
        if not missing_targets:
            job = await job_manager.complete(
                job.id,
                {
                    "project_id": project_id,
                    "targets": request.targets,
                    "reused_targets": request.targets,
                    "frame_count": graph.media.frame_count,
                    "inference_frames": 0,
                    "cache_hit": True,
                    "grade_graph_url": f"/api/projects/{project_id}/grade-graph",
                },
            )
        else:
            job_manager.spawn(
                _generate_masks_task(
                    job_id=job.id,
                    project_id=project_id,
                    request=request.model_copy(
                        update={"targets": missing_targets},
                    ),
                )
            )
    return OperationAccepted(
        project_id=project_id,
        job_id=job.id,
        status=job.status,
    )


@router.get("/{project_id}/masks/job", response_model=JobRecord | None)
async def get_active_mask_job(project_id: str) -> JobRecord | None:
    try:
        project_store().load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    return await job_manager.find_active(kind="masks", project_id=project_id)


@router.post("/{project_id}/commands", response_model=CommandPlan)
async def execute_command(
    project_id: str,
    request: CommandRequest,
) -> CommandPlan:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    try:
        plan = GradeCommandPlanner().plan(
            graph,
            request.prompt,
            request.context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await asyncio.to_thread(store.save_graph, project, plan.graph)
    return plan


@router.put("/{project_id}/grade-graph", response_model=GradeGraph)
async def replace_grade_graph(
    project_id: str,
    graph: GradeGraph,
) -> GradeGraph:
    if graph.project_id != project_id:
        raise HTTPException(status_code=409, detail="project id does not match graph")
    try:
        store = project_store()
        project = store.get(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    normalized = sync_look_instances(graph, touch=True)
    await asyncio.to_thread(store.save_graph, project, normalized)
    await asyncio.to_thread(AgentUIStore(project.root).reconcile_graph, normalized)
    return normalized


@router.post("/{project_id}/preview", response_model=PreviewResult)
async def render_preview(
    project_id: str,
    request: PreviewRequest,
) -> PreviewResult:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
        source = _source_path(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    timestamp = _decodable_preview_timestamp(
        request.time_seconds,
        duration_seconds=graph.media.duration_seconds,
        fps=graph.media.fps,
        frame_count=graph.media.frame_count,
    )
    frame_index = min(
        max(0, round(timestamp * graph.media.fps)),
        max(0, graph.media.frame_count - 1),
    )
    cache = build_preview_cache_entry(
        previews_dir=project.previews_dir,
        source=source,
        graph=graph,
        frame_index=frame_index,
        time_seconds=timestamp,
    )
    metrics = load_cached_metrics(cache.metrics_path)
    cache_hit = (
        cache.output_frame.is_file() and cache.source_frame.is_file() and metrics is not None
    )
    if not cache_hit:
        if not cache.source_frame.is_file():
            await asyncio.to_thread(
                extract_frame,
                source,
                timestamp,
                cache.source_frame,
                maximum_width=1920,
                high_quality=True,
            )
        # Interactive previews validate the requested mask frame while loading
        # it. Full sequence checks remain enabled for formal video rendering,
        # but would make every cold preview scan all mask assets first.
        resolver = GraphMaskResolver(graph, verify_storage=False)
        try:
            masks = (
                await asyncio.to_thread(
                    resolver.load_batch,
                    [frame_index],
                    device=compute_backend().torch_device,
                )
                if resolver.assets
                else None
            )
            metrics = await asyncio.to_thread(
                GradeRenderEngine(compute_backend()).render_image,
                cache.source_frame,
                cache.output_frame,
                graph,
                time_seconds=timestamp,
                masks=masks,
                display_color_space=None,
            )
            await asyncio.to_thread(save_cached_metrics, cache.metrics_path, metrics)
        finally:
            resolver.close()
    if metrics is None:
        raise RuntimeError("preview cache did not produce render metrics")
    return PreviewResult(
        url=f"/api/projects/{project_id}/previews/{cache.output_frame.name}",
        source_url=f"/api/projects/{project_id}/previews/{cache.source_frame.name}",
        time_seconds=timestamp,
        metrics=asdict(metrics),
        cache_hit=cache_hit,
        cache_key=cache.key,
    )


@router.post(
    "/{project_id}/preview-video",
    response_model=PreviewVideoPreparation,
)
async def prepare_preview_video(
    project_id: str,
    request: PreviewVideoRequest,
) -> PreviewVideoPreparation:
    try:
        store = project_store()
        project = store.get(project_id)
        stored_graph = store.load_graph(project_id)
        source = _source_path(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    graph = request.graph or stored_graph
    if graph.project_id != project_id:
        raise HTTPException(status_code=409, detail="project id does not match preview graph")

    preset = BROWSER_PROXY_PRESETS[request.quality]
    profile = _preview_playback_profile(graph, request)
    cache = build_preview_video_cache_entry(
        previews_dir=project.previews_dir,
        source=source,
        graph=graph,
        quality=request.quality,
        codec=profile.codec,
        codec_profile=profile.codec_profile,
        bit_depth=profile.bit_depth,
        pixel_format=profile.pixel_format,
        maximum_width=preset.maximum_width,
        maximum_height=preset.maximum_height,
        target_fps=preset.target_fps,
        color_range=profile.color_range,
        color_primaries=profile.color_primaries,
        color_transfer=profile.color_transfer,
        color_matrix=profile.color_matrix,
    )
    _LATEST_PREVIEW_VIDEO_KEYS[project_id] = cache.key
    cached = load_cached_preview_video(cache)
    url = f"/api/projects/{project_id}/preview-videos/{cache.output_video.name}"
    if cached is not None:
        return PreviewVideoPreparation(
            status="ready",
            cache_key=cache.key,
            cache_hit=True,
            url=url,
            profile=profile,
        )

    job, created = await job_manager.create_unique(
        kind=f"preview_video:{cache.key}",
        project_id=project_id,
    )
    if created:
        job_manager.spawn(
            _preview_video_task(
                job_id=job.id,
                project_id=project_id,
                source=source,
                graph=graph.model_copy(deep=True),
                cache=cache,
                maximum_width=preset.maximum_width,
                maximum_height=preset.maximum_height,
                target_fps=preset.target_fps,
                bit_depth=profile.bit_depth,
                profile=profile,
                batch_size=request.batch_size,
            )
        )
    return PreviewVideoPreparation(
        status="rendering",
        cache_key=cache.key,
        cache_hit=False,
        job_id=job.id,
        profile=profile,
    )


@router.post(
    "/{project_id}/preview-video-segment",
    response_model=PreviewVideoSegmentPreparation,
)
async def prepare_preview_video_segment(
    project_id: str,
    request: PreviewVideoSegmentRequest,
) -> PreviewVideoSegmentPreparation:
    try:
        store = project_store()
        project = store.get(project_id)
        stored_graph = store.load_graph(project_id)
        source = _source_path(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    graph = request.graph or stored_graph
    if graph.project_id != project_id:
        raise HTTPException(status_code=409, detail="project id does not match preview graph")

    preset = BROWSER_PROXY_PRESETS[request.quality]
    profile = _preview_playback_profile(graph, request)
    start_seconds, end_seconds = _preview_segment_bounds(
        request.time_seconds,
        graph.media.duration_seconds,
    )
    cache = build_preview_video_segment_cache_entry(
        previews_dir=project.previews_dir,
        source=source,
        graph=graph,
        quality=request.quality,
        codec=profile.codec,
        codec_profile=profile.codec_profile,
        bit_depth=profile.bit_depth,
        pixel_format=profile.pixel_format,
        maximum_width=preset.maximum_width,
        maximum_height=preset.maximum_height,
        target_fps=preset.target_fps,
        color_range=profile.color_range,
        color_primaries=profile.color_primaries,
        color_transfer=profile.color_transfer,
        color_matrix=profile.color_matrix,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    if request.priority:
        _LATEST_PREVIEW_SEGMENT_GROUP_KEYS[project_id] = cache.group_key
        request_epoch = _PREVIEW_SEGMENT_REQUEST_EPOCHS.get(project_id, 0) + 1
        _PREVIEW_SEGMENT_REQUEST_EPOCHS[project_id] = request_epoch
    else:
        if (
            request.group_key != cache.group_key
            or _LATEST_PREVIEW_SEGMENT_GROUP_KEYS.get(project_id) != cache.group_key
        ):
            raise HTTPException(
                status_code=409,
                detail="preview segment prefetch belongs to a stale Grade Graph",
            )
        request_epoch = _PREVIEW_SEGMENT_REQUEST_EPOCHS.get(project_id, 0)

    cached = load_cached_preview_video(cache)
    url = f"/api/projects/{project_id}/preview-videos/{cache.output_video.name}"
    if cached is not None:
        return PreviewVideoSegmentPreparation(
            status="ready",
            cache_key=cache.key,
            group_key=cache.group_key,
            cache_hit=True,
            start_seconds=cache.start_seconds,
            end_seconds=cache.end_seconds,
            url=url,
            profile=profile,
        )

    job, created = await job_manager.create_unique(
        kind=f"preview_video_segment:{cache.key}:{request_epoch}",
        project_id=project_id,
    )
    if created:
        job_manager.spawn(
            _preview_video_segment_task(
                job_id=job.id,
                project_id=project_id,
                source=source,
                graph=graph.model_copy(deep=True),
                cache=cache,
                maximum_width=preset.maximum_width,
                maximum_height=preset.maximum_height,
                target_fps=preset.target_fps,
                bit_depth=profile.bit_depth,
                profile=profile,
                batch_size=request.batch_size,
                request_epoch=request_epoch,
            )
        )
    return PreviewVideoSegmentPreparation(
        status="rendering",
        cache_key=cache.key,
        group_key=cache.group_key,
        cache_hit=False,
        start_seconds=cache.start_seconds,
        end_seconds=cache.end_seconds,
        job_id=job.id,
        profile=profile,
    )


@router.post("/{project_id}/preview-playback-metrics")
async def save_preview_playback_metrics(
    project_id: str,
    request: PreviewPlaybackTelemetryRequest,
) -> dict:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    try:
        return await asyncio.to_thread(
            record_playback_metrics,
            report_path=project.previews_dir / "playback-metrics.json",
            previews_dir=project.previews_dir,
            input_dir=project.input_dir,
            duration_seconds=graph.media.duration_seconds,
            cache_key=request.cache_key,
            profile=request.profile.model_dump(mode="json"),
            telemetry=request.model_dump(
                mode="json",
                exclude={"cache_key", "profile"},
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{project_id}/candidates")
async def compare_look_candidates(
    project_id: str,
    request: CandidateRequest,
) -> dict:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
        source = _source_path(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    comparison = await asyncio.to_thread(
        generate_look_candidates,
        source=source,
        graph=graph,
        previews_dir=project.previews_dir,
        time_seconds=request.time_seconds,
        prompt=request.prompt,
        backend=compute_backend(),
        analyzer=scene_analyzer(),
        limit=request.limit,
    )
    payload = comparison.model_dump(mode="json")
    for candidate in payload["candidates"]:
        candidate["url"] = f"/api/projects/{project_id}/previews/{candidate.pop('filename')}"
    return payload


@router.post(
    "/{project_id}/looks/apply",
    response_model=LookMutationResult,
)
async def apply_candidate_look(
    project_id: str,
    request: LookApplyRequest,
) -> LookMutationResult:
    try:
        store = project_store()
        project = store.get(project_id)
        stored_graph = store.load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc

    actual_digest = graph_digest(stored_graph)
    if request.graph_digest != actual_digest:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_candidate",
                "message": "candidate thumbnails no longer match the saved graph",
                "expected_graph_digest": request.graph_digest,
                "actual_graph_digest": actual_digest,
            },
        )
    if request.recipe_version != LOOK_RECIPE_VERSION:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recipe_version_mismatch",
                "message": "candidate recipe version is no longer current",
                "expected_recipe_version": request.recipe_version,
                "actual_recipe_version": LOOK_RECIPE_VERSION,
            },
        )
    if request.recipe_id not in LOOK_RECIPES:
        raise HTTPException(status_code=422, detail="unknown Look recipe")

    graph = sync_look_instances(stored_graph)
    active = active_look_node(graph, request.time_seconds)
    if active is None:
        raise HTTPException(status_code=422, detail="active scene does not contain a Look node")
    instance = look_instance_for_node(active)
    current_recipe_id = str(instance["base_recipe_id"])
    if current_recipe_id == request.recipe_id:
        if graph != stored_graph:
            await asyncio.to_thread(store.save_graph, project, graph)
        return LookMutationResult(
            action="unchanged",
            recipe_id=current_recipe_id,
            graph_digest=graph_digest(graph),
            graph=graph,
        )
    if instance["dirty"] and not request.discard_overrides:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "dirty_look_requires_confirmation",
                "message": "switching Look would discard project overrides",
                "current_recipe_id": current_recipe_id,
                "requested_recipe_id": request.recipe_id,
                "user_overrides": instance["user_overrides"],
            },
        )

    updated = graph_with_look_recipe(
        graph,
        request.recipe_id,
        time_seconds=request.time_seconds,
        source="candidate_apply/v1",
    )
    await asyncio.to_thread(store.save_graph, project, updated)
    return LookMutationResult(
        action="applied",
        recipe_id=request.recipe_id,
        graph_digest=graph_digest(updated),
        graph=updated,
    )


@router.post(
    "/{project_id}/looks/restore",
    response_model=LookMutationResult,
)
async def restore_original_look(
    project_id: str,
    request: LookRestoreRequest,
) -> LookMutationResult:
    try:
        store = project_store()
        project = store.get(project_id)
        stored_graph = store.load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc

    graph = sync_look_instances(stored_graph)
    active = active_look_node(graph, request.time_seconds)
    if active is None:
        raise HTTPException(status_code=422, detail="active scene does not contain a Look node")
    instance = look_instance_for_node(active)
    recipe_id = str(instance["base_recipe_id"])
    if not instance["dirty"]:
        if graph != stored_graph:
            await asyncio.to_thread(store.save_graph, project, graph)
        return LookMutationResult(
            action="unchanged",
            recipe_id=recipe_id,
            graph_digest=graph_digest(graph),
            graph=graph,
        )

    updated = graph_with_look_recipe(
        graph,
        recipe_id,
        time_seconds=request.time_seconds,
        source="restore_original/v1",
    )
    await asyncio.to_thread(store.save_graph, project, updated)
    return LookMutationResult(
        action="restored",
        recipe_id=recipe_id,
        graph_digest=graph_digest(updated),
        graph=updated,
    )


async def _partial_reference_task(
    *,
    job_id: str,
    project_id: str,
    request: PartialReferenceRequest,
) -> None:
    loop = asyncio.get_running_loop()
    store = project_store()
    try:
        project = store.get(project_id)
        source = _source_path(project_id)
        graph = store.load_graph(project_id)
        reference = Path(request.reference_media_path).resolve()
        backend = compute_backend()
        await job_manager.update(
            job_id,
            status=JobStatus.RUNNING,
            stage="align",
            progress=5,
            message="Extracting and geometrically aligning partial reference frames",
            device=backend.info.runtime,
        )
        last_progress = -1

        def report(stage: str, completed: int, total: int) -> None:
            nonlocal last_progress
            if stage == "align":
                value = 10 + round(completed / max(total, 1) * 50)
                message = f"Aligned supervision frame {completed}/{total}"
            else:
                value = 65 if completed == 0 else 92
                message = (
                    "Fitting low-frequency tone and color"
                    if completed == 0
                    else "Tone and color fit complete"
                )
            if value <= last_progress:
                return
            last_progress = value
            coroutine = job_manager.update(
                job_id,
                stage=stage,
                progress=value,
                message=message,
                device=backend.info.runtime,
            )
            loop.call_soon_threadsafe(asyncio.create_task, coroutine)

        result = await asyncio.to_thread(
            fit_partial_video_reference,
            source=source,
            reference=reference,
            graph=graph,
            work_dir=project.outputs_dir / "partial-reference",
            source_start_seconds=request.source_start_seconds,
            source_end_seconds=request.source_end_seconds,
            reference_start_seconds=request.reference_start_seconds,
            reference_end_seconds=request.reference_end_seconds,
            backend=backend,
            sample_count=request.sample_count,
            fit_samples=request.fit_samples,
            optimization_steps=request.optimization_steps,
            maximum_width=request.maximum_width,
            progress=report,
        )
        await asyncio.to_thread(store.save_graph, project, result.graph)
        payload = result.response_payload()
        payload.update(
            {
                "project_id": project_id,
                "grade_graph_url": f"/api/projects/{project_id}/grade-graph",
                "comparison_url": (
                    f"/api/projects/{project_id}/outputs/"
                    "partial-reference/partial-reference-comparison.jpg"
                ),
            }
        )
        await job_manager.complete(job_id, payload)
    except Exception as exc:
        await job_manager.fail(job_id, exc)


@router.post(
    "/{project_id}/partial-reference",
    response_model=OperationAccepted,
    status_code=202,
)
async def fit_partial_reference(
    project_id: str,
    request: PartialReferenceRequest,
) -> OperationAccepted:
    reference = Path(request.reference_media_path)
    if not reference.is_absolute():
        raise HTTPException(status_code=422, detail="reference_media_path must be absolute")
    if not reference.is_file():
        raise HTTPException(status_code=422, detail="reference video does not exist")
    try:
        graph = project_store().load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    if request.source_end_seconds > graph.media.duration_seconds + 1e-3:
        raise HTTPException(
            status_code=422,
            detail="source supervision range exceeds project duration",
        )
    job = await job_manager.create(kind="partial_reference", project_id=project_id)
    job_manager.spawn(
        _partial_reference_task(
            job_id=job.id,
            project_id=project_id,
            request=request,
        )
    )
    return OperationAccepted(
        project_id=project_id,
        job_id=job.id,
        status=job.status,
    )


async def _preview_video_task(
    *,
    job_id: str,
    project_id: str,
    source: Path,
    graph: GradeGraph,
    cache: PreviewVideoCacheEntry,
    maximum_width: int,
    maximum_height: int,
    target_fps: float,
    bit_depth: int,
    profile: PreviewPlaybackProfile,
    batch_size: int,
) -> None:
    loop = asyncio.get_running_loop()
    backend = compute_backend()
    render_lock = _PREVIEW_VIDEO_RENDER_LOCKS.setdefault(project_id, asyncio.Lock())
    await render_lock.acquire()
    try:
        if _LATEST_PREVIEW_VIDEO_KEYS.get(project_id) != cache.key:
            raise PreviewVideoRenderSuperseded(
                "true preview render was superseded by a newer Grade Graph"
            )
        cached = load_cached_preview_video(cache)
        if cached is not None:
            await job_manager.complete(
                job_id,
                {
                    "project_id": project_id,
                    "video_url": (
                        f"/api/projects/{project_id}/preview-videos/"
                        f"{cache.output_video.name}"
                    ),
                    "cache_key": cache.key,
                    "cache_hit": True,
                    "render": cached.get("render", {}),
                    "profile": profile.model_dump(mode="json"),
                },
            )
            return

        await job_manager.update(
            job_id,
            status=JobStatus.RUNNING,
            stage="preview_render",
            progress=1,
            message="Rendering the true graded playback cache",
            device=backend.info.runtime,
        )
        last_progress = -1
        progress_updates = []

        def report_render(completed: int, total: int) -> None:
            nonlocal last_progress
            if _LATEST_PREVIEW_VIDEO_KEYS.get(project_id) != cache.key:
                raise PreviewVideoRenderSuperseded(
                    "true preview render was superseded by a newer Grade Graph"
                )
            progress = 2 + round(completed / max(total, 1) * 96)
            if progress <= last_progress:
                return
            last_progress = progress
            coroutine = job_manager.update(
                job_id,
                stage="preview_render",
                progress=progress,
                message=f"Rendered {completed}/{total} true preview frames",
                device=backend.info.runtime,
            )
            try:
                progress_updates.append(
                    asyncio.run_coroutine_threadsafe(coroutine, loop)
                )
            except RuntimeError:
                coroutine.close()

        result = await asyncio.to_thread(
            VideoRenderer(backend).render,
            source,
            cache.output_video,
            graph,
            batch_size=batch_size,
            bit_depth=bit_depth,
            progress=report_render,
            maximum_width=maximum_width,
            maximum_height=maximum_height,
            target_fps=target_fps,
            verify_mask_storage=False,
        )
        if progress_updates:
            await asyncio.gather(
                *(asyncio.wrap_future(update) for update in progress_updates)
            )
        render_payload = asdict(result)
        await asyncio.to_thread(
            save_cached_preview_video,
            cache,
            render=render_payload,
            profile=profile.model_dump(mode="json"),
        )
        await job_manager.complete(
            job_id,
            {
                "project_id": project_id,
                "video_url": (
                    f"/api/projects/{project_id}/preview-videos/"
                    f"{cache.output_video.name}"
                ),
                "cache_key": cache.key,
                "cache_hit": False,
                "render": render_payload,
                "profile": profile.model_dump(mode="json"),
            },
        )
    except Exception as exc:
        await job_manager.fail(job_id, exc)
    finally:
        render_lock.release()


async def _preview_video_segment_task(
    *,
    job_id: str,
    project_id: str,
    source: Path,
    graph: GradeGraph,
    cache: PreviewVideoSegmentCacheEntry,
    maximum_width: int,
    maximum_height: int,
    target_fps: float,
    bit_depth: int,
    profile: PreviewPlaybackProfile,
    batch_size: int,
    request_epoch: int,
) -> None:
    loop = asyncio.get_running_loop()
    backend = compute_backend()
    render_lock = _PREVIEW_VIDEO_RENDER_LOCKS.setdefault(project_id, asyncio.Lock())
    await render_lock.acquire()

    def ensure_current_request() -> None:
        if (
            _LATEST_PREVIEW_SEGMENT_GROUP_KEYS.get(project_id) != cache.group_key
            or _PREVIEW_SEGMENT_REQUEST_EPOCHS.get(project_id, 0) != request_epoch
        ):
            raise PreviewVideoRenderSuperseded(
                "preview segment was superseded by a newer playback position or Grade Graph"
            )

    segment_payload = {
        "start_seconds": cache.start_seconds,
        "end_seconds": cache.end_seconds,
        "group_key": cache.group_key,
    }
    try:
        ensure_current_request()
        cached = load_cached_preview_video(cache)
        if cached is not None:
            await job_manager.complete(
                job_id,
                {
                    "project_id": project_id,
                    "video_url": (
                        f"/api/projects/{project_id}/preview-videos/"
                        f"{cache.output_video.name}"
                    ),
                    "cache_key": cache.key,
                    "cache_hit": True,
                    "render": cached.get("render", {}),
                    "profile": profile.model_dump(mode="json"),
                    **segment_payload,
                },
            )
            return

        await job_manager.update(
            job_id,
            status=JobStatus.RUNNING,
            stage="preview_segment",
            progress=1,
            message=(
                f"Rendering true preview segment "
                f"{cache.start_seconds:.1f}-{cache.end_seconds:.1f}s"
            ),
            device=backend.info.runtime,
        )
        last_progress = -1
        progress_updates = []

        def report_render(completed: int, total: int) -> None:
            nonlocal last_progress
            ensure_current_request()
            progress = min(98, 2 + round(completed / max(total, 1) * 96))
            if progress <= last_progress:
                return
            last_progress = progress
            coroutine = job_manager.update(
                job_id,
                stage="preview_segment",
                progress=progress,
                message=f"Rendered {completed}/{total} true preview segment frames",
                device=backend.info.runtime,
            )
            try:
                progress_updates.append(
                    asyncio.run_coroutine_threadsafe(coroutine, loop)
                )
            except RuntimeError:
                coroutine.close()

        result = await asyncio.to_thread(
            VideoRenderer(backend).render,
            source,
            cache.output_video,
            graph,
            batch_size=batch_size,
            bit_depth=bit_depth,
            progress=report_render,
            maximum_width=maximum_width,
            maximum_height=maximum_height,
            target_fps=target_fps,
            start_time_seconds=cache.start_seconds,
            end_time_seconds=cache.end_seconds,
            include_audio=False,
            verify_mask_storage=False,
        )
        if progress_updates:
            await asyncio.gather(
                *(asyncio.wrap_future(update) for update in progress_updates)
            )
        ensure_current_request()
        render_payload = asdict(result)
        await asyncio.to_thread(
            save_cached_preview_video,
            cache,
            render=render_payload,
            profile=profile.model_dump(mode="json"),
        )
        await job_manager.complete(
            job_id,
            {
                "project_id": project_id,
                "video_url": (
                    f"/api/projects/{project_id}/preview-videos/"
                    f"{cache.output_video.name}"
                ),
                "cache_key": cache.key,
                "cache_hit": False,
                "render": render_payload,
                "profile": profile.model_dump(mode="json"),
                **segment_payload,
            },
        )
    except Exception as exc:
        await job_manager.fail(job_id, exc)
    finally:
        render_lock.release()


async def _render_task(
    *,
    job_id: str,
    project_id: str,
    request: RenderRequest,
) -> None:
    loop = asyncio.get_running_loop()
    store = project_store()
    try:
        project = store.get(project_id)
        graph = store.load_graph(project_id)
        source = _source_path(project_id)
        output = project.outputs_dir / request.filename
        backend = compute_backend()
        await job_manager.update(
            job_id,
            status=JobStatus.RUNNING,
            stage="render",
            progress=10,
            message=(
                "Rendering 10-bit Main10 master in FP32"
                if request.bit_depth == 10
                else "Rendering 8-bit delivery video"
            ),
            device=backend.info.runtime,
        )
        last_progress = -1

        def report_render(completed: int, total: int) -> None:
            nonlocal last_progress
            progress = 10 + round(completed / max(total, 1) * 70)
            if progress <= last_progress:
                return
            last_progress = progress
            coroutine = job_manager.update(
                job_id,
                stage="render",
                progress=progress,
                message=f"Rendered {completed}/{total} frames",
                device=backend.info.runtime,
            )
            loop.call_soon_threadsafe(asyncio.create_task, coroutine)

        result = await asyncio.to_thread(
            VideoRenderer(backend).render,
            source,
            output,
            graph,
            batch_size=request.batch_size,
            bit_depth=request.bit_depth,
            progress=report_render,
        )
        await job_manager.update(
            job_id,
            stage="verify",
            progress=84,
            message="Running hard technical quality checks",
            device="cpu",
        )
        report = await asyncio.to_thread(
            analyze_video_quality,
            source,
            output,
            graph=graph,
        )
        verifier_actions: list[str] = []
        verifier_summary: dict[str, object] = {
            "objective_ids": [],
            "evaluations": 0,
            "accepted_rounds": 0,
            "rollback_count": 0,
            "attempt_decisions": {},
        }
        objective_ids = repairable_objective_ids(report)
        if objective_ids and request.repair_evaluation_budget > 0:
            await job_manager.update(
                job_id,
                stage="repair",
                progress=90,
                message=(
                    "Running bounded responsibility ablation and scoped repair search"
                ),
                device=backend.info.runtime,
            )
            repair_paths: set[Path] = set()
            repair_renders: dict[str, object] = {}
            repair_renderer = VideoRenderer(backend)

            def evaluate_repair(candidate_graph: GradeGraph) -> QualityReport:
                digest = graph_digest(candidate_graph)
                candidate_output = project.outputs_dir / (
                    f".{output.stem}-repair-{job_id[:8]}-{digest[:16]}.mp4"
                )
                repair_paths.add(candidate_output)
                candidate_render = repair_renderer.render(
                    source,
                    candidate_output,
                    candidate_graph,
                    batch_size=request.batch_size,
                    bit_depth=request.bit_depth,
                )
                repair_renders[str(candidate_output.resolve())] = candidate_render
                return analyze_video_quality(
                    source,
                    candidate_output,
                    graph=candidate_graph,
                )

            try:
                repair_search = await asyncio.to_thread(
                    search_technical_repairs,
                    graph,
                    report,
                    evaluate_repair,
                    policy=RepairPolicy(
                        evaluation_budget=request.repair_evaluation_budget,
                        maximum_rounds=request.repair_maximum_rounds,
                        maximum_ablation_nodes=max(
                            1,
                            min(2, request.repair_evaluation_budget - 1),
                        ),
                        beam_width=1,
                    ),
                )
                decision_counts = {
                    decision.value: sum(
                        attempt.decision == decision
                        for attempt in repair_search.attempts
                    )
                    for decision in RepairAttemptDecision
                    if any(
                        attempt.decision == decision
                        for attempt in repair_search.attempts
                    )
                }
                verifier_summary = {
                    "objective_ids": list(repair_search.objective_ids),
                    "evaluations": repair_search.evaluations,
                    "accepted_rounds": repair_search.accepted_rounds,
                    "rollback_count": repair_search.rollback_count,
                    "initial_objective_loss": repair_search.initial_objective_loss,
                    "final_objective_loss": repair_search.final_objective_loss,
                    "attempt_decisions": decision_counts,
                    "scope": asdict(repair_search.scope),
                }
                if repair_search.accepted:
                    selected_output = Path(repair_search.report.output_path).resolve()
                    selected_render = repair_renders.get(str(selected_output))
                    if selected_render is None or not selected_output.is_file():
                        raise RuntimeError(
                            "accepted repair has no matching rendered artifact"
                        )
                    await asyncio.to_thread(selected_output.replace, output)
                    result = replace(selected_render, output_path=str(output))
                    repair_search.report.output_path = str(output)
                    graph = repair_search.graph
                    report = repair_search.report
                    verifier_actions = repair_search.actions
                    await asyncio.to_thread(store.save_graph, project, graph)
            finally:
                for candidate_path in repair_paths:
                    if candidate_path.is_file():
                        await asyncio.to_thread(candidate_path.unlink)
        report.metrics["verifier_iterations"] = float(
            1 + int(verifier_summary["accepted_rounds"])
        )
        report.metrics["verifier_evaluations"] = float(
            int(verifier_summary["evaluations"])
        )
        report.metrics["verifier_rollbacks"] = float(
            int(verifier_summary["rollback_count"])
        )
        report_path = project.outputs_dir / "quality_report.json"
        await asyncio.to_thread(
            report_path.write_text,
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        await job_manager.complete(
            job_id,
            {
                "project_id": project_id,
                "video_url": f"/api/projects/{project_id}/outputs/{output.name}",
                "quality_url": f"/api/projects/{project_id}/quality",
                "render": asdict(result),
                "quality": report.model_dump(mode="json"),
                "verifier_actions": verifier_actions,
                "verifier_search": verifier_summary,
            },
        )
    except Exception as exc:
        await job_manager.fail(job_id, exc)


@router.post("/{project_id}/render", response_model=OperationAccepted, status_code=202)
async def render_video(
    project_id: str,
    request: RenderRequest,
) -> OperationAccepted:
    try:
        project_store().load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    job = await job_manager.create(kind="render", project_id=project_id)
    job_manager.spawn(
        _render_task(
            job_id=job.id,
            project_id=project_id,
            request=request,
        )
    )
    return OperationAccepted(
        project_id=project_id,
        job_id=job.id,
        status=job.status,
    )


@router.get("/{project_id}/quality", response_model=QualityReport)
async def get_quality(project_id: str) -> QualityReport:
    try:
        path = project_store().get(project_id).outputs_dir / "quality_report.json"
        return QualityReport.model_validate_json(
            await asyncio.to_thread(path.read_text, encoding="utf-8")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="quality report not found") from exc


@router.post("/{project_id}/export", status_code=201)
async def create_export(project_id: str) -> dict:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    video_candidates = sorted(
        project.outputs_dir.glob("*.mp4"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    quality_path = project.outputs_dir / "quality_report.json"
    package = await asyncio.to_thread(
        export_grade_package,
        graph,
        compute_backend(),
        project.outputs_dir / "package",
        video_path=video_candidates[0] if video_candidates else None,
        quality_report_path=quality_path if quality_path.is_file() else None,
    )
    return {
        **asdict(package),
        "download_url": (
            f"/api/projects/{project_id}/outputs/package/{Path(package.archive_path).name}"
        ),
    }


@router.get("/{project_id}/preview-videos/{filename}")
async def get_preview_video(project_id: str, filename: str) -> FileResponse:
    if (
        Path(filename).name != filename
        or not filename.startswith("graded-playback-")
        or Path(filename).suffix.lower() != ".mp4"
    ):
        raise HTTPException(status_code=400, detail="invalid preview video filename")
    try:
        path = project_store().get(project_id).previews_dir / filename
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="preview video not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/{project_id}/previews/{filename}")
async def get_preview(project_id: str, filename: str) -> FileResponse:
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(Path(filename).suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=400, detail="invalid preview image type")
    try:
        path = project_store().get(project_id).previews_dir / filename
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="preview not found")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/{project_id}/masks/{target}/{frame_index}")
async def get_mask(
    project_id: str,
    target: str,
    frame_index: int,
) -> FileResponse:
    if frame_index < 0 or not target.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid mask address")
    try:
        project = project_store().get(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    path = project.masks_dir / target / f"{frame_index:06d}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="mask not found")
    return FileResponse(path, media_type="image/png")


@router.get("/{project_id}/outputs/{asset_path:path}")
async def get_output(project_id: str, asset_path: str) -> FileResponse:
    try:
        root = project_store().get(project_id).outputs_dir.resolve()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    path = (root / asset_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="output not found")
    return FileResponse(path, filename=path.name)
