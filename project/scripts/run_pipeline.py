# project/scripts/run_pipeline.py
"""
R.A.G.E. (ROCm-Accelerated Generalist Embodiment) - Master Orchestrator

Purpose
-------
Wires all six previously-built modules into a single perception ->
retrieval -> scheduling -> reasoning -> action control loop, running
against the live Genesis simulation, and benchmarks the loop on AMD ROCm
hardware.

Pipeline per control cycle (every CONTROL_EVERY sim steps):

    cam_top.render()                                  [Genesis]
          |
          v  rgb frame (H, W, 3) uint8
    vision_process.detect()                            [Phase 3]
          |
          v  List[Detection] -> yolo_summary (str)
    vector_store.SOPVectorStore.retrieve_sop()          [Phase 3]
          |
          v  SOPResult -> sop_text (str)
    cds_heuristic.schedule_cable_insertions()           [Phase 3]
          |
          v  ScheduleResult -> cds_schedule (List[str])
    cognitive_manager.CognitiveManager.reason()         [Phase 4]
          |
          v  command (str)
    embodied_policy.EmbodiedPolicy.predict_action()     [Phase 5]
          |
          v  action: np.ndarray, shape (7,) - [dx,dy,dz,droll,dpitch,dyaw,grasp]
    Robot B's IK target = current_ee_pos + action[:3]   [Genesis, Phase 2]

Robot A is placed in a fixturing hover pose once before the loop and
re-asserts that pose every single sim step for the whole run (mirrors
server_assembly.py's active-fixturing "hold" behavior) so the scene stays
representative of the real cell while the benchmark focuses on Robot B's
perception-to-action loop.

Why NOT ArmIKController.move_to()/hold() directly in the loop
----------------------------------------------------------------
Those helpers each internally call `scene.step()` in their own loop. To
get an EXACT, easily-benchmarked "100 simulation steps" for this script
(one scene.step() per iteration, regardless of whether that iteration is
a control cycle or not), this script commands both arms' target DOFs
directly via `robot.control_dofs_position(...)` each iteration, and calls
`scene.step()` exactly once per iteration itself - the same low-level
pattern ArmIKController.move_to()/hold() use internally, just unrolled so
one iteration == one physics step.

Run:
    python -m project.scripts.run_pipeline
    python -m project.scripts.run_pipeline --dry-run   # no Genesis required;
                                                         # exercises the
                                                         # surrounding
                                                         # pipeline logic
                                                         # with a stand-in
                                                         # scene/robot
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from typing import List, Optional

import numpy as np

# --------------------------------------------------------------------------- #
# Phase 2 - physics environment
# --------------------------------------------------------------------------- #
#
# server_assembly.py does a hard `import genesis as gs` at module scope, so
# on a machine without Genesis/Vulkan installed, even importing THIS module
# would otherwise crash before argparse gets a chance to see --dry-run. We
# import it defensively and fall back to local copies of the handful of
# layout constants we need, so --dry-run (or any machine missing Genesis)
# degrades gracefully instead of hard-failing at import time.
try:
    from project.envs.server_assembly import (
        ArmIKController,
        CABLE_ANCHOR,
        CABLE_RADIUS,
        CABLE_SPACING_Y,
        GPU_BLOCK_POS,
        GPU_BLOCK_SIZE,
        HOVER_HEIGHT,
        build_scene,
        init_genesis,
    )
    _SERVER_ASSEMBLY_AVAILABLE = True
    _SERVER_ASSEMBLY_IMPORT_ERROR = None
except ImportError as exc:
    _SERVER_ASSEMBLY_AVAILABLE = False
    _SERVER_ASSEMBLY_IMPORT_ERROR = exc
    # Mirrors of server_assembly.py's constants - only used when the real
    # module (and therefore Genesis) isn't importable at all.
    CABLE_ANCHOR = (0.50, -0.40, 0.0)
    CABLE_RADIUS = 0.009
    CABLE_SPACING_Y = 0.16
    GPU_BLOCK_POS = (0.50, 0.40, 0.02)
    GPU_BLOCK_SIZE = (0.22, 0.16, 0.04)
    HOVER_HEIGHT = 0.18

# --------------------------------------------------------------------------- #
# Phase 3 - perception / RAG / scheduling
# --------------------------------------------------------------------------- #
from project.scripts.vision_process import detect as yolo_detect
from project.memory.vector_store import SOPVectorStore
from project.scripts.scheduling.cds_heuristic import schedule_cable_insertions

# --------------------------------------------------------------------------- #
# Phase 4 / 5 - cognition and action
# --------------------------------------------------------------------------- #
from project.scripts.cognitive_manager import CognitiveManager
from project.scripts.embodied_policy import EmbodiedPolicy

try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOTAL_SIM_STEPS = 30000      # total scene.step() calls in the benchmarked loop
CONTROL_EVERY = 10         # run the full perception->action pipeline every N steps
FAULT_QUERY_AFTER_STEP = 15000  # steps < this use the nominal SOP query, >= use the fault query

NOMINAL_SOP_QUERY = "align connector centroid before descending approach port normal axis"
FAULT_SOP_QUERY = "robot lost grip and dropped the cable mid transfer"

BENCHMARK_DIR = "amd_benchmarks"
BENCHMARK_FILE = os.path.join(BENCHMARK_DIR, "pipeline_metrics.json")


# --------------------------------------------------------------------------- #
# Pretty terminal logging helpers
# --------------------------------------------------------------------------- #

_RULE = "-" * 78


def log_header(text: str):
    print("\n" + "=" * 78)
    print(f"  {text}")
    print("=" * 78)


def log_section(tag: str, text: str):
    """One tagged line inside a control-cycle log block, e.g.
    log_section('VISION', '3 ports + 3 cables detected')."""
    print(f"    [{tag:^10s}] {text}")


def log_cycle_block(step: int, cycle_idx: int, query_used: str, sop_title: str,
                     yolo_summary: str, command: str, action: np.ndarray,
                     new_pos: np.ndarray):
    print(f"\n{_RULE}")
    print(f"  CONTROL CYCLE {cycle_idx}  (sim step {step})")
    print(_RULE)
    log_section("VISION", yolo_summary)
    log_section("RAG", f"query='{query_used}' -> SOP: \"{sop_title}\"")
    log_section("SCHEDULE", "CDS sequence recomputed (see solver log above)")
    log_section("COGNITION", f"\"{command}\"")
    log_section("ACTION", f"{np.round(action, 4).tolist()}")
    log_section("EE TARGET", f"new Robot B position -> {np.round(new_pos, 4).tolist()}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def get_camera_rgb(cam) -> np.ndarray:
    """Render `cam` and normalize its output to a plain (H, W, 3) uint8
    RGB array. Different Genesis versions have returned a bare rgb array,
    a (rgb, depth, ...) tuple, or a dict of named buffers from
    Camera.render() - handle all three so this script isn't brittle to
    the exact build installed on the hackathon rig.
    """
    rendered = cam.render()
    if isinstance(rendered, tuple):
        rgb = rendered[0]
    elif isinstance(rendered, dict):
        rgb = rendered.get("rgb", next(iter(rendered.values())))
    else:
        rgb = rendered
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return rgb


def summarize_detections(detections: List) -> str:
    """Turn vision_process.Detection objects into one compact human/LLM
    -readable line for the CognitiveManager prompt and terminal logs."""
    if not detections:
        return "No detections."
    ports = [d for d in detections if d.category == "port"]
    cables = [d for d in detections if d.category == "cable"]
    port_str = ", ".join(f"{d.color}_{d.shape}(conf={d.confidence:.2f})" for d in ports)
    cable_str = ", ".join(f"{d.color}(conf={d.confidence:.2f})" for d in cables)
    return (f"{len(ports)} ports detected [{port_str}]; "
            f"{len(cables)} cables detected [{cable_str}].")


def get_peak_vram_mb(device_index: int = 0) -> Optional[float]:
    """Best-effort peak VRAM usage in MB, for the AMD ROCm benchmark log.

    Preference order:
      1. torch.cuda.max_memory_allocated() - works transparently on a
         ROCm-built PyTorch, since ROCm exposes AMD GPUs under the same
         'cuda' namespace as NVIDIA CUDA. This only reflects tensors torch
         itself allocated (i.e. real CognitiveManager/EmbodiedPolicy
         weights, if loaded) - it will NOT see Genesis's own Vulkan
         allocations, which live outside torch's allocator entirely.
      2. `rocm-smi --showmeminfo vram --json` - a system-level reading
         that DOES include Genesis's Vulkan VRAM usage, so it's the more
         representative number for this pipeline's true footprint. Used
         as the primary source when available; torch's number is reported
         alongside it for reference.
    """
    system_reading = _read_vram_via_rocm_smi()
    if system_reading is not None:
        return system_reading

    if _TORCH_AVAILABLE and torch.cuda.is_available():
        torch.cuda.synchronize()
        return torch.cuda.max_memory_allocated(device_index) / (1024 ** 2)

    return None


def _read_vram_via_rocm_smi() -> Optional[float]:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        # rocm-smi's JSON nests per-GPU under keys like "card0"; pull the
        # first GPU's "VRAM Total Used Memory (B)" field, converting bytes
        # to MB. Field naming has shifted slightly across ROCm releases,
        # so search defensively rather than hardcoding one exact key.
        for gpu_key, gpu_data in data.items():
            if not isinstance(gpu_data, dict):
                continue
            for field_name, value in gpu_data.items():
                if "used memory" in field_name.lower():
                    return float(value) / (1024 ** 2)
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        # rocm-smi not installed, not on PATH, or produced unexpected
        # output - fall back to the torch reading in get_peak_vram_mb().
        return None


# --------------------------------------------------------------------------- #
# Minimal stand-ins for --dry-run (no Genesis / GPU required)
# --------------------------------------------------------------------------- #
#
# These exist ONLY to let the surrounding pipeline logic (perception ->
# RAG -> scheduling -> cognition -> action -> logging -> benchmarking) be
# exercised on a machine without Genesis/Vulkan installed, e.g. to sanity
# check this script before running it for real on the ROCm rig. They are
# never used in a normal (non---dry-run) invocation.

class _DryRunCamera:
    """Fakes cam_top.render() with a static blank frame."""
    def render(self):
        return np.zeros((960, 960, 3), dtype=np.uint8)


class _DryRunRobot:
    """Fakes just enough of a Genesis rigid-body entity's DOF control API
    for ArmIKController to run without a real physics backend."""
    def control_dofs_position(self, *args, **kwargs):
        pass

    def get_link(self, name):
        return self

    def set_dofs_kp(self, *args, **kwargs):
        pass

    def set_dofs_kv(self, *args, **kwargs):
        pass

    def set_dofs_force_range(self, *args, **kwargs):
        pass

    def inverse_kinematics(self, link, pos, quat):
        # Not a real IK solve - just enough DOF values (9, matching the
        # Franka's 7 arm + 2 finger DOFs) for downstream code to slice.
        return np.zeros(9, dtype=np.float32)


class _DryRunScene:
    def step(self):
        pass


def _build_dry_run_environment():
    """Returns (scene, robot_a_entity, robot_b_entity, cam_far, cam_top)
    shaped like build_scene()'s real return values, backed entirely by
    the fakes above."""
    scene = _DryRunScene()
    robot_a_entity = _DryRunRobot()
    robot_b_entity = _DryRunRobot()
    cam_far = _DryRunCamera()
    cam_top = _DryRunCamera()
    return scene, robot_a_entity, robot_b_entity, cam_far, cam_top


class _DryRunArmIKController:
    """Stand-in for server_assembly.ArmIKController, used ONLY when that
    real class couldn't even be imported (i.e. Genesis itself isn't
    installed on this machine at all). Exposes just the subset of the
    real class's interface this script touches: DOWNWARD_QUAT, solve_ik(),
    the arm_dofs/n_arm_dofs bookkeeping, and a ._last_qpos slot - enough
    for the surrounding pipeline logic to run unmodified.
    """
    DOWNWARD_QUAT = np.array([0.0, 1.0, 0.0, 0.0])

    def __init__(self, robot, name, n_arm_dofs=7):
        self.robot = robot
        self.name = name
        self.n_arm_dofs = n_arm_dofs
        self.arm_dofs = np.arange(0, n_arm_dofs)
        self._last_qpos = None

    def solve_ik(self, target_pos, target_quat):
        # No real kinematics here - just return a correctly-shaped
        # placeholder (7 arm + 2 finger DOFs) so downstream slicing works.
        return np.zeros(self.n_arm_dofs + 2, dtype=np.float32)


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #

def main(dry_run: bool = False):
    log_header("R.A.G.E. - Master Pipeline Orchestrator")

    # -- 1. Initialization ------------------------------------------------- #

    if not _SERVER_ASSEMBLY_AVAILABLE and not dry_run:
        print(f"[run_pipeline] WARNING: could not import server_assembly.py "
              f"({_SERVER_ASSEMBLY_IMPORT_ERROR!r}). Genesis is likely not "
              f"installed on this machine. Forcing --dry-run so this script "
              f"can still validate the surrounding pipeline logic.")
    effective_dry_run = dry_run or not _SERVER_ASSEMBLY_AVAILABLE

    if effective_dry_run:
        print("[run_pipeline] DRY RUN: skipping init_genesis()/build_scene(), "
              "using in-memory stand-ins. Physics/rendering are NOT real.")
        scene, robot_a_entity, robot_b_entity, cam_far, cam_top = _build_dry_run_environment()
    else:
        print("[run_pipeline] Initializing Genesis (ROCm/Vulkan backend)...")
        init_genesis()
        scene, entities, cam_far, cam_top = build_scene()
        robot_a_entity = entities["robot_a"]
        robot_b_entity = entities["robot_b"]

    if _SERVER_ASSEMBLY_AVAILABLE:
        robot_a = ArmIKController(robot_a_entity, name="robot_a_fixturer")
        robot_b = ArmIKController(robot_b_entity, name="robot_b_feeder")
    else:
        # Genesis itself isn't importable - use the interface-compatible
        # stand-in so the rest of this function needs zero branching.
        robot_a = _DryRunArmIKController(robot_a_entity, name="robot_a_fixturer")
        robot_b = _DryRunArmIKController(robot_b_entity, name="robot_b_feeder")

    # Robot A: one-time move into a fixturing hover pose above the GPU
    # block. It re-asserts this exact target every sim step for the rest
    # of the run (see the loop below), approximating Phase 2's active
    # fixturing without spending the full grasp+lift choreography's step
    # budget on this benchmarking pass.
    block_top_z = GPU_BLOCK_POS[2] + GPU_BLOCK_SIZE[2] / 2
    fixture_hover_pos = (GPU_BLOCK_POS[0], GPU_BLOCK_POS[1], block_top_z + 0.15)
    qpos_a = robot_a.solve_ik(fixture_hover_pos, robot_a.DOWNWARD_QUAT)
    robot_a._last_qpos = qpos_a
    robot_a.robot.control_dofs_position(qpos_a[: robot_a.n_arm_dofs], robot_a.arm_dofs)
    print(f"[run_pipeline] Robot A positioned at fixturing hover pose "
          f"{np.round(fixture_hover_pos, 3).tolist()}.")

    # Robot B: starting end-effector target is a hover pose above the red
    # cable (matches Phase 2's --hover-only IK proof's starting point).
    # `current_ee_pos` is the running position this script updates every
    # control cycle by applying the policy's action[:3] delta - it is the
    # single source of truth for "where do we want Robot B's EE next".
    red_cable_y = CABLE_ANCHOR[1] + (-1) * CABLE_SPACING_Y
    current_ee_pos = np.array(
        [CABLE_ANCHOR[0], red_cable_y, CABLE_RADIUS + HOVER_HEIGHT], dtype=np.float32
    )
    qpos_b = robot_b.solve_ik(tuple(current_ee_pos), robot_b.DOWNWARD_QUAT)
    robot_b._last_qpos = qpos_b
    robot_b.robot.control_dofs_position(qpos_b[: robot_b.n_arm_dofs], robot_b.arm_dofs)
    print(f"[run_pipeline] Robot B positioned at starting hover pose "
          f"{np.round(current_ee_pos, 3).tolist()}.")

    print("[run_pipeline] Loading Milvus Lite SOP memory...")
    sop_store = SOPVectorStore()
    sop_store.seed_if_empty()

    print("[run_pipeline] Loading CognitiveManager (mock mode - VRAM-safe default)...")
    brain = CognitiveManager(use_mock=False)

    print("[run_pipeline] Loading EmbodiedPolicy (mock mode - VRAM-safe default)...")
    policy = EmbodiedPolicy(use_mock=False)

    # Reset VRAM accounting right before the benchmarked loop starts, so
    # earlier setup (Genesis init, model loading) doesn't pollute the
    # "pipeline loop" peak-memory number.
    if _TORCH_AVAILABLE and torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    # -- 2 & 3. Control loop + data flow ------------------------------------ #

    log_header(f"Starting {TOTAL_SIM_STEPS}-step control loop "
               f"(perception->action every {CONTROL_EVERY} steps)")

    cycle_log = []          # one entry per control cycle, saved into the benchmark JSON
    cycle_idx = 0
    cam_far.start_recording()
    loop_start = time.perf_counter()

    for step in range(TOTAL_SIM_STEPS):
        # Robot A: continuously re-assert its fixturing target every
        # step, exactly like ArmIKController.hold()'s PD-resistance
        # behavior, but inlined here so it shares this iteration's single
        # scene.step() call instead of triggering its own.
        robot_a.robot.control_dofs_position(
            robot_a._last_qpos[: robot_a.n_arm_dofs], robot_a.arm_dofs
        )

        if step % CONTROL_EVERY == 0:
            cycle_idx += 1
            cycle_start = time.perf_counter()

            # ---- Perception: Genesis cam_top -> YOLOv8 mock detect() ---- #
            rgb_frame = get_camera_rgb(cam_top)
            detections = yolo_detect(rgb_frame, model=None, use_mock=True, seed=step)
            yolo_summary = summarize_detections(detections)

            # ---- Retrieval: Milvus SOP lookup, nominal vs. fault query -- #
            # First half of the run queries the nominal insertion SOP;
            # second half switches to a dropped-cable fault query to
            # demonstrate the RAG layer dynamically overriding the
            # downstream CognitiveManager's directive mid-run.
            query_used = NOMINAL_SOP_QUERY if step < FAULT_QUERY_AFTER_STEP else FAULT_SOP_QUERY
            sop_hits = sop_store.retrieve_sop(query_used, top_k=1)
            sop_text = sop_hits[0].text if sop_hits else "No SOP retrieved."
            sop_title = sop_hits[0].title if sop_hits else "N/A"

            # ---- Scheduling: CDS heuristic over Robot B's cable jobs ---- #
            schedule_result = schedule_cable_insertions()

            # ---- Cognition: fuse all 4 streams into one directive ------- #
            command = brain.reason(
                image=rgb_frame,
                yolo_summary=yolo_summary,
                sop_text=sop_text,
                cds_schedule=schedule_result.sequence,
            )

            # ---- Action: directive -> 7-DOF delta action ---------------- #
            action = policy.predict_action(rgb_frame, command)

            # ---- Apply action[:3] to Robot B's IK target ----------------- #
            new_ee_pos = current_ee_pos + action[:3]
            qpos_b = robot_b.solve_ik(tuple(new_ee_pos), robot_b.DOWNWARD_QUAT)
            robot_b._last_qpos = qpos_b
            robot_b.robot.control_dofs_position(
                qpos_b[: robot_b.n_arm_dofs], robot_b.arm_dofs
            )
            current_ee_pos = new_ee_pos

            cycle_elapsed_ms = (time.perf_counter() - cycle_start) * 1000.0

            log_cycle_block(step, cycle_idx, query_used, sop_title,
                             yolo_summary, command, action, current_ee_pos)

            cycle_log.append({
                "sim_step": step,
                "control_cycle": cycle_idx,
                "sop_query": query_used,
                "sop_title": sop_title,
                "yolo_summary": yolo_summary,
                "cds_sequence": list(schedule_result.sequence),
                "cds_makespan_s": schedule_result.makespan,
                "command": command,
                "action": np.round(action, 5).tolist(),
                "new_ee_pos": np.round(current_ee_pos, 5).tolist(),
                "cycle_wall_time_ms": round(cycle_elapsed_ms, 3),
            })

        else:
            # Non-control step: reassert Robot B's last commanded target
            # (active-hold behavior) rather than issuing a new command.
            robot_b.robot.control_dofs_position(
                robot_b._last_qpos[: robot_b.n_arm_dofs], robot_b.arm_dofs
            )

        scene.step()

    cam_far.stop_recording(save_to_filename="amd_benchmarks/rage_bimanual_demo.mp4", fps=30)
    loop_elapsed_s = time.perf_counter() - loop_start

    # -- 4. AMD ROCm benchmarking -------------------------------------------- #

    steps_per_second = TOTAL_SIM_STEPS / loop_elapsed_s if loop_elapsed_s > 0 else float("inf")
    peak_vram_mb = get_peak_vram_mb()

    log_header("Benchmark Results")
    print(f"    Total sim steps        : {TOTAL_SIM_STEPS}")
    print(f"    Control cycles run     : {cycle_idx}")
    print(f"    Total loop time        : {loop_elapsed_s:.3f} s")
    print(f"    Steps per second       : {steps_per_second:.2f}")
    if peak_vram_mb is not None:
        print(f"    Peak VRAM used         : {peak_vram_mb:.1f} MB")
    else:
        print("    Peak VRAM used         : unavailable "
              "(no rocm-smi on PATH and no CUDA/ROCm torch device found)")

    metrics = {
        "total_sim_steps": TOTAL_SIM_STEPS,
        "control_every_n_steps": CONTROL_EVERY,
        "control_cycles_run": cycle_idx,
        "total_loop_time_s": round(loop_elapsed_s, 4),
        "steps_per_second": round(steps_per_second, 3),
        "peak_vram_mb": round(peak_vram_mb, 2) if peak_vram_mb is not None else None,
        "dry_run": dry_run,
        "cognitive_manager_mock_mode": brain.use_mock,
        "embodied_policy_mock_mode": policy.use_mock,
        "cycles": cycle_log,
    }

    os.makedirs(BENCHMARK_DIR, exist_ok=True)
    with open(BENCHMARK_FILE, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\n[run_pipeline] Metrics saved -> {BENCHMARK_FILE}")

    log_header("R.A.G.E. pipeline run complete.")


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="R.A.G.E. master pipeline orchestrator.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Genesis entirely and run the surrounding pipeline logic "
             "(vision/RAG/scheduling/cognition/action/benchmarking) against "
             "lightweight stand-ins. Useful for validating this script on a "
             "machine without Genesis/Vulkan installed, before running for "
             "real on ROCm hardware.",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)