"""Evaluate compositional diagnosis and minimal-risk control on an unseen seed."""

from __future__ import annotations

import argparse
import csv
import json
from collections import deque
from pathlib import Path

import numpy as np
import torch
from metadrive import MetaDriveEnv
from metadrive.component.sensors.rgb_camera import RGBCamera
from metadrive.third_party.simplepbr import Pipeline

from chronosafe.control import DrivingMode, RiskStateMachine
from chronosafe.faults import FaultInjector
from chronosafe.features import (
    HealthFeatureExtractor,
    TimingAwareHealthFeatureExtractor,
    fault_risk_target,
)
from chronosafe.models.compositional_gru import CompositionalHealthGRU, compose_scenario


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path("artifacts/compositional_gru/model.pt"))
    parser.add_argument("--output", type=Path, default=Path("results/compositional_closed_loop"))
    parser.add_argument("--steps", type=int, default=210)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--degraded-threshold", type=float, default=0.45)
    parser.add_argument("--minimal-risk-threshold", type=float, default=0.62)
    parser.add_argument("--warmup-steps", type=int, default=8)
    parser.add_argument(
        "--raw-headless-fallback",
        action="store_true",
        help=(
            "Disable unsupported MetaDrive 0.4.3 tonemapping passes. This keeps "
            "raw camera buffers available but changes their feature distribution; "
            "use Xvfb without this fallback for formal evaluation."
        ),
    )
    return parser.parse_args()


def configure_headless_offscreen_rendering() -> None:
    """Disable unsupported tonemapping passes on headless MetaDrive 0.4.3.

    MetaDrive's offscreen RGB path constructs SimplePBR and camera tonemapping
    quads even when Panda3D did not create those quads.  The raw camera buffer
    remains available without these post-processing passes, which is all this
    sensor-health protocol requires.  The patch is process-local and does not
    modify the installed MetaDrive package.
    """

    Pipeline._setup_tonemapping = lambda self: None  # type: ignore[method-assign]
    RGBCamera._setup_effect = lambda self: None  # type: ignore[method-assign]


def create_env(seed: int, raw_headless_fallback: bool = False) -> MetaDriveEnv:
    if raw_headless_fallback:
        configure_headless_offscreen_rendering()
    return MetaDriveEnv(
        {
            "use_render": False,
            # The cloud instances are headless. Disable MetaDrive's SimplePBR
            # pipeline, which requires a display-backed shader context even
            # when use_render=False; classic Panda3D rendering still provides
            # the RGB camera observation needed by the closed-loop protocol.
            "render_pipeline": False,
            "image_observation": True,
            "stack_size": 1,
            "sensors": {"rgb_camera": (RGBCamera, 84, 84)},
            "vehicle_config": {"image_source": "rgb_camera"},
            "num_scenarios": 1,
            "start_seed": seed,
            "map": "S",
            "traffic_density": 0.15,
            "horizon": 1000,
        }
    )


