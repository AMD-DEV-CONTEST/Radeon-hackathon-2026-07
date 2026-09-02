#!/usr/bin/env python3
"""Render the frozen robust-only Challenge Arena pair as a visual replay."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "challenge_arena_v1.json"
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_challenge_arena_amd.py"
GENESIS_SOURCE_ROOT = Path("/workspace/genesis-v1.2.3-src-b")
GENESIS_VERSION = "1.2.3"
PAIR_COUNT = 128
TOTAL_ENVS = 256
FPS = 20
FRAMES = 140
STEPS_PER_FRAME = 5
PANEL_WIDTH = 640
PANEL_HEIGHT = 480
OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 720
TOP_HEIGHT = 96
REQUESTED_CODEC = "FMP4"
GATE_CENTERS = ((2.0, 0.0, 1.0), (4.0, 0.5, 1.1), (6.0, 0.0, 1.0))
GATE_YAWS = (0.0, 0.15, -0.15)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-summary-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def bind_sources() -> None:
    source = GENESIS_SOURCE_ROOT.resolve()
    require((source / "genesis/__init__.py").is_file(), "frozen Genesis source is missing")
    os.environ["HOME"] = "/root"
    sys.path.insert(0, str(source))
    sys.path.insert(0, str((PROJECT_ROOT / "src").resolve()))


def gate_local_offset(center, yaw, local_y, local_z):
    return (
        center[0] - math.sin(yaw) * local_y,
        center[1] + math.cos(yaw) * local_y,
        center[2] + local_z,
    )


def make_prebuild_hook(selected_offset, left_env: int, right_env: int):
    display_centers = tuple(
        tuple(center[axis] + selected_offset[axis] for axis in range(3))
        for center in GATE_CENTERS
    )

    def hook(*, gs, scene, drone, num_envs):
        del drone
        require(num_envs == TOTAL_ENVS, "renderer batch size mismatch")
        require(getattr(scene, "_is_built", None) is False, "visual scene is already built")
        palette = ((1.0, 0.35, 0.05, 1.0), (0.05, 0.45, 1.0, 1.0), (0.1, 0.85, 0.3, 1.0))
        for center, yaw, color in zip(display_centers, GATE_YAWS, palette, strict=True):
            for local_y, local_z, size in (
                (-0.63, 0.0, (0.08, 0.06, 1.12)),
                (0.63, 0.0, (0.08, 0.06, 1.12)),
                (0.0, -0.53, (0.08, 1.32, 0.06)),
                (0.0, 0.53, (0.08, 1.32, 0.06)),
            ):
                scene.add_entity(
                    material=gs.materials.Rigid(),
                    morph=gs.morphs.Box(
                        pos=gate_local_offset(center, yaw, local_y, local_z),
                        euler=(0.0, 0.0, math.degrees(yaw)),
                        size=size,
                        fixed=True,
                        collision=False,
                        visualization=True,
                    ),
                    surface=gs.surfaces.Default(color=color),
                )
        cameras = []
        for env_idx in (left_env, right_env):
            cameras.append(
                scene.add_camera(
                    model="pinhole",
                    res=(PANEL_WIDTH, PANEL_HEIGHT),
                    pos=(3.0, -7.5, 4.0),
                    lookat=(3.0, 0.0, 1.0),
                    up=(0.0, 0.0, 1.0),
                    fov=50.0,
                    GUI=False,
                    near=0.1,
                    far=30.0,
                    env_idx=env_idx,
                )
            )
        return {"cameras": tuple(cameras), "display_gate_centers": display_centers}

    return hook


def camera_rgb(camera, np):
    rendered = camera.render(rgb=True)
    require(isinstance(rendered, (tuple, list)) and rendered, "camera returned no RGB frame")
    array = np.asarray(rendered[0])
    require(array.shape == (PANEL_HEIGHT, PANEL_WIDTH, 3), f"unexpected RGB shape: {array.shape}")
    require(array.dtype == np.uint8 and np.isfinite(array).all(), "invalid RGB frame")
    return np.ascontiguousarray(array)


def overlay_frame(cv2, np, left_rgb, right_rgb, *, step, gates, terminal, terminal_steps, success, strike, primary):
    canvas = np.full((OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), (16, 18, 23), dtype=np.uint8)
    left = cv2.cvtColor(left_rgb, cv2.COLOR_RGB2BGR)
    right = cv2.cvtColor(right_rgb, cv2.COLOR_RGB2BGR)
    canvas[TOP_HEIGHT:TOP_HEIGHT + PANEL_HEIGHT, :PANEL_WIDTH] = left
    canvas[TOP_HEIGHT:TOP_HEIGHT + PANEL_HEIGHT, PANEL_WIDTH:] = right
    cv2.rectangle(canvas, (0, TOP_HEIGHT), (PANEL_WIDTH - 1, TOP_HEIGHT + PANEL_HEIGHT - 1), (70, 70, 235), 4)
    cv2.rectangle(canvas, (PANEL_WIDTH, TOP_HEIGHT), (OUTPUT_WIDTH - 1, TOP_HEIGHT + PANEL_HEIGHT - 1), (90, 220, 95), 4)
    cv2.putText(canvas, "FLIGHTGUARD CHALLENGE ARENA", (28, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.02, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "Same Genesis scene. Same state. One controller change.", (28, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (190, 210, 235), 2, cv2.LINE_AA)
    cv2.rectangle(canvas, (12, TOP_HEIGHT + 12), (PANEL_WIDTH - 12, TOP_HEIGHT + 58), (24, 24, 34), -1)
    cv2.rectangle(canvas, (PANEL_WIDTH + 12, TOP_HEIGHT + 12), (OUTPUT_WIDTH - 12, TOP_HEIGHT + 58), (24, 34, 26), -1)
    cv2.putText(canvas, "BASELINE  Nominal PD  kp_z=2.5  kd_z=2.0", (26, TOP_HEIGHT + 43), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (125, 150, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "ROBUST Z  kp_z=8.0  kd_z=3.6", (PANEL_WIDTH + 26, TOP_HEIGHT + 43), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (125, 255, 145), 2, cv2.LINE_AA)

    def status(index):
        if not terminal[index]:
            return f"RUNNING | gates {gates[index]}/3 | t={step * 0.01:.2f}s"
        if success[index]:
            return f"MISSION SUCCESS | gates {gates[index]}/3 | terminal step {terminal_steps[index]}"
        reason = "COLLISION" if strike[index] else "MISSION FAILED"
        return f"{reason} | gates {gates[index]}/3 | terminal step {terminal_steps[index]}"

    cv2.rectangle(canvas, (0, TOP_HEIGHT + PANEL_HEIGHT), (OUTPUT_WIDTH, OUTPUT_HEIGHT), (12, 14, 18), -1)
    cv2.putText(canvas, status(0), (26, 618), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (125, 150, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, status(1), (PANEL_WIDTH + 26, 618), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (125, 255, 145), 2, cv2.LINE_AA)
    result_line = (
        f"Frozen paired study (n={primary['pair_count']}): "
        f"{100.0 * primary['nominal_success_rate']:.1f}% -> {100.0 * primary['robust_success_rate']:.1f}% "
        f"(+{primary['success_delta_percentage_points']:.1f} pp), 0 regressions"
    )
    cv2.putText(canvas, result_line, (28, 660), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (235, 235, 235), 2, cv2.LINE_AA)
    cv2.putText(canvas, "SIMULATION ONLY | Genesis 1.2.3 | AMD Radeon / ROCm | Visual replay of a frozen raw pair", (28, 697), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (170, 180, 190), 1, cv2.LINE_AA)
    return canvas


def frame_stats(frame, np):
    return {"mean": float(frame.mean()), "std": float(frame.std()), "nonblack_fraction": float(np.mean(np.any(frame > 2, axis=2)))}


def render(args: argparse.Namespace) -> dict[str, Any]:
    require(args.output.suffix.lower() == ".mp4", "output must be .mp4")
    require(not args.output.exists(), "refusing to overwrite output")
    partial = args.output.with_name(args.output.name + ".partial.mp4")
    require(not partial.exists(), "partial output already exists")
    require(sha256_file(args.summary) == args.expected_summary_sha256, "summary SHA mismatch")
    summary = json.loads(args.summary.read_bytes())
    require(summary["status"] == "PASS", "summary is not PASS")
    require(summary["simulation_only"] is True, "summary is not simulation-only")
    require(summary["bindings"]["config"]["sha256"] == sha256_file(CONFIG_PATH), "config binding drift")
    require(summary["bindings"]["runner"]["sha256"] == sha256_file(RUNNER_PATH), "runner binding drift")
    demo = summary["demo_pair"]
    raw_path = Path(demo["raw_path"])
    require(sha256_file(raw_path) == demo["raw_sha256"], "raw pair source SHA mismatch")
    raw_run = json.loads(raw_path.read_bytes())
    record = raw_run["pair_records"][demo["pair_index"]]
    require(record == demo["record"], "summary demo record differs from raw pair")
    require(raw_run["experiment"]["pairs"] == PAIR_COUNT, "raw pair batch shape mismatch")
    require(raw_run["experiment"]["domain_profile"] == "adversarial", "raw pair profile mismatch")

    import cv2
    import numpy as np
    bind_sources()
    import genesis as gs
    import torch
    from flightguard.controller import BatchedWaypointController, controller_config_for_profile
    from flightguard.domain_randomization import sample_domain_parameters
    from flightguard.gate_math import gate_lookthrough_target
    from flightguard.genesis_env import FlightGuardGenesisEnv

    require(Path(gs.__file__).resolve().is_relative_to(GENESIS_SOURCE_ROOT.resolve()), "Genesis source binding escaped")
    require(gs.__version__ == GENESIS_VERSION, "Genesis version mismatch")
    seed = int(demo["seed"])
    pair_index = int(demo["pair_index"])
    domain_seed = int(raw_run["experiment"]["domain_seed"])
    config = json.loads(CONFIG_PATH.read_bytes())
    torch.manual_seed(seed)
    gs.init(backend=gs.amdgpu, precision="32", seed=seed, performance_mode=False, logging_level="warning")
    require(gs.backend == gs.amdgpu, "renderer is not using amdgpu")
    require(torch.cuda.is_available() and torch.cuda.device_count() == 1, "renderer requires one Radeon GPU")
    domain_one_block = sample_domain_parameters(PAIR_COUNT, profile="adversarial", seed=domain_seed)
    require(domain_one_block is not None, "adversarial domain sampling returned None")
    domain = domain_one_block.repeat(2)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    unit = torch.rand((PAIR_COUNT, 2), generator=generator, dtype=torch.float32, device="cpu") * 2.0 - 1.0
    gate_offsets = torch.zeros((PAIR_COUNT, 3), dtype=torch.float32, device="cpu")
    gate_offsets[:, 1] = unit[:, 0] * float(config["paired_design"]["gate_jitter_y_m"])
    gate_offsets[:, 2] = unit[:, 1] * float(config["paired_design"]["gate_jitter_z_m"])
    selected_offset = tuple(float(value) for value in gate_offsets[pair_index].tolist())
    require(list(selected_offset) == record["gate_offset_m"], "selected gate offset does not reproduce")
    require(float(domain_one_block.mass_scale[pair_index]) == record["mass_scale"], "selected mass does not reproduce")
    require(float(domain_one_block.thrust_scale[pair_index]) == record["thrust_scale"], "selected thrust does not reproduce")
    require([float(value) for value in domain_one_block.wind_acceleration_mps2[pair_index].tolist()] == record["wind_acceleration_mps2"], "selected wind does not reproduce")
    require(int(domain_one_block.action_delay_steps[pair_index]) == record["action_delay_steps"], "selected delay does not reproduce")
    require(int(domain_one_block.stratum[pair_index]) == record["stratum"], "selected stratum does not reproduce")

    right_env = PAIR_COUNT + pair_index
    env = FlightGuardGenesisEnv(
        TOTAL_ENVS,
        domain_parameters=domain,
        show_viewer=False,
        prebuild_scene_hook=make_prebuild_hook(selected_offset, pair_index, right_env),
    )
    attachment = env.prebuild_attachment
    require(isinstance(attachment, dict) and len(attachment["cameras"]) == 2, "camera attachment mismatch")
    cameras = attachment["cameras"]
    repeated_offsets = torch.cat((gate_offsets, gate_offsets), dim=0).to(device=gs.device)
    env.gates += repeated_offsets[:, None, :]
    displayed = torch.tensor(attachment["display_gate_centers"], dtype=torch.float32, device=gs.device)
    require(torch.equal(env.gates[pair_index], displayed), "visual gates do not match selected physics gates")
    require(torch.equal(env.gates[right_env], displayed), "paired visual gates do not match selected physics gates")
    env.reset(torch.arange(TOTAL_ENVS, device=gs.device))
    nominal_controller = BatchedWaypointController(controller_config_for_profile("nominal"))
    robust_controller = BatchedWaypointController(controller_config_for_profile("robust_z"))

    active = torch.ones(TOTAL_ENVS, dtype=torch.bool, device=gs.device)
    terminal = torch.zeros_like(active)
    success = torch.zeros_like(active)
    struck = torch.zeros_like(active)
    gates_passed = torch.zeros(TOTAL_ENVS, dtype=torch.long, device=gs.device)
    terminal_step = torch.full((TOTAL_ENVS,), -1, dtype=torch.long, device=gs.device)
    frozen_rgb = [None, None]
    selected_indices = (pair_index, right_env)
    output_frames = 0
    simulation_step = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(partial), cv2.VideoWriter_fourcc(*REQUESTED_CODEC), float(FPS), (OUTPUT_WIDTH, OUTPUT_HEIGHT), True)
    require(writer.isOpened(), "OpenCV could not open video writer")
    try:
        with torch.inference_mode():
            for _frame_index in range(FRAMES):
                if frozen_rgb[1] is None:
                    for _ in range(STEPS_PER_FRAME):
                        simulation_step += 1
                        active_before = active.clone()
                        position = env.drone.get_pos()
                        quaternion = env.drone.get_quat()
                        velocity = env.drone.get_vel()
                        angular_velocity = env.drone.get_ang()
                        env_index = torch.arange(TOTAL_ENVS, device=gs.device)
                        clamped = env.gate_index.clamp(min=0, max=env.gates.shape[1] - 1)
                        gate_center = env.gates[env_index, clamped]
                        gate_yaw = env.gate_yaws[env_index, clamped]
                        target = gate_lookthrough_target(gate_center, gate_yaw, float(config["paired_design"]["gate_lookthrough_m"]))
                        nominal_action = nominal_controller(position[:PAIR_COUNT], quaternion[:PAIR_COUNT], velocity[:PAIR_COUNT], angular_velocity[:PAIR_COUNT], target[:PAIR_COUNT])
                        robust_action = robust_controller(position[PAIR_COUNT:], quaternion[PAIR_COUNT:], velocity[PAIR_COUNT:], angular_velocity[PAIR_COUNT:], target[PAIR_COUNT:])
                        action = torch.cat((nominal_action, robust_action), dim=0)
                        action = torch.where(active_before[:, None], action, torch.zeros_like(action))
                        result = env.step(action)
                        gates_passed += (result.passed & active_before).long()
                        completed = result.done & (env.gate_index >= env.gates.shape[1])
                        newly_done = active_before & result.done
                        success |= newly_done & completed
                        struck |= newly_done & result.struck
                        terminal |= newly_done
                        terminal_step[newly_done] = simulation_step
                        active = active_before & ~newly_done
                        for visual_index, env_index_value in enumerate(selected_indices):
                            if bool(newly_done[env_index_value]) and frozen_rgb[visual_index] is None:
                                frozen_rgb[visual_index] = camera_rgb(cameras[visual_index], np)
                        done_idx = torch.nonzero(newly_done, as_tuple=False).reshape(-1)
                        if done_idx.numel():
                            env.reset(done_idx)
                        if frozen_rgb[1] is not None:
                            break
                frames = [
                    frozen_rgb[index] if frozen_rgb[index] is not None else camera_rgb(cameras[index], np)
                    for index in range(2)
                ]
                selected_gates = [int(gates_passed[index]) for index in selected_indices]
                selected_terminal = [bool(terminal[index]) for index in selected_indices]
                selected_terminal_steps = [int(terminal_step[index]) for index in selected_indices]
                selected_success = [bool(success[index]) for index in selected_indices]
                selected_strike = [bool(struck[index]) for index in selected_indices]
                composed = overlay_frame(
                    cv2,
                    np,
                    frames[0],
                    frames[1],
                    step=simulation_step,
                    gates=selected_gates,
                    terminal=selected_terminal,
                    terminal_steps=selected_terminal_steps,
                    success=selected_success,
                    strike=selected_strike,
                    primary=summary["primary"],
                )
                writer.write(composed)
                output_frames += 1
    finally:
        writer.release()

    observed = {}
    for name, env_index_value in zip(("nominal", "robust_z"), selected_indices, strict=True):
        observed[name] = {
            "mission_success": bool(success[env_index_value]),
            "strike": bool(struck[env_index_value]),
            "terminal": bool(terminal[env_index_value]),
            "terminal_step": int(terminal_step[env_index_value]),
            "gates_passed": int(gates_passed[env_index_value]),
        }
        expected = record["arms"][name]
        for field in observed[name]:
            require(observed[name][field] == expected[field], f"visual replay mismatch: {name}.{field}")
    require(output_frames == FRAMES, "video frame-count write mismatch")
    require(partial.is_file() and partial.stat().st_size > 0, "partial video is missing")
    capture = cv2.VideoCapture(str(partial))
    require(capture.isOpened(), "rendered video cannot be decoded")
    decoded = 0
    checks = {}
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            require(frame.shape == (OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), "decoded frame shape mismatch")
            if decoded in {0, FRAMES // 2, FRAMES - 1}:
                panel_checks = {}
                for name, x_start in (("nominal", 0), ("robust_z", PANEL_WIDTH)):
                    camera_only = frame[
                        TOP_HEIGHT + 64 : TOP_HEIGHT + PANEL_HEIGHT - 8,
                        x_start + 8 : x_start + PANEL_WIDTH - 8,
                    ]
                    stats = frame_stats(camera_only, np)
                    require(
                        stats["std"] > 5.0 and stats["nonblack_fraction"] > 0.05,
                        f"decoded {name} camera panel failed visibility gate",
                    )
                    panel_checks[name] = stats
                checks[str(decoded)] = panel_checks
            decoded += 1
        actual_fps = float(capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    require(decoded == FRAMES, "decoded frame count mismatch")
    require(math.isclose(actual_fps, FPS, rel_tol=0.0, abs_tol=0.05), "decoded FPS mismatch")
    os.replace(partial, args.output)
    os.chmod(args.output, 0o444)
    return {
        "status": "PASS",
        "metric_eligible": False,
        "simulation_only": True,
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_size_bytes": args.output.stat().st_size,
        "frames": decoded,
        "fps": actual_fps,
        "resolution": [OUTPUT_WIDTH, OUTPUT_HEIGHT],
        "codec": REQUESTED_CODEC,
        "summary_sha256": args.expected_summary_sha256,
        "raw_pair_sha256": demo["raw_sha256"],
        "seed": seed,
        "pair_index": pair_index,
        "context": {
            "stratum": record["stratum_name"],
            "mass_scale": record["mass_scale"],
            "thrust_scale": record["thrust_scale"],
            "wind_acceleration_mps2": record["wind_acceleration_mps2"],
            "action_delay_steps": record["action_delay_steps"],
            "gate_offset_m": record["gate_offset_m"],
        },
        "observed": observed,
        "frame_checks": checks,
        "runtime": {
            "genesis_version": gs.__version__,
            "gpu": torch.cuda.get_device_name(0),
            "torch_version": torch.__version__,
            "torch_hip": torch.version.hip,
            "visible_gpu_count": torch.cuda.device_count(),
        },
    }


def main() -> None:
    print(json.dumps(render(parse_args()), sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
