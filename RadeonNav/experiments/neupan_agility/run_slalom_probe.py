#!/usr/bin/env python3
"""Route v0.3 demo course, serpentine 3-row arena.

Sparse task anchors (one entry/exit pair per task = the literal policy
waypoint input, marked as flat green ground dots); NeuPAN owns all
free-space navigation between task corridors with a static planner cloud
(poles, slalom gate walls, bar wall) + three oscillating pedestrians.
rough (CPP random_rough heightfield) -> stairs -> seesaw -> elevated
tunnel combo (source arch mesh) -> bar (IMPASSABLE per capability
profile + BAR-SOLO matrix incl. the 0.10 m in-course sweep; NeuPAN
routes around the planner-side bar wall) -> tire jump -> poles slalom
(virtual gates force the S-weave, strict per-gate side verdict) ->
pedestrian zone -> end. Deployed stack unchanged (ep6 encoder, cell-D,
CM commit for jump classes, scheduled classes).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from bridge import path_to_tsc_waypoints, wrap_to_pi  # noqa: E402
from cpp_loco_sanity import _compose_env, _sha256  # noqa: E402
from run_bbc_sanity import _device, _live_env_contract, _write_json  # noqa: E402
from run_capstone import translated_fragment  # noqa: E402
from run_dynamic_planner import (  # noqa: E402
    COLLISION_DIST_M,
    build_neupan,
    obstacle_fragment,
    surface_points,
)
from run_source_task import (  # noqa: E402
    AGILITY_ROOT,
    HIGH_CHECKPOINT,
    POLICY_PROFILES,
    ROBOT_JOINTS,
    ContactProbe,
    SourceDepthCamera,
    _video_metadata,
)
from run_static_2p5d import JUMP_CLASSES, committed_delta_yaw  # noqa: E402
from run_waypoint_envelope import (  # noqa: E402
    CURRENT_LOOKAHEAD_M,
    MAX_ABS_YAW_RAD,
    NEXT_LOOKAHEAD_M,
    _base_yaw,
    remaining_policy_path,
)
from source_tasks import (  # noqa: E402
    HORIZONTAL_SCALE,
    SCAN_X,
    SCAN_Y,
    TASKS,
    VERTICAL_SCALE,
    configured_fragment,
)
from static_2p5d import (  # noqa: E402
    FREE_SPACE_CLASS,
    PATH_SPACING_M,
    ClassInterval,
    Rect,
    class_at_arc,
    resample_polyline,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
)
from unilab.terrains import HfFlatTerrainCfg  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
RESULTS_ROOT = ROOT / "outputs/radeon-nav/slalom-probe"
START_XY = (0.5, -4.0)
GOAL_XY = (15.0, -5.0)
GOAL_THRESHOLD_M = 0.5
EPISODE_STEPS = 3000
REPLAN_PERIOD_STEPS = 5
NEUPAN_REF_SPEED = 0.8
REFRESH_DEVIATION_RAD = 0.15
REFRESH_OBSTACLE_RADIUS_M = 2.0
CLASS_EXIT_MARGIN_M = 0.5
BAR_HEIGHT_M = 0.20

# Serpentine rows: row1 y=+4 (west->east), row2 y=0 (east->west),
# row3 y=-4 (west->east). Turns are 2 m arcs.
WAYPOINTS = [
    (0.5, -4.0),    # probe start (post-tire landing)
    (1.8, -4.3),
    (3.8, -5.0),
    (5.0, -5.6),    # weave reference tracked by the receding feed
    (5.9, -5.0),    # (slalom = task corridor; apex 0.6 at each pole)
    (6.8, -4.4),
    (7.7, -5.0),
    (8.6, -5.6),
    (9.5, -5.0),
    (10.4, -4.4),
    (11.3, -5.0),
    (15.0, -5.0),
]

# Straight-feed authority zones: inside these rects the receding feed and CM
# commit machinery keep control (proven approach alignment); everywhere else
# NeuPAN's proposals lead (free-space navigation, static + dynamic avoidance).
TASK_CORRIDORS = (
    Rect(-12.6, 4.0, 2.8, 5.2),    # row1: rough+stairs+seesaw as one lane
    Rect(0.8, 8.2, -1.2, 1.2),     # combo tunnel (approach + ramp recovery)
    Rect(-8.9, 0.9, -5.2, -2.8),   # tire runup + landing
    Rect(3.0, 11.8, -6.2, -3.8),   # poles slalom (weave reference lane)
)

FRAGMENTS = [  # (asset, dx, dy)
    ("stairs.xml", -5.5, 4.0),
    ("seesaw.xml", 0.3, 4.0),
    ("combo_tunnel.xml", 4.5, 0.0),
    ("bar_jump.xml", -6.0, 0.0),
    ("tire_jump.xml", -1.0, -4.0),
]
POLES_XY = ((5.0, -5.0), (6.8, -5.0), (8.6, -5.0), (10.4, -5.0))  # slalom line 1 m off the tire axis: the through-ring depth view stays empty (v1: on-axis structures trigger early jumps at any distance)
POLE_RADIUS_M = 0.1
ROUGH_CENTER = (-10.5, 4.0)
ROUGH_SIZE = (3.0, 2.4)
OBSTACLE_JOINTS = (
    ("source_seesaw_joint", -float(np.arcsin(0.25 / 1.5))),
    ("source_tire_joint", 0.475),
    ("source_bar_joint", BAR_HEIGHT_M),
)
AFFORDANCE = [  # (rect, class, entry_margin_m)
    (Rect(-1.2, 1.8, 3.7, 4.3), 3, 2.0),        # seesaw (row1)
    (Rect(3.5, 5.5, -0.4, 0.4), 5, 2.0),        # combo elevated tunnel
    (Rect(-1.3, -0.7, -4.35, -3.65), 4, 2.0),   # tire margin 2.0
]
# oscillating pedestrians: (cx, cy, amplitude_m, period_s, phase_rad)
PEDS = (
    (12.5, -5.0, 1.5, 9.0, 0.0),   # goal-zone crosser 1
    (13.6, -5.0, 1.5, 7.0, 3.5),   # goal-zone crosser 2 (thread between)
    (-2.8, 0.0, 1.4, 8.0, 2.1),    # row2 free segment before the bar wall
)
# Planner-only virtual walls (NeuPAN cloud; invisible to physics and depth).
# Slalom gates alternate sides so every feasible plan weaves the poles; the
# bar wall makes NeuPAN route around the bar on its own.
GATE_WALLS = ()
GATE_CAPS = ()
GATE_XS = tuple(x for x, _ in POLES_XY)
BAR_WALL = (-6.0, -1.05, 1.05)  # (x, y0, y1)


def static_cloud() -> np.ndarray:
    """World-frame 2D points NeuPAN plans around: poles + virtual walls."""
    angles = np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False)
    ring = 0.18 * np.stack((np.cos(angles), np.sin(angles)), axis=0)
    columns = [
        np.asarray(xy, dtype=np.float64).reshape(2, 1) + ring
        for xy in POLES_XY
    ]
    for x, y0, y1 in (BAR_WALL,):
        ys = np.arange(min(y0, y1), max(y0, y1) + 1e-6, 0.15)
        columns.append(np.vstack([np.full_like(ys, x), ys]))
    return np.hstack(columns)


@contextmanager
def rotated_fragment(source: Path, dx: float, dy: float) -> Iterator[Path]:
    """Translate + spin 180 deg about z (mirror the obstacle's facing)."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(source)
    root = tree.getroot()
    worldbody = root.find("worldbody")
    for child in list(worldbody):
        if child.tag in ("body", "geom"):
            pos = (child.get("pos") or "0 0 0").split()
            pos[0] = f"{float(pos[0]) + dx:.4f}"
            pos[1] = f"{float(pos[1]) + dy:.4f}"
            child.set("pos", " ".join(pos))
            child.set("euler", "0 0 180")
    for mesh in root.iter("mesh"):
        mesh_file = Path(mesh.get("file"))
        if not mesh_file.is_absolute():
            mesh.set("file", str((source.parent / mesh_file).resolve()))
    with tempfile.TemporaryDirectory(prefix="unilab-rot-") as tmp:
        out = Path(tmp) / f"{source.stem}_rot.xml"
        tree.write(out, encoding="utf-8")
        yield out


@contextmanager
def renamed_fragment(
    source: Path, dx: float, dy: float, suffix: str
) -> Iterator[Path]:
    """translated_fragment + unique name suffix (duplicate asset copies)."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(source)
    root = tree.getroot()
    for element in root.iter():
        name = element.get("name")
        if name:
            element.set("name", f"{name}{suffix}")
        mesh_reference = element.get("mesh")
        if mesh_reference:
            element.set("mesh", f"{mesh_reference}{suffix}")
    worldbody = root.find("worldbody")
    for child in list(worldbody):
        if child.tag in ("body", "geom"):
            pos = (child.get("pos") or "0 0 0").split()
            pos[0] = f"{float(pos[0]) + dx:.4f}"
            pos[1] = f"{float(pos[1]) + dy:.4f}"
            child.set("pos", " ".join(pos))
    for mesh in root.iter("mesh"):
        mesh_file = Path(mesh.get("file"))
        if not mesh_file.is_absolute():
            mesh.set("file", str((source.parent / mesh_file).resolve()))
    with tempfile.TemporaryDirectory(prefix="unilab-renamed-") as tmp:
        out = Path(tmp) / f"{source.stem}{suffix}.xml"
        tree.write(out, encoding="utf-8")
        yield out


@contextmanager
def dots_fragment(points: list[tuple[float, float]]) -> Iterator[Path]:
    """Flat green ground dots marking the policy-input waypoints.

    Replaces the v1 flags: a 4 mm-thick disc flush with the ground has a
    near-zero depth-camera signature, so no suppression radius around
    obstacles is needed (the v1 flag poles corrupted the ep6 latent at
    tunnel mouths and on jump runups).
    """
    geoms = []
    for i, (x, y) in enumerate(points):
        # sites, not geoms: they stay out of the contact pipeline, so path
        # tweaks no longer re-roll contact-solver tie-breaks on every segment
        geoms.append(
            f'    <site name="waypoint_dot_{i}" type="cylinder"'
            f' pos="{x:.3f} {y:.3f} 0.002" size="0.12 0.002"'
            f' rgba="0.10 0.80 0.25 1"/>'
        )
    content = (
        '<mujoco model="waypoint dots">\n  <worldbody>\n'
        + "\n".join(geoms)
        + "\n  </worldbody>\n</mujoco>\n"
    )
    with tempfile.TemporaryDirectory(prefix="unilab-dots-") as tmp:
        out = Path(tmp) / "dots.xml"
        out.write_text(content, encoding="utf-8")
        yield out


@contextmanager
def poles_fragment() -> Iterator[Path]:
    """Slalom poles at 1.8 m spacing (source task look, deployment spacing).

    The source 1.0 m spacing assumes the class-2 weave skill, which is
    IMPASSABLE in deployment form (capability profile); the demo threads
    the poles with waypoints + NeuPAN instead, which needs the wider gap.
    """
    geoms = []
    for i, (x, y) in enumerate(POLES_XY):
        geoms.append(
            f'    <geom name="course_pole_{i}" type="cylinder"'
            f' pos="{x:.3f} {y:.3f} 0.5" size="{POLE_RADIUS_M} 0.5"'
            f' friction="1 0.005 0.0001" rgba="0.55 0.55 0.55 1"/>'
        )
        geoms.append(
            f'    <geom name="course_pole_band_{i}" type="cylinder"'
            f' contype="0" conaffinity="0"'
            f' pos="{x:.3f} {y:.3f} 0.035" size="{POLE_RADIUS_M + 0.012} 0.035"'
            f' rgba="0.92 0.60 0.18 1"/>'
        )
    content = (
        '<mujoco model="course slalom poles">\n  <worldbody>\n'
        + "\n".join(geoms)
        + "\n  </worldbody>\n</mujoco>\n"
    )
    with tempfile.TemporaryDirectory(prefix="unilab-poles-") as tmp:
        out = Path(tmp) / "poles_course.xml"
        out.write_text(content, encoding="utf-8")
        yield out


@contextmanager
def rough_hfield_fragment(seed: int, png_dir: Path) -> Iterator[Path]:
    """CPP-adapter-style uneven ground: unilab.terrains random_rough patch.

    Continuous heightfield (max 4 cm, 1 cm quantization, 0.3 m flat border)
    instead of the v1 discrete boxes, per route v0.1 point 1.
    """
    import imageio.v3 as iio

    from unilab.terrains import random_rough

    cfg = random_rough(
        size=ROUGH_SIZE,
        noise_range=(0.0, 0.04),
        noise_step=0.01,
        border_width=0.3,
    )
    out = cfg.function(0.8, np.random.default_rng(seed))
    hf = out.heightfield
    heights_m = hf.noise.astype(np.float64) * hf.vertical_scale
    z_max = float(max(heights_m.max(), 1e-6))
    img = np.round(heights_m / z_max * 255.0).astype(np.uint8)
    # The PNG must outlive this context: the depth camera re-compiles the
    # merged scene (which references the PNG by path) after the fragment
    # ExitStack has closed. Park it in the run's output directory.
    png_dir.mkdir(parents=True, exist_ok=True)
    png = png_dir / "rough_hf.png"
    iio.imwrite(png, img.T)  # PNG rows follow the hfield y axis
    with tempfile.TemporaryDirectory(prefix="unilab-rough-") as tmp:
        content = f"""<mujoco model="rough heightfield patch">
  <asset>
    <hfield name="rough_hf" file="{png}"
      size="{ROUGH_SIZE[0] / 2:.3f} {ROUGH_SIZE[1] / 2:.3f} {z_max:.4f} 0.4"/>
  </asset>
  <worldbody>
    <geom name="rough_patch" type="hfield" hfield="rough_hf"
      pos="{ROUGH_CENTER[0]:.3f} {ROUGH_CENTER[1]:.3f} 0"
      friction="1 0.005 0.0001" rgba="0.62 0.55 0.42 1"/>
  </worldbody>
</mujoco>
"""
        frag = Path(tmp) / "rough.xml"
        frag.write_text(content, encoding="utf-8")
        yield frag


def course_terrain(seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "curriculum": False,
        "size": [34.0, 16.0],
        "horizontal_scale": HORIZONTAL_SCALE,
        "vertical_scale": VERTICAL_SCALE,
        "border_width": 4.0,
        "num_rows": 1,
        "num_cols": 1,
        "sub_terrains": {
            "flat": HfFlatTerrainCfg(
                proportion=1.0,
                horizontal_scale=HORIZONTAL_SCALE,
                vertical_scale=VERTICAL_SCALE,
            )
        },
    }


def build_course() -> tuple[np.ndarray, tuple[ClassInterval, ...]]:
    dense = resample_polyline(np.asarray(WAYPOINTS, dtype=np.float64), PATH_SPACING_M)
    arc = (np.arange(len(dense)) + 1) * PATH_SPACING_M
    intervals = []
    for rect, label, entry_margin in AFFORDANCE:
        inside = rect.contains(dense)
        if not np.any(inside):
            continue
        centre = np.asarray([(rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0])
        s_centre = float(
            arc[np.argmin(np.linalg.norm(dense - centre.reshape(1, 2), axis=1))]
        )
        intervals.append(
            ClassInterval(
                max(s_centre - entry_margin, 0.0),
                float(arc[inside].max()) + CLASS_EXIT_MARGIN_M,
                int(label),
            )
        )
    return dense, tuple(sorted(intervals, key=lambda i: i.s_start_m))


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    dense_path, intervals = build_course()
    policy_arc = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M
    goal_xy = np.asarray(GOAL_XY, dtype=np.float64)

    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        profile.low_checkpoint,
        device=device,
        low_contract=profile.low_contract,
        low_mode_count=profile.low_mode_count,
        command_profile="deployment",
        high_branch="student",
        use_half=True,
    )
    override = torch.load(
        args.depth_encoder_checkpoint, map_location=device, weights_only=True
    )
    adapter.depth_encoder.load_state_dict(override)
    adapter.depth_encoder.half()
    adapter.depth_encoder.eval()
    planner, shim = build_neupan()
    planner.reset()
    planner.pan.current_nom_values = [None] * 4
    anchor_arr = np.asarray(WAYPOINTS, dtype=np.float64)
    anchor_yaws = []
    for i in range(len(anchor_arr)):
        ahead = anchor_arr[min(i + 1, len(anchor_arr) - 1)] - anchor_arr[
            max(i - 1, 0)
        ]
        anchor_yaws.append(float(np.arctan2(ahead[1], ahead[0])))
    planner.update_initial_path_from_waypoints(
        [
            np.asarray([[x], [y], [yaw]])
            for (x, y), yaw in zip(anchor_arr.tolist(), anchor_yaws)
        ]
    )

    with ExitStack() as stack:
        fragments = []
        for name, dx, dy in FRAGMENTS:
            source = ASSETS / name
            if name == "bar_jump.xml":
                # 0.20 m leaves a 0.17 m under-gap the BBC tries to crawl
                # (v2-dryrun2/3 wedge); 0.125 m makes crawling impossible so
                # the jump skill engages. springref must follow the height,
                # or the stiff slide spring pulls the bar back to 0.20.
                source = stack.enter_context(
                    configured_fragment(TASKS["bar_jump"], bar_height=BAR_HEIGHT_M)
                )
            frag = stack.enter_context(translated_fragment(source, dx, dy))
            fragments.append(str(frag))
        fragments.append(
            str(
                stack.enter_context(
                    rough_hfield_fragment(args.seed, args.output_video.parent)
                )
            )
        )
        fragments.append(str(stack.enter_context(poles_fragment())))
        fragments.append(str(stack.enter_context(dots_fragment(WAYPOINTS))))
        fragments.append(str(stack.enter_context(obstacle_fragment(len(PEDS)))))
        env = _compose_env(
            terrain_generator_override=course_terrain(args.seed),
            terrain_scan_override={
                "measured_points_x": list(SCAN_X),
                "measured_points_y": list(SCAN_Y),
                "vertical_offset": 0.3,
                "scale": 1.0,
            },
            scene_fragment_files=fragments,
            ground_friction=1.0,
            control_gains=(40.0, 1.0),
            simulate_action_latency=True,
        )
    depth_camera = SourceDepthCamera(env, 0.0)
    probe = ContactProbe(env)
    backend = env._backend
    ctrl_dt = float(env.cfg.ctrl_dt)
    nq = backend.model.nq
    ped_idx = []
    for i in range(len(PEDS)):
        jxi = backend.model.joint(f"dyn_obs{i}_x")
        jyi = backend.model.joint(f"dyn_obs{i}_y")
        ped_idx.append(
            {
                "qpos": (1 + int(jxi.qposadr[0]), 1 + int(jyi.qposadr[0])),
                "qvel": (
                    1 + nq + int(jxi.dofadr[0]),
                    1 + nq + int(jyi.dofadr[0]),
                ),
            }
        )
    static_points = static_cloud()

    positions: list[list[float]] = []
    skills: list[int] = []
    classes: list[int] = []
    class_switches: list[dict[str, Any]] = []
    refresh_steps: list[int] = []
    forbidden_steps: list[int] = []
    collision_steps: list[int] = []
    done_steps: list[int] = []
    neupan_latency_ms: list[float] = []
    segment_marks: dict[str, int] = {}
    gate_sides: dict[str, str] = {}
    reached_step: int | None = None
    consumed = 0
    class_arc = 0.0
    held_proposal: tuple[float, float] | None = None
    held_frac = 1.0
    frozen_yaw: tuple[float, float] | None = None
    frozen_frac = 1.0
    last_class: int | None = None
    previous_foot_contact = np.zeros((1, 4), dtype=np.float32)
    all_finite = True
    live_contract: dict[str, Any] = {}
    started = time.monotonic()

    def ped_state(
        t: float, spec: tuple[float, float, float, float, float]
    ) -> tuple[np.ndarray, np.ndarray]:
        cx, cy, amp, period, phase = spec
        omega = 2.0 * np.pi / period
        y = cy + amp * np.sin(omega * t + phase)
        vy = amp * omega * np.cos(omega * t + phase)
        return np.asarray([cx, y]), np.asarray([0.0, vy])

    def initialize():
        nonlocal previous_foot_contact, live_contract
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        env.set_autoreset(False)
        qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
        qvel = np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1)
        qpos[0, :3] = (START_XY[0], START_XY[1], 0.42)
        qpos[0, 3:7] = (1.0, 0.0, 0.0, 0.0)
        indices = backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[0, indices] = profile.low_contract.source_default_dof
        for joint_name, joint_qpos in OBSTACLE_JOINTS:
            idx = backend.get_joint_dof_pos_indices((joint_name,))[0] + 7
            qpos[0, int(idx)] = joint_qpos
        for i, spec in enumerate(PEDS):
            centre, _ = ped_state(0.0, spec)
            ox = backend.get_joint_dof_pos_indices((f"dyn_obs{i}_x",))[0] + 7
            oy = backend.get_joint_dof_pos_indices((f"dyn_obs{i}_y",))[0] + 7
            qpos[0, int(ox)] = centre[0]
            qpos[0, int(oy)] = centre[1]
        backend.set_state(np.asarray([0], dtype=np.int32), qpos, qvel)
        state = env.update_state(state)
        adapter.reset()
        state.info["current_actions"] = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), profile.low_contract
        )
        previous_foot_contact.fill(0.0)
        return state

    def step(state):
        nonlocal reached_step, consumed, class_arc, held_proposal, held_frac
        nonlocal frozen_yaw, frozen_frac, last_class
        nonlocal previous_foot_contact, all_finite
        step_index = len(positions) + 1
        t = (step_index - 1) * ctrl_dt
        state_vec = backend._physics_state[0]
        ped_centres = []
        ped_vels = []
        for spec, idxs in zip(PEDS, ped_idx):
            c, v = ped_state(t, spec)
            state_vec[idxs["qpos"][0]] = c[0]
            state_vec[idxs["qpos"][1]] = c[1]
            state_vec[idxs["qvel"][0]] = v[0]
            state_vec[idxs["qvel"][1]] = v[1]
            ped_centres.append(c)
            ped_vels.append(v)
        ped_arr = np.asarray(ped_centres)

        base_quat = backend.get_base_quat().copy()
        base_pos = backend.get_base_pos().copy()
        robot_xy = base_pos[0, :2].astype(np.float64)
        base_yaw = _base_yaw(base_quat[0])
        if reached_step is None and (
            float(np.linalg.norm(robot_xy - goal_xy)) < GOAL_THRESHOLD_M
        ):
            reached_step = step_index - 1
        dist_obs = float(
            np.min(np.linalg.norm(ped_arr - robot_xy.reshape(1, 2), axis=1))
        )
        if reached_step is None and dist_obs < COLLISION_DIST_M:
            collision_steps.append(step_index)

        contact = probe.sample()
        sensor_floor = (np.linalg.norm(env.feet_force, axis=2) > 2.0).astype(np.float32)
        current_contact = np.maximum(contact["foot_contact"], sensor_floor)
        foot_contact = np.maximum(current_contact, previous_foot_contact)
        previous_foot_contact = current_contact

        nearest = int(
            np.argmin(np.linalg.norm(dense_path - robot_xy.reshape(1, 2), axis=1))
        )
        class_arc = max(class_arc, (nearest + 1) * PATH_SPACING_M)
        active_class = class_at_arc(intervals, class_arc)
        in_jump = active_class in JUMP_CLASSES
        if last_class is not None and active_class != last_class:
            class_switches.append(
                {"step": step_index, "from": last_class, "to": active_class}
            )
        last_class = active_class

        remaining, consumed = remaining_policy_path(
            dense_path, policy_arc, dense_path, robot_xy, consumed
        )
        waypoint = path_to_tsc_waypoints(
            remaining,
            np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
            CURRENT_LOOKAHEAD_M,
            NEXT_LOOKAHEAD_M,
            MAX_ABS_YAW_RAD,
        )
        base_pair = (
            base_yaw + float(waypoint.delta_yaw),
            base_yaw + float(waypoint.delta_next_yaw),
        )
        replan = (step_index - 1) % REPLAN_PERIOD_STEPS == 0
        if replan:
            planner_started = time.perf_counter()
            ped_points = surface_points(ped_arr)
            per_ped = ped_points.shape[1] // len(PEDS)
            ped_velocities = np.hstack(
                [np.tile(v.reshape(2, 1), (1, per_ped)) for v in ped_vels]
            )
            points = np.hstack([ped_points, static_points])
            velocities = np.hstack(
                [ped_velocities, np.zeros_like(static_points)]
            )
            action, info = planner(
                np.asarray([[robot_xy[0]], [robot_xy[1]], [base_yaw]]),
                points,
                velocities,
            )
            neupan_latency_ms.append((time.perf_counter() - planner_started) * 1000.0)
            if info["stop"] or info["arrive"]:
                held_proposal = None
                held_frac = 0.0 if info["stop"] else 1.0
            else:
                trajectory = np.hstack(planner.opt_trajectory).T
                pw = path_to_tsc_waypoints(
                    trajectory,
                    np.asarray([robot_xy[0], robot_xy[1], base_yaw]),
                    CURRENT_LOOKAHEAD_M,
                    NEXT_LOOKAHEAD_M,
                    MAX_ABS_YAW_RAD,
                )
                held_proposal = (
                    base_yaw + float(pw.delta_yaw),
                    base_yaw + float(pw.delta_next_yaw),
                )
                held_frac = float(np.clip(action[0, 0] / NEUPAN_REF_SPEED, 0.0, 1.0))
        in_corridor = any(
            bool(r.contains(robot_xy.reshape(1, 2))[0]) for r in TASK_CORRIDORS
        )
        obstacle_near = dist_obs < REFRESH_OBSTACLE_RADIUS_M
        neupan_leads = (not in_corridor) or obstacle_near
        current_heading = frozen_yaw[0] if frozen_yaw is not None else base_pair[0]
        # outside corridors NeuPAN is the primary navigator: adopt its
        # heading unconditionally (the 0.15 rad gate is an anti-jitter for
        # in-corridor pedestrian dodges only; keeping it in free space lets
        # the robot walk into the stop radius of planner-side walls).
        deviation_ok = (
            not in_corridor
            or abs(wrap_to_pi(held_proposal[0] - current_heading))
            > REFRESH_DEVIATION_RAD
            if held_proposal is not None
            else False
        )
        adopt = neupan_leads and held_proposal is not None and deviation_ok
        frac_base = held_frac if neupan_leads else 1.0
        if in_jump:
            if frozen_yaw is None:
                frozen_yaw = base_pair
                frozen_frac = frac_base
            if adopt and replan:
                frozen_yaw = held_proposal
                frozen_frac = frac_base
                refresh_steps.append(step_index)
            delta_yaw, _ = committed_delta_yaw(frozen_yaw, base_yaw)
            frac = frozen_frac
        else:
            frozen_yaw = None
            heading_pair = held_proposal if adopt else base_pair
            delta_yaw, _ = committed_delta_yaw(heading_pair, base_yaw)
            frac = frac_base
            if adopt:
                refresh_steps.append(step_index)

        command, diagnostics = adapter.preview_command(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            depth_image=depth_camera.capture(),
            delta_yaw=delta_yaw,
            obstacle_type=int(active_class),
        )
        skill = int(diagnostics["skill"][0])
        vx_min = float(adapter.commander.command_offset_mat[skill, 0])
        actor_vx = float(command[0, 0])
        command = command.copy()
        command[0, 0] = float(np.clip(frac * actor_vx, vx_min, max(actor_vx, vx_min)))
        action, low = adapter.bbc.act(
            base_quat_wxyz=base_quat,
            base_ang_vel=env.get_gyro().copy(),
            dof_pos=env.get_dof_pos().copy(),
            dof_vel=env.get_dof_vel().copy(),
            foot_contact=foot_contact,
            command=command,
            explicit=None,
        )
        adapter.bbc.history.fill(0.0)
        skills.append(skill)
        classes.append(active_class)
        state = env.step(action)
        if np.any(state.terminated):
            done_steps.append(step_index)
        base_after = backend.get_base_pos().copy()
        positions.append(base_after[0].tolist())
        marks = (
            ("rough", 4.0, -8.8, "x>"),
            ("stairs", 4.0, -4.2, "x>"),
            ("seesaw", 4.0, 2.1, "x>"),
            ("turn1", 0.0, 8.0, "row2"),
            ("combo", 0.0, 1.5, "x<"),
            ("bar_avoid", 0.0, -6.8, "row2wide"),
            ("turn2", -4.0, -8.0, "row3"),
            ("tire", -4.0, 0.2, "x>"),
        )
        x_now, y_now = base_after[0, 0], base_after[0, 1]
        for name, row_y, threshold, mode in marks:
            if name in segment_marks:
                continue
            on_row = abs(y_now - row_y) < 1.2
            if mode == "x>" and on_row and x_now > threshold:
                segment_marks[name] = step_index
            elif mode == "x<" and on_row and x_now < threshold:
                segment_marks[name] = step_index
            elif mode == "row2" and abs(y_now - 0.0) < 0.8 and x_now > threshold:
                segment_marks[name] = step_index
            elif mode == "row3" and abs(y_now + 4.0) < 0.8 and x_now < threshold:
                segment_marks[name] = step_index
            elif mode == "row2wide" and abs(y_now) < 2.6 and x_now < threshold:
                segment_marks[name] = step_index
        # strict slalom verdict: record which side each gate pole is passed
        # on; "poles" only marks when all four alternate S/N/S/N (the v2
        # official bypassed the whole line south and still got marked).
        for gi, gx in enumerate(GATE_XS):
            key = f"gate{gi}"
            if (
                key not in gate_sides
                and abs(x_now - gx) < 0.12
                and abs(y_now + 5.0) < 1.6
            ):
                gate_sides[key] = "S" if y_now < -5.0 else "N"
        if "poles" not in segment_marks and len(gate_sides) == 4:
            if tuple(gate_sides[f"gate{g}"] for g in range(4)) == (
                "S",
                "N",
                "S",
                "N",
            ):
                segment_marks["poles"] = step_index
        after = probe.sample()
        if after["forbidden"]:
            forbidden_steps.append(step_index)
        all_finite = all_finite and all(
            np.isfinite(v).all()
            for v in (action, delta_yaw, command, low["source_action"], base_after)
        )
        return state

    try:
        rendered = env.run_playback(
            initialize=initialize,
            step=step,
            num_steps=EPISODE_STEPS,
            output_video=args.output_video,
            headless=True,
            record_video=True,
            camera_kwargs={
                "cam_tracking": True,
                "cam_tracking_env_idx": 0,
                "cam_tracking_extra_envs": 0,
                "cam_distance": 5.0,
                "cam_elevation": -24.0,
                "cam_azimuth": 135.0,
            },
        )
    finally:
        depth_camera.close()
        env.close()

    video_exists = rendered is not None and args.output_video.is_file()
    video = _video_metadata(args.output_video) if video_exists else {}
    gate_end = reached_step if reached_step is not None else len(positions)
    done_before = [s for s in done_steps if s <= gate_end]
    checks = {
        "live_env_action_contract": bool(live_contract["passed"]),
        "rollout_finite": all_finite,
        "video_created": video_exists,
        "no_fall_before_success": not done_before,
        "no_pedestrian_collision": not collision_steps,
        "reached_goal": reached_step is not None,
    }
    return {
        "run_id": args.run_id,
        "status": "PASSED" if all(checks.values()) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "RadeonNav serpentine slalom probe",
        "seed": args.seed,
        "checks": checks,
        "metrics": {
            "reached_step": reached_step,
            "final_base_xyz_m": positions[-1],
            "trajectory_every_10": [
                [round(v, 3) for v in p] for p in positions[::10]
            ],
            "segment_marks": segment_marks,
            "class_switches": class_switches,
            "collision_steps": collision_steps[:10],
            "forbidden_contact_step_count": len(
                [s for s in forbidden_steps if s <= gate_end]
            ),
            "refresh_steps": refresh_steps[:20],
            "neupan_latency_ms_p95": (
                float(np.percentile(neupan_latency_ms, 95))
                if neupan_latency_ms
                else None
            ),
            "done_before_success_steps": done_before,
            "wall_time_sec": time.monotonic() - started,
        },
        "skill_counts": {
            str(int(s)): int(c)
            for s, c in zip(*np.unique(np.asarray(skills), return_counts=True))
        },
        "contracts": {
            "waypoints": WAYPOINTS,
            "fragments": [[n, dx, dy] for n, dx, dy in FRAGMENTS],
            "bar_disposition": (
                "IMPASSABLE per capability profile + BAR-SOLO matrix; the "
                "bar is a planner-side wall and NeuPAN routes around it"
            ),
            "task_corridors": [
                [r.x0, r.x1, r.y0, r.y1] for r in TASK_CORRIDORS
            ],
            "pedestrians": [
                {
                    "center": [p[0], p[1]],
                    "amplitude_m": p[2],
                    "period_s": p[3],
                    "phase_rad": p[4],
                }
                for p in PEDS
            ],
            "gate_walls": [list(g) for g in GATE_WALLS],
            "bar_wall": list(BAR_WALL),
            "gate_sides": gate_sides,
            "class_intervals": [
                {"s_start_m": i.s_start_m, "s_end_m": i.s_end_m, "label": i.label}
                for i in intervals
            ],
            "free_space_class": FREE_SPACE_CLASS,
            "episode_steps": EPISODE_STEPS,
            "depth_encoder_override_sha256": _sha256(args.depth_encoder_checkpoint),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
            "headless_tkinter_shim": shim,
        },
        "video": {
            "path": str(args.output_video),
            "sha256": _sha256(args.output_video) if video_exists else None,
            **video,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--depth-encoder-checkpoint",
        type=Path,
        default=ROOT
        / "experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt",
    )
    parser.add_argument("--tag", default="dryrun")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not args.depth_encoder_checkpoint.is_file():
        parser.error(f"missing checkpoint: {args.depth_encoder_checkpoint}")
    args.run_id = f"RADEON-NAV-SLALOM-{args.tag}"
    args.output_dir = args.output_dir or RESULTS_ROOT / args.tag
    args.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.output_video = args.output_dir / f"radeon-nav-slalom_{args.tag}.mp4"
    return args


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / f"result_{args.stamp}.json"
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": args.run_id,
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(result_path, payload)
    shutil.copy2(result_path, args.output_dir / "result.json")
    print(f"{payload['status']}: {result_path}")
    if "metrics" in payload:
        print("segments:", payload["metrics"]["segment_marks"])
        print("final:", [round(v, 2) for v in payload["metrics"]["final_base_xyz_m"]])
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
