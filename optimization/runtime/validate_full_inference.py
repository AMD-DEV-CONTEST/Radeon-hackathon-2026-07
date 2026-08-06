from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if "--backend" in sys.argv:
    index = sys.argv.index("--backend")
    if index + 1 < len(sys.argv) and sys.argv[index + 1] == "compile":
        os.environ.setdefault("TORCHINDUCTOR_FREEZING", "1")
        os.environ.setdefault("TORCHINDUCTOR_MAX_AUTOTUNE_GEMM", "1")
        os.environ.setdefault("TORCHINDUCTOR_MAX_AUTOTUNE_POINTWISE", "1")

import numpy as np
import torch

from optimization.common import add_common_args, load_benchmark, system_info
from optimization.runtime.backends import install_backend

RESULTS = Path(__file__).resolve().parent / "results"


def compare(reference: torch.Tensor, candidate: torch.Tensor, *, atol: float, rtol: float) -> dict:
    reference = reference.detach().float().cpu()
    candidate = candidate.detach().float().cpu()
    diff = candidate - reference
    flat_reference = reference.flatten()
    flat_candidate = candidate.flatten()
    denominator = torch.linalg.vector_norm(flat_reference) * torch.linalg.vector_norm(flat_candidate)
    return {
        "finite": bool(torch.isfinite(candidate).all()),
        "max_abs_error": float(diff.abs().max()),
        "mean_abs_error": float(diff.abs().mean()),
        "rmse": float(torch.sqrt(torch.mean(diff.square()))),
        "cosine_similarity": float(torch.dot(flat_reference, flat_candidate) / denominator),
        "allclose": bool(torch.allclose(reference, candidate, atol=atol, rtol=rtol)),
    }


def perturb_batch(batch: dict) -> None:
    for key, value in batch.items():
        if not isinstance(value, torch.Tensor) or not value.is_floating_point():
            continue
        if key.startswith("observation.images"):
            value.add_(0.01).clamp_(-1.0, 1.0)
        elif key == "observation.state":
            value.add_(0.01)


def main():
    parser = argparse.ArgumentParser(description="Validate optimized real sample_actions against eager")
    add_common_args(parser)
    parser.add_argument("--backend", choices=("compile", "hip-graph"), required=True)
    parser.add_argument("--compile-mode", default="max-autotune-no-cudagraphs")
    parser.add_argument("--fullgraph", action="store_true")
    parser.add_argument("--matmul-precision", choices=("highest", "high"), default="highest")
    parser.add_argument("--capture-warmup", type=int, default=3)
    parser.add_argument("--atol", type=float, default=1e-4)
    parser.add_argument("--rtol", type=float, default=1e-3)
    args = parser.parse_args()
    if args.output is None:
        suffix = f"_bs{args.batch_size}" if args.batch_size != 1 else ""
        args.output = str(RESULTS / f"validation_{args.backend}{suffix}.json")

    reference_pb, reference_batch, _, reference_call = load_benchmark(args)
    candidate_pb, candidate_batch, _, candidate_call = load_benchmark(args)
    backend_config = install_backend(
        candidate_pb.policy.model,
        args.backend,
        batch_size=args.batch_size,
        device=candidate_pb.device,
        compile_mode=args.compile_mode,
        fullgraph=args.fullgraph,
        capture_warmup=args.capture_warmup,
        matmul_precision=args.matmul_precision,
    )

    with torch.inference_mode():
        reference_initial = reference_call()
        candidate_initial = candidate_call()
    initial = compare(reference_initial, candidate_initial, atol=args.atol, rtol=args.rtol)

    perturb_batch(reference_batch)
    perturb_batch(candidate_batch)
    with torch.inference_mode():
        reference_changed = reference_call()
        candidate_changed = candidate_call()
    changed = compare(reference_changed, candidate_changed, atol=args.atol, rtol=args.rtol)
    response_to_change = compare(candidate_initial, candidate_changed, atol=args.atol, rtol=args.rtol)
    reference_response = compare(reference_initial, reference_changed, atol=args.atol, rtol=args.rtol)
    graph_runner = getattr(candidate_pb.policy.model, "_hip_graph_runner", None)

    output_changed = response_to_change["max_abs_error"] > 0.0
    validation_passed = initial["allclose"] and changed["allclose"] and output_changed
    result = {
        "status": "ok" if validation_passed else "numerical_mismatch",
        "experiment": f"runtime_validation_{args.backend}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            **backend_config,
            "batch_size": args.batch_size,
            "seed": args.seed,
            "atol": args.atol,
            "rtol": args.rtol,
        },
        "validation_passed": validation_passed,
        "fixed_input_comparison": initial,
        "changed_input_comparison": changed,
        "optimized_response_to_input_change": response_to_change,
        "eager_response_to_input_change": reference_response,
        "dynamic_input_check": {
            "optimized_output_changed": output_changed,
            "capture_count": graph_runner.capture_count if graph_runner is not None else None,
        },
        "system": system_info(candidate_pb.device),
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.save_output:
        output_path = Path(args.save_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_path, candidate_initial.detach().float().cpu().numpy())
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"[validation] wrote {path}")


if __name__ == "__main__":
    main()
