"""Train an RGB + proprioception estimator for object and goal positions."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
import yaml
from torch.utils.data import DataLoader, Subset

from algorithms.vision_state_estimator import VisualTaskStateEstimator
from data import RobotInteractionDataset


def _task_positions(state: torch.Tensor) -> torch.Tensor:
    """Extract object xyz and target xyz from the documented 39-D state layout."""
    if state.shape[-1] != 39:
        raise ValueError(f"expected 39-D privileged state, got {state.shape[-1]} dimensions")
    return torch.cat((state[:, 25:28], state[:, 32:35]), dim=-1)


def _statistics(loader, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    total = total_sq = None
    count = 0
    for batch in loader:
        positions = _task_positions(batch["state"].to(device))
        part_sum, part_sq_sum = positions.sum(0), positions.square().sum(0)
        total = part_sum if total is None else total + part_sum
        total_sq = part_sq_sum if total_sq is None else total_sq + part_sq_sum
        count += positions.shape[0]
    mean = total / count
    std = (total_sq / count - mean.square()).clamp_min(1e-8).sqrt().clamp_min(1e-3)
    return mean, std


def _select_pick_region(dataset: RobotInteractionDataset, config: dict) -> list[int]:
    """Keep pre-grasp table observations rather than learning held-object poses.

    The visual-IK controller only needs an object estimate before the contact
    latch engages. Filtering out lifted and placed-object images prevents the
    regressor from averaging incompatible object heights and task phases.
    """
    x_min = float(config["object_x_min"])
    table_z_max = float(config["object_table_z_max"])
    selected: list[int] = []
    for index in range(len(dataset)):
        object_position = dataset[index]["state"][25:28]
        if float(object_position[0]) >= x_min and float(object_position[2]) <= table_z_max:
            selected.append(index)
    if not selected:
        raise ValueError("object_position_filter removed every transition")
    return selected


def _checkpoint_payload(
    model: VisualTaskStateEstimator, *, height: int, width: int, proprio_dim: int,
    mean: torch.Tensor, std: torch.Tensor,
) -> dict[str, object]:
    return {
        "state_dict": model.state_dict(), "image_height": height, "image_width": width,
        "proprio_dim": proprio_dim, "position_mean": mean.cpu(), "position_std": std.cpu(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train_visual_ik.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    device = torch.device(config["device"])
    source_dataset = RobotInteractionDataset(
        config["dataset_dir"], modalities=("state", "proprio", "rgb"),
    )
    train_dataset = source_dataset
    if "object_position_filter" in config:
        selected = _select_pick_region(source_dataset, config["object_position_filter"])
        # Selection reads HDF5 in the parent process. Close that handle before
        # worker processes are created so each worker opens its own handle.
        source_dataset.close()
        train_dataset = Subset(source_dataset, selected)
        print(f"pick_region_transitions={len(selected)} total_transitions={len(source_dataset)}")
    loader = DataLoader(
        train_dataset, batch_size=int(config["batch_size"]), shuffle=True,
        num_workers=int(config.get("num_workers", 0)),
        pin_memory=bool(config.get("pin_memory", False)),
        persistent_workers=int(config.get("num_workers", 0)) > 0,
    )
    first = next(iter(loader))
    height, width = first["rgb"].shape[1:3]
    model = VisualTaskStateEstimator(
        image_height=height, image_width=width, proprio_dim=first["proprio"].shape[-1],
    ).to(device)
    mean, std = _statistics(loader, device)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    output = Path(config["checkpoint"])
    output.parent.mkdir(parents=True, exist_ok=True)
    latest_output = output.with_name(f"{output.stem}_latest{output.suffix}")
    best_output = output.with_name(f"{output.stem}_best{output.suffix}")
    checkpoint_every = int(config.get("checkpoint_every_epochs", 10))
    best_loss = float("inf")
    for epoch in range(int(config["epochs"])):
        total_loss = 0.0
        for batch in loader:
            labels = _task_positions(batch["state"].to(device))
            prediction = model(batch["rgb"].to(device), batch["proprio"].to(device))
            loss = torch.nn.functional.mse_loss(prediction, (labels - mean) / std)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach()) * labels.shape[0]
        epoch_loss = total_loss / len(loader.dataset)
        print(f"epoch={epoch + 1} normalized_position_mse={epoch_loss:.6f}")
        payload = _checkpoint_payload(
            model, height=height, width=width, proprio_dim=first["proprio"].shape[-1], mean=mean, std=std,
        )
        if epoch_loss < best_loss:
            best_loss = epoch_loss
            torch.save(payload, best_output)
        if checkpoint_every and (epoch + 1) % checkpoint_every == 0:
            torch.save(payload, latest_output)
    torch.save(_checkpoint_payload(
        model, height=height, width=width, proprio_dim=first["proprio"].shape[-1], mean=mean, std=std,
    ), output)
    print(f"Visual IK estimator checkpoint: {output} (best: {best_output}, latest: {latest_output})")
    source_dataset.close()


if __name__ == "__main__":
    main()
