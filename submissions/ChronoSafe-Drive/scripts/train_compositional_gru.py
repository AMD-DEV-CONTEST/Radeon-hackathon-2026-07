"""Train compositional degradation diagnosis with robust multi-domain calibration."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from chronosafe.models.compositional_gru import (
    CAMERA_CLASSES,
    DELAY_CLASSES,
    LIDAR_CLASSES,
    CompositionalHealthGRU,
    compose_scenario,
    factor_targets,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/chronosafe_dataset_v2.npz"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/compositional_gru"))
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--sequence-length", type=int, default=8)
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--calibration-seed-count", type=int, default=2)
    parser.add_argument("--test-seed-count", type=int, default=2)
    return parser.parse_args()


def make_sequences(
    features: np.ndarray,
    labels: np.ndarray,
    risks: np.ndarray,
    seeds: np.ndarray,
    selected: list[int],
    length: int,
) -> tuple[np.ndarray, ...]:
    xs, ys, rs, ss = [], [], [], []
    for seed in selected:
        indices = np.flatnonzero(seeds == seed)
        for end in range(length - 1, len(indices)):
            window = indices[end - length + 1 : end + 1]
            xs.append(features[window])
            ys.append(int(labels[indices[end]]))
            rs.append(float(risks[indices[end]]))
            ss.append(seed)
    return (
        np.asarray(xs, dtype=np.float32),
        np.asarray(ys, dtype=np.int64),
        np.asarray(rs, dtype=np.float32),
        np.asarray(ss, dtype=np.int64),
    )


def make_loader(x: np.ndarray, y: np.ndarray, r: np.ndarray, batch: int, shuffle: bool) -> DataLoader:
    camera, lidar, delay = factor_targets(y)
    dataset = TensorDataset(
        torch.from_numpy(x),
        torch.from_numpy(y),
        torch.from_numpy(camera),
        torch.from_numpy(lidar),
        torch.from_numpy(delay),
        torch.from_numpy(r),
    )
    return DataLoader(dataset, batch_size=batch, shuffle=shuffle)


def balanced_weights(targets: np.ndarray, classes: int, device: torch.device) -> torch.Tensor:
    counts = np.bincount(targets, minlength=classes).clip(min=1)
    weights = len(targets) / (classes * counts)
    return torch.as_tensor(weights, dtype=torch.float32, device=device)


@torch.inference_mode()
def predict(model: nn.Module, data: DataLoader, device: torch.device) -> dict[str, np.ndarray]:
    output: dict[str, list[np.ndarray]] = {
        key: [] for key in ("scenario", "camera", "lidar", "delay", "risk", "camera_hat", "lidar_hat", "delay_hat", "risk_hat")
    }
    model.eval()
    for x, scenario, camera, lidar, delay, risk in data:
        camera_logits, lidar_logits, delay_logits, risk_hat = model(x.to(device))
        values = {
            "scenario": scenario.numpy(),
            "camera": camera.numpy(),
            "lidar": lidar.numpy(),
            "delay": delay.numpy(),
            "risk": risk.numpy(),
            "camera_hat": camera_logits.argmax(1).cpu().numpy(),
            "lidar_hat": lidar_logits.argmax(1).cpu().numpy(),
            "delay_hat": delay_logits.argmax(1).cpu().numpy(),
            "risk_hat": risk_hat.cpu().numpy(),
        }
        for key, value in values.items():
            output[key].append(value)
    return {key: np.concatenate(value) for key, value in output.items()}


def conformal_quantile(residuals: np.ndarray, alpha: float) -> float:
    level = min(1.0, math.ceil((len(residuals) + 1) * (1 - alpha)) / len(residuals))
    return float(np.quantile(residuals, level, method="higher"))


def composed_predictions(result: dict[str, np.ndarray]) -> np.ndarray:
    names = [
        compose_scenario(int(camera), int(lidar), int(delay))
        for camera, lidar, delay in zip(
            result["camera_hat"], result["lidar_hat"], result["delay_hat"], strict=True
        )
    ]
    order = [
        "clean",
        "progressive_blur",
        "camera_freeze",
        "lidar_dropout",
        "dynamic_delay",
        "freeze_plus_dropout",
        "blur_plus_delay",
    ]
    lookup = {name: index for index, name in enumerate(order)}
    return np.asarray([lookup[name] for name in names], dtype=np.int64)


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("ROCm GPU is required")
    device = torch.device("cuda")
    payload = np.load(args.data)
    features, labels, risks, seeds = (
        payload["features"], payload["labels"], payload["risks"], payload["seeds"]
    )
    unique_seeds = np.unique(seeds).tolist()
    held_out = args.calibration_seed_count + args.test_seed_count
    if len(unique_seeds) <= held_out:
        raise ValueError("Not enough seeds for train/calibration/test")
    train_seeds = unique_seeds[:-held_out]
    calibration_seeds = unique_seeds[-held_out : -args.test_seed_count]
    test_seeds = unique_seeds[-args.test_seed_count :]

    train_x, train_y, train_r, _ = make_sequences(
        features, labels, risks, seeds, train_seeds, args.sequence_length
    )
    calibration_x, calibration_y, calibration_r, calibration_domain = make_sequences(
        features, labels, risks, seeds, calibration_seeds, args.sequence_length
    )
    test_x, test_y, test_r, _ = make_sequences(
        features, labels, risks, seeds, test_seeds, args.sequence_length
    )
    mean = train_x.reshape(-1, train_x.shape[-1]).mean(0)
    std = train_x.reshape(-1, train_x.shape[-1]).std(0).clip(min=1e-6)
    train_x = (train_x - mean) / std
    calibration_x = (calibration_x - mean) / std
    test_x = (test_x - mean) / std

    train_loader = make_loader(train_x, train_y, train_r, args.batch_size, True)
    calibration_loader = make_loader(calibration_x, calibration_y, calibration_r, args.batch_size, False)
    test_loader = make_loader(test_x, test_y, test_r, args.batch_size, False)
    train_camera, train_lidar, train_delay = factor_targets(train_y)

    model = CompositionalHealthGRU(features.shape[1], args.hidden_size).to(device)
    camera_loss = nn.CrossEntropyLoss(weight=balanced_weights(train_camera, 3, device))
    lidar_loss = nn.CrossEntropyLoss(weight=balanced_weights(train_lidar, 2, device))
    delay_loss = nn.CrossEntropyLoss(weight=balanced_weights(train_delay, 2, device))
    risk_loss = nn.MSELoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)

    print(f"device: {device}")
    print(f"gpu: {torch.cuda.get_device_name(0)}")
    print(f"hip: {torch.version.hip}")
    print(f"train/calibration/test seeds: {train_seeds}/{calibration_seeds}/{test_seeds}")
    started = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for x, _, camera, lidar, delay, risk in train_loader:
            x, camera, lidar, delay, risk = (
                x.to(device), camera.to(device), lidar.to(device), delay.to(device), risk.to(device)
            )
            optimizer.zero_grad(set_to_none=True)
            camera_logits, lidar_logits, delay_logits, risk_hat = model(x)
            loss = (
                camera_loss(camera_logits, camera)
                + lidar_loss(lidar_logits, lidar)
                + delay_loss(delay_logits, delay)
                + 0.5 * risk_loss(risk_hat, risk)
            )
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(x)
        if epoch == 1 or epoch % 10 == 0 or epoch == args.epochs:
            print(f"epoch={epoch:03d} loss={total / len(train_loader.dataset):.6f}")

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    calibration = predict(model, calibration_loader, device)
    test = predict(model, test_loader, device)
    domain_radii = {}
    for seed in calibration_seeds:
        mask = calibration_domain == seed
        domain_radii[str(seed)] = conformal_quantile(
            np.abs(calibration["risk"][mask] - calibration["risk_hat"][mask]), args.alpha
        )
    radius = max(domain_radii.values())
    scenario_hat = composed_predictions(test)
    coverage = float(np.mean(test["risk"] <= test["risk_hat"] + radius))

    metrics = {
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "training_seconds": round(elapsed, 4),
        "scenario_accuracy": round(float(np.mean(test["scenario"] == scenario_hat)), 6),
        "camera_accuracy": round(float(np.mean(test["camera"] == test["camera_hat"])), 6),
        "lidar_accuracy": round(float(np.mean(test["lidar"] == test["lidar_hat"])), 6),
        "delay_accuracy": round(float(np.mean(test["delay"] == test["delay_hat"])), 6),
        "risk_mae": round(float(np.mean(np.abs(test["risk"] - test["risk_hat"]))), 6),
        "robust_conformal_radius": round(radius, 6),
        "domain_radii": {key: round(value, 6) for key, value in domain_radii.items()},
        "upper_risk_coverage": round(coverage, 6),
        "train_seeds": train_seeds,
        "calibration_seeds": calibration_seeds,
        "test_seeds": test_seeds,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_type": "compositional_health_gru",
            "model_state": model.state_dict(),
            "input_size": features.shape[1],
            "hidden_size": args.hidden_size,
            "feature_mean": mean,
            "feature_std": std,
            "sequence_length": args.sequence_length,
            "conformal_radius": radius,
            "camera_classes": CAMERA_CLASSES,
            "lidar_classes": LIDAR_CLASSES,
            "delay_classes": DELAY_CLASSES,
        },
        args.output / "model.pt",
    )
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"artifact: {args.output / 'model.pt'}")
    print("ROCm compositional GRU training: PASS")


if __name__ == "__main__":
    main()
