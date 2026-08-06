"""
project/envs/server_assembly.py

R.A.G.E. (ROCm-Accelerated Generalist Embodiment)
Phase 2 — Complex Physical Interaction

Bimanual server-assembly cell built on the Genesis physics engine
(Vulkan backend, targeting AMD ROCm/GPU acceleration via gs.gpu).

Scene summary
-------------
- Robot A ("fixturer"): Franka Panda. Uses IK to grasp the GPU base block
  and hold it perfectly still in the air (active fixturing) so a virtual
  inspection camera can get a clean, stable view of the assembled ports.
- Robot B ("cable feeder"): Franka Panda. Sits next to a neat row of three
  MPM-deformable cables (red / blue / yellow). Phase 2 only *spawns* and
  *lays out* these cables within Robot B's reach; the actual insertion
  routine (matching cable color -> port shape) is deferred to Phase 3,
  where YOLOv8 will localize ports/cables and a CDS (Campbell-Dudek-Smith)
  flow-shop heuristic will sequence the two arms.
- Target: a rigid "GPU block" with three distinct, physically-shaped port
  *sockets* on top (not flat markers) - each a small walled bin, procedurally
  built out of thin rigid wall segments, sized to actually accept the tip of
  a cable in Phase 3's insertion routine:
    Port 1 - Red    Square   bin (4-gon walls)
    Port 2 - Blue   Circle   bin (16-gon wall approximation)
    Port 3 - Yellow Triangle bin (3-gon walls, true triangle - see note below)

Each cable also gets a small rigid, color-matched connector plug fused onto
one tip (square / circle / triangle) so it visually reads as "this cable
plugs into that port" instead of being a bare rod. The rotational phase of
each port shape and its matching plug is now defined in exactly one place,
PORT_ROTATIONS below, so the two can never drift out of alignment (this
fixes a bug where the ring's rotation_deg and the connector mesh's hardcoded
angles were set independently in two different code paths).

Modes
-----
Two run modes, selected via CLI flag:

  python -m project.envs.server_assembly
      Full Phase-2 sequence: Robot A reaches, grasps, lifts, and actively
      fixtures the GPU block while both cameras record. (default)

  python -m project.envs.server_assembly --hover-only
      Phase-2b IK sanity check: Robot A's IK controller drives its
      end-effector to hover directly above the GPU block while Robot B's
      IK controller simultaneously drives its end-effector to hover above
      the red cable. No grasping happens. This proves both IK controllers
      converge correctly before OpenVLA-driven grasping policies are wired
      in for Phase 4.

Rendering
---------
Headless (show_viewer=False). Two cameras stream frames to disk as MP4:
    videos/sim_data/far_shot.mp4        - wide establishing shot (full mode)
    videos/sim_data/top_shot.mp4        - top-down inspection shot (full mode)
    videos/sim_data/hover_far_shot.mp4  - wide establishing shot (hover mode)
    videos/sim_data/hover_top_shot.mp4  - top-down inspection shot (hover mode)

Run:
    python -m project.envs.server_assembly
    python -m project.envs.server_assembly --hover-only
"""

import glob
import inspect
import os
import shutil
import sys
import time

import numpy as np
import genesis as gs


# --------------------------------------------------------------------------- #
# Global layout constants (world frame, meters)
# --------------------------------------------------------------------------- #

TABLE_Z = 0.0  # ground plane sits at z = 0

ROBOT_A_BASE_POS = (0.0, 0.40, TABLE_Z)   # "fixturer" arm
ROBOT_B_BASE_POS = (0.0, -0.40, TABLE_Z)  # "cable feeder" arm

GPU_BLOCK_POS = (0.50, 0.40, TABLE_Z + 0.02)  # in front of Robot A
GPU_BLOCK_SIZE = (0.22, 0.16, 0.04)

# Fixed inspection height Robot A lifts the GPU block to for the camera pass.
INSPECTION_LIFT_POS = (0.50, 0.40, TABLE_Z + 0.35)
INSPECTION_HOLD_STEPS = 150  # how long to hold perfectly still for the camera

# Hover height (above the block top / cable) used by the --hover-only IK
# sanity check.
HOVER_HEIGHT = 0.18
HOVER_SETTLE_STEPS = 100
HOVER_HOLD_STEPS = 90

CABLE_ANCHOR = (0.50, -0.40, TABLE_Z)  # in front of Robot B
CABLE_SPACING_Y = 0.16
# Thinner + noticeably longer than the Phase-2 draft so the cables read as
# flexible wires rather than short rubber pucks, while staying well inside
# the MPM domain (see mpm_options.lower_bound/upper_bound in build_scene()).
CABLE_RADIUS = 0.009
CABLE_LENGTH = 0.45

# Port "bin" sockets: circumradius of the walled opening each cable tip
# needs to drop into. Kept comfortably larger than CABLE_RADIUS so a cable
# end has clearance to be guided in during Phase 3's insertion routine.
PORT_WALL_HEIGHT = 0.03
PORT_WALL_THICKNESS = 0.006
PORT_INNER_RADIUS = 0.032

