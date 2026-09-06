"""Build a SO101 manipulation scene with a green workspace and colored cubes."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from genesis.options.vis import DirectionalLight
from genesis.utils.geom import euler_to_R
from scipy.spatial.transform import Rotation as _Rot

# --- Paths -------------------------------------------------------------------

SO101_URDF = Path(__file__).resolve().parent.parent / "assets" / "so101" / "so101_north.urdf"


def default_policy_device() -> str:
    """Torch device string for policy inference, resolved per machine.

    Separate from ``default_backend``: that one picks Genesis' physics backend, this one picks
    where the ACT network runs. ROCm reports itself as ``cuda``, which is correct here (unlike
    for Genesis, see ``default_backend``). Hardcoding "mps" made every evaluation script fail
    on Linux inside LeRobot's ``get_safe_torch_device``.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def default_backend(force_cpu: bool = False):
    """Pick a Genesis compute backend that is known to simulate this scene correctly.

    Two lessons are baked in here, both learned the hard way on a Radeon host:

    1. **Ask for ``gs.gpu`` and let Genesis resolve the device.** On the Radeon Cloud host it
       resolves to ``gs.amdgpu``, and training, rendering and closed-loop evaluation all run
       there. This is also what the Track 3 reference demo does.
    2. **Never name ``gs.cuda``, and do not trust torch to tell you.** ROCm reuses torch's
       CUDA API, so ``torch.cuda.is_available()`` returns **True** — while Genesis computes
       through Taichi, which has no HIP path, and rejects the backend with
       "Torch device 'cuda' not available".

    Known limitation: the many-episode data-collection loop (scripted expert + per-episode
    domain randomisation) has shown contact instability on the ROCm backend — the rake grasp
    flicks the cube off the table. Single-episode ``grasp_demo_so101`` and closed-loop policy
    evaluation are fine there; the submitted datasets were collected on Apple silicon. Pass
    ``force_cpu`` or set ``SO101_GENESIS_BACKEND=cpu`` if you hit it while collecting.

    Override with ``SO101_GENESIS_BACKEND=gpu|amdgpu|cuda|cpu|metal`` to experiment.
    """
    import os

    import genesis as gs

    if force_cpu:
        return gs.cpu

    override = os.environ.get("SO101_GENESIS_BACKEND", "").strip().lower()
    if override:
        chosen = {"cpu": gs.cpu, "gpu": gs.gpu, "cuda": gs.cuda,
                  "amdgpu": gs.amdgpu, "metal": gs.metal}.get(override)
        if chosen is None:
            raise ValueError(f"SO101_GENESIS_BACKEND={override!r} is not a Genesis backend")
        return chosen

    try:
        import platform
        import torch
        if platform.system() == "Darwin" and getattr(torch.backends, "mps", None) \
                and torch.backends.mps.is_available():
            return gs.metal                      # verified: results were produced with this
        if torch.cuda.is_available():
            # gs.gpu, not gs.amdgpu/gs.cuda: let Genesis resolve the device itself. This is
            # what the Track 3 reference demo uses and what works on the Radeon host.
            return gs.gpu
    except Exception:
        pass
    return gs.cpu

# --- Workspace geometry ------------------------------------------------------
# Real rig: circular green table with a thin silver rim, dark floor around it.
# The green disk is large enough that the top-down world cam sees green to the
# corners (corner distance at 0.58 m / FOV 52° ≈ 0.47 m < TABLE_RADIUS).

WORKSPACE_COLOR = (0.22, 0.60, 0.43, 1.0)   # green matching the real table
FLOOR_COLOR     = (0.08, 0.08, 0.09, 1.0)   # dark floor beyond the table
TABLE_RADIUS    = 0.50                        # green disk radius
TABLE_RIM_RADIUS = 0.515                      # silver rim slightly wider
TABLE_RIM_COLOR = (0.62, 0.63, 0.65, 1.0)
TABLE_H         = 0.04                        # disk thickness
WORKSPACE_Z     = 0.005                       # table-top surface Z (above floor plane)

