"""Project-bound synthetic image and video fixtures for local demos."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageOps


ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets" / "demo_multimodal"
SCENE_ASSETS = {
    "demo_a": "demo_a-intersection-v1.jpg",
    "demo_b": "demo_b-scene-v1.jpg",
    "demo_c": "demo_c-scene-v1.jpg",
}
VIDEO_ASSETS = {
    "demo_a": "demo_a-dashcam-v1.mp4",
    "demo_b": "demo_b-dashcam-v1.mp4",
    "demo_c": "demo_c-dashcam-v1.mp4",
}
FRAME_SIZE = (480, 270)


def scene_asset_path(scenario_id: str) -> Path:
    try:
        path = ASSET_ROOT / SCENE_ASSETS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown multimodal scenario: {scenario_id}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def materialize_video_fixture(
    directory: Path,
    scenario_id: str,
) -> tuple[Path, list[Path]]:
    """Copy a browser/QuickTime-compatible MP4 and create its keyframes."""

    directory.mkdir(parents=True, exist_ok=True)
    frame_paths = _write_keyframes(directory, scenario_id)
    try:
        source = ASSET_ROOT / VIDEO_ASSETS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown multimodal scenario: {scenario_id}") from exc
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(source)
    destination = directory / f"{scenario_id}-dashcam-synthetic.mp4"
    shutil.copyfile(source, destination)
    return destination, frame_paths


def materialize_signal_fixture(directory: Path, scenario_id: str) -> Path:
    """Create a distinct signal-context still from the synthetic scene."""

    directory.mkdir(parents=True, exist_ok=True)
    with Image.open(scene_asset_path(scenario_id)) as source:
        normalized = ImageOps.exif_transpose(source).convert("RGB")
        width, height = normalized.size
        signal_context = normalized.crop(
            (width // 5, 0, width * 4 // 5, height * 3 // 5)
        )
        signal_context = ImageOps.fit(
            signal_context,
            (960, 540),
            method=Image.Resampling.LANCZOS,
        )
    destination = directory / f"{scenario_id}-road-signal-synthetic.jpg"
    signal_context.save(
        destination,
        format="JPEG",
        quality=88,
        optimize=True,
    )
    return destination


def _write_keyframes(directory: Path, scenario_id: str) -> list[Path]:
    with Image.open(scene_asset_path(scenario_id)) as source:
        normalized = ImageOps.exif_transpose(source).convert("RGB")
        stage = ImageOps.fit(
            normalized,
            (560, 315),
            method=Image.Resampling.LANCZOS,
        )

    offsets = (
        ((0, 0), (40, 22), (80, 45))
        if scenario_id != "demo_c"
        else ((80, 45), (40, 22), (0, 0))
    )
    paths: list[Path] = []
    width, height = FRAME_SIZE
    for index, (left, top) in enumerate(offsets, start=1):
        frame = stage.crop((left, top, left + width, top + height))
        path = directory / f"{scenario_id}-frame-{index:02d}.jpg"
        frame.save(path, format="JPEG", quality=88, optimize=True)
        paths.append(path)
    return paths