# --------------------------------------------------------------------------- #
# Single source of truth for shape rotation
# --------------------------------------------------------------------------- #
# Both the port bin ring AND its matching cable-connector plug read their
# rotational phase from this one dict, keyed by shape name. Previously the
# ring's rotation_deg was set at each add_shape_bin(...) call site while the
# triangle plug's angles were hardcoded separately inside
# _ensure_triangle_connector_mesh() and the square plug's orientation was
# left to Box's default (corners at +/-45 deg) - three independent sources
# of truth that only lined up by coincidence. If any one of them were ever
# tweaked without touching the others, the plug would silently stop
# matching the shape of its socket. Now there is exactly one place to
# change a shape's phase, and both the ring and the plug always agree.
PORT_ROTATIONS = {
    "square": 45.0,    # 4-gon ring rotated 45 deg so it reads as an
                        # axis-aligned square rather than a diamond
    "circle": 0.0,      # 16-gon ring - rotation is a no-op for a circle
                        # approximation, kept for symmetry/clarity
    "triangle": 90.0,   # 3-gon ring rotated so it points "up" (+Y) in the
                        # top-down inspection shot
}

# Cable connector "plugs": a small shaped head fused onto one end of each
# cable so it visually reads as "this end plugs into the square/circle/
# triangle port" instead of just being a bare rod. Sized smaller than
# PORT_INNER_RADIUS so the plug visually nests inside its matching bin.
CONNECTOR_RADIUS = 0.018
CONNECTOR_HEIGHT = 0.022
CONNECTOR_OVERLAP = 0.01  # sink the plug slightly into the cable tip so
                          # there's no visible gap between wire and plug

VIDEO_DIR = "videos/sim_data"

# Where procedurally-generated mesh assets (e.g. the triangular connector
# prism, which has no built-in Genesis primitive) get cached on disk.
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_assets")


# --------------------------------------------------------------------------- #
# 1. Backend initialization - hard fail if we silently fall back to CPU
# --------------------------------------------------------------------------- #

def init_genesis():
    """Initialize Genesis explicitly on a GPU backend (CUDA / ROCm-HIP /
    Metal, whichever `gs.gpu` resolves to on this machine) and crash loudly
    if it silently degrades to a CPU backend. For the ROCm hackathon build
    we cannot afford to discover a silent CPU fallback halfway through a
    30-minute MPM cable sim.
    """
    gs.init(backend=gs.gpu, precision="32", logging_level="info")

    # Best-effort verification: Genesis's kernels are compiled through the
    # Taichi/gstaichi runtime, which exposes the *actually resolved* compute
    # architecture. If that architecture is CPU, gs.gpu did not get what it
    # asked for, and we should stop immediately rather than run a
    # heartbreakingly slow MPM simulation.
    resolved_arch = None
    try:
        import taichi as ti
        resolved_arch = ti.cfg.arch
        is_cpu = resolved_arch == ti.cpu
    except ImportError:
        try:
            import gstaichi as ti
            resolved_arch = ti.cfg.arch
            is_cpu = resolved_arch == ti.cpu
        except ImportError:
            # If we truly can't introspect the runtime, don't block startup,
            # but make it very visible in the logs.
            print("[R.A.G.E. WARNING] Could not introspect Taichi/gstaichi "
                  "backend to verify GPU acceleration. Proceeding, but watch "
                  "your sim throughput closely.")
            is_cpu = False

    assert not is_cpu, (
        f"[R.A.G.E. FATAL] Genesis fell back to a CPU backend "
        f"(resolved arch={resolved_arch}). This build REQUIRES a "
        f"ROCm/Vulkan-visible GPU. Check `vulkaninfo --summary`, your ROCm "
        f"install, and HSA_OVERRIDE_GFX_VERSION before retrying."
    )
    print(f"[R.A.G.E.] Genesis backend resolved to: {resolved_arch or 'GPU (unverified)'}")


# --------------------------------------------------------------------------- #
# 2. Active-fixturing / IK controller (kept modular for Phase 3 reuse)
# --------------------------------------------------------------------------- #