# --- Robot -------------------------------------------------------------------

SO101_POS   = (0.0, -0.20, WORKSPACE_Z)       # base directly on the table surface
SO101_EULER = (0.0,  0.0,  0.0)          # rotation baked into so101_north.urdf (+90° Z)
# home qpos: upper arm folded back + elbow folded → compact zigzag rest pose,
# finger tips +4 cm above the table.
# [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper]
SO101_HOME_QPOS = np.array([0.0, -1.2, 1.3, 0.9, 0.0, 0.0])
# observe qpos: shoulder raised / elbow folded so finger tips clear the table
# (~6 cm clearance, tool axis near straight down → good wrist cam view)
SO101_OBS_QPOS  = np.array([0.0, -0.9, 1.0, 1.0, 0.0, 0.3])

# --- Objects -----------------------------------------------------------------

CUBE_SIZE       = (0.040, 0.040, 0.040)
# Pulled toward the robot (base at y=-0.20) so the grasp happens well inside the
# arm's reach envelope — tracking is stiffer and the tool stays near vertical.
CUBE_POS        = (0.02, 0.00, WORKSPACE_Z + CUBE_SIZE[2] / 2)
CUBE_COLOR_RED  = (0.85, 0.12, 0.12, 1.0)
CUBE_COLOR_BLUE = (0.12, 0.18, 0.85, 1.0)

# DR: list of candidate cube colors cycled per episode
CUBE_COLOR_PALETTE = [
    (0.85, 0.12, 0.12, 1.0),  # red
    (0.12, 0.18, 0.85, 1.0),  # blue
    (0.15, 0.70, 0.20, 1.0),  # green
    (0.90, 0.70, 0.05, 1.0),  # yellow
]

TARGET_SIZE   = (0.11, 0.11, 0.0008)          # essentially flat (printed sheet look)
TARGET_COLOR  = (0.95, 0.95, 0.95, 1.0)
TARGET_BORDER = 0.010                         # black border width on each side
TARGET_BORDER_COLOR = (0.05, 0.05, 0.05, 1.0)
# Flat printed-sheet look: black border lies on the table, white square sits
# a fraction of a mm above it (enough to avoid z-fighting, no visible height).
# Single frame on the RIGHT of the world-cam view (screen right = +x), pulled
# toward the robot so placing stays well inside the reach envelope.
_TBH = TARGET_SIZE[2]                         # border sheet thickness = same as target
TARGET_BORDER_POS = (0.13, 0.00, WORKSPACE_Z + _TBH / 2)
TARGET_POS        = (0.13, 0.00, WORKSPACE_Z + _TBH + TARGET_SIZE[2] / 2)

# --- Walls (front/back/left/right only; no ceiling; floor stays green) -------
# WALL_HALF = 1.20: at cam height 0.70m + FOV 55°, half-view = 0.70*tan(27.5°)≈0.36m
# → walls at 1.20m are well outside the overhead cam frame
WALL_COLOR = (0.20, 0.20, 0.20, 1.0)
WALL_H     = 0.80   # tall enough to fill wrist-cam FOV
WALL_T     = 0.02   # thickness
WALL_HALF  = 1.20   # distance from center to each wall face
WALL_CY    = WALL_H / 2

# --- Cameras -----------------------------------------------------------------

WORLD_CAM_RES    = (640, 480)
# Shifted +y so arm base (y=-0.20) appears near bottom edge of frame
WORLD_CAM_POS    = (0.0, 0.00, 0.58)
WORLD_CAM_LOOKAT = (0.0, 0.00, 0.0)
WORLD_CAM_FOV    = 52

