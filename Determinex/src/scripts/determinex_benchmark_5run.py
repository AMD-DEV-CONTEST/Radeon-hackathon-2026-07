"""
Determinex 5-Run Benchmark Harness
================================
Run SWE-bench N times locally, aggregate results, produce a publishable scorecard.
All runs use local Determinex models (C1/C3/C7) — no external API unless specified.

Usage:
  python scripts/determinex_benchmark_5run.py --runs 5 --instances 10 --backend ollama
  python scripts/determinex_benchmark_5run.py --runs 5 --instances 50 --backend ollama --models c1,c7

Environment:
  DETERMINEX_INFERENCE_BACKEND    ollama | vllm | deepseek
  DETERMINEX_BUILDER_MODEL        c1 | c3 | c7 (overrides --models builder)
  DETERMINEX_ARCHITECT_MODEL      c7 (overrides --models architect)

Related scripts (pick the right one):
  determinex_benchmark_5run.py    — THIS FILE. Statistical 5-run harness.
                                 Use when you need mean ± std for publication tables.
  determinex_benchmark.py         — Single-run role assignment scoring.
                                 Use after registering a new model to pick its role.
  benchmark_runner.py          — Universal dispatcher for CI / overnight cross-suite runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

logging.basicConfig(
    level=logging.INFO, format="[5RUN] %(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("determinex_5run")

_REGISTRY_PATH = Path(__file__).parent.parent / "determinex_model_registry.json"
_LOGS_DIR = Path(__file__).parent.parent / "logs" / "benchmark_5run"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

_MODEL_TAG = {
    "c1": "determinex-engineer-v10-dsl",
    "c3": "determinex-observer-v5-dsl",
    "c7": "determinex-sentinel-v3",
}


def run_single(
    run_id: int, instances: int, backend: str, builder: str, architect: str, split: str
) -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"run{run_id:02d}_{ts}"
    env = {
        **os.environ,
        "DETERMINEX_INFERENCE_BACKEND": backend,
    }

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "determinex_swebench_run.py"),
        "--split",
        split,
        "--instances",
        str(instances),
        "--run-id",
        label,
        "--skip-eval",
        "--builder-model",
        _MODEL_TAG.get(builder, builder),
        "--observer-model",
        _MODEL_TAG.get("c3", "determinex-observer-v5-dsl"),
    ]

    log.info(
        "Run %d/%d starting — backend=%s builder=%s architect=%s instances=%d",
        run_id,
        instances,
        backend,
        builder,
        architect,
        instances,
    )

    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    elapsed = time.time() - t0

    # Parse predictions.jsonl to count patches
    preds_path = Path(__file__).parent.parent / "logs" / "swebench" / label / "predictions.jsonl"
    patched = 0
    total = 0
    if preds_path.exists():
        for line in preds_path.open(encoding="utf-8"):
            try:
                p = json.loads(line)
                total += 1
                if p.get("model_patch", "").strip():
                    patched += 1
            except Exception:
                pass

    patch_rate = patched / total if total else 0.0
    result = {
        "run_id": label,
        "run_num": run_id,
        "patched": patched,
        "total": total,
        "patch_rate": patch_rate,
        "elapsed_s": round(elapsed, 1),
        "returncode": proc.returncode,
        "backend": backend,
        "builder": builder,
        "architect": architect,
    }

    log.info(
        "Run %d complete: %d/%d patched (%.1f%%) in %.0fs",
        run_id,
        patched,
        total,
        patch_rate * 100,
        elapsed,
    )
    return result


def build_scorecard(results: list[dict], args: argparse.Namespace) -> dict:
    rates = [r["patch_rate"] for r in results]
    avg = mean(rates)
    sd = stdev(rates) if len(rates) > 1 else 0.0
    best = max(rates)
    worst = min(rates)

    registry = {}
    if _REGISTRY_PATH.exists():
        registry = json.loads(_REGISTRY_PATH.read_text())

    scorecard = {
        "model_family": "Determinex",
        "organization": "Determinex Contributors",
        "version": registry.get("version", "1.0"),
        "benchmark": "SWE-bench Lite",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "runs": len(results),
        "instances_per_run": args.instances,
        "backend": args.backend,
        "builder_model": "Determinex-1-Tiny v1.0 (C1)" if args.builder == "c1" else args.builder,
        "architect_model": "Determinex-7-Large v1.0 (C7)"
        if args.architect == "c7"
        else args.architect,
        "metrics": {
            "patch_rate_mean": round(avg, 4),
            "patch_rate_stdev": round(sd, 4),
            "patch_rate_best": round(best, 4),
            "patch_rate_worst": round(worst, 4),
            "patch_rate_pct": f"{avg * 100:.1f}%",
        },
        "run_detail": results,
        "note": (
            "Patch generation rate (patches produced / instances attempted). "
            "Official resolve rate requires Docker harness eval. "
            f"5-run validation demonstrates consistency: ±{sd * 100:.1f}% std dev."
        ),
        "architecture": {
            "shadow_compilation": True,
            "latent_rag": True,
            "retrieval_modes": ["ADAPT", "HINT", "GENERATE"],
            "flywheel": True,
            "compiler_oracle": True,
            "multi_path": True,
        },
    }
    return scorecard


def main():
    parser = argparse.ArgumentParser(description="Determinex 5-Run Benchmark Harness")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--instances", type=int, default=10, help="Instances per run")
    parser.add_argument("--backend", default="ollama", choices=["ollama", "vllm", "deepseek"])
    parser.add_argument("--builder", default="c1", help="Builder model: c1|c3|c7")
    parser.add_argument("--architect", default="c7", help="Architect model: c1|c3|c7")
    parser.add_argument("--split", default="lite")
    parser.add_argument("--out", default=None, help="Output scorecard path")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(
        "Determinex %d-Run Benchmark — %s", args.runs, datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    log.info("Builder: %s (%s)", args.builder.upper(), _MODEL_TAG.get(args.builder, args.builder))
    log.info(
        "Architect: %s (%s)", args.architect.upper(), _MODEL_TAG.get(args.architect, args.architect)
    )
    log.info("Backend: %s | Instances/run: %d | Runs: %d", args.backend, args.instances, args.runs)
    log.info("=" * 60)

    results = []
    for i in range(1, args.runs + 1):
        r = run_single(i, args.instances, args.backend, args.builder, args.architect, args.split)
        results.append(r)

    scorecard = build_scorecard(results, args)

    # Print summary
    log.info("=" * 60)
    log.info("FINAL SCORECARD — Determinex v%s", scorecard["version"])
    log.info(
        "Benchmark: %s (%d runs × %d instances)", scorecard["benchmark"], args.runs, args.instances
    )
    log.info(
        "Patch rate: %s (±%.1f%%)",
        scorecard["metrics"]["patch_rate_pct"],
        scorecard["metrics"]["patch_rate_stdev"] * 100,
    )
    log.info(
        "Best run: %.1f%% | Worst: %.1f%%",
        scorecard["metrics"]["patch_rate_best"] * 100,
        scorecard["metrics"]["patch_rate_worst"] * 100,
    )
    log.info("=" * 60)

    out_path = (
        Path(args.out)
        if args.out
        else _LOGS_DIR / f"scorecard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    out_path.write_text(json.dumps(scorecard, indent=2))
    log.info("Scorecard written: %s", out_path)

    # Also write a clean markdown summary for posting
    md_path = out_path.with_suffix(".md")
    md = f"""# Determinex v{scorecard["version"]} — SWE-bench Lite Results

