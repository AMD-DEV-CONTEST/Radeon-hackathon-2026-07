from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.agent import color_features_from_analyses, group_consecutive_shots
from colorgraph.api.dependencies import compute_backend, project_store, scene_analyzer
from colorgraph.config import settings
from colorgraph.domain.grade_graph import ColorSpace, GradeGraph, TimeRange
from colorgraph.domain.jobs import JobStatus
from colorgraph.grading.color import SUPPORTED_LOG_PROFILES
from colorgraph.grading.looks import sync_look_instances
from colorgraph.grading.video import select_encoder
from colorgraph.media.color_analysis import analyze_video_color
from colorgraph.media.color_conversion import convert_log_frame_for_display
from colorgraph.media.metadata import apply_color_management_override
from colorgraph.media.probe import probe_media
from colorgraph.media.proxy import (
    BROWSER_PROXY_PRESETS,
    DEFAULT_BROWSER_PROXY_QUALITY,
    BrowserProxyCodec,
    BrowserProxyQuality,
    ProxyCreationError,
    browser_proxy_filename,
    create_browser_proxy,
)
from colorgraph.media.representative_frames import (
    embedding_candidate_paths,
    extract_representative_candidates,
    materialize_representatives,
    quality_representative_sources,
    representative_metadata,
    select_cosine_medoids,
)
from colorgraph.media.shots import detect_shot_ranges
from colorgraph.services.color_pipeline_migration import (
    ColorPipelineMigrationPreview,
    preview_aces2_migration,
)
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.services.jobs import job_manager

router = APIRouter(prefix="/api/projects", tags=["projects"])
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_PROXY_GENERATION_LOCKS: dict[
    tuple[str, BrowserProxyQuality, BrowserProxyCodec, int],
    asyncio.Lock,
] = {}


class ProjectCreation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    job_id: str
    status: JobStatus


class LocalProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_path: str = Field(min_length=1, max_length=32767)
    name: str = Field(default="", max_length=160)
    input_color_space: ColorSpace = ColorSpace.BT709_OETF
    source_log_profile: str | None = None


class ColorManagementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_color_space: ColorSpace = ColorSpace.BT709_OETF
    source_log_profile: str | None = None


class ColorPipelineMigrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str
    is_default_demo: bool
    updated_at: str
    duration_seconds: float
    shot_count: int
    mask_count: int
    source_url: str


def _validate_color_management(
    input_color_space: ColorSpace,
    source_log_profile: str | None,
) -> None:
    if input_color_space == ColorSpace.REC709:
        raise HTTPException(
            status_code=422,
            detail=(
                "ambiguous legacy input_color_space 'rec709'; "
                "use 'bt709_oetf', 'rec1886', or 'srgb'"
            ),
        )
    if input_color_space == ColorSpace.LOG:
        if source_log_profile not in SUPPORTED_LOG_PROFILES:
            supported = ", ".join(sorted(SUPPORTED_LOG_PROFILES))
            raise HTTPException(
                status_code=422,
                detail=f"log input requires source_log_profile to be one of: {supported}",
            )
    elif source_log_profile is not None:
        raise HTTPException(
            status_code=422,
            detail="source_log_profile is only valid for log input",
        )


def _validate_video_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported video type; expected one of {sorted(ALLOWED_VIDEO_SUFFIXES)}",
        )
    return suffix


def _fit_ranges_to_duration(
    ranges: list[TimeRange],
    duration_seconds: float,
) -> list[TimeRange]:
    fitted: list[TimeRange] = []
    for time_range in ranges:
        start = min(time_range.start_seconds, max(0.0, duration_seconds - 0.001))
        end = min(time_range.end_seconds, duration_seconds)
        if end > start:
            fitted.append(TimeRange(start_seconds=start, end_seconds=end))
    if not fitted:
        return [TimeRange(start_seconds=0, end_seconds=max(duration_seconds, 0.001))]
    fitted[-1] = TimeRange(
        start_seconds=fitted[-1].start_seconds,
        end_seconds=max(duration_seconds, fitted[-1].start_seconds + 0.001),
    )
    return fitted