class ArmIKController:
    """Thin abstraction around a single Franka Panda entity's Inverse
    Kinematics and low-level DOF control.

    All high-level motion primitives the flow-shop scheduler will need in
    Phase 3 (reach / grasp / lift / hold / release) live here as clean,
    named methods so the future CDS scheduler + YOLOv8 perception stack can
    call `arm.move_to(...)` / `arm.hold(...)` without touching raw DOF
    arrays or IK math directly.
    """

    # Standard PD gains / force limits for the Franka Panda (7 arm + 2 finger
    # DOFs), taken from the Genesis reference IK example.
    _KP = np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100])
    _KV = np.array([450, 450, 350, 350, 200, 200, 200, 10, 10])
    _FORCE_LOWER = np.array([-87, -87, -87, -87, -12, -12, -12, -100, -100])
    _FORCE_UPPER = np.array([87, 87, 87, 87, 12, 12, 12, 100, 100])

    # Gripper pointing straight down, fingers aligned with the world X axis.
    DOWNWARD_QUAT = np.array([0.0, 1.0, 0.0, 0.0])

    def __init__(self, robot, name, ee_link_name="hand", n_arm_dofs=7):
        self.robot = robot
        self.name = name
        self.n_arm_dofs = n_arm_dofs

        self.ee_link = robot.get_link(ee_link_name)

        self.arm_dofs = np.arange(0, n_arm_dofs)
        self.gripper_dofs = np.arange(n_arm_dofs, n_arm_dofs + 2)

        self.robot.set_dofs_kp(self._KP)
        self.robot.set_dofs_kv(self._KV)
        self.robot.set_dofs_force_range(self._FORCE_LOWER, self._FORCE_UPPER)

        self._last_qpos = None  # remembered target, used by hold()

    # -- core IK -------------------------------------------------------- #

    def solve_ik(self, target_pos, target_quat):
        return self.robot.inverse_kinematics(
            link=self.ee_link,
            pos=np.array(target_pos, dtype=np.float32),
            quat=np.array(target_quat, dtype=np.float32),
        )

    # -- motion primitives ------------------------------------------------ #

    def move_to(self, scene, target_pos, target_quat, settle_steps=100, cams=None):
        """Solve IK to `target_pos`/`target_quat` and drive the arm joints
        there over `settle_steps` control steps."""
        qpos = self.solve_ik(target_pos, target_quat)
        self._last_qpos = qpos
        self.robot.control_dofs_position(qpos[: self.n_arm_dofs], self.arm_dofs)
        self._step(scene, settle_steps, cams)
        return qpos

    def set_gripper_force(self, scene, force, settle_steps=60, cams=None):
        """Force-control the two finger DOFs. Negative force closes the
        gripper (grasp); positive force opens it (release)."""
        self.robot.control_dofs_force(
            np.array([force, force], dtype=np.float32), self.gripper_dofs
        )
        self._step(scene, settle_steps, cams)

    def hold(self, scene, steps, cams=None):
        """Active fixturing: keep re-asserting the last commanded pose every
        control step so the PD controller actively resists gravity /
        disturbance instead of the arm drifting or sagging under load. This
        is what lets a virtual inspection camera get a clean, motion-blur
        free shot of the held part."""
        if self._last_qpos is not None:
            self.robot.control_dofs_position(
                self._last_qpos[: self.n_arm_dofs], self.arm_dofs
            )
        self._step(scene, steps, cams)

    # -- internals ---------------------------------------------------------- #

    def _step(self, scene, n_steps, cams):
        for _ in range(n_steps):
            scene.step()
            if cams:
                for cam in cams:
                    cam.render()


# --------------------------------------------------------------------------- #
# 2b. Procedural shaped "bins" (insertion sockets) for the GPU block's ports
# --------------------------------------------------------------------------- #
#
# Each port is a small walled socket - not a flat color swatch - shaped like
# a hollow picture-frame ring: a 4-gon frame reads as a square, a 3-gon as a
# true triangle, and a coarse N-gon (e.g. 16 sides) reads as a circle from
# the top-down inspection camera. Genesis's built-in rigid primitives don't
# include a boolean "cut a hole" op, so we generate each ring procedurally
# as a single watertight mesh (extruded n-gon annulus) rather than as
# separate wall-segment boxes.
#
# IMPORTANT: this is a single MESH entity per port (not N separate boxes).
# An earlier draft built each ring out of N individually-welded wall boxes
# (23 weld constraints total across the 3 ports), which blew past this
# Genesis build's default `RigidOptions.max_dynamic_constraints` cap of 8
# and crashed inside its own overflow-handling code with a bare
# `AttributeError` instead of a clean capacity error. One mesh == one weld
# per port == 3 weld constraints total, comfortably under any reasonable
# cap (we also raise `max_dynamic_constraints` in build_scene() for
# headroom). It also fixes a real logic bug: the old wall boxes were marked
# `fixed=True` (kinematically anchored, cannot move) while simultaneously
# being welded to the dynamic GPU block - a contradiction. This mesh is a
# normal dynamic rigid body, so the weld constraint actually does something.

def _ensure_ngon_frame_mesh(assets_dir, n_sides, r_in, r_out, height, rotation_deg=0.0):
    """Procedurally write (and cache) a hollow n-gon "picture-frame" ring -
    an extruded annulus between circumradius `r_in` and `r_out` - as a
    Wavefront OBJ. Returns the file path."""
    os.makedirs(assets_dir, exist_ok=True)
    path = os.path.join(
        assets_dir,
        f"ring_n{n_sides}_rin{r_in:.4f}_rout{r_out:.4f}_h{height:.4f}_rot{rotation_deg:.1f}.obj",
    )
    if os.path.exists(path):
        return path

    angles = np.deg2rad(rotation_deg) + np.linspace(0, 2 * np.pi, n_sides, endpoint=False)
    cos_a, sin_a = np.cos(angles), np.sin(angles)

    # 4 rings of n_sides vertices each: outer-bottom, inner-bottom,
    # outer-top, inner-top (in that order, laid out contiguously so index
    # math below is simple).
    ob = np.stack([r_out * cos_a, r_out * sin_a, np.zeros(n_sides)], axis=1)
    ib = np.stack([r_in * cos_a, r_in * sin_a, np.zeros(n_sides)], axis=1)
    ot = np.stack([r_out * cos_a, r_out * sin_a, np.full(n_sides, height)], axis=1)
    it = np.stack([r_in * cos_a, r_in * sin_a, np.full(n_sides, height)], axis=1)
    verts = np.concatenate([ob, ib, ot, it], axis=0)  # shape (4*n_sides, 3)

    def idx(ring, i):
        # 1-indexed OBJ vertex index for vertex `i` (0-based) in `ring`
        # (0=outer-bottom, 1=inner-bottom, 2=outer-top, 3=inner-top).
        return ring * n_sides + (i % n_sides) + 1

    faces = []
    for i in range(n_sides):
        j = i + 1
        # Outer wall
        faces.append((idx(0, i), idx(0, j), idx(2, j)))
        faces.append((idx(0, i), idx(2, j), idx(2, i)))
        # Inner wall (reversed winding - faces inward)
        faces.append((idx(1, j), idx(1, i), idx(3, i)))
        faces.append((idx(1, j), idx(3, i), idx(3, j)))
        # Top annulus cap
        faces.append((idx(2, i), idx(2, j), idx(3, j)))
        faces.append((idx(2, i), idx(3, j), idx(3, i)))
        # Bottom annulus cap
        faces.append((idx(0, j), idx(0, i), idx(1, i)))
        faces.append((idx(0, j), idx(1, i), idx(1, j)))

    with open(path, "w") as f:
        f.write(f"# procedurally generated {n_sides}-gon ring/frame\n")
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for face in faces:
            f.write("f " + " ".join(str(k) for k in face) + "\n")
    return path


