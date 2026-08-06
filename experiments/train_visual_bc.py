"""Train an RGB + proprioception behavior-cloning student from HDF5 demos."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
import yaml

from algorithms.vision_actor_critic import VisualActorCritic
from data import build_dataloader


def _action_delta_statistics(loader, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute per-DOF teacher-delta statistics without retaining RGB batches."""
    total = None
    total_sq = None
    count = 0
    for batch in loader:
        delta = batch["action"].to(device) - batch["proprio"].to(device)[:, :9]
        batch_sum = delta.sum(dim=0)
        batch_sq_sum = delta.square().sum(dim=0)
        total = batch_sum if total is None else total + batch_sum
        total_sq = batch_sq_sum if total_sq is None else total_sq + batch_sq_sum
        count += delta.shape[0]
    mean = total / count
    # Avoid exploding normalized targets for nearly constant DOFs.
    std = (total_sq / count - mean.square()).clamp_min(1e-8).sqrt().clamp_min(1e-3)
    return mean, std


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train_visual_bc_smoke.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    device = torch.device(config["device"])
    loader = build_dataloader(
        config["dataset_dir"], batch_size=int(config["batch_size"]),
        shuffle=True, num_workers=int(config.get("num_workers", 0)),
        modalities=("state", "proprio", "rgb"),
    )
    first = next(iter(loader))
    height, width = first["rgb"].shape[1:3]
    model = VisualActorCritic(
        image_height=height, image_width=width,
        proprio_dim=first["proprio"].shape[-1], action_dim=first["action"].shape[-1],
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    action_mean, action_std = _action_delta_statistics(loader, device)
    gripper_weight = float(config.get("gripper_loss_weight", 4.0))
    loss_weights = torch.ones_like(action_mean)
    loss_weights[-2:] = gripper_weight
    print(
        "teacher_delta_mean_abs="
        f"{action_mean.abs().mean().item():.5f} "
        "teacher_delta_std_mean="
        f"{action_std.mean().item():.5f}"
    )
    for epoch in range(int(config["epochs"])):
        total_loss = 0.0
        total_prediction_abs = 0.0
        for batch in loader:
            prediction = model.mean_action(batch["rgb"].to(device), batch["proprio"].to(device))
            # Regress the teacher's local qpos correction, rather than an
            # absolute arm pose.  This is bounded, safer, and substantially
            # easier to imitate from a modest RGB demonstration set.
            target_delta = batch["action"].to(device) - batch["proprio"].to(device)[:, :9]
            normalized_target = (target_delta - action_mean) / action_std
            per_dof_loss = (prediction - normalized_target).square().mean(dim=0)
            loss = (per_dof_loss * loss_weights).sum() / loss_weights.sum()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach()) * len(batch["action"])
            denormalized_prediction = prediction.detach() * action_std + action_mean
            total_prediction_abs += float(denormalized_prediction.abs().mean()) * len(batch["action"])
        print(
            f"epoch={epoch + 1} normalized_action_mse={total_loss / len(loader.dataset):.6f} "
            f"predicted_delta_mean_abs={total_prediction_abs / len(loader.dataset):.5f}"
        )
    output = Path(config["checkpoint"])
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": model.state_dict(), "image_height": height, "image_width": width,
        "proprio_dim": first["proprio"].shape[-1], "action_dim": first["action"].shape[-1],
        "action_representation": "normalized_delta_qpos",
        "action_delta_mean": action_mean.detach().cpu(),
        "action_delta_std": action_std.detach().cpu(),
    }, output)
    print(f"Visual BC checkpoint: {output}")


if __name__ == "__main__":
    main()
