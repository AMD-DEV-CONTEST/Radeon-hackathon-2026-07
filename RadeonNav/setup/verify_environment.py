#!/usr/bin/env python3
"""Fail-fast verification for the RadeonNav AMD/ROCm reproduction bundle."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CHECKPOINT_SHA256 = (
    "a40a79881f07b2f8473d31820c8f2590625d6e3d1f07bf9dcc569c3e88ca7265"
)
CHECKPOINT = (
    ROOT
    / "experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN"
    / "ft1_depth_encoder_epoch6.pt"
)
REQUIRED_WEIGHTS = (
    ROOT / "quadrupedal-agility/go2_deploy/models/high_policy/cruft/model.pt",
    ROOT / "quadrupedal-agility/go2_deploy/models/ll_policy/3_model/model.pt",
    ROOT / "quadrupedal-agility/tsc/weights/bbc/model.pt",
    ROOT
    / "CPP/go2_rl_gym/deploy/pre_train/go2"
    / "go2_moe_cts_high_slope_thre_164k_0.6715.pt",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_state(name: str, expected: int) -> dict[str, object]:
    directory = ROOT / "experiment-results/quadrupedal-agility" / name
    json_stems = {path.stem for path in directory.glob("*.json")}
    npz_stems = {path.stem for path in directory.glob("*.npz")}
    if len(json_stems) != expected or json_stems != npz_stems:
        raise RuntimeError(
            f"{name}: expected {expected} paired JSON/NPZ episodes, "
            f"found json={len(json_stems)} npz={len(npz_stems)}"
        )
    return {"directory": str(directory), "paired_episodes": len(json_stems)}


def run_probe(source: str) -> dict[str, object]:
    env = os.environ.copy()
    env.setdefault("MUJOCO_GL", "egl")
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(ROOT / "UniLab/src"),
            str(ROOT / "NeuPAN"),
            env.get("PYTHONPATH", ""),
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", source],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"environment probe exited {completed.returncode}: {details}"
        )
    return json.loads(completed.stdout)


def main() -> int:
    # Keep native stacks in isolated processes. Importing MuJoCo/EGL and
    # NeuPAN's plotting dependencies in one bare verification process can
    # crash in native library finalizers even though the actual runners work.
    torch_state = run_probe(
        "import json, torch; "
        "available=torch.cuda.is_available(); "
        "probe=torch.arange(4,device='cuda').sum().item() if available else None; "
        "print(json.dumps({'version':torch.__version__,'hip':torch.version.hip,"
        "'available':available,'device':torch.cuda.get_device_name(0) if available "
        "else None,'probe':probe}))"
    )
    if torch_state["hip"] is None:
        raise RuntimeError(f"PyTorch is not a ROCm build: {torch_state['version']}")
    if not torch_state["available"]:
        raise RuntimeError("ROCm PyTorch cannot access an AMD GPU")
    if torch_state["probe"] != 6:
        raise RuntimeError(f"unexpected GPU tensor result: {torch_state['probe']}")

    # JAX runs in its own process here. PyTorch and the AMD JAX plugin ship
    # different HIP runtime copies, which are unified by the dedicated MPAX
    # launcher only for the joint NeuPAN smoke test.
    jax_state = run_probe(
        "import json, jax, jax.numpy as jnp; "
        "probe=float(jnp.arange(4.0).sum()); "
        "print(json.dumps({'version':jax.__version__,"
        "'backend':jax.default_backend(),'devices':[str(d) for d in jax.devices()],"
        "'probe':probe}))"
    )
    if jax_state["backend"] != "gpu" or jax_state["probe"] != 6.0:
        raise RuntimeError(f"JAX ROCm probe failed: {jax_state}")

    mujoco_state = run_probe(
        "import json, mujoco; print(json.dumps({'version':mujoco.__version__}))"
    )
    unilab_state = run_probe(
        "import json, pathlib, unilab; "
        "print(json.dumps({'module':str(pathlib.Path(unilab.__file__).resolve())}))"
    )
    neupan_state = run_probe(
        "import json,sys,types; shim=False; "
        "exec(\"try:\\n import tkinter\\nexcept ModuleNotFoundError:\\n "
        "shim=True\\n tkinter=types.ModuleType('tkinter')\\n tkinter.Scale=object\\n "
        "sys.modules['tkinter']=tkinter\"); "
        "import neupan; print(json.dumps({'module':neupan.__file__,'shim':shim}))"
    )

    missing = [str(path) for path in REQUIRED_WEIGHTS if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing policy weights: " + ", ".join(missing))
    if not CHECKPOINT.is_file():
        raise FileNotFoundError(CHECKPOINT)
    checkpoint_sha = sha256(CHECKPOINT)
    if checkpoint_sha != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            f"checkpoint digest mismatch: {checkpoint_sha} != "
            f"{EXPECTED_CHECKPOINT_SHA256}"
        )

    state = {
        "status": "PASSED",
        "root": str(ROOT),
        "torch_version": torch_state["version"],
        "torch_hip_version": torch_state["hip"],
        "device_name": torch_state["device"],
        "jax_version": jax_state["version"],
        "jax_backend": jax_state["backend"],
        "jax_devices": jax_state["devices"],
        "mujoco_version": mujoco_state["version"],
        "unilab_module": unilab_state["module"],
        "neupan_module": neupan_state["module"],
        "headless_tkinter_shim": neupan_state["shim"],
        "datasets": {
            "FT1-DATA": dataset_state("FT1-DATA", 159),
            "FT2-DATA": dataset_state("FT2-DATA", 119),
        },
        "checkpoint": str(CHECKPOINT),
        "checkpoint_sha256": checkpoint_sha,
        "required_policy_weights": [str(path) for path in REQUIRED_WEIGHTS],
    }
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
