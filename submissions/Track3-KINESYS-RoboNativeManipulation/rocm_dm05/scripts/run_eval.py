#!/usr/bin/env python3
"""Run deterministic native or 3DGS DM05 evaluation on AMD GPUs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("native", "3dgs"), required=True)
    parser.add_argument("--opendm-root", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--demo", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gpus", default="0")
    parser.add_argument("--seed-start", type=int, default=200000)
    parser.add_argument("--num-episodes", type=int, default=50)
    parser.add_argument("--diffusion-steps", type=int, default=10)
    parser.add_argument("--three-dgs-root", type=Path)
    parser.add_argument("--visual-shell-profile", type=Path)
    return parser.parse_args()


def checked_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Missing {label}: {resolved}")
    return resolved


def checked_dir(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(f"Missing {label}: {resolved}")
    return resolved


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    opendm_root = checked_dir(args.opendm_root, "OpenDM checkout")
    model_path = checked_dir(args.model_path, "model")
    demo = checked_file(args.demo, "BiGym demonstration")
    if args.output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_dir}")
    if args.num_episodes <= 0:
        raise ValueError("num-episodes must be positive")

    three_dgs_root: Path | None = None
    visual_shell_profile: Path | None = None
    if args.mode == "3dgs":
        if args.three_dgs_root is None or args.visual_shell_profile is None:
            raise ValueError(
                "3dgs mode requires --three-dgs-root and --visual-shell-profile"
            )
        three_dgs_root = checked_dir(args.three_dgs_root, "3DGS ROCm checkout")
        visual_shell_profile = checked_file(
            args.visual_shell_profile, "visual shell profile"
        )

    gpus = [item.strip() for item in args.gpus.split(",") if item.strip()]
    if not gpus:
        raise ValueError("At least one AMD GPU is required")
    seeds = list(range(args.seed_start, args.seed_start + args.num_episodes))
    seed_groups = [seeds[index:: len(gpus)] for index in range(len(gpus))]
    args.output_dir.mkdir(parents=True)
    processes: list[tuple[int, subprocess.Popen, object]] = []

    for shard, (gpu, shard_seeds) in enumerate(zip(gpus, seed_groups)):
        if not shard_seeds:
            continue
        shard_dir = args.output_dir / f"shard{shard}"
        log_handle = (args.output_dir / f"shard{shard}.log").open(
            "w", encoding="utf-8"
        )
        env = os.environ.copy()
        env.update(
            {
                "HIP_VISIBLE_DEVICES": gpu,
                "ROCR_VISIBLE_DEVICES": gpu,
                "MUJOCO_EGL_DEVICE_ID": gpu,
                "MUJOCO_GL": "egl",
                "PYOPENGL_PLATFORM": "egl",
                "OPENDM_ROOT": str(opendm_root),
                "PYTORCH_ROCM_ARCH": env.get("PYTORCH_ROCM_ARCH", "gfx1100"),
                "MAX_JOBS": env.get("MAX_JOBS", "4"),
                "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        python_path = [
            str(opendm_root),
            str(opendm_root / "d"),
            str(repo_root / "eval"),
            str(repo_root / "train"),
        ]
        if args.mode == "3dgs" and three_dgs_root is not None:
            rocm_wrapper = checked_dir(
                three_dgs_root / "toolchains" / "rocm-wrapper",
                "ROCm compiler wrapper",
            )
            env["TORCH_EXTENSIONS_DIR"] = str(
                three_dgs_root / "cache" / "torch-extensions-gsplat"
            )
            env["ROCM_HOME"] = str(rocm_wrapper)
            env["PATH"] = f"{rocm_wrapper / 'bin'}:{env.get('PATH', '')}"
            include_path = str(repo_root / "compat" / "include")
            if env.get("CPLUS_INCLUDE_PATH"):
                include_path += f":{env['CPLUS_INCLUDE_PATH']}"
            env["CPLUS_INCLUDE_PATH"] = include_path
        if env.get("PYTHONPATH"):
            python_path.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_path)

        evaluator = repo_root / "eval" / f"eval_cutlery_{args.mode}.py"
        command = [
            sys.executable,
            str(evaluator),
            "--model-path",
            str(model_path),
            "--output-dir",
            str(shard_dir),
            "--demo",
            str(demo),
            "--seeds",
            *map(str, shard_seeds),
            "--control-frequency",
            "20",
            "--policy-frequency",
            "20",
            "--chunk-size",
            "16",
            "--diffusion-steps",
            str(args.diffusion_steps),
            "--execute-actions",
            "8",
            "--max-policy-steps",
            "800",
            "--model-max-length",
            "896",
            "--no-lora-wrapper",
            "--reuse-kv-workspace",
        ]
        if visual_shell_profile is not None:
            command.extend(
                ["--visual-shell-profile", str(visual_shell_profile)]
            )
        process = subprocess.Popen(
            command,
            cwd=opendm_root,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        processes.append((shard, process, log_handle))
        print(f"started shard={shard} gpu={gpu} seeds={shard_seeds}", flush=True)

    failures = []
    for shard, process, log_handle in processes:
        return_code = process.wait()
        log_handle.close()
        if return_code:
            failures.append((shard, return_code))
    if failures:
        raise RuntimeError(f"Evaluation shard failures: {failures}")

    summaries = [
        args.output_dir / f"shard{shard}" / "summary.json"
        for shard, _, _ in processes
    ]
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "eval" / "merge_shards.py"),
            "--expected-seeds",
            *map(str, seeds),
            "--output",
            str(args.output_dir / "summary.json"),
            *map(str, summaries),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