async def _analyze_project(
    *,
    job_id: str,
    project_id: str,
    project_name: str,
    source_path: Path,
    input_color_space: ColorSpace,
    source_log_profile: str | None,
    reference_path: Path | None,
    source_import_mode: str,
) -> None:
    store = project_store()
    project = store.get(project_id)
    try:
        await job_manager.update(
            job_id,
            status=JobStatus.RUNNING,
            stage="decode",
            progress=8,
            message="Probing media streams with FFprobe",
            device="cpu",
        )
        media = await asyncio.to_thread(probe_media, source_path)
        media = apply_color_management_override(
            media,
            input_color_space,
            source_log_profile,
        )

        await job_manager.update(
            job_id,
            stage="proxy",
            progress=12,
            message="正在生成浏览器代理；高码率素材约需 1–3 分钟",
        )
        preferred_encoder, _ = select_encoder(compute_backend())
        proxy = await asyncio.to_thread(
            create_browser_proxy,
            source_path,
            project.input_dir / "browser-proxy.mp4",
            media,
            preferred_encoder=preferred_encoder,
        )
        analysis_path = proxy.path

        await job_manager.update(
            job_id,
            stage="shots",
            progress=24,
            message="Detecting shot boundaries",
        )
        ranges = await asyncio.to_thread(detect_shot_ranges, analysis_path)
        ranges = _fit_ranges_to_duration(ranges, media.duration_seconds)

        await job_manager.update(
            job_id,
            stage="color",
            progress=38,
            message="Analyzing exposure, white balance and lighting changes",
        )
        color_analyses = await asyncio.to_thread(
            analyze_video_color,
            analysis_path,
            ranges,
            input_color_space=input_color_space,
            source_log_profile=source_log_profile,
        )

        await job_manager.update(
            job_id,
            stage="frames",
            progress=52,
            message=f"Extracting multi-frame candidates for {len(ranges)} shots",
        )
        frame_transform = None
        if input_color_space == ColorSpace.LOG:
            analysis_backend = compute_backend()

            def transform_log_candidate(frame_path: Path) -> object:
                return convert_log_frame_for_display(
                    frame_path,
                    analysis_backend,
                    source_log_profile,
                )

            frame_transform = transform_log_candidate

        candidate_sets = await asyncio.to_thread(
            extract_representative_candidates,
            source_path,
            ranges,
            project.frames_dir,
            fps=media.fps,
            frame_transform=frame_transform,
        )
        representative_sources = quality_representative_sources(candidate_sets)
        representative_frames = materialize_representatives(
            candidate_sets,
            representative_sources,
        )
        representative_frame_metadata = representative_metadata(
            candidate_sets,
            representative_sources,
            method="quality_filtered_temporal_fallback",
        )

        scene_analyses = []
        scene_grouping = None
        reference_style = None
        reference_similarities: list[float] = []
        scene_analysis_error: str | None = None
        if settings.enable_scene_model:
            await job_manager.update(
                job_id,
                stage="vision",
                progress=68,
                message="Understanding representative frames with local CLIP",
                device=compute_backend().info.runtime,
            )
            try:
                analyzer = scene_analyzer()
                embedding_paths, _ = embedding_candidate_paths(candidate_sets)
                candidate_embeddings = await asyncio.to_thread(
                    analyzer.embed_images,
                    embedding_paths,
                )
                selection = select_cosine_medoids(
                    candidate_sets,
                    candidate_embeddings,
                )
                representative_frames = materialize_representatives(
                    candidate_sets,
                    selection.source_paths,
                )
                representative_frame_metadata = selection.metadata
                for frame_path in representative_frames:
                    scene_analyses.append(await asyncio.to_thread(analyzer.analyze, frame_path))
                embeddings = selection.shot_embeddings
                scene_grouping = group_consecutive_shots(
                    embeddings,
                    scene_analyses,
                    color_features=color_features_from_analyses(color_analyses),
                )
                if reference_path is not None:
                    reference_style = await asyncio.to_thread(
                        analyzer.rank_look,
                        reference_path,
                    )
                    reference_embedding = await asyncio.to_thread(
                        analyzer.embed_images,
                        [reference_path],
                    )
                    reference_similarities = (
                        (embeddings @ reference_embedding[0].unsqueeze(1)).squeeze(1).tolist()
                    )
            except Exception as exc:
                scene_analysis_error = str(exc)

        await job_manager.update(
            job_id,
            stage="graph",
            progress=78,
            message="Building typed grade graph",
        )
        graph = build_initial_graph(
            project_id=project_id,
            project_name=project_name,
            media=media,
            shot_ranges=ranges,
            representative_frames=representative_frames,
            representative_frame_metadata=representative_frame_metadata,
            color_analyses=color_analyses,
            scene_analyses=scene_analyses,
            scene_groups=(scene_grouping.shot_groups if scene_grouping is not None else None),
            scene_grouping_metadata=(
                scene_grouping.model_dump(mode="json") if scene_grouping is not None else None
            ),
            reference_frame=reference_path,
            reference_style=reference_style,
            reference_similarities=reference_similarities,
        )
        if scene_analysis_error:
            graph.metadata["scene_analysis_error"] = scene_analysis_error
        graph.metadata["source_import"] = {
            "mode": source_import_mode,
            "browser_proxy": (
                {
                    "path": str(proxy.path),
                    "encoder": proxy.encoder,
                }
                if proxy.created
                else None
            ),
        }
        await asyncio.to_thread(store.save_graph, project, graph)
        await job_manager.complete(
            job_id,
            {
                "project_id": project_id,
                "grade_graph_url": f"/api/projects/{project_id}/grade-graph",
                "shots": len(graph.shots),
                "duration_seconds": graph.media.duration_seconds,
            },
        )
    except Exception as exc:
        await job_manager.fail(job_id, exc)


