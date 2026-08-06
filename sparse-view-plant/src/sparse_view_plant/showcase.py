"""Gradio showcase for the sparse-view plant reconstruction pipeline."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tomllib
import traceback
import uuid
from collections import deque
from collections.abc import Generator, MutableMapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

import gradio as gr
import numpy as np
from plyfile import PlyData, PlyElement

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUTS_DIR = REPO_ROOT / "outputs"
DEFAULT_EXAMPLES_MANIFEST = REPO_ROOT / "configs/gradio_examples.toml"
DEFAULT_EXAMPLES_ROOT = REPO_ROOT / "assets/examples"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LiveResult = tuple[str, str | None, str | None, str | None, str | None, str]

SHOWCASE_CSS = """
.gradio-container { max-width: 1440px !important; }
.hero {
  padding: 24px 28px;
  border: 1px solid var(--border-color-primary);
  border-radius: 18px;
  background: linear-gradient(120deg, rgba(24, 132, 82, 0.18), rgba(20, 28, 40, 0.04));
}
.hero h1 { margin: 0 0 8px; font-size: 2.15rem; }
.hero p { margin: 0; color: var(--body-text-color-subdued); }
"""


@dataclass(frozen=True)
class ExamplePhotoGroup:
    """A resolved, read-only group of input photos for the live demo."""

    id: str
    label: str
    source: str
    description: str
    files: tuple[Path, ...]


def load_example_photo_groups(
    manifest_path: Path,
    examples_root: Path = DEFAULT_EXAMPLES_ROOT,
) -> list[ExamplePhotoGroup]:
    """Resolve complete example groups stored with the repository."""
    if not manifest_path.is_file():
        return []
    with manifest_path.open("rb") as handle:
        payload = tomllib.load(handle)

    groups: list[ExamplePhotoGroup] = []
    seen_ids: set[str] = set()
    for raw_group in payload.get("groups", []):
        group_id = str(raw_group["id"])
        if group_id in seen_ids:
            raise ValueError(f"Duplicate Gradio example id: {group_id}")
        seen_ids.add(group_id)

        relative_files = [Path(value) for value in raw_group.get("files", [])]
        if not 3 <= len(relative_files) <= 6:
            raise ValueError(f"Example {group_id!r} must contain 3–6 images")
        for relative_path in relative_files:
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(
                    f"Example {group_id!r} contains an unsafe path: {relative_path}"
                )
            if relative_path.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(
                    f"Example {group_id!r} contains a non-image file: {relative_path}"
                )

        source = str(raw_group["source"])
        root = examples_root.expanduser().resolve()
        resolved_files = tuple((root / path).resolve() for path in relative_files)
        if not root.is_dir() or not all(path.is_file() for path in resolved_files):
            continue
        groups.append(
            ExamplePhotoGroup(
                id=group_id,
                label=str(raw_group["label"]),
                source=source,
                description=str(raw_group.get("description", "")),
                files=resolved_files,
            )
        )
    return groups


def _path_or_none(path: Path) -> str | None:
    return str(path) if path.is_file() else None


# Format version: bump to invalidate cached Model3D PLYs when the writer
# changes (the cache key is derived from the source file, not the writer).
_MODEL3D_PLY_VERSION = 3

# Canvas3DGS renders .ply files as gaussian splats; these constants produce a
# cloud that fills its orbit viewport (~distance 5, focal 1132) with splats of
# a few pixels. Scale values are written in log space (the parser exponentiates
# them); opacity is a logit (the parser applies a sigmoid and scales by 255).
_MODEL3D_CLOUD_DIAGONAL = 1.5
_MODEL3D_SPLAT_SCALE = 0.006
_MODEL3D_OPACITY_LOGIT = 20.0

# Format version for cached 2DGS Model3D PLYs; independent of the point-cloud
# writer version (the cache key is derived from the source file).
_MODEL3D_GAUSSIANS_VERSION = 1


def model3d_compatible_gaussians(source: Path, cache_dir: Path) -> str | None:
    """Center + rescale a splat PLY for the Canvas3DGS orbit camera.

    ``gaussians.ply`` is already a renderable splat cloud (``opacity`` /
    log-space ``scale_*`` / ``rot_*`` properties), so unlike point clouds it
    displays directly in Gradio's Model3D. Only the positions need adjusting:
    VGGT camera-frame geometry sits at an arbitrary scale and offset, while
    the Canvas3DGS orbit camera looks at the world origin from distance 5.
    Every splat attribute is preserved unchanged.
    """
    if not source.is_file():
        return None
    stat = source.stat()
    cache_key = hashlib.sha256(
        (
            f"v{_MODEL3D_GAUSSIANS_VERSION}:{source.resolve()}:"
            f"{stat.st_mtime_ns}:{stat.st_size}"
        ).encode()
    ).hexdigest()[:16]
    target = cache_dir / f"{source.stem}-model3d-{cache_key}.ply"
    if target.is_file():
        return str(target)

    vertices = PlyData.read(source)["vertex"].data
    names = set(vertices.dtype.names or ())
    required = {"x", "y", "z", "opacity", "scale_0", "scale_1", "scale_2"}
    if not required.issubset(names):
        raise ValueError(
            "PLY is not a Canvas3DGS-renderable splat cloud "
            f"(missing {sorted(required - names)}): {source}"
        )
    positions = np.column_stack([vertices[axis] for axis in ("x", "y", "z")])
    centre = positions.mean(axis=0)
    diagonal = float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0)))
    if diagonal > 0:
        positions = (positions - centre) * (_MODEL3D_CLOUD_DIAGONAL / diagonal)
    else:
        positions = positions - centre
    normalized = np.empty_like(vertices)
    normalized[...] = vertices
    for index, axis in enumerate(("x", "y", "z")):
        normalized[axis] = positions[:, index]

    cache_dir.mkdir(parents=True, exist_ok=True)
    PlyData([PlyElement.describe(normalized, "vertex")], text=False).write(target)
    return str(target)


def model3d_compatible_pointcloud(source: Path, cache_dir: Path) -> str | None:
    """Rewrite a point-cloud PLY as a splat PLY that Canvas3DGS can display.

    Gradio's Model3D ignores ``display_mode`` for .ply files and renders them
    with the Canvas3DGS gaussian-splat viewer (the orbit camera looks at the
    world origin from distance 5). A bare x/y/z + colour point cloud has no
    ``opacity`` or ``scale_*`` properties, so every splat is transparent and
    the widget appears black even though the PLY is valid. Normalize the cloud
    to a fixed box around the origin and emit opacity / log-space scales /
    identity rotation so the splats are actually visible.
    """
    if not source.is_file():
        return None
    stat = source.stat()
    cache_key = hashlib.sha256(
        (
            f"v{_MODEL3D_PLY_VERSION}:{source.resolve()}:"
            f"{stat.st_mtime_ns}:{stat.st_size}"
        ).encode()
    ).hexdigest()[:16]
    target = cache_dir / f"{source.stem}-{cache_key}.ply"
    if target.is_file():
        return str(target)

    vertices = PlyData.read(source)["vertex"].data
    names = set(vertices.dtype.names or ())
    if not {"x", "y", "z"}.issubset(names):
        raise ValueError(f"PLY has no xyz vertex properties: {source}")
    positions = np.column_stack([vertices[axis] for axis in ("x", "y", "z")])
    centre = positions.mean(axis=0)
    diagonal = float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0)))
    if diagonal > 0:
        positions = (positions - centre) * (_MODEL3D_CLOUD_DIAGONAL / diagonal)
    else:
        positions = positions - centre
    compatible = np.empty(
        len(vertices),
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("red", "<f4"),
            ("green", "<f4"),
            ("blue", "<f4"),
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
    for index, axis in enumerate(("x", "y", "z")):
        compatible[axis] = positions[:, index]
    for colour in ("red", "green", "blue"):
        compatible[colour] = vertices[colour] if colour in names else 255.0
    compatible["opacity"] = _MODEL3D_OPACITY_LOGIT
    compatible["scale_0"] = np.log(_MODEL3D_SPLAT_SCALE)
    compatible["scale_1"] = np.log(_MODEL3D_SPLAT_SCALE)
    compatible["scale_2"] = np.log(_MODEL3D_SPLAT_SCALE)
    compatible["rot_0"] = 1.0  # identity quaternion (w, x, y, z)
    compatible["rot_1"] = 0.0
    compatible["rot_2"] = 0.0
    compatible["rot_3"] = 0.0

    cache_dir.mkdir(parents=True, exist_ok=True)
    PlyData([PlyElement.describe(compatible, "vertex")], text=False).write(target)
    return str(target)


def ensure_localhost_no_proxy(
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Keep Gradio's startup self-check away from machine-level HTTP proxies."""
    values = os.environ if environment is None else environment
    for key in ("NO_PROXY", "no_proxy"):
        entries = [entry.strip() for entry in values.get(key, "").split(",") if entry]
        for host in ("127.0.0.1", "localhost"):
            if host not in entries:
                entries.append(host)
        values[key] = ",".join(entries)


