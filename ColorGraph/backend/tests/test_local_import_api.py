import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from colorgraph.api.routes import projects
from colorgraph.domain.grade_graph import ColorSpace, GradeGraph, MediaInfo
from colorgraph.grading.color import DJI_DLOG_DGAMUT, DJI_MAVIC3_DLOG_REC709
from colorgraph.media.proxy import BrowserProxy
from colorgraph.storage import ProjectStore


@pytest.mark.asyncio
async def test_local_project_import_stages_source_without_upload(tmp_path, monkeypatch) -> None:
    source = tmp_path / "large-prores.mov"
    source.write_bytes(b"local-source")
    store = ProjectStore(tmp_path / "projects")
    spawned = False

    def capture_spawn(coroutine) -> None:
        nonlocal spawned
        spawned = True
        coroutine.close()

    monkeypatch.setattr(projects, "project_store", lambda: store)
    monkeypatch.setattr(projects.job_manager, "spawn", capture_spawn)

    response = await projects.create_local_project(
        projects.LocalProjectRequest(
            media_path=str(source),
            name="Large ProRes",
            input_color_space=ColorSpace.BT709_OETF,
        )
    )

    project = store.get(response.project_id)
    assert spawned
    assert response.status.value == "queued"
    assert store.resolve_source(project).samefile(source)


@pytest.mark.asyncio
async def test_local_project_import_requires_absolute_path() -> None:
    with pytest.raises(HTTPException) as error:
        await projects.create_local_project(projects.LocalProjectRequest(media_path="relative.mov"))

    assert error.value.status_code == 422


def test_dji_dlog_color_management_is_supported() -> None:
    projects._validate_color_management(ColorSpace.LOG, DJI_DLOG_DGAMUT)
    projects._validate_color_management(ColorSpace.LOG, DJI_MAVIC3_DLOG_REC709)

    with pytest.raises(HTTPException) as error:
        projects._validate_color_management(ColorSpace.LOG, "dji_dlogm")

    assert error.value.status_code == 422


def test_ambiguous_legacy_rec709_input_is_rejected_for_new_projects() -> None:
    with pytest.raises(HTTPException) as error:
        projects._validate_color_management(ColorSpace.REC709, None)

    assert error.value.status_code == 422
    assert "bt709_oetf" in error.value.detail