WRIST_CAM_RES              = (640, 480)
WRIST_CAM_FOV              = 100         # wide angle, plain pinhole lens (no distortion)
WRIST_CAM_NEAR             = 0.01
WRIST_CAM_FAR              = 1.5
WRIST_CAM_LINK             = "gripper_link"
# Camera mounted above/behind the gripper looking along the tool direction, so
# both finger tips appear symmetric at the bottom of the frame (matches real rig).
WRIST_CAM_UP_OFFSET        = 0.060   # metres along camera-up (closer → fingers appear larger)
WRIST_CAM_BACK_OFFSET      = -0.02   # metres opposite the tool direction (negative = ahead of wrist, keeps arm out of frame)
WRIST_CAM_LOOKAT_DIST      = 0.08    # metres past finger tips (small → finger tips near frame centre)


# --- Scene bundle ------------------------------------------------------------

@dataclass
class SceneBundleSO101:
    scene:     gs.Scene
    robot:     gs.RigidEntity
    cube:      gs.RigidEntity
    target:    gs.RigidEntity
    table:     "gs.RigidEntity | None" = None   # green tabletop (runtime friction DR:
                                                # contact friction is max() over the pair,
                                                # so the support surface must scale too)
    world_cam: "gs.vis.camera.Camera | None" = None
    wrist_cam: "gs.vis.camera.Camera | None" = None
    _wrist_link: "gs.RigidLink | None" = None

    def update_wrist_cam(self) -> None:
        if self.wrist_cam is None or self._wrist_link is None:
            return
        link = self._wrist_link
        pos = np.array(link.get_pos().tolist())
        q = link.get_quat().tolist()                    # Genesis WXYZ
        q_xyzw = [q[1], q[2], q[3], q[0]]
        R = _Rot.from_quat(q_xyzw).as_matrix()

        # Lens faces along arm approach direction (-local_Z = tool direction).
        # UP is the link-fixed local +Y axis: it equals the previous world-referenced
        # construction away from vertical, but never degenerates when the tool points
        # straight down (the old world-up cross product flipped sign frame-to-frame
        # there, mirroring the image during transport).
        cam_fwd = -R[:, 2]   # arm approach / tool direction
        up = R[:, 1]         # rigidly mounted camera: up rotates with the wrist
        finger_tip = pos + 0.098 * cam_fwd
        lookat = finger_tip + WRIST_CAM_LOOKAT_DIST * cam_fwd
        # Mount above/behind the gripper: fingers appear at the bottom of frame.
        cam_pos = pos + WRIST_CAM_UP_OFFSET * up - WRIST_CAM_BACK_OFFSET * cam_fwd
        self.wrist_cam.set_pose(pos=cam_pos, lookat=lookat, up=up)

    def render(self, *, rgb: bool = True, depth: bool = False) -> dict:
        out = {}
        if self.world_cam is not None:
            out["world"] = self.world_cam.render(rgb=rgb, depth=depth)
        if self.wrist_cam is not None:
            out["wrist"] = self.wrist_cam.render(rgb=rgb, depth=depth)
        return out


# --- Builder -----------------------------------------------------------------

