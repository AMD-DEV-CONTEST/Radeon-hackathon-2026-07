"""Environment inspection for local development and strict AMD execution."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import torch


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def collect_environment() -> dict[str, Any]:
    available = torch.cuda.is_available()
    count = torch.cuda.device_count() if available else 0
    devices = [torch.cuda.get_device_name(index) for index in range(count)]

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "git_commit": _git_commit(),
        "hip_visible_devices": os.environ.get("HIP_VISIBLE_DEVICES"),
        "torch": torch.__version__,
        "torch_hip": torch.version.hip,
        "accelerator_available": available,
        "visible_device_count": count,
        "visible_devices": devices,
        "genesis": _package_version("genesis-world"),
        "lerobot": _package_version("lerobot"),
        "transformers": _package_version("transformers"),
    }


def require_single_amd(environment: dict[str, Any]) -> None:
    errors: list[str] = []
    if environment["torch_hip"] is None:
        errors.append("PyTorch is not a ROCm/HIP build")
    if not environment["accelerator_available"]:
        errors.append("PyTorch cannot access an accelerator")
    if environment["visible_device_count"] != 1:
        errors.append(f"Exactly one GPU must be visible; found {environment['visible_device_count']}")
    if environment["visible_devices"] and not any(
        token in environment["visible_devices"][0].lower() for token in ("amd", "radeon")
    ):
        errors.append(f"Visible GPU is not identified as AMD Radeon: {environment['visible_devices'][0]}")
    if errors:
        raise RuntimeError("; ".join(errors))


def run_tensor_smoke(require_amd: bool) -> dict[str, Any]:
    device = torch.device("cuda" if require_amd else "cpu")
    x = torch.randn(128, 128, device=device, requires_grad=True)
    loss = (x @ x).square().mean()
    loss.backward()
    result: dict[str, Any] = {
        "tensor_device": str(x.device),
        "loss": float(loss.detach().cpu()),
    }
    if device.type == "cuda":
        result["peak_vram_mib"] = torch.cuda.max_memory_allocated() / 1024**2
    return result


def init_genesis(require_amd: bool) -> dict[str, str]:
    # Numba otherwise tries to cache compiled Genesis helpers next to the installed
    # package or below the default cache directory. Both locations can be read-only in
    # restricted containers and managed development environments.
    cache_dir = Path(tempfile.gettempdir()) / "radeonvla-numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(cache_dir))

    import genesis as gs

    backend = gs.amdgpu if require_amd else gs.cpu
    gs.init(backend=backend, seed=0, logging_level="warning")
    return {
        "requested_backend": str(backend),
        "resolved_backend": str(gs.backend),
        "device": str(gs.device),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-amd",
        action="store_true",
        help="Fail unless exactly one ROCm-visible AMD Radeon GPU is available.",
    )
    parser.add_argument(
        "--init-genesis",
        action="store_true",
        help="Initialize Genesis using AMD on strict runs or CPU on local runs.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional path for the machine-readable environment report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = collect_environment()

    if args.require_amd:
        require_single_amd(environment)

    environment["tensor_smoke"] = run_tensor_smoke(args.require_amd)
    if args.init_genesis:
        environment["genesis_runtime"] = init_genesis(args.require_amd)

    rendered = json.dumps(environment, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
