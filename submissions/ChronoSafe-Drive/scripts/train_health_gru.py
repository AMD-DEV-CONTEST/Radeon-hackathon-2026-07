"""Train and calibrate the ChronoSafe health GRU on AMD ROCm."""

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

from chronosafe.models import HealthGRU


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/chronosafe_dataset.npz"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/health_gru"))
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--sequence-length", type=int, default=8)
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--calibration-seed-count", type=int, default=1)
    parser.add_argument("--test-seed-count", type=int, default=1)
    return parser.parse_args()


def make_sequences(
    features: np.ndarray,
    labels: np.ndarray,
    risks: np.ndarray,
    seeds: np.ndarray,
    selected_seeds: list[int],
    length: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs: list[np.ndarray] = []
    ys: list[int] = []
    rs: list[float] = []
    for seed in selected_seeds:
        indices = np.flatnonzero(seeds == seed)
        for end in range(length - 1, len(indices)):
            window = indices[end - length + 1 : end + 1]
            xs.append(features[window])
            ys.append(int(labels[indices[end]]))
            rs.append(float(risks[indices[end]]))
    return (
        np.asarray(xs, dtype=np.float32),
        np.asarray(ys, dtype=np.int64),
        np.asarray(rs, dtype=np.float32),
    )


def loader(x: np.ndarray, y: np.ndarray, r: np.ndarray, batch: int, shuffle: bool) -> DataLoader:
    dataset = TensorDataset(torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(r))
    return DataLoader(dataset, batch_size=batch, shuffle=shuffle)


@torch.inference_mode()
def predict(model: nn.Module, data: DataLoader, device: torch.device) -> tuple[np.ndarray, ...]:
    labels: list[np.ndarray] = []
    predictions: list[np.ndarray] = []
    risks: list[np.ndarray] = []
    predicted_risks: list[np.ndarray] = []
    model.eval()
    for x, y, risk in data:
        logits, risk_hat = model(x.to(device))
        labels.append(y.numpy())
        predictions.append(logits.argmax(dim=1).cpu().numpy())
        risks.append(risk.numpy())
        predicted_risks.append(risk_hat.cpu().numpy())
    return tuple(np.concatenate(items) for items in (labels, predictions, risks, predicted_risks))


def confusion_matrix(labels: np.ndarray, predictions: np.ndarray, classes: int) -> np.ndarray:
    matrix = np.zeros((classes, classes), dtype=np.int64)
    for truth, predicted in zip(labels, predictions, strict=True):
        matrix[truth, predicted] += 1
    return matrix


def macro_f1(matrix: np.ndarray) -> float:
    scores = []
    for index in range(len(matrix)):
        tp = matrix[index, index]
        fp = matrix[:, index].sum() - tp
        fn = matrix[index, :].sum() - tp
        denominator = 2 * tp + fp + fn
        scores.append(0.0 if denominator == 0 else 2 * tp / denominator)
    return float(np.mean(scores))


def conformal_quantile(residuals: np.ndarray, alpha: float) -> float:
    level = min(1.0, math.ceil((len(residuals) + 1) * (1 - alpha)) / len(residuals))
    return float(np.quantile(residuals, level, method="higher"))


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("ROCm GPU is required for this training run")

    device = torch.device("cuda")
    payload = np.load(args.data)
    features = payload["features"]
    labels = payload["labels"]
    risks = payload["risks"]
    seeds = payload["seeds"]
    class_names = payload["class_names"].tolist()
    unique_seeds = np.unique(seeds).tolist()
    held_out = args.calibration_seed_count + args.test_seed_count
    if args.calibration_seed_count < 1 or args.test_seed_count < 1:
        raise ValueError("Calibration and test seed counts must both be positive")
    if len(unique_seeds) <= held_out:
        raise ValueError("Dataset does not contain enough seeds for the requested split")

    train_seeds = unique_seeds[:-held_out]
    calibration_seeds = unique_seeds[-held_out : -args.test_seed_count]
    test_seeds = unique_seeds[-args.test_seed_count :]
    train_x, train_y, train_r = make_sequences(
        features, labels, risks, seeds, train_seeds, args.sequence_length
    )
    calibration_x, calibration_y, calibration_r = make_sequences(
        features, labels, risks, seeds, calibration_seeds, args.sequence_length
    )
    test_x, test_y, test_r = make_sequences(
        features, labels, risks, seeds, test_seeds, args.sequence_length
    )

    mean = train_x.reshape(-1, train_x.shape[-1]).mean(axis=0)
    std = train_x.reshape(-1, train_x.shape[-1]).std(axis=0).clip(min=1e-6)
    train_x = (train_x - mean) / std
    calibration_x = (calibration_x - mean) / std
    test_x = (test_x - mean) / std

    train_loader = loader(train_x, train_y, train_r, args.batch_size, True)
    calibration_loader = loader(calibration_x, calibration_y, calibration_r, args.batch_size, False)
    test_loader = loader(test_x, test_y, test_r, args.batch_size, False)

    model = HealthGRU(features.shape[1], args.hidden_size, len(class_names)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    classification_loss = nn.CrossEntropyLoss()
    risk_loss = nn.MSELoss()

    print(f"device: {device}")
    print(f"gpu: {torch.cuda.get_device_name(0)}")
    print(f"hip: {torch.version.hip}")
    print(f"train/calibration/test seeds: {train_seeds}/{calibration_seeds}/{test_seeds}")
    started = time.perf_counter()

    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for x, y, risk in train_loader:
            x, y, risk = x.to(device), y.to(device), risk.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits, risk_hat = model(x)
            loss = classification_loss(logits, y) + 0.5 * risk_loss(risk_hat, risk)
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(x)
        if epoch == 1 or epoch % 5 == 0 or epoch == args.epochs:
            print(f"epoch={epoch:03d} loss={total / len(train_loader.dataset):.6f}")

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    cal_y, cal_pred, cal_risk, cal_risk_hat = predict(model, calibration_loader, device)
    test_y, test_pred, test_risk, test_risk_hat = predict(model, test_loader, device)
    residuals = np.abs(cal_risk - cal_risk_hat)
    radius = conformal_quantile(residuals, args.alpha)
    coverage = float(np.mean(np.abs(test_risk - test_risk_hat) <= radius))
    matrix = confusion_matrix(test_y, test_pred, len(class_names))

    metrics = {
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "epochs": args.epochs,
        "training_seconds": round(elapsed, 4),
        "test_accuracy": round(float(np.mean(test_y == test_pred)), 6),
        "test_macro_f1": round(macro_f1(matrix), 6),
        "test_risk_mae": round(float(np.mean(np.abs(test_risk - test_risk_hat))), 6),
        "conformal_alpha": args.alpha,
        "conformal_radius": round(radius, 6),
        "test_risk_coverage": round(coverage, 6),
        "train_seeds": train_seeds,
        "calibration_seeds": calibration_seeds,
        "test_seeds": test_seeds,
        "class_names": class_names,
        "confusion_matrix": matrix.tolist(),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state": model.state_dict(),
            "input_size": features.shape[1],
            "hidden_size": args.hidden_size,
            "class_names": class_names,
            "feature_mean": mean,
            "feature_std": std,
            "sequence_length": args.sequence_length,
            "conformal_radius": radius,
        },
        args.output / "model.pt",
    )
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"artifact: {args.output / 'model.pt'}")
    print("ROCm GRU training: PASS")


if __name__ == "__main__":
    main()
