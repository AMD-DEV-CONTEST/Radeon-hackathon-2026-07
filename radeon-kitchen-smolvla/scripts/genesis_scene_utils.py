"""
Genesis scene utilities — generic API for loading assets and rendering
with correct OpenGL-compatible coordinate handling.

Coordinate conventions:
    - Genesis world: right-handed, Z-up
    - glTF / GLB:    right-handed, Y-up  (may appear mirrored when loaded)
    - OpenGL image:  origin at bottom-left → needs vertical flip for PNG

Typical usage:
    from genesis_scene_utils import (
        ensure_display, load_mesh, load_franka, set_franka_home,
        render_rgb, save_image,
    )

    ensure_display()
    import genesis as gs
    gs.init(backend=gs.gpu)

    scene = gs.Scene(...)
    kitchen = load_mesh(scene, gs, "kitchen.glb", opengl_correct=True)
    franka  = load_franka(scene, gs, pos=(0, 0, 0))
    cam     = scene.add_camera(...)
    scene.build()
    set_franka_home(franka)

    img = render_rgb(cam)
    save_image(img, "out.png")
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Franka Panda constants (from MJCF model)
# ---------------------------------------------------------------------------
JOINT_NAMES: list[str] = [
    "joint1", "joint2", "joint3", "joint4",
    "joint5", "joint6", "joint7",
    "finger_joint1", "finger_joint2",
]

HOME_QPOS = np.array(
    [0, -0.3, 0, -2.2, 0, 2.0, 0.79, 0.04, 0.04], dtype=np.float32
)

KP = np.array(
    [4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100], dtype=np.float32
)
KV = np.array(
    [450, 450, 350, 350, 200, 200, 200, 10, 10], dtype=np.float32
)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def ensure_display() -> None:
    """Start Xvfb on headless Linux when no DISPLAY is set."""
    if sys.platform == "win32" or os.environ.get("DISPLAY"):
        return
    xvfb = subprocess.run(["which", "Xvfb"], capture_output=True)
    if xvfb.returncode != 0:
        return
    proc = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x1024x24",
         "-ac", "+extension", "GLX"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = ":99"
    time.sleep(2)
    if proc.poll() is None:
        print(f"[display] Xvfb started (PID={proc.pid})")


# ---------------------------------------------------------------------------
# Mesh loading
# ---------------------------------------------------------------------------
def load_mesh(
    scene,
    gs,
    file_path: str | Path,
    *,
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    euler: tuple[float, float, float] | None = None,
    scale: float = 1.0,
    fixed: bool = True,
    collision: bool = False,
    visualization: bool = True,
    decimate: bool = False,
    convexify: bool = False,
    opengl_correct: bool = False,
):
    """Load a mesh file (GLB / OBJ) into a Genesis scene.

    Parameters
    ----------
    opengl_correct : bool
        If True, apply ``euler=(0, 180, 0)`` to fix the orientation of GLB
        meshes that appear upside-down and horizontally mirrored when loaded
        into Genesis.  Rotating 180° around the Y axis flips both X (left/
        right) and Z (up/down), correcting the mismatch between the glTF
        coordinate convention and Genesis's internal rendering without
        requiring any post-render image flip.
        If an explicit *euler* is also provided, *opengl_correct* is ignored.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Mesh not found: {file_path}")

    if euler is None and opengl_correct:
        euler = (0.0, 180.0, 0.0)

    kwargs: dict = dict(
        file=str(file_path),
        pos=pos,
        scale=scale,
        fixed=fixed,
        collision=collision,
        visualization=visualization,
        decimate=decimate,
    )
    if euler is not None:
        kwargs["euler"] = euler
    if convexify:
        kwargs["convexify"] = True

    entity = scene.add_entity(gs.morphs.Mesh(**kwargs))
    tag = "collision" if collision else "visual"
    size_mb = file_path.stat().st_size / (1024 * 1024)
    print(f"[load_mesh] {file_path.name} ({size_mb:.1f} MB) "
          f"pos={pos} euler={euler} scale={scale} [{tag}]")
    return entity