@router.post("", response_model=ProjectCreation, status_code=202)
async def create_project(
    media: Annotated[UploadFile, File()],
    reference_image: Annotated[UploadFile | None, File()] = None,
    name: Annotated[str, Form()] = "ColorGraph Project",
    input_color_space: Annotated[ColorSpace, Form()] = ColorSpace.BT709_OETF,
    source_log_profile: Annotated[str | None, Form()] = None,
) -> ProjectCreation:
    _validate_color_management(input_color_space, source_log_profile)
    suffix = _validate_video_suffix(media.filename or "")
    reference_suffix = (
        Path(reference_image.filename or "").suffix.lower() if reference_image is not None else None
    )
    if reference_suffix is not None and reference_suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported reference image; expected one of {sorted(ALLOWED_IMAGE_SUFFIXES)}",
        )

    store = project_store()
    project = store.create(name)
    source_path = project.input_dir / f"source{suffix}"
    try:
        async with aiofiles.open(source_path, "wb") as output:
            while chunk := await media.read(1024 * 1024):
                await output.write(chunk)
    except Exception:
        raise
    finally:
        await media.close()

    reference_path: Path | None = None
    if reference_image is not None and reference_suffix is not None:
        reference_path = project.input_dir / f"reference{reference_suffix}"
        try:
            async with aiofiles.open(reference_path, "wb") as output:
                while chunk := await reference_image.read(1024 * 1024):
                    await output.write(chunk)
        finally:
            await reference_image.close()

    job = await job_manager.create(kind="analyze", project_id=project.id)
    job_manager.spawn(
        _analyze_project(
            job_id=job.id,
            project_id=project.id,
            project_name=name,
            source_path=source_path,
            input_color_space=input_color_space,
            source_log_profile=source_log_profile,
            reference_path=reference_path,
            source_import_mode="uploaded",
        )
    )
    return ProjectCreation(
        project_id=project.id,
        job_id=job.id,
        status=job.status,
    )


