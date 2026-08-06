import errno
import json
from pathlib import Path

from colorgraph.domain.grade_graph import (
    LEGACY_GRADE_GRAPH_SCHEMA_VERSION,
    LEGACY_RENDERER_VERSION,
    MetadataSource,
)
from colorgraph.storage import ProjectStore


def test_project_store_creates_scoped_directories(tmp_path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Alpine Escape")
    assert project.root.parent == tmp_path.resolve()
    assert project.frames_dir.is_dir()
    assert project.outputs_dir.is_dir()


def test_project_store_hardlinks_local_source(tmp_path) -> None:
    source = tmp_path / "camera-original.mov"
    source.write_bytes(b"prores-placeholder")
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Local ProRes")

    imported = store.import_local_source(project, source)

    assert imported.mode == "hardlink"
    assert imported.path.parent == project.input_dir
    assert imported.path.samefile(source)
    assert store.resolve_source(project).samefile(source)


def test_project_store_references_cross_volume_source(tmp_path, monkeypatch) -> None:
    source = tmp_path / "camera-original.mov"
    source.write_bytes(b"prores-placeholder")
    store = ProjectStore(tmp_path / "projects")
    project = store.create("External ProRes")

    def fail_hardlink(_: Path, __: Path) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr("colorgraph.storage.projects.os.link", fail_hardlink)
    imported = store.import_local_source(project, source)

    assert imported.mode == "external_reference"
    assert imported.path == source.resolve()
    assert store.resolve_source(project) == source.resolve()
    reference = json.loads(
        (project.input_dir / "source-reference.json").read_text(encoding="utf-8")
    )
    assert reference["path"] == str(source.resolve())


def test_project_store_loads_v1_graph_with_legacy_renderer(tmp_path) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Legacy Graph")
    project.graph_path.write_text(
        json.dumps(
            {
                "schema_version": LEGACY_GRADE_GRAPH_SCHEMA_VERSION,
                "id": "legacy-graph",
                "project_id": project.id,
                "project_name": "Legacy Graph",
                "working_color_space": "linear_rec709",
                "output_color_space": "rec709",
                "media": {
                    "path": "source.mp4",
                    "duration_seconds": 1,
                    "width": 1920,
                    "height": 1080,
                    "fps": 24,
                    "frame_count": 24,
                    "codec": "h264",
                    "input_color_space": "rec709",
                },
            }
        ),
        encoding="utf-8",
    )

    graph = store.load_graph(project.id)

    assert graph.renderer_version == LEGACY_RENDERER_VERSION
    assert graph.media.metadata_evidence.input_color_space.source == MetadataSource.DEFAULT
    assert graph.media.metadata_evidence.input_color_space.reported_values == ["rec709"]
    store.save_graph(project, graph)
    assert store.load_graph(project.id).renderer_version == LEGACY_RENDERER_VERSION


def test_project_store_relocates_frozen_windows_project_paths(tmp_path) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Portable Graph")
    source = project.input_dir / "source.mp4"
    source.write_bytes(b"source")
    frame = project.frames_dir / "shot_001.jpg"
    frame.write_bytes(b"frame")
    sequence = project.masks_dir / "sky"
    sequence.mkdir()
    video = project.masks_dir / "sky.mkv"
    video.write_bytes(b"mask-video")
    frozen_root = rf"C:\frozen\colorgraph\{project.id}"
    project.graph_path.write_text(
        json.dumps(
            {
                "schema_version": LEGACY_GRADE_GRAPH_SCHEMA_VERSION,
                "id": "portable-graph",
                "project_id": project.id,
                "project_name": "Portable Graph",
                "working_color_space": "linear_rec709",
                "output_color_space": "rec709",
                "media": {
                    "path": rf"{frozen_root}\input\source.mp4",
                    "duration_seconds": 1,
                    "width": 1920,
                    "height": 1080,
                    "fps": 24,
                    "frame_count": 24,
                    "codec": "h264",
                    "input_color_space": "rec709",
                },
                "scenes": [
                    {
                        "id": "scene_001",
                        "index": 0,
                        "label": "Scene 1",
                        "shot_ids": ["shot_001"],
                    }
                ],
                "shots": [
                    {
                        "id": "shot_001",
                        "scene_id": "scene_001",
                        "index": 0,
                        "time_range": {"start_seconds": 0, "end_seconds": 1},
                        "representative_frame": (
                            rf"{frozen_root}\frames\shot_001.jpg"
                        ),
                    }
                ],
                "masks": [
                    {
                        "id": "mask_sky",
                        "kind": "semantic",
                        "target": "sky",
                        "path": rf"{frozen_root}\masks\sky",
                        "frame_count": 24,
                        "metadata": {
                            "video_path": rf"{frozen_root}\masks\sky.mkv",
                            "source_path": rf"{frozen_root}\input\source.mp4",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    graph = store.load_graph(project.id)

    assert graph.media.path == str(source.resolve())
    assert graph.shots[0].representative_frame == str(frame.resolve())
    assert graph.masks[0].path == str(sequence.resolve())
    assert graph.masks[0].metadata["video_path"] == str(video.resolve())
    assert graph.masks[0].metadata["source_path"] == str(source.resolve())