@pytest.mark.asyncio
async def test_project_list_marks_primary_grading_demo(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    demo = store.create("DJI Demo")
    source = demo.input_dir / "source.mov"
    source.write_bytes(b"source")
    store.save_graph(
        demo,
        GradeGraph(
            id=f"graph_{demo.id}",
            project_id=demo.id,
            project_name="DJI Demo",
            media=MediaInfo(
                path=str(source),
                duration_seconds=1,
                width=1920,
                height=1080,
                fps=24,
                frame_count=24,
                codec="prores",
            ),
            metadata={"demo": {"role": "primary_grading_demo"}},
        ),
    )
    monkeypatch.setattr(projects, "project_store", lambda: store)

    summaries = await projects.list_projects()

    assert len(summaries) == 1
    assert summaries[0].project_id == demo.id
    assert summaries[0].is_default_demo


@pytest.mark.asyncio
async def test_existing_project_can_be_reanalyzed_with_dji_transform(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("DJI")
    source = project.input_dir / "source.mov"
    source.write_bytes(b"source")
    store.save_graph(
        project,
        GradeGraph(
            id=f"graph_{project.id}",
            project_id=project.id,
            project_name="DJI",
            media=MediaInfo(
                path=str(source),
                duration_seconds=1,
                width=1920,
                height=1080,
                fps=24,
                frame_count=24,
                codec="prores",
            ),
        ),
    )
    captured: dict[str, object] = {}

    def capture_spawn(coroutine) -> None:
        captured.update(coroutine.cr_frame.f_locals)
        coroutine.close()

    monkeypatch.setattr(projects, "project_store", lambda: store)
    monkeypatch.setattr(projects.job_manager, "spawn", capture_spawn)

    response = await projects.update_color_management(
        project.id,
        projects.ColorManagementRequest(
            input_color_space=ColorSpace.LOG,
            source_log_profile=DJI_MAVIC3_DLOG_REC709,
        ),
    )

    assert response.project_id == project.id
    assert captured["source_path"] == source.resolve()
    assert captured["source_log_profile"] == DJI_MAVIC3_DLOG_REC709


@pytest.mark.asyncio
async def test_project_source_defaults_to_1080p_proxy(tmp_path, monkeypatch) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Preview Quality")
    source = project.input_dir / "source.mov"
    source.write_bytes(b"source")
    store.save_graph(
        project,
        GradeGraph(
            id=f"graph_{project.id}",
            project_id=project.id,
            project_name="Preview Quality",
            media=MediaInfo(
                path=str(source),
                duration_seconds=1,
                width=3840,
                height=2160,
                fps=59.94,
                frame_count=60,
                codec="prores",
            ),
        ),
    )
    captured: dict[str, object] = {}

    def create_proxy(
        source_path,
        destination,
        media,
        **options,
    ) -> BrowserProxy:
        target = destination.resolve()
        target.write_bytes(b"proxy")
        captured.update(options)
        captured["source"] = source_path
        captured["destination"] = target
        captured["media"] = media
        return BrowserProxy(path=target, created=True, encoder="libx264")

    monkeypatch.setattr(projects, "project_store", lambda: store)
    monkeypatch.setattr(projects, "compute_backend", object)
    monkeypatch.setattr(
        projects,
        "select_encoder",
        lambda _, **_options: ("libx264", None),
    )
    monkeypatch.setattr(projects, "create_browser_proxy", create_proxy)

    response = await projects.get_source(project.id)

    assert response.path.name == (
        "browser-proxy-1080p-h264-high-8bit-bt709-limited.mp4"
    )
    assert captured["maximum_width"] == 1920
    assert captured["maximum_height"] == 1080
    assert captured["target_fps"] == 30
    assert captured["high_quality"] is True
    assert captured["codec"] == "h264"
    assert captured["bit_depth"] == 8


@pytest.mark.asyncio
async def test_project_source_requests_4k_hevc_main10_profile(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("HEVC Preview")
    source = project.input_dir / "source.mov"
    source.write_bytes(b"source")
    store.save_graph(
        project,
        GradeGraph(
            id=f"graph_{project.id}",
            project_id=project.id,
            project_name="HEVC Preview",
            media=MediaInfo(
                path=str(source),
                duration_seconds=1,
                width=3840,
                height=2160,
                fps=59.94,
                frame_count=60,
                codec="prores",
            ),
        ),
    )
    captured: dict[str, object] = {}

    def create_proxy(source_path, destination, media, **options) -> BrowserProxy:
        target = destination.resolve()
        target.write_bytes(b"proxy")
        captured.update(options)
        return BrowserProxy(
            path=target,
            created=True,
            encoder="hevc_nvenc",
            codec="hevc",
            codec_profile="main10",
            bit_depth=10,
            pixel_format="yuv420p10le",
            width=3840,
            height=2160,
            fps=30,
        )

    monkeypatch.setattr(projects, "project_store", lambda: store)
    monkeypatch.setattr(projects, "compute_backend", object)
    monkeypatch.setattr(
        projects,
        "select_encoder",
        lambda _, **_options: ("hevc_nvenc", None),
    )
    monkeypatch.setattr(projects, "create_browser_proxy", create_proxy)

    response = await projects.get_source(
        project.id,
        quality="2160p",
        codec="hevc",
        bit_depth=10,
    )

    assert response.path.name == (
        "browser-proxy-2160p-hevc-main10-10bit-bt709-limited.mp4"
    )
    assert response.headers["x-colorgraph-preview-codec"] == "hevc"
    assert response.headers["x-colorgraph-preview-profile"] == "main10"
    assert response.headers["x-colorgraph-preview-bit-depth"] == "10"
    assert response.headers["x-colorgraph-preview-width"] == "3840"
    assert captured["maximum_width"] == 3840
    assert captured["maximum_height"] == 2160
    assert captured["codec"] == "hevc"
    assert captured["bit_depth"] == 10


@pytest.mark.asyncio
async def test_project_source_http_query_coerces_bit_depth(
    tmp_path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("HTTP Preview Query")
    source = project.input_dir / "source.mov"
    source.write_bytes(b"source")
    store.save_graph(
        project,
        GradeGraph(
            id=f"graph_{project.id}",
            project_id=project.id,
            project_name="HTTP Preview Query",
            media=MediaInfo(
                path=str(source),
                duration_seconds=1,
                width=1920,
                height=1080,
                fps=30,
                frame_count=30,
                codec="prores",
            ),
        ),
    )
    captured: dict[str, object] = {}

    def create_proxy(source_path, destination, media, **options) -> BrowserProxy:
        target = destination.resolve()
        target.write_bytes(b"proxy")
        captured.update(options)
        return BrowserProxy(
            path=target,
            created=True,
            encoder="libx264",
            codec="h264",
            codec_profile="high",
            bit_depth=8,
            pixel_format="yuv420p",
            width=1920,
            height=1080,
            fps=30,
        )

    monkeypatch.setattr(projects, "project_store", lambda: store)
    monkeypatch.setattr(projects, "compute_backend", object)
    monkeypatch.setattr(
        projects,
        "select_encoder",
        lambda _, **_options: ("libx264", None),
    )
    monkeypatch.setattr(projects, "create_browser_proxy", create_proxy)
    application = FastAPI()
    application.include_router(projects.router)

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/projects/{project.id}/source",
            params={
                "quality": "1080p",
                "codec": "h264",
                "bit_depth": "8",
            },
        )

    assert response.status_code == 200
    assert captured["bit_depth"] == 8
    assert response.headers["x-colorgraph-preview-codec"] == "h264"
