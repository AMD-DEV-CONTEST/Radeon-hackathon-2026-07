import pytest

from colorgraph.api.routes import operations
from colorgraph.domain.grade_graph import (
    GradeGraph,
    MaskAsset,
    MediaInfo,
    SpatialKind,
)
from colorgraph.domain.jobs import JobStatus
from colorgraph.services.jobs import JobManager
from colorgraph.storage import ProjectStore


@pytest.mark.asyncio
async def test_unique_job_reuses_active_record_until_it_finishes() -> None:
    manager = JobManager()

    first, first_created = await manager.create_unique(
        kind="masks",
        project_id="project-1",
    )
    await manager.update(first.id, status=JobStatus.RUNNING, progress=25)
    reused, reused_created = await manager.create_unique(
        kind="masks",
        project_id="project-1",
    )

    assert first_created is True
    assert reused_created is False
    assert reused.id == first.id
    active = await manager.find_active(kind="masks", project_id="project-1")
    assert active is not None
    assert active.id == first.id

    await manager.complete(first.id, {})
    replacement, replacement_created = await manager.create_unique(
        kind="masks",
        project_id="project-1",
    )

    assert replacement_created is True
    assert replacement.id != first.id


@pytest.mark.asyncio
async def test_mask_api_returns_existing_active_job_without_spawning_another(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Active Masks")
    store.save_graph(
        project,
        GradeGraph(
            id=f"graph_{project.id}",
            project_id=project.id,
            project_name="Active Masks",
            media=MediaInfo(
                path="source.mov",
                duration_seconds=1,
                width=8,
                height=6,
                fps=24,
                frame_count=24,
                codec="prores",
            ),
        ),
    )
    manager = JobManager()
    existing, _ = await manager.create_unique(
        kind="masks",
        project_id=project.id,
    )
    await manager.update(existing.id, status=JobStatus.RUNNING, progress=42)

    def unexpected_spawn(_coroutine) -> None:
        pytest.fail("an existing mask job must not spawn a duplicate")

    monkeypatch.setattr(operations, "project_store", lambda: store)
    monkeypatch.setattr(operations, "job_manager", manager)
    monkeypatch.setattr(manager, "spawn", unexpected_spawn)

    response = await operations.generate_masks(
        project.id,
        operations.MaskRequest(),
    )
    active = await operations.get_active_mask_job(project.id)

    assert response.job_id == existing.id
    assert response.status == JobStatus.RUNNING
    assert active is not None
    assert active.id == existing.id
    assert active.progress == 42


@pytest.mark.asyncio
async def test_mask_api_reuses_complete_verified_assets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Cached Masks")
    sequence_root = project.masks_dir / "sky"
    sequence_root.mkdir()
    video_path = project.masks_dir / "sky.mkv"
    video_path.write_bytes(b"verified-mask-video")
    graph = GradeGraph(
        id=f"graph_{project.id}",
        project_id=project.id,
        project_name="Cached Masks",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=1,
            width=8,
            height=6,
            fps=24,
            frame_count=24,
            codec="prores",
        ),
        masks=[
            MaskAsset(
                id="mask_sky",
                kind=SpatialKind.SEMANTIC,
                target="sky",
                path=str(sequence_root),
                frame_count=24,
                metadata={
                    "video_path": str(video_path),
                    "frame_count": 24,
                    "file_count": 24,
                    "decode_verified": True,
                    "sequence_sha256": "a" * 64,
                    "video_sha256": "b" * 64,
                },
            )
        ],
    )
    store.save_graph(project, graph)
    manager = JobManager()

    def unexpected_spawn(_coroutine) -> None:
        pytest.fail("verified masks must be reused without spawning inference")

    monkeypatch.setattr(operations, "project_store", lambda: store)
    monkeypatch.setattr(operations, "job_manager", manager)
    monkeypatch.setattr(manager, "spawn", unexpected_spawn)

    response = await operations.generate_masks(
        project.id,
        operations.MaskRequest(targets=["sky"]),
    )
    completed = await manager.get(response.job_id)

    assert response.status == JobStatus.COMPLETED
    assert completed.result is not None
    assert completed.result["cache_hit"] is True
    assert completed.result["inference_frames"] == 0
