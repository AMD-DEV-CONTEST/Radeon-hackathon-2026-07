from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
import numpy as np
import pytest
from PIL import Image
from plyfile import PlyData, PlyElement

import sparse_view_plant.pipeline as pipeline_module
from sparse_view_plant.showcase import (
    build_app,
    configure_local_vggt,
    ensure_localhost_no_proxy,
    load_example_photo_groups,
    model3d_compatible_gaussians,
    model3d_compatible_pointcloud,
    run_live_reconstruction,
)


def test_ensure_localhost_no_proxy_preserves_existing_hosts() -> None:
    environment = {"NO_PROXY": "example.com", "no_proxy": ""}
    ensure_localhost_no_proxy(environment)
    assert environment["NO_PROXY"] == "example.com,127.0.0.1,localhost"
    assert environment["no_proxy"] == "127.0.0.1,localhost"


def test_configure_local_vggt_discovers_workspace_models(tmp_path: Path) -> None:
    repo_root = tmp_path / "Project/sparse-view-plant"
    source = tmp_path / "Git/vggt"
    checkpoint = repo_root / "models/vggt"
    (source / "vggt").mkdir(parents=True)
    checkpoint.mkdir(parents=True)
    (checkpoint / "model.safetensors").touch()
    environment: dict[str, str] = {}

    resolved = configure_local_vggt(environment, repo_root)

    assert resolved == {
        "source": source.resolve(),
        "checkpoint": checkpoint.resolve(),
    }
    assert environment["VGGT_SRC"] == str(source.resolve())
    assert environment["VGGT_CKPT"] == str(checkpoint.resolve())