def configure_local_vggt(
    environment: MutableMapping[str, str] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Path]:
    """Discover an existing local VGGT clone and checkpoint for the demo."""
    values = os.environ if environment is None else environment
    resolved: dict[str, Path] = {}

    configured_source = values.get("VGGT_SRC")
    source_candidates = [
        Path(configured_source).expanduser() if configured_source else None,
        repo_root / "external/vggt",
        repo_root.parent.parent / "Git/vggt",
    ]
    for candidate in source_candidates:
        if candidate is not None and (candidate / "vggt").is_dir():
            source = candidate.resolve()
            values["VGGT_SRC"] = str(source)
            resolved["source"] = source
            break

    configured_checkpoint = values.get("VGGT_CKPT")
    checkpoint_candidates = [
        Path(configured_checkpoint).expanduser() if configured_checkpoint else None,
        repo_root / "models/vggt",
        # Local fallback: the original development checkout keeps weights in
        # its own models/ directory, which the public clone does not ship.
        repo_root.parent / "sparse-view-plant/models/vggt",
    ]
    for candidate in checkpoint_candidates:
        if candidate is not None and (candidate / "model.safetensors").is_file():
            checkpoint = candidate.resolve()
            values["VGGT_CKPT"] = str(checkpoint)
            resolved["checkpoint"] = checkpoint
            break
    return resolved