@router.post("/local", response_model=ProjectCreation, status_code=202)
async def create_local_project(request: LocalProjectRequest) -> ProjectCreation:
    _validate_color_management(request.input_color_space, request.source_log_profile)
    candidate = Path(request.media_path).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(status_code=422, detail="media_path must be an absolute local path")
    source = candidate.resolve()
    if not source.is_file():
        raise HTTPException(status_code=404, detail="local media file was not found")
    _validate_video_suffix(source.name)

    project_name = request.name.strip() or source.stem
    store = project_store()
    project = store.create(project_name)
    imported = await asyncio.to_thread(store.import_local_source, project, source)
    job = await job_manager.create(kind="analyze", project_id=project.id)
    job_manager.spawn(
        _analyze_project(
            job_id=job.id,
            project_id=project.id,
            project_name=project_name,
            source_path=imported.path,
            input_color_space=request.input_color_space,
            source_log_profile=request.source_log_profile,
            reference_path=None,
            source_import_mode=imported.mode,
        )
    )
    return ProjectCreation(
        project_id=project.id,
        job_id=job.id,
        status=job.status,
    )


@router.post(
    "/{project_id}/color-management",
    response_model=ProjectCreation,
    status_code=202,
)
async def update_color_management(
    project_id: str,
    request: ColorManagementRequest,
) -> ProjectCreation:
    _validate_color_management(request.input_color_space, request.source_log_profile)
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
        source = store.resolve_source(project)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc

    reference_path = next(
        (
            path
            for path in sorted(project.input_dir.glob("reference.*"))
            if path.is_file() and path.suffix.lower() in ALLOWED_IMAGE_SUFFIXES
        ),
        None,
    )
    source_import = graph.metadata.get("source_import")
    source_import_mode = (
        str(source_import.get("mode", "reanalyzed"))
        if isinstance(source_import, dict)
        else "reanalyzed"
    )
    job = await job_manager.create(kind="analyze", project_id=project.id)
    job_manager.spawn(
        _analyze_project(
            job_id=job.id,
            project_id=project.id,
            project_name=graph.project_name,
            source_path=source,
            input_color_space=request.input_color_space,
            source_log_profile=request.source_log_profile,
            reference_path=reference_path,
            source_import_mode=source_import_mode,
        )
    )
    return ProjectCreation(
        project_id=project.id,
        job_id=job.id,
        status=job.status,
    )


@router.get("", response_model=list[ProjectSummary])
async def list_projects() -> list[ProjectSummary]:
    graphs = await asyncio.to_thread(project_store().list_graphs)
    return [
        ProjectSummary(
            project_id=graph.project_id,
            project_name=graph.project_name,
            is_default_demo=(
                isinstance(graph.metadata.get("demo"), dict)
                and graph.metadata["demo"].get("role") == "primary_grading_demo"
            ),
            updated_at=graph.updated_at.isoformat(),
            duration_seconds=graph.media.duration_seconds,
            shot_count=len(graph.shots),
            mask_count=len(graph.masks),
            source_url=f"/api/projects/{graph.project_id}/source",
        )
        for graph in graphs
    ]