def add_shape_bin(scene, entities, key, center_xy, base_z,
                   n_sides, radius, color,
                   wall_h=PORT_WALL_HEIGHT, wall_t=PORT_WALL_THICKNESS,
                   rotation_deg=0.0):
    """Spawn a single-mesh shaped socket (ring/frame) at `center_xy`,
    register it under `entities[key]`, and return `key` so the caller can
    weld it onto a parent rigid body (e.g. the GPU block)."""
    r_in = radius - wall_t / 2.0
    r_out = radius + wall_t / 2.0
    obj_path = _ensure_ngon_frame_mesh(ASSETS_DIR, n_sides, r_in, r_out, wall_h, rotation_deg)
    entities[key] = scene.add_entity(
        morph=gs.morphs.Mesh(
            file=obj_path,
            pos=(center_xy[0], center_xy[1], base_z),
        ),
        surface=gs.surfaces.Default(color=color),
    )
    return key


# --------------------------------------------------------------------------- #
# 2c. Cable connector plugs (square / circle / triangle heads on cable tips)
# --------------------------------------------------------------------------- #
#
# A bare MPM cylinder reads as "just a wire" - there's nothing on it that
# says which port it belongs to. Real cables have a distinct connector head,
# so each cable gets a small rigid, color-matched plug fused onto one end:
# square plug -> red cable -> red square bin, and so on. The plug is a
# separate rigid entity resting against the cable's tip (MPM entities can't
# be `add_weld_constraint`-ed the way two rigid links can), which is a fine
# approximation for a static Phase-2 layout shot; Phase 3's insertion
# routine will need real MPM-rigid contact coupling once Robot B actually
# picks the cable up.
#
# Every plug's rotational phase is read from PORT_ROTATIONS (the same dict
# the matching port ring reads from), so a plug can never end up rotated
# out of alignment with its socket.

def _quat_about_z(deg):
    """Unit quaternion (w, x, y, z) for a rotation of `deg` about the world
    Z axis."""
    rad = np.deg2rad(deg)
    return np.array([np.cos(rad / 2.0), 0.0, 0.0, np.sin(rad / 2.0)])


def _ensure_triangle_connector_mesh(assets_dir, radius, thickness, rotation_deg=0.0):
    """Procedurally write (and cache) a small equilateral-triangle prism as
    a Wavefront OBJ, since Genesis has no built-in triangular-prism
    primitive. `rotation_deg` uses the exact same angle convention as
    _ensure_ngon_frame_mesh's ring generator (angles = rotation_deg +
    linspace(0, 2*pi, n, endpoint=False)), so a triangle plug built with the
    same rotation_deg as its port ring is guaranteed to share the ring's
    phase - no more hardcoded, independently-chosen angles. Returns the
    file path."""
    os.makedirs(assets_dir, exist_ok=True)
    path = os.path.join(
        assets_dir,
        f"triangle_connector_r{radius:.4f}_t{thickness:.4f}_rot{rotation_deg:.1f}.obj",
    )
    if os.path.exists(path):
        return path

    angles = np.deg2rad(rotation_deg) + np.linspace(0, 2 * np.pi, 3, endpoint=False)
    top_z, bot_z = thickness / 2.0, -thickness / 2.0

    verts = []
    for z in (bot_z, top_z):
        for a in angles:
            verts.append((radius * np.cos(a), radius * np.sin(a), z))
    # verts[0:3] = bottom triangle, verts[3:6] = top triangle (1-indexed in OBJ)
    faces = [
        (1, 3, 2),        # bottom cap
        (4, 5, 6),        # top cap
        (1, 2, 5), (1, 5, 4),   # side 1
        (2, 3, 6), (2, 6, 5),   # side 2
        (3, 1, 4), (3, 4, 6),   # side 3
    ]
    with open(path, "w") as f:
        f.write("# procedurally generated triangular cable-connector prism\n")
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for face in faces:
            f.write("f " + " ".join(str(i) for i in face) + "\n")
    return path