# ---------------------------------------------------------------------------
# Robot loading
# ---------------------------------------------------------------------------
def load_franka(
    scene,
    gs,
    *,
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    euler: tuple[float, float, float] | None = None,
    mjcf_file: str = "xml/franka_emika_panda/panda.xml",
    surface=None,
):
    """Load a Franka Emika Panda robot into the scene.

    Parameters
    ----------
    euler : tuple | None
        Euler angles in degrees ``(rx, ry, rz)``.  Use ``(0, 0, yaw)``
        to rotate the robot around Z (change facing direction).
    surface : gs.surfaces.Surface | None
        Visual surface to apply.  If *None*, the default MJCF material is used.

    Returns the Genesis entity (call ``set_franka_home`` after
    ``scene.build()`` to move it to the home configuration).
    """
    morph_kw: dict = dict(file=mjcf_file, pos=pos)
    if euler is not None:
        morph_kw["euler"] = euler
    kwargs: dict = dict(morph=gs.morphs.MJCF(**morph_kw))
    if surface is not None:
        kwargs["surface"] = surface
    franka = scene.add_entity(**kwargs)
    sname = type(surface).__name__ if surface is not None else "default"
    print(f"[load_franka] pos={pos} euler={euler} surface={sname}")
    return franka


def set_franka_home(franka) -> list[int]:
    """Set Franka to home joint configuration.  Must be called **after**
    ``scene.build()``.

    Returns the motor DOF indices for downstream control.
    """
    motors_dof = [
        franka.get_joint(name).dofs_idx_local[0] for name in JOINT_NAMES
    ]
    franka.set_dofs_position(HOME_QPOS, motors_dof)
    franka.control_dofs_position(HOME_QPOS, motors_dof)
    return motors_dof


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_rgb(cam) -> np.ndarray:
    """Render an RGB frame from a Genesis camera.

    Genesis's rasterizer already outputs images in standard orientation
    (origin at top-left), consistent with PNG / PIL convention.
    No image flip is applied — coordinate mismatches should be fixed at
    the asset loading level (e.g. ``euler`` rotation on the mesh).

    Returns
    -------
    np.ndarray  shape (H, W, 3), dtype uint8
    """
    rgb, _, _, _ = cam.render(
        rgb=True, depth=False, segmentation=False, normal=False,
    )
    arr = rgb.cpu().numpy() if hasattr(rgb, "cpu") else np.array(rgb)
    if arr.ndim == 4:
        arr = arr[0]
    return arr.astype(np.uint8)


def to_numpy(t) -> np.ndarray:
    """Convert a tensor (or array-like) to a 1-D numpy array."""
    arr = t.cpu().numpy() if hasattr(t, "cpu") else np.array(t)
    return arr[0] if arr.ndim > 1 else arr


def lerp(a, b, n: int) -> list[np.ndarray]:
    """Return *n* linearly-interpolated steps from *a* to *b* (exclusive of *a*)."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return [a + (b - a) * (i + 1) / max(n, 1) for i in range(n)]


def mesh_aabb(
    file_path: str | Path,
    *,
    scale: float = 1.0,
    opengl_correct: bool = False,
):
    """Compute axis-aligned bounding box of a GLB/OBJ mesh in Genesis world
    coordinates (approximate).

    Uses ``trimesh`` to load the mesh, then applies the same scale + euler
    transform that ``load_mesh`` would apply.  The result closely matches
    the bounds you would see after ``scene.build()`` in Genesis.

    Returns ``(bbox_min, bbox_max, center)`` — each a length-3 numpy array.
    """
    import trimesh as _tm

    raw = _tm.load(str(file_path), force="mesh", process=False)
    verts = np.array(raw.vertices, dtype=np.float64)

    # glTF is Y-up; Genesis is Z-up.
    # Genesis internally converts: gen_x = glb_x, gen_y = -glb_z, gen_z = glb_y
    verts = verts[:, [0, 2, 1]].copy()
    verts[:, 1] *= -1  # negate new-Y (was glb-Z)

    if opengl_correct:
        # euler=(0, 180, 0) around Genesis Y-axis: x→-x, z→-z
        verts[:, 0] *= -1
        verts[:, 2] *= -1

    verts *= scale

    bbox_min = verts.min(axis=0)
    bbox_max = verts.max(axis=0)
    center = (bbox_min + bbox_max) / 2.0
    return bbox_min, bbox_max, center


def save_image(arr: np.ndarray, path: str | Path) -> None:
    """Save a numpy RGB array as PNG."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        Image.fromarray(arr).save(str(path))
    except ImportError:
        import imageio
        imageio.imwrite(str(path), arr)
    print(f"[save_image] {path}  shape={arr.shape}")