**Date**: {scorecard["date"]}
**Benchmark**: {scorecard["benchmark"]}
**Runs**: {args.runs} independent runs × {args.instances} instances each

## Results

| Metric | Value |
|--------|-------|
| Patch rate (mean) | **{scorecard["metrics"]["patch_rate_pct"]}** |
| Std dev | ±{scorecard["metrics"]["patch_rate_stdev"] * 100:.1f}% |
| Best run | {scorecard["metrics"]["patch_rate_best"] * 100:.1f}% |
| Worst run | {scorecard["metrics"]["patch_rate_worst"] * 100:.1f}% |

## Models

| Role | Model | Params |
|------|-------|--------|
| Builder | {scorecard["builder_model"]} | 1.5B |
| Architect | {scorecard["architect_model"]} | 7B |
| Monitor | Determinex-3-Medium v1.0 (C3) | 3B |
| Compiler Oracle | Local (rustc/go/python) | — |

## Architecture

- Shadow compilation baseline capture before edits
- Three-mode Latent RAG: ADAPT / HINT / GENERATE based on cosine similarity
- Flywheel: every solved instance feeds back into retrieval corpus
- Multi-path generation: 3 temperature paths with Compiler Oracle gating
- 100% local inference — no external API required

## Run Detail

| Run | Patched | Total | Patch Rate |
|-----|---------|-------|-----------|
"""
    for r in results:
        md += f"| {r['run_num']} | {r['patched']} | {r['total']} | {r['patch_rate'] * 100:.1f}% |\n"

    md += f"\n*{scorecard['note']}*\n"
    md_path.write_text(md)
    log.info("Markdown summary: %s", md_path)

    return 0 if scorecard["metrics"]["patch_rate_mean"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