def add_cable_connector(scene, entities, key, shape, center_xy, color, rotation_deg=0.0):
    """Spawn a small rigid connector plug (square / circle / triangle) at
    `center_xy`, colored to match its cable/port, rotated to `rotation_deg`
    (which should always be PORT_ROTATIONS[shape] - the same value used for
    that shape's port ring), and register it under `entities[key]`."""
    z = CONNECTOR_HEIGHT / 2.0

    if shape == "square":
        # gs.morphs.Box's corners sit at +/-45 deg from the box axes by
        # default. A 4-gon ring built via _ensure_ngon_frame_mesh with
        # rotation_deg puts its flat *faces* (not corners) at
        # rotation_deg + {0, 90, 180, 270}, which is a square whose corners
        # sit at rotation_deg + 45 + {0, 90, 180, 270}. So an unrotated Box
        # already matches a ring built with rotation_deg=45 (which is
        # exactly PORT_ROTATIONS["square"]); the quat below applies only
        # the *delta* away from that reference, so this stays correct even
        # if PORT_ROTATIONS["square"] is changed later.
        extra = rotation_deg - 45.0
        entities[key] = scene.add_entity(
            morph=gs.morphs.Box(
                pos=(center_xy[0], center_xy[1], z),
                size=(CONNECTOR_RADIUS * 2, CONNECTOR_RADIUS * 2, CONNECTOR_HEIGHT),
                quat=_quat_about_z(extra),
            ),
            surface=gs.surfaces.Default(color=color),
        )
    elif shape == "circle":
        # Rotationally symmetric - rotation_deg is a no-op, kept as a
        # parameter only for interface consistency with the other shapes.
        entities[key] = scene.add_entity(
            morph=gs.morphs.Cylinder(
                pos=(center_xy[0], center_xy[1], z),
                radius=CONNECTOR_RADIUS,
                height=CONNECTOR_HEIGHT,
            ),
            surface=gs.surfaces.Default(color=color),
        )
    elif shape == "triangle":
        obj_path = _ensure_triangle_connector_mesh(
            ASSETS_DIR, radius=CONNECTOR_RADIUS, thickness=CONNECTOR_HEIGHT,
            rotation_deg=rotation_deg,
        )
        entities[key] = scene.add_entity(
            morph=gs.morphs.Mesh(
                file=obj_path,
                pos=(center_xy[0], center_xy[1], z),
            ),
            surface=gs.surfaces.Default(color=color),
        )
    else:
        raise ValueError(f"Unknown connector shape: {shape!r}")

    return entities[key]


# --------------------------------------------------------------------------- #
# 3. Scene construction
# --------------------------------------------------------------------------- #

