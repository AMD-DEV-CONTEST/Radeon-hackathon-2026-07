#!/usr/bin/env python3
"""Render a nominal FlightGuard Genesis replay for visual submission use only."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENESIS_SOURCE_ROOT = Path("/workspace/genesis-v1.2.3-src-b")
GENESIS_RUNTIME_HOME = "/root"
GENESIS_VERSION = "1.2.3"
RENDER_SEED = 5001
NUM_ENVS = 1
SIM_DT_SECONDS = 0.01
GATE_LOOKTHROUGH_METERS = 0.5
REQUESTED_CODEC = "FMP4"
DISCLAIMER = "TRUTH-CONTROLLER | VISUAL REPLAY ONLY | SIMULATION | METRIC-INELIGIBLE"
EXPECTED_GATE_CENTERS = (
    (2.0, 0.0, 1.0),
    (4.0, 0.5, 1.1),
    (6.0, 0.0, 1.0),
)
EXPECTED_GATE_YAWS = (0.0, 0.15, -0.15)


def parse_resolution(value: str) -> tuple[int, int]:
    """Parse an even WIDTHxHEIGHT video resolution."""

    parts = value.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("resolution must be WIDTHxHEIGHT")
    try:
        width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("resolution must use integer dimensions") from exc
    if width < 64 or height < 64 or width % 2 or height % 2:
        raise argparse.ArgumentTypeError(
            "resolution dimensions must be even integers of at least 64 pixels"
        )
    return width, height


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render one fixed-seed nominal Genesis replay. The resulting MP4 is "
            "visual-only and must not be used as metric evidence."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New .mp4 output path; an existing path is rejected.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=5.0,
        help="Video duration in seconds (default: 5).",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=10,
        help="Output frames per second (default: 10).",
    )
    parser.add_argument(
        "--simulation-steps-per-frame",
        type=int,
        default=10,
        help=(
            "Genesis simulation steps advanced before each output frame "
            "(default: 10)."
        ),
    )
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=parse_resolution("1280x720"),
        metavar="WIDTHxHEIGHT",
        help="Even output resolution (default: 1280x720).",
    )
    return parser.parse_args()


def validate_cli(args: argparse.Namespace) -> tuple[Path, int, int, int, int]:
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("--output must end in .mp4")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0.0:
        raise ValueError("--duration-seconds must be finite and positive")
    if isinstance(args.fps, bool) or args.fps <= 0:
        raise ValueError("--fps must be a positive integer")
    if (
        isinstance(args.simulation_steps_per_frame, bool)
        or args.simulation_steps_per_frame <= 0
    ):
        raise ValueError("--simulation-steps-per-frame must be a positive integer")

    frame_count_float = args.duration_seconds * args.fps
    frame_count = int(round(frame_count_float))
    if frame_count <= 0 or not math.isclose(
        frame_count_float,
        frame_count,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise ValueError("duration-seconds * fps must be an exact positive integer")

    width, height = args.resolution
    return (
        output,
        width,
        height,
        frame_count,
        args.simulation_steps_per_frame,
    )


def bind_frozen_genesis_source() -> None:
    """Bind imports to the frozen Genesis v1.2.3 source tree."""

    source = GENESIS_SOURCE_ROOT.resolve()
    genesis_init = source / "genesis" / "__init__.py"
    if not genesis_init.is_file():
        raise FileNotFoundError(f"frozen Genesis source is missing: {genesis_init}")
    os.environ["HOME"] = GENESIS_RUNTIME_HOME
    source_text = str(source)
    sys.path[:] = [entry for entry in sys.path if entry != source_text]
    sys.path.insert(0, source_text)


def gate_local_offset(
    center: tuple[float, float, float],
    yaw: float,
    local_y: float,
    local_z: float,
) -> tuple[float, float, float]:
    """Transform a yaw-only gate-frame offset into world coordinates."""

    return (
        center[0] - math.sin(yaw) * local_y,
        center[1] + math.cos(yaw) * local_y,
        center[2] + local_z,
    )


def make_prebuild_scene_hook(width: int, height: int):
    """Create one GUI-free camera and three collision-disabled gate frames."""

    def hook(*, gs, scene, drone, num_envs):
        del drone
        if num_envs != NUM_ENVS:
            raise RuntimeError(f"visual replay requires num_envs={NUM_ENVS}")
        if getattr(scene, "_is_built", None) is not False:
            raise RuntimeError("visual attachments require an unbuilt Genesis scene")

        palette = (
            (1.0, 0.35, 0.05, 1.0),
            (0.05, 0.45, 1.0, 1.0),
            (0.1, 0.85, 0.3, 1.0),
        )
        gate_frames = []
        half_width = 0.60
        half_height = 0.50
        bar_thickness = 0.06
        plane_thickness = 0.08
        for center, yaw, color in zip(
            EXPECTED_GATE_CENTERS,
            EXPECTED_GATE_YAWS,
            palette,
            strict=True,
        ):
            gate_entities = []
            members = (
                (
                    -(half_width + bar_thickness / 2.0),
                    0.0,
                    (plane_thickness, bar_thickness, 2.0 * half_height + 0.12),
                ),
                (
                    +(half_width + bar_thickness / 2.0),
                    0.0,
                    (plane_thickness, bar_thickness, 2.0 * half_height + 0.12),
                ),
                (
                    0.0,
                    -(half_height + bar_thickness / 2.0),
                    (plane_thickness, 2.0 * half_width + 0.12, bar_thickness),
                ),
                (
                    0.0,
                    +(half_height + bar_thickness / 2.0),
                    (plane_thickness, 2.0 * half_width + 0.12, bar_thickness),
                ),
            )
            for local_y, local_z, size in members:
                gate_entities.append(
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
                )
            gate_frames.append(tuple(gate_entities))

        camera = scene.add_camera(
            model="pinhole",
            res=(width, height),
            pos=(3.0, -7.5, 4.0),
            lookat=(3.0, 0.0, 1.0),
            up=(0.0, 0.0, 1.0),
            fov=50.0,
            GUI=False,
            near=0.1,
            far=30.0,
            env_idx=0,
        )
        return {"camera": camera, "gate_frames": tuple(gate_frames)}

    return hook


def require_exact_environment_geometry(env, torch) -> None:
    """Prove that visual-frame constants exactly match the live environment."""

    expected_gates = torch.tensor(
        EXPECTED_GATE_CENTERS,
        dtype=torch.float32,
        device=env.device,
    ).unsqueeze(0)
    expected_yaws = torch.tensor(
        EXPECTED_GATE_YAWS,
        dtype=torch.float32,
        device=env.device,
    ).unsqueeze(0)
    if not torch.equal(env.gates, expected_gates):
        raise RuntimeError("visual gate centers do not exactly match the environment")
    if not torch.equal(env.gate_yaws, expected_yaws):
        raise RuntimeError("visual gate yaws do not exactly match the environment")


def require_rgb_frame(rgb, *, width: int, height: int, np):
    array = np.asarray(rgb)
    if array.shape != (height, width, 3):
        raise RuntimeError(
            f"camera RGB shape mismatch: expected {(height, width, 3)}, got {array.shape}"
        )
    if array.dtype != np.uint8:
        raise RuntimeError(f"camera RGB dtype mismatch: expected uint8, got {array.dtype}")
    if not np.isfinite(array).all():
        raise RuntimeError("camera RGB contains non-finite values")
    return np.ascontiguousarray(array)


def frame_quality(frame, *, np) -> dict[str, float]:
    return {
        "mean": float(frame.mean()),
        "std": float(frame.std()),
        "nonblack_fraction": float(np.mean(np.any(frame > 2, axis=2))),
    }


def require_visible_frame(stats: dict[str, float], frame_index: int) -> None:
    if stats["nonblack_fraction"] <= 0.01 or stats["std"] <= 2.0:
        raise RuntimeError(
            f"encoded frame {frame_index} failed visibility checks: {stats}"
        )


def fourcc_text(value: float) -> str:
    code = int(round(value))
    if code <= 0:
        raise RuntimeError(f"video decoder did not report a FourCC value: {value}")
    text = "".join(chr((code >> (8 * index)) & 0xFF) for index in range(4))
    text = text.rstrip("\x00")
    if not text:
        raise RuntimeError(f"video decoder reported an empty FourCC: {value}")
    return text


def render(args: argparse.Namespace) -> dict[str, object]:
    (
        output,
        width,
        height,
        frame_count,
        simulation_steps_per_frame,
    ) = validate_cli(args)

    import cv2
    import numpy as np

    version_parts = cv2.__version__.split(".")
    if len(version_parts) < 2 or tuple(map(int, version_parts[:2])) != (4, 13):
        raise RuntimeError(f"OpenCV 4.13 is required, got {cv2.__version__}")

    project_source = str((PROJECT_ROOT / "src").resolve())
    if project_source not in sys.path:
        sys.path.insert(0, project_source)
    bind_frozen_genesis_source()

    import genesis as gs
    import torch

    genesis_file = Path(gs.__file__).resolve()
    if not genesis_file.is_relative_to(GENESIS_SOURCE_ROOT.resolve()):
        raise RuntimeError(f"Genesis import escaped frozen source: {genesis_file}")
    if getattr(gs, "__version__", None) != GENESIS_VERSION:
        raise RuntimeError(
            f"expected Genesis {GENESIS_VERSION}, got {getattr(gs, '__version__', None)}"
        )

    gs.init(
        backend=gs.amdgpu,
        precision="32",
        seed=RENDER_SEED,
        performance_mode=False,
        logging_level="warning",
    )
    if gs.backend != gs.amdgpu:
        raise RuntimeError(f"expected gs.amdgpu, got {gs.backend}")
    if torch.version.hip is None:
        raise RuntimeError("PyTorch is not a ROCm build")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("visual replay requires exactly one visible Radeon GPU")

    from flightguard.controller import (
        BatchedWaypointController,
        controller_config_for_profile,
    )
    from flightguard.gate_math import gate_lookthrough_target
    from flightguard.genesis_env import FlightGuardGenesisEnv

    env = FlightGuardGenesisEnv(
        NUM_ENVS,
        dt=SIM_DT_SECONDS,
        show_viewer=False,
        prebuild_scene_hook=make_prebuild_scene_hook(width, height),
    )
    attachment = env.prebuild_attachment
    if not isinstance(attachment, dict) or set(attachment) != {"camera", "gate_frames"}:
        raise RuntimeError("prebuild hook returned an unexpected attachment")
    gate_frames = attachment["gate_frames"]
    if len(gate_frames) != 3 or any(len(frame) != 4 for frame in gate_frames):
        raise RuntimeError("prebuild hook did not create exactly three four-member gate frames")
    camera = attachment["camera"]
    require_exact_environment_geometry(env, torch)

    controller = BatchedWaypointController(controller_config_for_profile("nominal"))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"output appeared before writer creation: {output}")

    fourcc = cv2.VideoWriter_fourcc(*REQUESTED_CODEC)
    writer = cv2.VideoWriter(
        str(output),
        fourcc,
        float(args.fps),
        (width, height),
        True,
    )
    if not writer.isOpened():
        writer.release()
        raise RuntimeError(f"OpenCV could not open FMP4 writer: {output}")

    simulation_step = 0
    terminal = False
    written_frames = 0
    try:
        with torch.inference_mode():
            for frame_index in range(frame_count):
                if not terminal:
                    for _ in range(simulation_steps_per_frame):
                        position = env.drone.get_pos()
                        quaternion = env.drone.get_quat()
                        velocity = env.drone.get_vel()
                        angular_velocity = env.drone.get_ang()
                        clamped_gate_index = env.gate_index.clamp_max(
                            env.gates.shape[1] - 1
                        )
                        env_index = torch.arange(NUM_ENVS, device=env.device)
                        gate_center = env.gates[env_index, clamped_gate_index]
                        gate_yaw = env.gate_yaws[env_index, clamped_gate_index]
                        target = gate_lookthrough_target(
                            gate_center,
                            gate_yaw,
                            GATE_LOOKTHROUGH_METERS,
                        )
                        action = controller(
                            position,
                            quaternion,
                            velocity,
                            angular_velocity,
                            target,
                        )
                        result = env.step(action)
                        simulation_step += 1
                        if bool(result.done[0].item()):
                            terminal = True
                            break

                rendered = camera.render(rgb=True)
                if not isinstance(rendered, (tuple, list)) or not rendered:
                    raise RuntimeError("Genesis camera.render(rgb=True) returned no RGB frame")
                rgb = require_rgb_frame(
                    rendered[0],
                    width=width,
                    height=height,
                    np=np,
                )
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                cv2.rectangle(bgr, (0, 0), (width, 76), (0, 0, 0), thickness=-1)
                cv2.putText(
                    bgr,
                    DISCLAIMER,
                    (18, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.68,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    bgr,
                    (
                        f"step={simulation_step} | "
                        f"simulation_steps_per_frame={simulation_steps_per_frame} | "
                        f"seed={RENDER_SEED}"
                    ),
                    (18, 61),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.64,
                    (180, 220, 255),
                    2,
                    cv2.LINE_AA,
                )
                writer.write(bgr)
                written_frames += 1
    finally:
        writer.release()

    if written_frames != frame_count:
        raise RuntimeError(
            f"writer frame-count mismatch: expected {frame_count}, wrote {written_frames}"
        )
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("video output is missing or empty after writer release")

    capture = cv2.VideoCapture(str(output))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"OpenCV could not reopen rendered video: {output}")
    try:
        reported_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        actual_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        actual_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        actual_fps = float(capture.get(cv2.CAP_PROP_FPS))
        actual_codec = fourcc_text(capture.get(cv2.CAP_PROP_FOURCC))
        if actual_codec != REQUESTED_CODEC:
            raise RuntimeError(
                "encoded codec mismatch: "
                f"requested={REQUESTED_CODEC}, actual={actual_codec}"
            )

        check_indices = {0, frame_count // 2, frame_count - 1}
        frame_checks: dict[str, dict[str, float]] = {}
        decoded_count = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape != (height, width, 3) or frame.dtype != np.uint8:
                raise RuntimeError(
                    f"decoded frame {decoded_count} has shape={frame.shape}, dtype={frame.dtype}"
                )
            if not np.isfinite(frame).all():
                raise RuntimeError(f"decoded frame {decoded_count} contains non-finite values")
            if decoded_count in check_indices:
                stats = frame_quality(frame, np=np)
                require_visible_frame(stats, decoded_count)
                frame_checks[str(decoded_count)] = stats
            decoded_count += 1
    finally:
        capture.release()

    if reported_count != frame_count or decoded_count != frame_count:
        raise RuntimeError(
            "encoded frame-count mismatch: "
            f"expected={frame_count}, reported={reported_count}, decoded={decoded_count}"
        )
    if (actual_width, actual_height) != (width, height):
        raise RuntimeError(
            f"encoded resolution mismatch: expected={(width, height)}, "
            f"actual={(actual_width, actual_height)}"
        )
    if not math.isfinite(actual_fps) or not math.isclose(
        actual_fps,
        float(args.fps),
        rel_tol=0.0,
        abs_tol=0.05,
    ):
        raise RuntimeError(f"encoded FPS mismatch: expected={args.fps}, actual={actual_fps}")
    if set(frame_checks) != {str(index) for index in check_indices}:
        raise RuntimeError(f"missing encoded frame checks: {frame_checks}")

    return {
        "status": "VISUAL_ONLY",
        "metric_eligible": False,
        "disclaimer": DISCLAIMER,
        "output": str(output),
        "output_size_bytes": output.stat().st_size,
        "actual_frame_count": decoded_count,
        "actual_resolution": [actual_width, actual_height],
        "actual_fps": actual_fps,
        "requested_codec": REQUESTED_CODEC,
        "actual_codec": actual_codec,
        "seed": RENDER_SEED,
        "num_envs": NUM_ENVS,
        "simulation_steps": simulation_step,
        "simulation_steps_per_frame": simulation_steps_per_frame,
        "terminal_reached": terminal,
        "controller_profile": "nominal",
        "controller_state_source": (
            "FlightGuardGenesisEnv simulator truth: "
            "position/quaternion/velocity/angular_velocity"
        ),
        "genesis_version": GENESIS_VERSION,
        "genesis_source": str(GENESIS_SOURCE_ROOT),
        "opencv_version": cv2.__version__,
        "frame_checks": frame_checks,
    }


def main() -> None:
    result = render(parse_args())
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