def test_configure_local_vggt_falls_back_to_sibling_project_models(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "Project/sparse-view-plant-public"
    source = tmp_path / "Git/vggt"
    checkpoint = tmp_path / "Project/sparse-view-plant/models/vggt"
    (source / "vggt").mkdir(parents=True)
    checkpoint.mkdir(parents=True)
    (checkpoint / "model.safetensors").touch()
    environment: dict[str, str] = {}

    resolved = configure_local_vggt(environment, repo_root)

    assert resolved == {
        "source": source.resolve(),
        "checkpoint": checkpoint.resolve(),
    }
    assert environment["VGGT_CKPT"] == str(checkpoint.resolve())


def test_model3d_compatible_pointcloud_emits_canvas3dgs_splat_properties(
    tmp_path: Path,
) -> None:
    vertices = np.array(
        [(0.0, 0.0, 0.0, 10, 20, 30), (1.0, 2.0, 3.0, 40, 50, 60)],
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    source = tmp_path / "pointcloud.ply"
    PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(source)

    result = model3d_compatible_pointcloud(source, tmp_path / "cache")

    assert result is not None
    converted = PlyData.read(result)["vertex"].data
    # Colors are written as floats (Canvas3DGS only reads float/int properties).
    assert converted.dtype["red"].kind == "f"
    assert converted[0]["red"] == 10.0
    # Canvas3DGS renders PLY as splats; without these the widget is all black.
    for name in ("opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_3"):
        assert name in converted.dtype.names
    assert converted[0]["opacity"] > 10.0
    assert converted[0]["scale_0"] == converted[0]["scale_1"]
    assert converted[0]["rot_0"] == 1.0
    assert converted[0]["rot_3"] == 0.0
    # The cloud is centred on the origin and scaled to a fixed diagonal so the
    # Canvas3DGS orbit camera (which looks at the origin) frames it fully.
    expected_diagonal = 1.5
    normalized_diagonal = np.linalg.norm(
        [
            converted["x"].max() - converted["x"].min(),
            converted["y"].max() - converted["y"].min(),
            converted["z"].max() - converted["z"].min(),
        ]
    )
    assert normalized_diagonal == pytest.approx(expected_diagonal)
    assert converted["x"].mean() == pytest.approx(0.0)
    assert converted["y"].mean() == pytest.approx(0.0)
    assert converted["z"].mean() == pytest.approx(0.0)


def test_model3d_compatible_pointcloud_handles_single_point(tmp_path: Path) -> None:
    vertices = np.array(
        [(1.0, 2.0, 3.0, 10, 20, 30)],
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    source = tmp_path / "pointcloud.ply"
    PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(source)

    result = model3d_compatible_pointcloud(source, tmp_path / "cache")

    assert result is not None
    converted = PlyData.read(result)["vertex"].data
    assert converted[0]["x"] == pytest.approx(0.0)
    assert converted[0]["red"] == 10.0


def _splat_ply_path(tmp_path: Path, count: int = 2) -> Path:
    rng = np.random.default_rng(0)
    vertices = np.empty(
        count,
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("nx", "<f4"),
            ("ny", "<f4"),
            ("nz", "<f4"),
            ("f_dc_0", "<f4"),
            ("f_dc_1", "<f4"),
            ("f_dc_2", "<f4"),
            ("opacity", "<f4"),
            ("scale_0", "<f4"),
            ("scale_1", "<f4"),
            ("scale_2", "<f4"),
            ("rot_0", "<f4"),
            ("rot_1", "<f4"),
            ("rot_2", "<f4"),
            ("rot_3", "<f4"),
        ],
    )
    vertices["x"] = rng.uniform(-0.3, 0.6, count)
    vertices["y"] = rng.uniform(-0.4, 0.2, count)
    vertices["z"] = rng.uniform(0.7, 1.3, count)
    vertices["nx"] = 0.0
    vertices["ny"] = 0.0
    vertices["nz"] = 1.0
    vertices["f_dc_0"] = -1.0
    vertices["f_dc_1"] = 0.2
    vertices["f_dc_2"] = 0.3
    vertices["opacity"] = 1.5
    vertices["scale_0"] = -7.0
    vertices["scale_1"] = -6.0
    vertices["scale_2"] = -5.0
    vertices["rot_0"] = 0.9
    vertices["rot_1"] = 0.1
    vertices["rot_2"] = 0.2
    vertices["rot_3"] = 0.3
    source = tmp_path / "gaussians.ply"
    PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(source)
    return source


def test_model3d_compatible_gaussians_centers_and_preserves_splats(
    tmp_path: Path,
) -> None:
    source = _splat_ply_path(tmp_path)

    result = model3d_compatible_gaussians(source, tmp_path / "cache")

    assert result is not None
    converted = PlyData.read(result)["vertex"].data
    expected_diagonal = 1.5
    normalized_diagonal = np.linalg.norm(
        [
            converted["x"].max() - converted["x"].min(),
            converted["y"].max() - converted["y"].min(),
            converted["z"].max() - converted["z"].min(),
        ]
    )
    assert normalized_diagonal == pytest.approx(expected_diagonal)
    assert converted["x"].mean() == pytest.approx(0.0, abs=1e-6)
    assert converted["y"].mean() == pytest.approx(0.0, abs=1e-6)
    assert converted["z"].mean() == pytest.approx(0.0, abs=1e-6)
    # Splat attributes must survive untouched: only positions are normalized.
    original = PlyData.read(source)["vertex"].data
    for name in ("f_dc_0", "opacity", "scale_0", "scale_1", "scale_2"):
        assert converted[name].tolist() == original[name].tolist()
    assert converted["rot_0"].tolist() == original["rot_0"].tolist()
    assert converted["rot_3"].tolist() == original["rot_3"].tolist()


def test_model3d_compatible_gaussians_returns_none_for_missing_file(
    tmp_path: Path,
) -> None:
    result = model3d_compatible_gaussians(tmp_path / "missing.ply", tmp_path / "cache")
    assert result is None


def test_model3d_compatible_gaussians_rejects_non_splat_cloud(tmp_path: Path) -> None:
    vertices = np.array(
        [(0.0, 0.0, 0.0, 10, 20, 30), (1.0, 2.0, 3.0, 40, 50, 60)],
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    source = tmp_path / "pointcloud.ply"
    PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(source)

    with pytest.raises(ValueError, match="splat"):
        model3d_compatible_gaussians(source, tmp_path / "cache")


def test_live_reconstruction_yields_before_pipeline_execution(tmp_path: Path) -> None:
    files = []
    for index in range(3):
        path = tmp_path / f"view-{index}.png"
        Image.new("RGB", (8, 8), "green").save(path)
        files.append(str(path))

    updates = run_live_reconstruction(files, 0.5, False, tmp_path / "outputs")
    status, model, pointcloud, gaussians, gaussians_model, log = next(updates)
    updates.close()

    assert "running" in status
    assert model is pointcloud is gaussians is gaussians_model is None
    assert "Starting in-process pipeline" in log


def test_live_reconstruction_streams_in_process_pipeline(
    tmp_path: Path, monkeypatch
) -> None:
    files = []
    for index in range(3):
        path = tmp_path / f"view-{index}.png"
        Image.new("RGB", (8, 8), "green").save(path)
        files.append(str(path))

    def fake_pipeline(args) -> int:
        print("[pipeline] pointcloud stage")
        args.output.mkdir(parents=True)
        vertices = np.array(
            [(1.0, 2.0, 3.0, 10, 20, 30)],
            dtype=[
                ("x", "<f4"),
                ("y", "<f4"),
                ("z", "<f4"),
                ("red", "u1"),
                ("green", "u1"),
                ("blue", "u1"),
            ],
        )
        PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(
            args.output / "pointcloud.ply"
        )
        print("[pipeline] gaussian stage")
        _splat_ply_path(args.output, count=1)
        return 0

    monkeypatch.setattr(pipeline_module, "run_pipeline", fake_pipeline)
    updates = list(run_live_reconstruction(files, 0.5, False, tmp_path / "outputs"))

    assert "running" in updates[0][0]
    assert any("pointcloud stage" in update[5] for update in updates)
    status, model, pointcloud, gaussians, gaussians_model, log = updates[-1]
    assert "complete" in status
    assert model != pointcloud
    assert model is not None
    assert PlyData.read(model)["vertex"].data.dtype["red"].kind == "f"
    assert pointcloud is not None
    assert gaussians is not None
    assert gaussians_model is not None
    assert PlyData.read(gaussians_model)["vertex"].data.dtype["opacity"].kind == "f"
    assert PlyData.read(gaussians_model)["vertex"].data["x"].mean() == pytest.approx(
        0.0
    )
    assert "gaussian stage" in log


def test_live_reconstruction_toggles_birefnet_export_trim(
    tmp_path: Path, monkeypatch
) -> None:
    files = []
    for index in range(3):
        path = tmp_path / f"view-{index}.png"
        Image.new("RGB", (8, 8), "green").save(path)
        files.append(str(path))
    captured: dict[str, list[str]] = {}

    def fake_reconstruct(
        images,
        output,
        *,
        config_path,
        config_overrides=(),
        stage="all",
    ) -> int:
        captured["overrides"] = list(config_overrides)
        Path(output).mkdir(parents=True)
        vertices = np.array(
            [(1.0, 2.0, 3.0, 10, 20, 30)],
            dtype=[
                ("x", "<f4"),
                ("y", "<f4"),
                ("z", "<f4"),
                ("red", "u1"),
                ("green", "u1"),
                ("blue", "u1"),
            ],
        )
        PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(
            Path(output) / "pointcloud.ply"
        )
        _splat_ply_path(Path(output), count=1)
        return 0

    monkeypatch.setattr(pipeline_module, "reconstruct_plant", fake_reconstruct)

    list(run_live_reconstruction(files, 0.5, True, tmp_path / "outputs"))

    assert "gaussians.refine_export_trim=birefnet" in captured["overrides"]
    assert any(
        override.startswith("gaussians.refine_export_opacity_threshold=")
        for override in captured["overrides"]
    )


def test_load_example_photo_groups_resolves_complete_source(tmp_path: Path) -> None:
    root = tmp_path / "planest"
    group_dir = root / "Rose/ROSE_03_IMAGES"
    group_dir.mkdir(parents=True)
    relative_files = []
    for index in range(3):
        relative = f"Rose/ROSE_03_IMAGES/view-{index}.JPG"
        Image.new("RGB", (8, 8), "green").save(root / relative)
        relative_files.append(relative)
    manifest = tmp_path / "examples.toml"
    manifest.write_text(
        "[[groups]]\n"
        'id = "rose"\n'
        'label = "Rose"\n'
        'source = "planest"\n'
        'description = "Three views"\n'
        f"files = {json.dumps(relative_files)}\n",
        encoding="utf-8",
    )

    groups = load_example_photo_groups(manifest, root)

    assert len(groups) == 1
    assert groups[0].id == "rose"
    assert all(path.is_absolute() for path in groups[0].files)


def test_load_example_photo_groups_skips_incomplete_group(tmp_path: Path) -> None:
    manifest = tmp_path / "examples.toml"
    manifest.write_text(
        "[[groups]]\n"
        'id = "rose"\n'
        'label = "Rose"\n'
        'source = "planest"\n'
        'files = ["a.jpg", "b.jpg", "c.jpg"]\n',
        encoding="utf-8",
    )
    assert load_example_photo_groups(manifest, tmp_path / "examples") == []


def test_build_app_without_showcase_outputs(tmp_path: Path, monkeypatch) -> None:
    static_paths = []
    monkeypatch.setattr(gr, "set_static_paths", static_paths.append)
    examples_root = tmp_path / "examples"
    examples_root.mkdir()

    demo = build_app(tmp_path, examples_root=examples_root)
    config = demo.get_config_file()
    assert config["title"] == "Sparse View Plant — Live Reconstruction"
    assert len(config["components"]) > 10
    assert static_paths == [[examples_root, tmp_path.resolve()]]
    hero = next(
        component
        for component in config["components"]
        if component["type"] == "html" and 'class="hero"' in component["props"]["value"]
    )
    assert "Sparse View Plant" in hero["props"]["value"]
    # Without any curated groups the Examples dataset is omitted entirely.
    assert not any(component["type"] == "dataset" for component in config["components"])
    acknowledgement = next(
        dependency
        for dependency in config["dependencies"]
        if dependency.get("api_name") == "lambda"
    )
    reconstruction = next(
        dependency
        for dependency in config["dependencies"]
        if dependency.get("api_name") == "run_live"
    )
    assert acknowledgement["queue"] is False
    assert reconstruction["trigger_after"] == acknowledgement["id"]


def test_build_app_populates_examples_dataset(tmp_path: Path, monkeypatch) -> None:
    static_paths = []
    monkeypatch.setattr(gr, "set_static_paths", static_paths.append)
    root = tmp_path / "planest"
    group_dir = root / "Rose/ROSE_03_IMAGES"
    group_dir.mkdir(parents=True)
    relative_files = []
    for index in range(3):
        relative = f"Rose/ROSE_03_IMAGES/view-{index}.JPG"
        Image.new("RGB", (8, 8), "green").save(root / relative)
        relative_files.append(relative)
    manifest = tmp_path / "examples.toml"
    manifest.write_text(
        "[[groups]]\n"
        'id = "rose"\n'
        'label = "Rose"\n'
        'source = "planest"\n'
        'description = "Three views"\n'
        f"files = {json.dumps(relative_files)}\n",
        encoding="utf-8",
    )

    demo = build_app(tmp_path, examples_root=root, example_manifest=manifest)
    config = demo.get_config_file()

    dataset = next(
        component
        for component in config["components"]
        if component["type"] == "dataset"
    )
    assert dataset["props"]["label"] == "Curated photo groups"
    assert dataset["props"]["sample_labels"] == ["Rose"]
    assert len(dataset["props"]["samples"]) == 1
    # Clicking an example only fills the File input; the long reconstruction
    # stays behind the Reconstruct button.
    assert any(
        dependency.get("api_name") == "load_example"
        for dependency in config["dependencies"]
    )