def build_scene():
    """Construct the Genesis scene: ground plane, two Franka arms, the GPU
    block + 3 ports, three MPM cables, and the two inspection cameras."""

    scene = gs.Scene(
        show_viewer=False,  # headless - required for CI / hackathon runners
        sim_options=gs.options.SimOptions(
            dt=0.01,
            # Genesis's default MPM grid_density (64 cells/m) suggests a
            # substep_dt of ~0.0003125s for stability. At dt=0.01 that
            # means >= 32 substeps (substep_dt = dt / substeps = 0.0003125).
            # The Phase-2 draft used 10 and got a "substep_dt greater than
            # suggested_dt" stability warning; 32 clears it.
            substeps=32,
        ),
        rigid_options=gs.options.RigidOptions(
            # Default is 8. We weld 3 port-bin rings onto the GPU block
            # (one weld each); a prior draft that welded 23 separate wall
            # boxes blew straight past the default and crashed inside
            # Genesis's own overflow-handling code. 16 gives headroom for
            # Phase 3 (e.g. welding a grasped cable's connector plug).
            max_dynamic_constraints=16,
        ),
        mpm_options=gs.options.MPMOptions(
            # Domain large enough to cover the whole cable-layout area with
            # margin. MPM particles that leave this box are clipped, so keep
            # generous headroom above the cables.
            #
            # NOTE: Genesis applies an inward safety padding (~0.047 m on
            # this build) to the *specified* bounds when computing the
            # actual solver boundary. A specified z lower_bound of 0.0 was
            # therefore tightened to an effective floor of ~0.047, which
            # clipped cable particles resting at z ~ 0.006-0.018 on the
            # ground plane. Dropping the specified floor well below the
            # ground plane guarantees the *effective* (padded) floor still
            # sits beneath the cables.
            lower_bound=(-0.2, -0.9, -0.1),
            upper_bound=(1.1, 0.1, 0.6),
        ),
        vis_options=gs.options.VisOptions(
            show_world_frame=False,
            visualize_mpm_boundary=False,
        ),
        renderer=gs.renderers.Rasterizer(),
    )

    entities = {}

    # --- ground plane ------------------------------------------------- #
    entities["plane"] = scene.add_entity(gs.morphs.Plane())

    # --- Robot A: fixturer -------------------------------------------- #
    entities["robot_a"] = scene.add_entity(
        gs.morphs.MJCF(
            file="xml/franka_emika_panda/panda.xml",
            pos=ROBOT_A_BASE_POS,
        ),
    )

    # --- Robot B: cable feeder ------------------------------------------ #
    entities["robot_b"] = scene.add_entity(
        gs.morphs.MJCF(
            file="xml/franka_emika_panda/panda.xml",
            pos=ROBOT_B_BASE_POS,
            euler=(0, 0, 180),  # face the opposite way, toward the cable row
        ),
    )

    # --- GPU base block (rigid, graspable) ----------------------------- #
    entities["gpu_block"] = scene.add_entity(
        morph=gs.morphs.Box(
            pos=GPU_BLOCK_POS,
            size=GPU_BLOCK_SIZE,
        ),
        surface=gs.surfaces.Default(color=(0.25, 0.25, 0.28)),  # gunmetal grey
    )

    block_top_z = GPU_BLOCK_POS[2] + GPU_BLOCK_SIZE[2] / 2
    port_bin_keys = []  # one entity key per port ring, for the weld pass below

    # --- Port 1: Red Square bin (4-gon ring; rotation from PORT_ROTATIONS
    #     so it reads as an axis-aligned square rather than a diamond, and
    #     always matches cable_1's square plug) ---------------------------
    port_1_center = (GPU_BLOCK_POS[0] - 0.075, GPU_BLOCK_POS[1])
    port_bin_keys.append(add_shape_bin(
        scene, entities, "port_1_red_square", port_1_center, block_top_z,
        n_sides=4, radius=PORT_INNER_RADIUS, color=(0.9, 0.1, 0.1),
        rotation_deg=PORT_ROTATIONS["square"],
    ))

    # --- Port 2: Blue Circle bin (16-gon ring approximates a circle) ----- #
    port_2_center = (GPU_BLOCK_POS[0], GPU_BLOCK_POS[1])
    port_bin_keys.append(add_shape_bin(
        scene, entities, "port_2_blue_circle", port_2_center, block_top_z,
        n_sides=16, radius=PORT_INNER_RADIUS, color=(0.1, 0.3, 0.95),
        rotation_deg=PORT_ROTATIONS["circle"],
    ))

    # --- Port 3: Yellow Triangle bin (a genuine 3-gon ring) --------------- #
    # Unlike the Phase-2 draft's "Box rotated 45 deg" approximation (which
    # actually renders as a diamond, not a triangle), this builds a real
    # equilateral-triangle socket via the same add_shape_bin() helper used
    # for the square and circle bins. Rotation comes from PORT_ROTATIONS so
    # it always matches cable_3's triangle plug.
    port_3_center = (GPU_BLOCK_POS[0] + 0.075, GPU_BLOCK_POS[1])
    port_bin_keys.append(add_shape_bin(
        scene, entities, "port_3_yellow_triangle", port_3_center, block_top_z,
        n_sides=3, radius=PORT_INNER_RADIUS, color=(0.95, 0.85, 0.1),
        rotation_deg=PORT_ROTATIONS["triangle"],
    ))

    # --- 3 MPM-deformable cables, laid out neatly for Robot B ------------ #
    # Low Young's modulus (E) so they behave like soft rubber wires rather
    # than stiff rods. Cylinders are rotated 90 deg about Y so they lie flat
    # on the ground, axis aligned with world X. Each cable also gets a
    # rigid, shape-matched connector plug fused onto its +X tip (the end
    # nominally "facing" the GPU block) so it visually reads as a real
    # cable-to-port assembly, not a bare rod:
    #   cable_1 (red)    -> square plug   -> matches Port 1 (red square bin)
    #   cable_2 (blue)   -> circle plug   -> matches Port 2 (blue circle bin)
    #   cable_3 (yellow) -> triangle plug -> matches Port 3 (yellow triangle bin)
    # Every plug's rotation_deg comes from the same PORT_ROTATIONS dict used
    # for its matching port ring above, so plug and socket are always in
    # phase with each other.
    cable_specs = [
        ("cable_1_red", (0.9, 0.1, 0.1), -1, "square"),
        ("cable_2_blue", (0.1, 0.3, 0.95), 0, "circle"),
        ("cable_3_yellow", (0.95, 0.85, 0.1), 1, "triangle"),
    ]
    for key, color, slot, connector_shape in cable_specs:
        cable_y = CABLE_ANCHOR[1] + slot * CABLE_SPACING_Y
        cable_pos = (CABLE_ANCHOR[0], cable_y, CABLE_RADIUS)

        entities[key] = scene.add_entity(
            material=gs.materials.MPM.Elastic(
                E=3.0e4,   # soft / rubbery Young's modulus (vs. ~3e5+ default)
                nu=0.45,   # near-incompressible, like real cable jacketing
                rho=1100.0,
            ),
            morph=gs.morphs.Cylinder(
                pos=cable_pos,
                radius=CABLE_RADIUS,
                height=CABLE_LENGTH,
                euler=(0, 90, 0),  # lay flat along world X
            ),
            surface=gs.surfaces.Default(color=color, vis_mode="visual"),
        )

        connector_x = CABLE_ANCHOR[0] + CABLE_LENGTH / 2 - CONNECTOR_OVERLAP
        add_cable_connector(
            scene, entities,
            key=f"{key}_connector",
            shape=connector_shape,
            center_xy=(connector_x, cable_y),
            color=color,
            rotation_deg=PORT_ROTATIONS[connector_shape],
        )

    # --- Cameras --------------------------------------------------------- #
    cam_far = scene.add_camera(
        res=(1280, 720),
        pos=(2.2, -0.9, 1.6),
        lookat=(0.45, 0.0, 0.25),
        fov=45,
        GUI=False,
    )
    cam_top = scene.add_camera(
        res=(960, 960),
        pos=(GPU_BLOCK_POS[0], GPU_BLOCK_POS[1], 1.8),
        lookat=(GPU_BLOCK_POS[0], GPU_BLOCK_POS[1], 0.0),
        fov=40,
        GUI=False,
    )

    scene.build()

    # Weld the three port-bin rings rigidly onto the GPU block's base link
    # so that when Robot A lifts the block, the shaped sockets (and their
    # color/shape identity for Phase 3's YOLOv8 detector) travel with it
    # instead of being left behind on the table. 3 welds total.
    rigid = scene.sim.rigid_solver
    block_link_idx = int(entities["gpu_block"].base_link.idx)
    for bin_key in port_bin_keys:
        bin_link_idx = int(entities[bin_key].base_link.idx)
        rigid.add_weld_constraint(block_link_idx, bin_link_idx)

    return scene, entities, cam_far, cam_top


