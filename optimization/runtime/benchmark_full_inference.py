from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Inductor reads these while torch modules are imported, so set them before
# importing the shared benchmark/backend modules.
if "--backend" in sys.argv:
    index = sys.argv.index("--backend")
    if index + 1 < len(sys.argv) and sys.argv[index + 1] == "compile":
        os.environ.setdefault("TORCHINDUCTOR_FREEZING", "1")
        os.environ.setdefault("TORCHINDUCTOR_MAX_AUTOTUNE_GEMM", "1")
        os.environ.setdefault("TORCHINDUCTOR_MAX_AUTOTUNE_POINTWISE", "1")

from optimization.common import add_common_args, load_benchmark, run_standard
from optimization.runtime.backends import install_backend

RESULTS = Path(__file__).resolve().parent / "results"


def main():
    parser = argparse.ArgumentParser(description="Benchmark a backend on the real full SmolVLA sample_actions path")
    add_common_args(parser)
    parser.add_argument("--backend", choices=("eager", "compile", "hip-graph"), required=True)
    parser.add_argument("--compile-mode", default="max-autotune-no-cudagraphs")
    parser.add_argument("--fullgraph", action="store_true")
    parser.add_argument("--matmul-precision", choices=("highest", "high"), default="highest")
    parser.add_argument("--capture-warmup", type=int, default=3)
    args = parser.parse_args()
    if args.output is None:
        suffix = f"_bs{args.batch_size}" if args.batch_size != 1 else ""
        args.output = str(RESULTS / f"full_{args.backend}{suffix}.json")
    pb, _, _, call = load_benchmark(args)
    config = install_backend(
        pb.policy.model,
        args.backend,
        batch_size=args.batch_size,
        device=pb.device,
        compile_mode=args.compile_mode,
        fullgraph=args.fullgraph,
        capture_warmup=args.capture_warmup,
        matmul_precision=args.matmul_precision,
    )
    config.update(
        {
            "scope": "real full model.sample_actions",
            "inductor_freezing": os.environ.get("TORCHINDUCTOR_FREEZING"),
            "max_autotune_gemm": os.environ.get("TORCHINDUCTOR_MAX_AUTOTUNE_GEMM"),
            "max_autotune_pointwise": os.environ.get("TORCHINDUCTOR_MAX_AUTOTUNE_POINTWISE"),
        }
    )
    run_standard(args, f"runtime_full_{args.backend}", call, pb.device, config)


if __name__ == "__main__":
    main()