def build_scene_so101(
    *,
    show_viewer:    bool = False,
    add_world_cam:  bool = True,
    add_wrist_cam:  bool = True,
    cube_color:     tuple = CUBE_COLOR_RED,
    bg_color:       tuple = WORKSPACE_COLOR,
    ambient:        float = 0.70,     # DR knob: ambient fill level
    light_intensity: float = 1.6,     # DR knob: top-down directional light
) -> SceneBundleSO101:

    scene = gs.Scene(
        # substeps=4: finer contact integration — with 2, thin-finger contacts are
        # chaotic and grasps randomly fail (verified 5/5 vs ~2/5 grasp holds).
        sim_options=gs.options.SimOptions(dt=0.01, substeps=4),
        rigid_options=gs.options.RigidOptions(
            dt=0.01,
            constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            enable_joint_limit=True,
            # Stiffer, more accurate contacts for grasping (defaults let the fingers
            # sink visibly into the cube and the grip slowly slips):
            constraint_timeconst=0.005,   # harder contact (min 2x substep dt)
            iterations=100,               # more solver iterations per step
            noslip_iterations=10,         # suppress tangential grip slip (measured:
                                          # in-grip transport drift 1.3mm@5 -> 0.2mm@10;
                                          # 15 shows no further gain)
        ),
        viewer_options=gs.options.ViewerOptions(
            res=(1280, 960),
            camera_pos=WORLD_CAM_POS,
            camera_lookat=WORLD_CAM_LOOKAT,
            camera_fov=45,
        ),
        vis_options=gs.options.VisOptions(
            ambient_light=(ambient,) * 3,            # strong ambient fill → soft flat look like real footage
            background_color=(0.75, 0.75, 0.75),     # gray BG for out-of-scene areas
            shadow=True,                              # subtle shadows (top-down light → small under-object shadows)
            lights=[
                DirectionalLight(dir=(0.0, 0.0, -1.0), color=(1.0, 1.0, 1.0), intensity=light_intensity),
            ],
        ),
        show_viewer=show_viewer,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )

    # Dark floor plane (visible beyond the round table in the wrist cam view)
    scene.add_entity(
        gs.morphs.Plane(),
        surface=gs.surfaces.Default(color=FLOOR_COLOR),
    )

    # Silver rim disk (slightly wider, top just below the green surface)
    scene.add_entity(
        morph=gs.morphs.Cylinder(
            radius=TABLE_RIM_RADIUS,
            height=TABLE_H,
            pos=(0.0, 0.0, WORKSPACE_Z - 0.002 - TABLE_H / 2),
            fixed=True,
        ),
        surface=gs.surfaces.Default(color=TABLE_RIM_COLOR),
    )

    # Round green table top — bg_color is a DR knob (default: green matching real rig)
    table = scene.add_entity(
        morph=gs.morphs.Cylinder(
            radius=TABLE_RADIUS,
            height=TABLE_H,
            pos=(0.0, 0.0, WORKSPACE_Z - TABLE_H / 2),
            fixed=True,
        ),
        surface=gs.surfaces.Default(color=bg_color),
    )

    # Gray walls: front (+y), back (-y), left (-x), right (+x) — no ceiling
    # emissive=(0.35,0.35,0.35) keeps walls visibly gray regardless of light direction
    wall_surf = gs.surfaces.Default(color=WALL_COLOR)
    _span = WALL_HALF * 2  # full span for the perpendicular dimension
    # front (+y)
    scene.add_entity(morph=gs.morphs.Box(size=(_span, WALL_T, WALL_H),
        pos=(0.0,  WALL_HALF, WALL_CY), fixed=True), surface=wall_surf)
    # back (-y)
    scene.add_entity(morph=gs.morphs.Box(size=(_span, WALL_T, WALL_H),
        pos=(0.0, -WALL_HALF, WALL_CY), fixed=True), surface=wall_surf)
    # left (-x)
    scene.add_entity(morph=gs.morphs.Box(size=(WALL_T, _span, WALL_H),
        pos=(-WALL_HALF, 0.0, WALL_CY), fixed=True), surface=wall_surf)
    # right (+x)
    scene.add_entity(morph=gs.morphs.Box(size=(WALL_T, _span, WALL_H),
        pos=( WALL_HALF, 0.0, WALL_CY), fixed=True), surface=wall_surf)

    # SO101 robot — uses so101_white.urdf where 3d_printed=white, sts3215=black.
    # convexify=False keeps the true (concave) collision shape of the gripper jaw;
    # the default convex hull fills the jaw's cup so it can never cage an object
    # (verified: grasps fail with convexify=True, succeed with False). Visuals unchanged.
    robot = scene.add_entity(
        gs.morphs.URDF(
            file=str(SO101_URDF),
            pos=SO101_POS,
            euler=SO101_EULER,
            fixed=True,
            convexify=False,
        ),
    )

    # Cube (color configurable for DR)
    cube = scene.add_entity(
        morph=gs.morphs.Box(size=CUBE_SIZE, pos=CUBE_POS),
        surface=gs.surfaces.Default(color=cube_color),
        material=gs.materials.Rigid(rho=500.0, friction=0.8),
    )

    # Black border frame (slightly larger, sits under white target)
    _border_size = (
        TARGET_SIZE[0] + 2 * TARGET_BORDER,
        TARGET_SIZE[1] + 2 * TARGET_BORDER,
        _TBH,
    )
    scene.add_entity(
        morph=gs.morphs.Box(size=_border_size, pos=TARGET_BORDER_POS, fixed=True),
        surface=gs.surfaces.Default(color=TARGET_BORDER_COLOR),
    )

    # White target square (sits on top of black frame)
    target = scene.add_entity(
        morph=gs.morphs.Box(size=TARGET_SIZE, pos=TARGET_POS, fixed=True),
        surface=gs.surfaces.Default(color=TARGET_COLOR),
    )

    # World camera
    world_cam = None
    if add_world_cam:
        world_cam = scene.add_camera(
            res=WORLD_CAM_RES,
            pos=WORLD_CAM_POS,
            lookat=WORLD_CAM_LOOKAT,
            fov=WORLD_CAM_FOV,
            GUI=False,
        )

    # Wrist camera (attached after build)
    wrist_cam = None
    if add_wrist_cam:
        wrist_cam = scene.add_camera(
            res=WRIST_CAM_RES,
            fov=WRIST_CAM_FOV,
            near=WRIST_CAM_NEAR,
            far=WRIST_CAM_FAR,
            GUI=False,
        )

    scene.build()

    # Set robot home pose (index into the 6 controllable DOFs; root is fixed)
    _set_home(robot)

    # Store wrist link reference for dynamic camera updates
    wrist_link = None
    if wrist_cam is not None:
        try:
            wrist_link = robot.get_link(WRIST_CAM_LINK)
        except Exception as exc:
            print(f"[WARNING] wrist link not found ({exc}); wrist cam disabled.")
            wrist_cam = None

    return SceneBundleSO101(
        scene=scene,
        robot=robot,
        cube=cube,
        target=target,
        table=table,
        world_cam=world_cam,
        wrist_cam=wrist_cam,
        _wrist_link=wrist_link,
    )