def _validate_images(files: list[str] | None) -> tuple[bool, str]:
    if not files or not 3 <= len(files) <= 6:
        return False, "Please upload 3–6 images of one plant."
    invalid = [
        Path(path).name
        for path in files
        if Path(path).suffix.lower() not in IMAGE_SUFFIXES
    ]
    if invalid:
        return False, f"Unsupported image files: {', '.join(invalid)}"
    return True, ""


class _QueueWriter:
    """Minimal text stream that forwards pipeline prints to the Gradio worker."""

    def __init__(self, messages: Queue[str | None]) -> None:
        self._messages = messages

    def write(self, value: str) -> int:
        if value:
            self._messages.put(value)
        return len(value)

    def flush(self) -> None:
        return None


def _tail_log(chunks: deque[str]) -> str:
    clean = ANSI_ESCAPE.sub("", "".join(chunks))
    return "\n".join(clean.splitlines()[-120:])


def run_live_reconstruction(
    files: list[str] | None,
    opacity_threshold: float,
    birefnet_trim: bool,
    outputs_dir: Path,
) -> Generator[LiveResult]:
    """Run the pipeline in-process while streaming status and logs to Gradio.

    ``birefnet_trim`` toggles ``gaussians.refine_export_trim=birefnet``:
    exported 2DGS geometry is trimmed to the BiRefNet foreground mask, which
    removes background splats and raises silhouette IoU at a small geometry
    cost (geometry-first runs keep it off).
    """
    valid, reason = _validate_images(files)
    if not valid:
        yield f"### Input required\n{reason}", None, None, None, None, ""
        return

    assert files is not None
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_root = outputs_dir / "gradio_runs" / run_id
    input_dir = run_root / "inputs"
    result_dir = run_root / "result"
    input_dir.mkdir(parents=True, exist_ok=False)
    for index, source_value in enumerate(files):
        source = Path(source_value)
        target = input_dir / f"{index:02d}_{source.name}"
        shutil.copy2(source, target)

    yield (
        f"### Reconstruction running\nRun `{run_id}` is preparing {len(files)} images.",
        None,
        None,
        None,
        None,
        "Starting in-process pipeline…",
    )

    messages: Queue[str | None] = Queue()
    outcome: dict[str, int | str] = {}

    def execute_pipeline() -> None:
        writer = _QueueWriter(messages)
        try:
            from sparse_view_plant.pipeline import reconstruct_plant

            with redirect_stdout(writer), redirect_stderr(writer):
                config_overrides = [
                    (
                        "gaussians.refine_export_opacity_threshold="
                        f"{opacity_threshold:.3f}"
                    ),
                ]
                if birefnet_trim:
                    config_overrides.append("gaussians.refine_export_trim=birefnet")
                outcome["returncode"] = reconstruct_plant(
                    input_dir,
                    result_dir,
                    config_path=(
                        REPO_ROOT / "configs/pipeline_gs_refine_vggt_2dgs.toml"
                    ),
                    config_overrides=config_overrides,
                    stage="all",
                )
        except (Exception, SystemExit):  # noqa: BLE001 - surface model failures in UI
            outcome["error"] = traceback.format_exc()
        finally:
            messages.put(None)

    worker = Thread(target=execute_pipeline, name=f"plant-reconstruction-{run_id}")
    worker.start()
    chunks: deque[str] = deque(maxlen=240)
    while worker.is_alive() or not messages.empty():
        try:
            message = messages.get(timeout=0.25)
        except Empty:
            continue
        if message is None:
            break
        chunks.append(message)
        yield (
            f"### Reconstruction running\nRun `{run_id}` is executing in-process.",
            None,
            None,
            None,
            None,
            _tail_log(chunks),
        )
    worker.join()

    if error := outcome.get("error"):
        chunks.append(str(error))
        yield "### Reconstruction failed", None, None, None, None, _tail_log(chunks)
        return

    log = _tail_log(chunks)
    pointcloud = result_dir / "pointcloud.ply"
    gaussians = result_dir / "gaussians.ply"
    returncode = int(outcome.get("returncode", 1))
    if returncode != 0:
        yield (
            f"### Reconstruction failed\nPipeline returned code {returncode}.",
            None,
            None,
            None,
            None,
            log,
        )
        return
    display_pointcloud = model3d_compatible_pointcloud(
        pointcloud, outputs_dir / "gradio_cache/model3d"
    )
    display_gaussians = model3d_compatible_gaussians(
        gaussians, outputs_dir / "gradio_cache/model3d"
    )
    yield (
        f"### Reconstruction complete\nRun `{run_id}` used {len(files)} images.",
        display_pointcloud,
        _path_or_none(pointcloud),
        _path_or_none(gaussians),
        display_gaussians,
        log,
    )


