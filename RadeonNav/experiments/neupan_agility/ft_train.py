#!/usr/bin/env python3
"""M-FT-1 trainer: fine-tune the depth encoder against the source loss.

Preregistered in EXPERIMENT_PLAN.md M-FT-1. Only RecurrentDepthBackbone is
trained (fp32); the depth actor is frozen and used to route action-imitation
gradients into the encoder. Loss replicates tsc/rsl_rl/algorithms/ppo.py:327-337
(CE discrete + L2 continuous + weighted-L2 yaw on a GT/1.5 head target + CE
over the already-softmaxed class probs), without the BYOL learner. BPTT: 24
step chunks, hidden carried within an episode, detached per chunk, reset at
episode boundaries. Actor obs follow the deployment cell-D contract: injected
yaw/class in the aux slots, zero 570-D history, zero scan slots.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _sha256  # noqa: E402
from run_bbc_sanity import _device, _write_json  # noqa: E402
from run_source_task import (  # noqa: E402
    AGILITY_ROOT,
    HIGH_CHECKPOINT,
    POLICY_PROFILES,
)
from ft_collect import DATA_ROOT  # noqa: E402
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
)

CHUNK_STEPS = 24
YAW_WEIGHTS = (2.0, 0.5)
OUTPUT_ROOT = ROOT / "experiment-results/quadrupedal-agility/FT1-TRAIN"


def load_episodes(data_dirs: list[Path]) -> list[dict[str, np.ndarray]]:
    episodes = []
    npz_paths: list[Path] = []
    for data_dir in data_dirs:
        npz_paths.extend(sorted(data_dir.glob("*.npz")))
    for npz_path in npz_paths:
        data = dict(np.load(npz_path))
        done = data["done"].astype(bool)
        # Frames at or after the first termination never enter the loss.
        data["valid_steps"] = int(np.argmax(done)) if done.any() else len(done)
        data["tag"] = npz_path.stem
        episodes.append(data)
    if not episodes:
        raise FileNotFoundError(f"no episode .npz files under {data_dirs}")
    return episodes


def build_actor_obs(
    proprio57: torch.Tensor,
    injected_yaw: torch.Tensor,
    gt_class: torch.Tensor,
    explicit4: torch.Tensor,
) -> torch.Tensor:
    """Deployment cell-D actor observation: 65 aux-filled + 132 zeros + 4 + 570 zeros."""
    batch = proprio57.shape[0]
    one_hot = F.one_hot(gt_class, num_classes=6).to(proprio57.dtype)
    return torch.cat(
        (
            proprio57,
            injected_yaw,
            one_hot,
            torch.zeros(batch, 132, dtype=proprio57.dtype, device=proprio57.device),
            explicit4,
            torch.zeros(batch, 570, dtype=proprio57.dtype, device=proprio57.device),
        ),
        dim=1,
    )


def encoder_proprio(proprio57: torch.Tensor, abs_yaw: torch.Tensor) -> torch.Tensor:
    """Deployment encoder proprio: slot 57 = wrapped absolute yaw, slots 58-64 zero."""
    batch = proprio57.shape[0]
    aux = torch.zeros(batch, 8, dtype=proprio57.dtype, device=proprio57.device)
    aux[:, 0] = abs_yaw[:, 0]
    return torch.cat((proprio57, aux), dim=1)


def train(args: argparse.Namespace) -> dict:
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    np.random.seed(args.seed)
    device = _device(args.device)
    profile = POLICY_PROFILES["deployment3"]
    adapter = AgilityTscPolicyAdapter(
        AGILITY_ROOT,
        HIGH_CHECKPOINT,
        profile.low_checkpoint,
        device=device,
        low_contract=profile.low_contract,
        low_mode_count=profile.low_mode_count,
        command_profile="deployment",
        high_branch="student",
        use_half=False,
    )
    encoder = adapter.depth_encoder
    actor = adapter.high_model
    encoder.train()
    actor.eval()
    for parameter in actor.parameters():
        parameter.requires_grad_(False)

    episodes = load_episodes(args.data_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # All episodes span the same recorded length; per-episode validity masks
    # (t < first_done) gate the loss instead of any global truncation.
    recorded = min(len(episode["done"]) for episode in episodes)
    steps = (recorded // CHUNK_STEPS) * CHUNK_STEPS
    batch = len(episodes)
    valid_mask = torch.as_tensor(
        np.stack(
            [
                np.arange(steps) < episode["valid_steps"]
                for episode in episodes
            ]
        ),
        device=device,
        dtype=torch.float32,
    )
    total_valid = int(valid_mask.sum())

    def tensor(key: str, dtype: torch.dtype) -> torch.Tensor:
        stacked = np.stack([episode[key][:steps] for episode in episodes])
        return torch.as_tensor(stacked, device=device, dtype=dtype)

    depth = tensor("depth", torch.float32)  # (B, T, 58, 87)
    proprio = tensor("proprio57", torch.float32)
    abs_yaw = tensor("abs_yaw", torch.float32)
    explicit = tensor("explicit4", torch.float32)
    injected_yaw = tensor("injected_yaw", torch.float32)
    gt_yaw = tensor("gt_yaw", torch.float32)
    gt_class = tensor("gt_class", torch.long)
    teacher_idx = tensor("teacher_idx", torch.long)
    teacher_c = tensor("teacher_c18", torch.float32)
    yaw_weights = torch.tensor(YAW_WEIGHTS, device=device, dtype=torch.float32)

    # Near-miss weighting (M-FT-3): frames within +/-halo steps of a
    # forbidden contact get an upweighted loss. Episodes collected before
    # the forbidden flag existed contribute uniform weight 1.
    def frame_weights(episode) -> np.ndarray:
        weights = np.ones(steps, dtype=np.float32)
        flags = episode.get("forbidden")
        if flags is None or args.near_miss_weight <= 1.0:
            return weights
        flags = flags[:steps].astype(bool)
        if flags.any():
            halo = args.near_miss_halo
            kernel = np.ones(2 * halo + 1, dtype=np.float32)
            dilated = np.convolve(flags.astype(np.float32), kernel, "same") > 0
            weights[dilated] = args.near_miss_weight
        return weights

    loss_weights = valid_mask * torch.as_tensor(
        np.stack([frame_weights(episode) for episode in episodes]),
        device=device,
        dtype=torch.float32,
    )

    optimizer = torch.optim.Adam(encoder.parameters(), lr=args.learning_rate)
    total_updates = args.epochs * (steps // CHUNK_STEPS)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max(total_updates, 1), eta_min=1e-5
    )
    history: list[dict] = []
    started = time.monotonic()
    update = 0
    for epoch in range(args.epochs):
        encoder.delete_memory()
        for chunk_start in range(0, steps, CHUNK_STEPS):
            chunk_mask = loss_weights[:, chunk_start : chunk_start + CHUNK_STEPS]
            normalizer = chunk_mask.sum().clamp(min=1.0)
            losses = {"d": 0.0, "c": 0.0, "yaw": 0.0, "cls": 0.0}
            chunk_loss = torch.zeros((), device=device)
            for t in range(chunk_start, chunk_start + CHUNK_STEPS):
                mask_t = loss_weights[:, t]
                latent = encoder(
                    depth[:, t], encoder_proprio(proprio[:, t], abs_yaw[:, t])
                )
                obs = build_actor_obs(
                    proprio[:, t], injected_yaw[:, t], gt_class[:, t], explicit[:, t]
                )
                embedding = actor(
                    obs, hist_encoding=True, scandots_latent=latent[:, :32]
                )
                logits_d = actor.actor_d(embedding)
                mean_c = actor.actor_c(embedding)
                loss_d = (
                    F.cross_entropy(logits_d, teacher_idx[:, t], reduction="none")
                    * mask_t
                ).sum()
                loss_c = (
                    (teacher_c[:, t] - mean_c).norm(p=2, dim=1) * mask_t
                ).sum()
                loss_yaw = (
                    ((gt_yaw[:, t] - 1.5 * latent[:, 32:34]) * yaw_weights).norm(
                        p=2, dim=1
                    )
                    * mask_t
                ).sum()
                # Source quirk kept: CE applied to already-softmaxed probs.
                loss_cls = (
                    F.cross_entropy(latent[:, 34:40], gt_class[:, t], reduction="none")
                    * mask_t
                ).sum()
                chunk_loss = chunk_loss + loss_d + loss_c + loss_yaw + loss_cls
                losses["d"] += float(loss_d)
                losses["c"] += float(loss_c)
                losses["yaw"] += float(loss_yaw)
                losses["cls"] += float(loss_cls)
            if float(normalizer) >= 1.0 and float(chunk_mask.sum()) > 0.0:
                optimizer.zero_grad()
                (chunk_loss / normalizer).backward()
                torch.nn.utils.clip_grad_norm_(encoder.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
            update += 1
            encoder.detach_hidden_states()
            history.append(
                {
                    "epoch": epoch,
                    "update": update,
                    "lr": scheduler.get_last_lr()[0],
                    "valid_frames": float(chunk_mask.sum()),
                    **{
                        key: value / max(float(chunk_mask.sum()), 1.0)
                        for key, value in losses.items()
                    },
                }
            )
        if args.save_every_epoch:
            torch.save(
                encoder.state_dict(),
                args.output_dir / f"ft1_depth_encoder_epoch{epoch + 1}.pt",
            )
    encoder.eval()
    checkpoint_path = args.output_dir / "ft1_depth_encoder.pt"
    torch.save(encoder.state_dict(), checkpoint_path)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "episodes": [episode["tag"] for episode in episodes],
        "episode_valid_steps": {
            episode["tag"]: int(episode["valid_steps"]) for episode in episodes
        },
        "total_valid_frames": total_valid,
        "batch": batch,
        "steps_per_episode": steps,
        "seed": args.seed,
        "epochs": args.epochs,
        "updates": update,
        "learning_rate": args.learning_rate,
        "chunk_steps": CHUNK_STEPS,
        "yaw_weights": list(YAW_WEIGHTS),
        "near_miss_weight": args.near_miss_weight,
        "near_miss_halo_steps": args.near_miss_halo,
        "near_miss_weighted_frames": int((loss_weights > 1.0).sum()),
        "first_update_losses": history[0] if history else None,
        "last_update_losses": history[-1] if history else None,
        "loss_history": history,
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": _sha256(checkpoint_path),
        "trainer_sha256": _sha256(Path(__file__)),
        "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
        "wall_time_sec": time.monotonic() - started,
        "gpu_hours": (time.monotonic() - started) / 3600.0,
    }
    _write_json(args.output_dir / "train_report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, nargs="+", default=[DATA_ROOT]
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--save-every-epoch", action="store_true")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--near-miss-weight", type=float, default=3.0)
    parser.add_argument("--near-miss-halo", type=int, default=25)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = train(args)
    first, last = report["first_update_losses"], report["last_update_losses"]
    print(
        "TRAINED "
        f"updates={report['updates']} "
        f"loss d {first['d']:.4f}->{last['d']:.4f} "
        f"c {first['c']:.4f}->{last['c']:.4f} "
        f"yaw {first['yaw']:.4f}->{last['yaw']:.4f} "
        f"cls {first['cls']:.4f}->{last['cls']:.4f}"
    )
    print(f"checkpoint: {report['checkpoint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