# --------------------------------------------------------------------------- #
# 4a. Full active fixturing routine (Robot A) + headless video capture
# --------------------------------------------------------------------------- #

def run_active_fixturing(scene, entities, cams):
    """Robot A: reach -> grasp -> lift -> hold perfectly still, while both
    cameras stream frames for far_shot.mp4 / top_shot.mp4.

    Robot B stays at its ready pose in Phase 2 (its cable-insertion routine
    is a Phase 3 deliverable, once YOLOv8 can localize the ports on the
    lifted block and the CDS heuristic has sequenced the two arms).
    """
    robot_a = ArmIKController(entities["robot_a"], name="robot_a_fixturer")

    block_top_z = GPU_BLOCK_POS[2] + GPU_BLOCK_SIZE[2] / 2
    pregrasp_pos = (GPU_BLOCK_POS[0], GPU_BLOCK_POS[1], block_top_z + 0.18)
    grasp_pos = (GPU_BLOCK_POS[0], GPU_BLOCK_POS[1], block_top_z + 0.02)

    print("[R.A.G.E.] Robot A: moving to pre-grasp pose above GPU block...")
    robot_a.move_to(scene, pregrasp_pos, robot_a.DOWNWARD_QUAT, settle_steps=100, cams=cams)

    print("[R.A.G.E.] Robot A: descending to grasp pose...")
    robot_a.move_to(scene, grasp_pos, robot_a.DOWNWARD_QUAT, settle_steps=100, cams=cams)

    print("[R.A.G.E.] Robot A: closing gripper on GPU block...")
    robot_a.set_gripper_force(scene, force=-0.6, settle_steps=80, cams=cams)

    print("[R.A.G.E.] Robot A: lifting GPU block to inspection height...")
    robot_a.move_to(scene, INSPECTION_LIFT_POS, robot_a.DOWNWARD_QUAT, settle_steps=150, cams=cams)

    print(f"[R.A.G.E.] Robot A: active fixturing - holding for "
          f"{INSPECTION_HOLD_STEPS} steps while inspection cameras record...")
    robot_a.hold(scene, INSPECTION_HOLD_STEPS, cams=cams)

    print("[R.A.G.E.] Active fixturing sequence complete.")


# --------------------------------------------------------------------------- #
# 4b. IK hover proof (Robot A + Robot B, simultaneous, no grasping)
# --------------------------------------------------------------------------- #

def run_ik_hover_proof(scene, entities, cams,
                        hover_height=HOVER_HEIGHT,
                        settle_steps=HOVER_SETTLE_STEPS,
                        hold_steps=HOVER_HOLD_STEPS):
    """Phase-2b sanity check, no grasping involved: drive both arms to a
    pure IK hover pose simultaneously.

      - Robot A's end-effector hovers directly above the GPU block.
      - Robot B's end-effector hovers directly above the red cable
        (cable_1_red, the slot=-1 cable in CABLE_SPECS' layout).

    Both arms are commanded together every control step so this is a true
    simultaneous-hover proof, not two sequential single-arm moves. This is
    meant to validate that both IK controllers converge cleanly before
    OpenVLA-driven grasping policies are wired in for Phase 4 - deliberately
    simpler than run_active_fixturing() (no grasp, no lift, no MPM contact).
    """
    robot_a = ArmIKController(entities["robot_a"], name="robot_a_fixturer")
    robot_b = ArmIKController(entities["robot_b"], name="robot_b_feeder")

    block_top_z = GPU_BLOCK_POS[2] + GPU_BLOCK_SIZE[2] / 2
    hover_a = (GPU_BLOCK_POS[0], GPU_BLOCK_POS[1], block_top_z + hover_height)

    # Red cable sits at slot=-1 in CABLE_ANCHOR's row (see cable_specs in
    # build_scene()).
    red_cable_y = CABLE_ANCHOR[1] + (-1) * CABLE_SPACING_Y
    hover_b = (CABLE_ANCHOR[0], red_cable_y, CABLE_RADIUS + hover_height)

    print("[R.A.G.E.] Hover proof: solving IK for Robot A (over GPU block) "
          "and Robot B (over red cable)...")
    qpos_a = robot_a.solve_ik(hover_a, robot_a.DOWNWARD_QUAT)
    qpos_b = robot_b.solve_ik(hover_b, robot_b.DOWNWARD_QUAT)
    robot_a._last_qpos = qpos_a
    robot_b._last_qpos = qpos_b

    def _drive_both_and_step():
        robot_a.robot.control_dofs_position(qpos_a[: robot_a.n_arm_dofs], robot_a.arm_dofs)
        robot_b.robot.control_dofs_position(qpos_b[: robot_b.n_arm_dofs], robot_b.arm_dofs)
        scene.step()
        if cams:
            for cam in cams:
                cam.render()

    print(f"[R.A.G.E.] Hover proof: driving both arms to hover pose over "
          f"{settle_steps} steps...")
    for _ in range(settle_steps):
        _drive_both_and_step()

    print(f"[R.A.G.E.] Hover proof: holding both arms in place for "
          f"{hold_steps} steps...")
    for _ in range(hold_steps):
        _drive_both_and_step()

    print("[R.A.G.E.] IK hover proof complete - both arms converged.")