def build_app(
    outputs_dir: Path | None = None,
    *,
    examples_root: Path = DEFAULT_EXAMPLES_ROOT,
    example_manifest: Path = DEFAULT_EXAMPLES_MANIFEST,
) -> gr.Blocks:
    """Build the Live Reconstruction app without launching a server."""
    run_root = (outputs_dir or DEFAULT_OUTPUTS_DIR).resolve()
    static_paths = [path for path in (examples_root, run_root) if path.is_dir()]
    if static_paths:
        gr.set_static_paths(static_paths)
    example_groups = load_example_photo_groups(example_manifest, examples_root)

    with gr.Blocks(
        title="Sparse View Plant — Live Reconstruction", fill_width=True
    ) as demo:
        gr.HTML(
            """
            <div class="hero">
              <h1>Sparse View Plant</h1>
              <p>3–6 uncalibrated RGB photos → VGGT geometry → surface-aligned
              2D Gaussian refinement.</p>
            </div>
            """
        )
        with gr.Row():
            with gr.Column():
                uploads = gr.File(
                    label="Plant images",
                    file_count="multiple",
                    file_types=["image"],
                    type="filepath",
                    allow_reordering=True,
                )
                if example_groups:
                    gr.Examples(
                        examples=[
                            [[str(path) for path in group.files]]
                            for group in example_groups
                        ],
                        inputs=[uploads],
                        label="Curated photo groups",
                        examples_per_page=6,
                        example_labels=[group.label for group in example_groups],
                    )
            with gr.Column():
                opacity = gr.Slider(
                    0.0,
                    0.8,
                    value=0.5,
                    step=0.05,
                    label="Visual export opacity threshold",
                    info="Use 0.0 for geometry evaluation; 0.5 for the showcase export.",
                )
                birefnet_trim = gr.Checkbox(
                    label="BiRefNet background mask",
                    value=False,
                    info=(
                        "Trim exported 2DGS geometry to the BiRefNet "
                        "foreground mask (removes background splats, "
                        "raises silhouette IoU; geometry-first runs "
                        "keep this off)."
                    ),
                )
                run_button = gr.Button("Reconstruct plant", variant="primary")
        live_status = gr.Markdown("### Waiting for input")
        with gr.Row():
            live_model = gr.Model3D(
                label="Reconstructed point cloud",
                display_mode="point_cloud",
                clear_color=(0.05, 0.07, 0.09, 1.0),
                height=480,
            )
            live_gaussians_model = gr.Model3D(
                label="Refined 2DGS geometry",
                clear_color=(0.05, 0.07, 0.09, 1.0),
                height=480,
            )
        with gr.Row():
            live_pointcloud = gr.File(label="Point cloud PLY")
            live_gaussians = gr.File(label="2DGS PLY")
        live_log = gr.Textbox(
            label="Pipeline log",
            lines=14,
            max_lines=24,
            interactive=False,
        )

        def run_live(
            files: list[str] | None,
            threshold: float,
            use_bg_mask: bool,
        ) -> Generator[LiveResult]:
            yield from run_live_reconstruction(files, threshold, use_bg_mask, run_root)

        acknowledge_run = run_button.click(
            fn=lambda: (
                "### Request received\nValidating inputs before reconstruction.",
                "Request received by the Gradio backend…",
            ),
            inputs=None,
            outputs=[live_status, live_log],
            queue=False,
            show_progress="hidden",
        )
        acknowledge_run.then(
            fn=run_live,
            inputs=[uploads, opacity, birefnet_trim],
            outputs=[
                live_status,
                live_model,
                live_pointcloud,
                live_gaussians,
                live_gaussians_model,
                live_log,
            ],
            concurrency_limit=1,
            concurrency_id="plant-reconstruction",
        )

    return demo.queue(max_size=4, default_concurrency_limit=1)