def _set_home(robot: gs.RigidEntity) -> None:
    robot.set_qpos(SO101_HOME_QPOS.copy())


# --- CLI entry point ---------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build and preview the SO101 scene.")
    parser.add_argument("-v", "--vis",         action="store_true",
                        help="open the interactive viewer (runs until the window is closed)")
    parser.add_argument("--save-frames",       action="store_true")
    parser.add_argument("--steps", type=int,   default=30,
                        help="simulation steps in headless mode (ignored with --vis)")
    parser.add_argument("--no-world-cam",      action="store_true")
    parser.add_argument("--no-wrist-cam",      action="store_true")
    parser.add_argument("--pose", choices=["home", "observe"], default="home",
                        help="arm pose held during preview (home = folded, observe = raised over workspace)")
    args = parser.parse_args()

    gs.init(backend=gs.metal)
    bundle = build_scene_so101(
        show_viewer=args.vis,
        add_world_cam=not args.no_world_cam,
        add_wrist_cam=not args.no_wrist_cam,
    )

    qpos = (SO101_OBS_QPOS if args.pose == "observe" else SO101_HOME_QPOS).copy()

    def _step() -> None:
        bundle.robot.set_qpos(qpos)   # hold pose exactly for preview rendering
        bundle.scene.step()
        bundle.update_wrist_cam()

    if args.vis:
        # Interactive mode: keep stepping until the viewer window is closed (Ctrl-C also works)
        try:
            while bundle.scene.viewer.is_alive():
                _step()
        except KeyboardInterrupt:
            pass
    else:
        for _ in range(args.steps):
            _step()

    if args.save_frames:
        import imageio.v2 as imageio
        frames = bundle.render()
        for name, result in frames.items():
            rgb = result[0] if isinstance(result, tuple) else result
            path = f"so101_{name}.png"
            imageio.imwrite(path, rgb)
            print(f"Saved {path}")

    print(f"Scene OK — robot DOFs: {bundle.robot.n_dofs}")


if __name__ == "__main__":
    main()