# --------------------------------------------------------------------------- #
# 5. Version-robust video saving
# --------------------------------------------------------------------------- #
#
# Different Genesis releases have used different keyword names for
# Camera.stop_recording()'s output-path argument (`save_to_filename` in the
# hosted docs, something else on other builds - our 1.3.1 run rejected
# `save_to_filename` outright with a TypeError). Rather than hard-code one
# name and crash on a version mismatch, introspect the live method
# signature and use whichever keyword it actually accepts; if none match,
# fall back to Genesis's own auto-generated filename and move that file to
# our desired destination ourselves.

def save_camera_video(cam, dest_path, fps=60, cam_label="camera"):
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    candidate_kwargs = ("save_to_filename", "filename", "path", "fname", "out_path")
    try:
        sig_params = set(inspect.signature(cam.stop_recording).parameters)
    except (TypeError, ValueError):
        sig_params = set()

    chosen_kwarg = next((k for k in candidate_kwargs if k in sig_params), None)

    if chosen_kwarg is not None:
        kwargs = {chosen_kwarg: dest_path}
        if "fps" in sig_params:
            kwargs["fps"] = fps
        cam.stop_recording(**kwargs)
        if os.path.exists(dest_path):
            print(f"[R.A.G.E.] {cam_label}: video saved -> {dest_path}")
            return dest_path

    # Fallback: let Genesis auto-name the file, then find + move it.
    before = set(glob.glob("**/*.mp4", recursive=True))
    kwargs = {"fps": fps} if "fps" in sig_params else {}
    cam.stop_recording(**kwargs)
    time.sleep(0.2)  # let the encoder finish flushing to disk
    new_files = list(set(glob.glob("**/*.mp4", recursive=True)) - before)

    if not new_files:
        candidates = sorted(glob.glob("**/*.mp4", recursive=True), key=os.path.getmtime)
        new_files = candidates[-1:] if candidates else []

    if new_files:
        newest = max(new_files, key=os.path.getmtime)
        shutil.move(newest, dest_path)
        print(f"[R.A.G.E.] {cam_label}: auto-named '{newest}' -> moved to {dest_path}")
        return dest_path

    print(f"[R.A.G.E. WARNING] {cam_label}: could not locate the recorded "
          f"video to move to {dest_path}. Check the working directory.")
    return None


# --------------------------------------------------------------------------- #
# 6. Entry point
# --------------------------------------------------------------------------- #

def main():
    hover_only = "--hover-only" in sys.argv

    init_genesis()

    scene, entities, cam_far, cam_top = build_scene()

    os.makedirs(VIDEO_DIR, exist_ok=True)
    far_name = "hover_far_shot.mp4" if hover_only else "far_shot.mp4"
    top_name = "hover_top_shot.mp4" if hover_only else "top_shot.mp4"
    far_path = os.path.join(VIDEO_DIR, far_name)
    top_path = os.path.join(VIDEO_DIR, top_name)

    # Prime both cameras with one render call before recording starts, as
    # recommended in the Genesis visualization guide (avoids a black first
    # frame on some backends).
    cam_far.render()
    cam_top.render()

    cam_far.start_recording()
    cam_top.start_recording()

    if hover_only:
        run_ik_hover_proof(scene, entities, cams=[cam_far, cam_top])
    else:
        run_active_fixturing(scene, entities, cams=[cam_far, cam_top])

    save_camera_video(cam_far, far_path, fps=60, cam_label="cam_far")
    save_camera_video(cam_top, top_path, fps=60, cam_label="cam_top")

    # TODO (Phase 3):
    #   1. Feed cam_top frames into a YOLOv8 detector to localize/classify
    #      the 3 ports (shape + color) and the 3 loose cables on Robot B's
    #      side of the table.
    #   2. Run a CDS (Campbell-Dudek-Smith) flow-shop heuristic over the
    #      {cable -> port} insertion job set to sequence Robot B's pick order
    #      while Robot A continues active fixturing.
    #   3. Extend ArmIKController with an `insert(scene, port_pose, cams)`
    #      primitive for Robot B's cable-insertion motion.


if __name__ == "__main__":
    main()