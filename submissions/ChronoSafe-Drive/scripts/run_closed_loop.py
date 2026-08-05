"""Run ROCm diagnosis, calibrated risk, and minimal-risk control in closed loop."""

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

from chronosafe.control import DrivingMode, RiskStateMachine
from chronosafe.faults import FaultInjector
from chronosafe.features import HealthFeatureExtractor, fault_risk_target
from chronosafe.models import HealthGRU


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path("artifacts/health_gru/model.pt"))
    parser.add_argument("--output", type=Path, default=Path("results/closed_loop"))
    parser.add_argument("--steps", type=int, default=210)
    parser.add_argument("--seed", type=int, default=31)
    return parser.parse_args()


def create_env(seed: int) -> MetaDriveEnv:
    return MetaDriveEnv(
        {
            "use_render": False,
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
        raise RuntimeError("ROCm GPU is required for closed-loop inference")
    device = torch.device("cuda")
    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    model = HealthGRU(
        checkpoint["input_size"], checkpoint["hidden_size"], len(checkpoint["class_names"])
    ).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    mean = torch.as_tensor(checkpoint["feature_mean"], dtype=torch.float32, device=device)
    std = torch.as_tensor(checkpoint["feature_std"], dtype=torch.float32, device=device)
    sequence_length = int(checkpoint["sequence_length"])
    radius = float(checkpoint["conformal_radius"])
    class_names = checkpoint["class_names"]

    env = create_env(args.seed)
    injector = FaultInjector(args.steps, seed=args.seed)
    extractor = HealthFeatureExtractor()
    state_machine = RiskStateMachine()
    history: deque[np.ndarray] = deque(maxlen=sequence_length)
    rows: list[dict[str, object]] = []
    previous_mode = DrivingMode.NORMAL

    print(f"device: {device}")
    print(f"gpu: {torch.cuda.get_device_name(0)}")
    print(f"hip: {torch.version.hip}")
    print(f"conformal radius: {radius:.6f}")

    try:
        obs, _ = env.reset()
        for step in range(args.steps):
            rgb = np.asarray(obs["image"], dtype=np.float32)[..., 0]
            lidar = read_lidar(env)
            faulty_rgb, faulty_lidar, fault = injector.apply(step, rgb, lidar)
            feature = extractor.extract(faulty_rgb, faulty_lidar, env.agent.speed_km_h)
            history.append(feature)
            while len(history) < sequence_length:
                history.appendleft(feature.copy())

            sequence = torch.as_tensor(np.stack(history), dtype=torch.float32, device=device)
            sequence = ((sequence - mean) / std).unsqueeze(0)
            with torch.inference_mode():
                logits, predicted_risk = model(sequence)
            predicted_class = int(logits.argmax(dim=1).item())
            risk_hat = float(predicted_risk.item())
            risk_upper = min(1.0, risk_hat + radius)
            mode = state_machine.update(risk_upper)
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
                    "predicted_class": class_names[predicted_class],
                    "true_risk": round(true_risk, 6),
                    "predicted_risk": round(risk_hat, 6),
                    "risk_upper": round(risk_upper, 6),
                    "mode": mode.name,
                    "speed_km_h": round(float(env.agent.speed_km_h), 6),
                    "longitudinal_action": throttle,
                }
            )
            action = np.asarray([0.0, throttle], dtype=np.float32)
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

    correct = np.asarray([row["scenario"] == row["predicted_class"] for row in rows])
    errors = np.asarray([abs(float(row["true_risk"]) - float(row["predicted_risk"])) for row in rows])
    covered = np.asarray([float(row["true_risk"]) <= float(row["risk_upper"]) for row in rows])
    mode_counts = {mode.name: sum(row["mode"] == mode.name for row in rows) for mode in DrivingMode}
    metrics = {
        "steps": len(rows),
        "seed": args.seed,
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "classification_accuracy": round(float(correct.mean()), 6),
        "risk_mae": round(float(errors.mean()), 6),
        "upper_risk_coverage": round(float(covered.mean()), 6),
        "mode_counts": mode_counts,
        "minimal_risk_reached": mode_counts[DrivingMode.MINIMAL_RISK.name] > 0,
        "final_speed_km_h": rows[-1]["speed_km_h"],
    }
    (args.output / "summary.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"log: {csv_path}")
    print("ChronoSafe closed-loop MRM: PASS")


if __name__ == "__main__":
    main()
