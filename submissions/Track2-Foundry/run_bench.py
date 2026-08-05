"""Run the quantization/speed/accuracy benchmark on a finished build.

Usage:
    python run_bench.py --config configs/local_4060.toml --run-dir runs/build-...
    python run_bench.py ... --quants Q4_K_M,Q8_0 --no-teacher

The teacher llama-server must NOT be running (ports + VRAM).
"""

import argparse
from pathlib import Path

from foundry import config as config_mod
from foundry.bench import run_bench


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/local_4060.toml")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--quants", default=None,
                    help="Comma-separated, e.g. Q4_K_M,Q5_K_M,Q6_K,Q8_0")
    ap.add_argument("--no-teacher", action="store_true",
                    help="Skip the teacher speed benchmark")
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    quants = args.quants.split(",") if args.quants else None
    run_bench(cfg, Path(args.run_dir), quants=quants,
              bench_teacher=not args.no_teacher)


if __name__ == "__main__":
    main()
