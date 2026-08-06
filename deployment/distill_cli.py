"""Train and export a compact policy from recorded expert demonstrations."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import yaml

from deployment.distill import PolicyDistiller, StudentPolicy
from deployment.export import export_student


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/distill.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    states = np.load(Path(config["dataset_dir"]) / "state.npy")
    actions = np.load(Path(config["dataset_dir"]) / "action.npy")
    student = StudentPolicy(states.shape[-1], actions.shape[-1])
    distiller = PolicyDistiller(student, device=config["device"])
    generator = torch.Generator().manual_seed(0)
    for _ in range(int(config["epochs"])):
        permutation = torch.randperm(len(states), generator=generator)
        for indices in permutation.split(int(config["batch_size"])):
            distiller.step(torch.from_numpy(states[indices]), torch.from_numpy(actions[indices]))
    output = Path(config["checkpoint"])
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": student.state_dict(), "observation_dim": states.shape[-1], "action_dim": actions.shape[-1]}, output)
    exported = export_student(student, states.shape[-1], output.parent)
    print(f"Student checkpoint: {output}; ONNX: {exported['onnx']}")


if __name__ == "__main__":
    main()
