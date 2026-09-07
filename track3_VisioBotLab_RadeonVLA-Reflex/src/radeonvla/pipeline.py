"""One-command pipeline stages for local smoke and remote full runs.

Stages
------
assets     -> setup_assets
env        -> check_env
scene      -> scene smoke
expert     -> scripted expert episodes
record     -> collect LeRobot demos
validate   -> dataset checks
train      -> lerobot-train wrapper (optional dry-run)
eval       -> closed-loop evaluation (needs checkpoint)
benchmark  -> sim throughput
all-smoke  -> assets + env + scene + expert(1) + record(1) + validate + train dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from radeonvla.paths import PROJECT_ROOT
from radeonvla.tasks import SUITES


def _run(cmd: list[str]) -> int:
    print(f"[pipeline] $ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def _banner(title: str) -> None:
    print(f"\n======== {title} ========", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "assets",
            "env",
            "scene",
            "expert",
            "record",
            "validate",
            "train",
            "eval",
            "benchmark",
            "all-smoke",
        ),
    )
    parser.add_argument("--backend", choices=("cpu", "gpu", "amdgpu"), default="cpu")
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--task", default=None, help="Single task id (default: banana_white_left for smoke).")
    parser.add_argument("--suite", default="basic", choices=sorted(SUITES))
    parser.add_argument("--repo-id", default="visiobot/radeonvla_reflex_smoke")
    parser.add_argument("--dataset-root", default="datasets/radeonvla_reflex_smoke")
    parser.add_argument("--steps-train", type=int, default=100)
    parser.add_argument("--policy-path", default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dry-run-train", action="store_true")
    parser.add_argument("--require-amd", action="store_true")
    parser.add_argument("--dr", action="store_true", help="Enable appearance+runtime DR when recording.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Safely replace an existing published dataset after staging validates.",
    )
    parser.add_argument(
        "--discard-incomplete",
        action="store_true",
        help="Discard this target's incomplete staging directory before recording.",
    )
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    py = sys.executable
    root = PROJECT_ROOT
    dataset_path = Path(args.dataset_root)
    if not dataset_path.is_absolute():
        dataset_path = (root / dataset_path).resolve()
    dataset_root = str(dataset_path)
    task = args.task or "banana_white_left"
    t0 = time.time()

    def stage_assets() -> int:
        _banner("assets")
        return _run([py, "-m", "radeonvla.setup_assets"])

    def stage_env() -> int:
        _banner("env")
        cmd = [py, "-m", "radeonvla.check_env"]
        if args.require_amd:
            cmd += ["--require-amd", "--init-genesis"]
        return _run(cmd)

    def stage_scene() -> int:
        _banner("scene")
        return _run([py, "-m", "radeonvla.scene", "--backend", args.backend, "--steps", "30", "--save-frames"])

    def stage_expert() -> int:
        _banner(f"expert ({task})")
        return _run(
            [
                py,
                "-m",
                "radeonvla.expert",
                "--backend",
                args.backend,
                "--task",
                task,
                "--episodes",
                str(args.episodes),
                "--seed",
                str(args.seed),
            ]
        )

    def stage_record() -> int:
        _banner(f"record (episodes={args.episodes})")
        cmd = [
            py,
            "-m",
            "radeonvla.record_dataset",
            "--backend",
            args.backend,
            "--episodes",
            str(args.episodes),
            "--repo-id",
            args.repo_id,
            "--dataset-root",
            dataset_root,
            "--seed",
            str(args.seed),
        ]
        if args.overwrite:
            cmd.append("--overwrite")
        if args.discard_incomplete:
            cmd.append("--discard-incomplete")
        if args.task:
            cmd += ["--task", args.task]
        else:
            cmd += ["--suite", args.suite]
            if args.suite == "basic" and args.episodes >= 20:
                cmd.append("--require-coverage")
        if args.dr:
            cmd += ["--dr-appearance", "--dr-object-color", "--dr-runtime"]
        return _run(cmd)

    def stage_validate() -> int:
        _banner("validate")
        return _run(
            [
                py,
                "-m",
                "radeonvla.validate_dataset",
                "--repo-id",
                args.repo_id,
                "--dataset-root",
                dataset_root,
            ]
        )

    def stage_train() -> int:
        _banner("train" + (" (dry-run)" if args.dry_run_train else ""))
        cmd = [
            py,
            "-m",
            "radeonvla.train_policy",
            "smolvla",
            "--repo-id",
            args.repo_id,
            "--dataset-root",
            dataset_root,
            "--steps",
            str(args.steps_train),
            "--device",
            args.device,
            "--batch-size",
            "1",
            "--num-workers",
            "0",
        ]
        if args.dry_run_train:
            cmd.append("--dry-run")
        return _run(cmd)

    def stage_eval() -> int:
        _banner("eval")
        if not args.policy_path:
            print("[pipeline] --policy-path is required for eval", flush=True)
            return 2
        cmd = [
            py,
            "-m",
            "radeonvla.evaluate",
            "--policy-path",
            args.policy_path,
            "--repo-id",
            args.repo_id,
            "--dataset-root",
            dataset_root,
            "--backend",
            args.backend,
            "--episodes-per-task",
            str(max(1, args.episodes)),
        ]
        if args.task:
            cmd += ["--tasks", args.task]
        else:
            cmd += ["--suite", args.suite]
        if args.backend == "cpu":
            cmd.append("--cpu")
        return _run(cmd)

    def stage_benchmark() -> int:
        _banner("benchmark")
        return _run([py, "-m", "radeonvla.benchmark", "--backend", args.backend, "--steps", "100"])

    stages = {
        "assets": stage_assets,
        "env": stage_env,
        "scene": stage_scene,
        "expert": stage_expert,
        "record": stage_record,
        "validate": stage_validate,
        "train": stage_train,
        "eval": stage_eval,
        "benchmark": stage_benchmark,
    }

    if args.stage == "all-smoke":
        # Force a single easy task for reliable smoke.
        args.task = args.task or "banana_white_left"
        args.episodes = 1
        for name in ("assets", "env", "scene", "expert", "record", "validate"):
            code = stages[name]()
            if code != 0:
                print(f"[pipeline] stage {name} failed with code {code}", flush=True)
                return code
        args.dry_run_train = True
        code = stage_train()
        print(f"[pipeline] all-smoke done in {time.time() - t0:.1f}s", flush=True)
        return code

    code = stages[args.stage]()
    print(f"[pipeline] stage={args.stage} done in {time.time() - t0:.1f}s code={code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
