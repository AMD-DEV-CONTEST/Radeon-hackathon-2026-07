"""Train RationalVLA (API version) end-to-end.

Two-stage training adapted for API-based MLLM:
  Stage 1: Train ACT embedding on defect dataset
  Stage 2: Joint train ACT embedding + ACT policy

Usage:
    python train_rationalvla_api.py --stage 1 --steps 2000
    python train_rationalvla_api.py --stage 2 --steps 5000 --resume outputs/rationalvla/stage1/latest.pt
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rationalvla_model import (
    RationalVLA,
    APIMLLM,
    build_rationalvla,
)


class TrajectoryDataset(Dataset):
    """Load trajectory data from npz files for ACT policy training."""
    def __init__(self, scene_dirs: list[Path]):
        self.states = []
        self.actions = []
        for d in scene_dirs:
            for f in sorted(d.glob("*.npz")):
                data = np.load(f, allow_pickle=True)
                if "states" in data and "actions" in data:
                    self.states.append(data["states"])
                    self.actions.append(data["actions"])
        if self.states:
            self.states = np.concatenate(self.states, axis=0)
            self.actions = np.concatenate(self.actions, axis=0)
        else:
            self.states = np.zeros((1, 7))
            self.actions = np.zeros((1, 7))
        print(f"  Loaded {len(self.states)} trajectory steps from {len(scene_dirs)} scenes", flush=True)

    def __len__(self):
        return len(self.states)

    def __getitem__(self, idx):
        return {
            "state": torch.tensor(self.states[idx], dtype=torch.float32),
            "action": torch.tensor(self.actions[idx], dtype=torch.float32),
        }


class DefectDataset(Dataset):
    """Pre-computed defect dataset — labels come from jsonl, no API needed."""

    def __init__(self, jsonl_path: Path):
        self.samples = []
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                conv = data["conversations"]
                if len(conv) < 3:
                    continue
                instruction = conv[1].get("content", conv[1].get("value", ""))
                gpt_msg = conv[2].get("content", conv[2].get("value", ""))
                is_rejected = "<REJ>" in gpt_msg
                dimension = data.get("defect_dimension", "executable")

                self.samples.append({
                    "instruction": instruction,
                    "is_rejected": is_rejected,
                    "dimension": dimension,
                })
        print(f"  Loaded {len(self.samples)} defect samples", flush=True)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        s = self.samples[idx]
        return {
            "label": torch.tensor(0 if s["is_rejected"] else 1, dtype=torch.long),
            "is_act": torch.tensor(not s["is_rejected"], dtype=torch.bool),
            "dimension": s["dimension"],
        }


def train_stage1(
    model: RationalVLA,
    train_loader: DataLoader,
    val_loader: DataLoader,
    args: argparse.Namespace,
    device: torch.device,
):
    model.freeze_act()
    model.to(device)

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.steps)

    losses = defaultdict(list)
    global_step = 0

    # Single classifier trained jointly with embedding
    classifier = nn.Linear(512, 2).to(device)
    optimizer.add_param_group({"params": classifier.parameters()})

    pbar = tqdm(total=args.steps, desc="Stage 1: Embedding")

    while global_step < args.steps:
        for batch in train_loader:
            if global_step >= args.steps:
                break

            is_act = batch["is_act"].to(device)
            label = batch["label"].to(device)

            latent_z = model.act_embedding(is_act)  # [B, 512]
            logits = classifier(latent_z)
            loss = F.cross_entropy(logits, label)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.act_embedding.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            pred = logits.argmax(dim=-1)
            acc = (pred == label).float().mean()

            losses["loss"].append(loss.item())
            losses["acc"].append(acc.item())

            global_step += 1
            pbar.update(1)
            pbar.set_postfix(loss=f"{loss.item():.4f}", acc=f"{acc.item():.4f}")

            if global_step % args.log_freq == 0:
                avg_loss = np.mean(losses["loss"][-100:])
                avg_acc = np.mean(losses["acc"][-100:])
                tqdm.write(f"  [Step {global_step}] loss={avg_loss:.4f} acc={avg_acc:.4f}")

            if global_step % args.save_freq == 0:
                save_checkpoint(model, optimizer, global_step, args.output_dir, "stage1")

    pbar.close()

    if val_loader is not None:
        val_acc = evaluate_embedding(model, val_loader, device, classifier)
        print(f"  Validation acc: {val_acc:.4f}")

    save_checkpoint(model, optimizer, global_step, args.output_dir, "stage1")
    print(f"  Stage 1 done. Saved to {args.output_dir}/stage1/")


def evaluate_embedding(model, loader, device, classifier):
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for batch in loader:
            is_act = batch["is_act"].to(device)
            label = batch["label"].to(device)
            z = model.act_embedding(is_act)
            logits = classifier(z)
            pred = logits.argmax(dim=-1)
            correct += (pred == label).sum().item()
            total += len(label)
    model.train()
    return correct / max(total, 1)


def train_stage2(
    model: RationalVLA,
    defect_loader: DataLoader,
    traj_loader: DataLoader | None,
    args: argparse.Namespace,
    device: torch.device,
):
    model.unfreeze_act()
    model.to(device)
    model.train()

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.steps)

    classifier = nn.Linear(512, 2).to(device)
    optimizer.add_param_group({"params": classifier.parameters()})

    losses = defaultdict(list)
    global_step = 0
    pbar = tqdm(total=args.steps, desc="Stage 2: Joint")

    defect_iter = iter(defect_loader)
    traj_iter = iter(traj_loader) if traj_loader else None

    while global_step < args.steps:
        # Alternate between defect and trajectory data
        try:
            defect_batch = next(defect_iter)
        except StopIteration:
            defect_iter = iter(defect_loader)
            defect_batch = next(defect_iter)

        is_act = defect_batch["is_act"].to(device)
        label = defect_batch["label"].to(device)
        B = is_act.shape[0]

        dummy_image = torch.randn(B, 3, 224, 224, device=device)
        dummy_state = torch.randn(B, 9, device=device)

        output = model(dummy_image, dummy_state, is_act=is_act)
        latent_z = output["latent_z"]

        loss_cls = F.cross_entropy(classifier(latent_z), label)

        act_mask = is_act.to(torch.bool)
        if act_mask.sum() > 0 and (~act_mask).sum() > 0:
            z_act = F.normalize(latent_z[act_mask], dim=-1)
            z_rej = F.normalize(latent_z[~act_mask], dim=-1)
            loss_contrast = (z_act @ z_rej.T).mean()
        else:
            loss_contrast = torch.tensor(0.0, device=device)

        # Trajectory loss (if available)
        loss_traj = torch.tensor(0.0, device=device)
        if traj_loader is not None and traj_iter is not None:
            try:
                traj_batch = next(traj_iter)
            except StopIteration:
                traj_iter = iter(traj_loader)
                traj_batch = next(traj_iter)

            traj_state = traj_batch["state"].to(device)
            traj_action = traj_batch["action"].to(device)
            TB = traj_state.shape[0]

            # Pad state to 9 dims if needed
            if traj_state.shape[-1] < 9:
                pad = torch.zeros(TB, 9 - traj_state.shape[-1], device=device)
                traj_state = torch.cat([traj_state, pad], dim=-1)

            traj_image = torch.randn(TB, 3, 224, 224, device=device)
            traj_output = model(traj_image, traj_state, is_act=torch.ones(TB, dtype=torch.bool, device=device))
            pred_action = traj_output["action"]

            # Chunk the trajectory actions
            chunk_size = model.act_policy.chunk_size
            if traj_action.shape[0] >= chunk_size:
                # Take a random chunk
                start_idx = np.random.randint(0, max(1, traj_action.shape[0] - chunk_size))
                target_chunk = traj_action[start_idx:start_idx + chunk_size].unsqueeze(0)  # [1, chunk, action_dim]
                if target_chunk.shape[0] == 1 and pred_action.shape[0] == 1:
                    loss_traj = F.mse_loss(pred_action, target_chunk)

        loss = loss_cls + 0.1 * loss_contrast + 0.5 * loss_traj

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

        losses["loss"].append(loss.item())

        global_step += 1
        pbar.update(1)
        pbar.set_postfix(loss=f"{loss.item():.4f}")

        if global_step % args.log_freq == 0:
            avg = np.mean(losses["loss"][-100:])
            tqdm.write(f"  [Step {global_step}] loss={avg:.4f}")

        if global_step % args.save_freq == 0:
            save_checkpoint(model, optimizer, global_step, args.output_dir, "stage2")

    pbar.close()
    save_checkpoint(model, optimizer, global_step, args.output_dir, "stage2")
    print(f"  Stage 2 done. Saved to {args.output_dir}/stage2/")


def save_checkpoint(model, optimizer, step, output_dir, prefix):
    path = Path(output_dir) / prefix
    path.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "step": step,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
    }
    torch.save(checkpoint, path / f"checkpoint-{step}.pt")
    torch.save(checkpoint, path / "latest.pt")


def main():
    parser = argparse.ArgumentParser(description="Train RationalVLA (API version)")
    parser.add_argument("--stage", type=int, required=True, choices=[1, 2])
    parser.add_argument("--defect-dataset", type=str, default="datasets/defect_instructions/defect_instructions.jsonl")
    parser.add_argument("--trajectory-dirs", type=str, nargs="+", default=None,
                        help="List of scene directories containing .npz trajectory files")
    parser.add_argument("--resume", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default="outputs/rationalvla")
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--log-freq", type=int, default=200)
    parser.add_argument("--save-freq", type=int, default=1000)
    parser.add_argument("--val-split", type=float, default=0.1)
    parser.add_argument("--scene-name", type=str, default=None,
                        help="Scene name (A/B/C/D) for dynamic prompt injection. None=all scenes")
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    try:
        print("Building model...", flush=True)
        print(f"  Scene: {args.scene_name or 'all scenes combined'}", flush=True)
        model = build_rationalvla(use_api=False, scene_name=args.scene_name)
        print(f"Model built OK, params: {sum(p.numel() for p in model.parameters()):,}", flush=True)
    except Exception as e:
        print(f"Model build failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    if args.resume:
        ckpt_path = Path(args.resume)
        if not ckpt_path.is_absolute():
            ckpt_path = _ROOT / ckpt_path
        if ckpt_path.exists():
            ckpt = torch.load(ckpt_path, map_location=device)
            model.load_state_dict(ckpt["model_state_dict"], strict=False)
            print(f"Resumed from step {ckpt['step']}")

    jsonl_path = Path(args.defect_dataset)
    if not jsonl_path.is_absolute():
        jsonl_path = (_ROOT / jsonl_path).resolve()

    print(f"Loading defect dataset from {jsonl_path}...")
    try:
        dataset = DefectDataset(jsonl_path)
    except Exception as e:
        print(f"Dataset load failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    n_val = max(1, int(len(dataset) * args.val_split))
    n_train = len(dataset) - n_val
    train_ds, val_ds = torch.utils.data.random_split(dataset, [n_train, n_val])
    defect_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)
    print(f"Defect Train: {n_train}, Val: {n_val}", flush=True)

    # Load trajectory data if provided
    traj_loader = None
    if args.trajectory_dirs:
        scene_dirs = [Path(d) for d in args.trajectory_dirs]
        print(f"Loading trajectory data from {len(scene_dirs)} scenes...")
        traj_dataset = TrajectoryDataset(scene_dirs)
        traj_loader = DataLoader(traj_dataset, batch_size=args.batch_size, shuffle=True)

    if args.stage == 1:
        train_stage1(model, defect_loader, val_loader, args, device)
    else:
        train_stage2(model, defect_loader, traj_loader, args, device)


if __name__ == "__main__":
    main()