def read_lidar(env: MetaDriveEnv) -> np.ndarray:
    points, _ = env.agent.lidar.perceive(
        base_vehicle=env.agent,
        physics_world=env.engine.physics_world.dynamic_world,
        num_lasers=64,
        distance=50,
    )
    return np.asarray(points, dtype=np.float32)


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("ROCm GPU is required")
    device = torch.device("cuda")
    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    model = CompositionalHealthGRU(checkpoint["input_size"], checkpoint["hidden_size"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    mean = torch.as_tensor(checkpoint["feature_mean"], dtype=torch.float32, device=device)
    std = torch.as_tensor(checkpoint["feature_std"], dtype=torch.float32, device=device)
    sequence_length = int(checkpoint["sequence_length"])
    radius = float(checkpoint["conformal_radius"])

    degraded_threshold = args.degraded_threshold
    minimal_risk_threshold = args.minimal_risk_threshold
    state_machine = RiskStateMachine(
        degraded_threshold=degraded_threshold,
        minimal_risk_threshold=minimal_risk_threshold,
        recovery_frames=15,
    )
    env = create_env(args.seed, args.raw_headless_fallback)
    injector = FaultInjector(args.steps, seed=args.seed)
    extractor = (
        TimingAwareHealthFeatureExtractor()
        if int(checkpoint["input_size"]) > 10
        else HealthFeatureExtractor()
    )
    history: deque[np.ndarray] = deque(maxlen=sequence_length)
    rows: list[dict[str, object]] = []
    previous_mode = DrivingMode.NORMAL

    print(f"device: {device}")
    print(f"gpu: {torch.cuda.get_device_name(0)}")
    print(f"hip: {torch.version.hip}")
    print(f"robust conformal radius: {radius:.6f}")
    print(f"thresholds: degraded={degraded_threshold:.3f}, minimal_risk={minimal_risk_threshold:.3f}")

    try:
        obs, _ = env.reset()
        for step in range(args.steps):
            rgb = np.asarray(obs["image"], dtype=np.float32)[..., 0]
            lidar = read_lidar(env)
            faulty_rgb, faulty_lidar, fault = injector.apply(step, rgb, lidar)
            if isinstance(extractor, TimingAwareHealthFeatureExtractor):
                feature = extractor.extract(
                    faulty_rgb,
                    faulty_lidar,
                    env.agent.speed_km_h,
                    camera_age_frames=fault.delay_frames,
                    lidar_age_frames=fault.delay_frames,
                )
            else:
                feature = extractor.extract(faulty_rgb, faulty_lidar, env.agent.speed_km_h)
            history.append(feature)
            while len(history) < sequence_length:
                history.appendleft(feature.copy())
            sequence = torch.as_tensor(np.stack(history), dtype=torch.float32, device=device)
            sequence = ((sequence - mean) / std).unsqueeze(0)
            with torch.inference_mode():
                camera_logits, lidar_logits, delay_logits, risk_prediction = model(sequence)
            camera = int(camera_logits.argmax(1).item())
            lidar_factor = int(lidar_logits.argmax(1).item())
            delay = int(delay_logits.argmax(1).item())
            predicted_scenario = compose_scenario(camera, lidar_factor, delay)
            risk_hat = float(risk_prediction.item())
            risk_upper = min(1.0, risk_hat + radius)
            mode = (
                DrivingMode.NORMAL
                if step < args.warmup_steps
                else state_machine.update(risk_upper)
            )
            throttle = state_machine.longitudinal_action(mode, env.agent.speed_km_h)
            true_risk = fault_risk_target(
                fault.blur_sigma, fault.camera_frozen, fault.lidar_dropout, fault.delay_frames
            )
            if mode != previous_mode:
                print(
                    f"step={step:04d} transition={previous_mode.name}->{mode.name} "
                    f"risk_upper={risk_upper:.3f}"
                )
                previous_mode = mode
            rows.append(
                {
                    "step": step,
                    "scenario": fault.name,
                    "predicted_scenario": predicted_scenario,
                    "camera_factor": camera,
                    "lidar_factor": lidar_factor,
                    "delay_factor": delay,
                    "true_risk": round(true_risk, 6),
                    "predicted_risk": round(risk_hat, 6),
                    "risk_upper": round(risk_upper, 6),
                    "mode": mode.name,
                    "speed_km_h": round(float(env.agent.speed_km_h), 6),
                }
            )
            action = np.asarray(
                [0.0, state_machine.longitudinal_action(mode, env.agent.speed_km_h)], dtype=np.float32
            )
            obs, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                obs, _ = env.reset()
                extractor.reset()
                history.clear()
    finally:
        env.close()

    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "closed_loop.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    accuracy = float(np.mean([row["scenario"] == row["predicted_scenario"] for row in rows]))
    risk_mae = float(
        np.mean([abs(float(row["true_risk"]) - float(row["predicted_risk"])) for row in rows])
    )
    coverage = float(
        np.mean([float(row["true_risk"]) <= float(row["risk_upper"]) for row in rows])
    )
    mode_counts = {mode.name: sum(row["mode"] == mode.name for row in rows) for mode in DrivingMode}
    summary = {
        "steps": len(rows),
        "seed": args.seed,
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "scenario_accuracy": round(accuracy, 6),
        "risk_mae": round(risk_mae, 6),
        "upper_risk_coverage": round(coverage, 6),
        "mode_counts": mode_counts,
        "minimal_risk_reached": mode_counts["MINIMAL_RISK"] > 0,
        "final_speed_km_h": rows[-1]["speed_km_h"],
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"log: {csv_path}")
    print("ChronoSafe compositional closed-loop: PASS")


if __name__ == "__main__":
    main()