@router.get("/{project_id}/grade-graph", response_model=GradeGraph)
async def get_grade_graph(project_id: str) -> GradeGraph:
    try:
        store = project_store()
        project = store.get(project_id)
        stored = await asyncio.to_thread(store.load_graph, project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    normalized = sync_look_instances(stored)
    if normalized != stored:
        await asyncio.to_thread(store.save_graph, project, normalized)
    return normalized


@router.get(
    "/{project_id}/color-pipeline/migration-preview",
    response_model=ColorPipelineMigrationPreview,
)
async def get_color_pipeline_migration_preview(
    project_id: str,
) -> ColorPipelineMigrationPreview:
    try:
        graph = await asyncio.to_thread(project_store().load_graph, project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc
    return await asyncio.to_thread(preview_aces2_migration, graph)


@router.post(
    "/{project_id}/color-pipeline/migrate",
    response_model=GradeGraph,
)
async def migrate_color_pipeline(
    project_id: str,
    request: ColorPipelineMigrationRequest,
) -> GradeGraph:
    if not request.confirm:
        raise HTTPException(
            status_code=422,
            detail="set confirm=true after reviewing the migration preview",
        )
    store = project_store()
    try:
        project = store.get(project_id)
        graph = await asyncio.to_thread(store.load_graph, project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project or graph not found") from exc

    preview = await asyncio.to_thread(preview_aces2_migration, graph)
    if preview.status == "blocked" or preview.migrated_graph is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "ACES 2 migration is blocked",
                "reasons": preview.blocked_reasons,
            },
        )
    if preview.status == "already_current":
        return graph

    await asyncio.to_thread(
        store.save_graph_revision,
        project,
        graph,
        label="pre-aces-v3",
    )
    await asyncio.to_thread(store.save_graph, project, preview.migrated_graph)
    return preview.migrated_graph


@router.get("/{project_id}/frames/{filename}")
async def get_representative_frame(project_id: str, filename: str) -> FileResponse:
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    try:
        project = project_store().get(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    path = project.frames_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{project_id}/source")
async def get_source(
    project_id: str,
    quality: BrowserProxyQuality = DEFAULT_BROWSER_PROXY_QUALITY,
    codec: BrowserProxyCodec = "h264",
    bit_depth: int = 8,
) -> FileResponse:
    try:
        store = project_store()
        project = store.get(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc

    if (codec, bit_depth) not in {("h264", 8), ("hevc", 10)}:
        raise HTTPException(
            status_code=422,
            detail="H.264 preview must be 8-bit and HEVC preview must be 10-bit",
        )
    preset = BROWSER_PROXY_PRESETS[quality]
    proxy_path = project.input_dir / browser_proxy_filename(quality, codec, bit_depth)
    lock = _PROXY_GENERATION_LOCKS.setdefault(
        (project_id, quality, codec, bit_depth),
        asyncio.Lock(),
    )
    try:
        async with lock:
            source = store.resolve_source(project)
            graph = store.load_graph(project_id)
            preferred_encoder, _ = select_encoder(
                compute_backend(),
                bit_depth=bit_depth,
            )
            proxy = await asyncio.to_thread(
                create_browser_proxy,
                source,
                proxy_path,
                graph.media,
                preferred_encoder=preferred_encoder,
                maximum_width=preset.maximum_width,
                maximum_height=preset.maximum_height,
                target_fps=preset.target_fps,
                high_quality=preset.high_quality,
                codec=codec,
                bit_depth=bit_depth,
            )
    except (FileNotFoundError, OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc
    except ProxyCreationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(
        proxy.path,
        media_type="video/mp4" if proxy.created else None,
        headers={
            "X-ColorGraph-Preview-Quality": quality,
            "X-ColorGraph-Preview-Codec": codec,
            "X-ColorGraph-Preview-Profile": proxy.codec_profile or "",
            "X-ColorGraph-Preview-Bit-Depth": str(proxy.bit_depth or bit_depth),
            "X-ColorGraph-Preview-Width": str(proxy.width or graph.media.width),
            "X-ColorGraph-Preview-Height": str(proxy.height or graph.media.height),
            "X-ColorGraph-Preview-Pixel-Format": proxy.pixel_format or "",
            "X-ColorGraph-Preview-Color-Range": "limited",
            "X-ColorGraph-Preview-Color-Primaries": "bt709",
            "X-ColorGraph-Preview-Color-Transfer": "bt709",
            "X-ColorGraph-Preview-Color-Matrix": "bt709",
        },
    )


@router.get("/{project_id}/device")
async def project_device(project_id: str) -> dict:
    try:
        project_store().get(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return compute_backend().info.model_dump(mode="json")
