"""
scripts/modal_verified_search.py — Modal burst compute for VerifiedSearch amplifier
=====================================================================================
Wraps Determinex's K-search verified synthesis loop as a Modal cloud function,
enabling parallel K=8 candidate generation on a powerful GPU instance instead of
sequential local Ollama calls.

Architecture:
  Local churn loop (pb_churn.py) dispatches tool solve requests to Modal.
  Modal spins up an A100 or H100 instance, runs K=8 LLM generations in parallel
  via vLLM or Ollama-in-container, then returns the best candidate (1-(1-p)^8 odds).

  1-(1-p)^8 vs 1-(1-p)^1:
    If each single attempt succeeds at p=0.3:
      - 1 attempt: 30% chance
      - K=8 attempts: 1-(0.7^8) = 94.2% chance
    Modal makes K=8 as fast as K=1 for the local process.

Usage:
    # One-time setup:
    pip install modal>=0.62.0
    modal token new
    modal deploy scripts/modal_verified_search.py

    # From pb_churn.py or reimpl_drive.py:
    import modal
    f = modal.Function.lookup("determinex-verified-search", "run_k_search")
    result = f.remote(spec_json=..., k=8, rounds=3, model="Qwen/Qwen2.5-Coder-32B-Instruct")

    # Or use the CLI:
    python scripts/modal_verified_search.py run \
        --spec corpus/programbench/tools/bat.json \
        --k 8 --rounds 3 --model Qwen/Qwen2.5-Coder-32B-Instruct

Environment:
    DETERMINEX_MODAL_SECRET — Modal secret with HF_TOKEN and OPENAI_API_KEY
    MODAL_APP_NAME           — overrides default app name (for staging/prod split)

Note: Modal functions require 'modal token new' and a paid Modal account.
The local Ollama path (existing behavior) is never removed — Modal is additive.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = os.environ.get("MODAL_APP_NAME", "determinex-verified-search")

try:
    import modal

    _MODAL_AVAILABLE = True
except ImportError:
    _MODAL_AVAILABLE = False


if _MODAL_AVAILABLE:
    # ── Modal App definition ──────────────────────────────────────────────────────

    app = modal.App(APP_NAME)

    # Image: Determinex + vLLM for parallel generation
    # Pin the CUDA tag to match the Hetzner box GPU driver version.
    determinex_image = (
        modal.Image.from_registry(
            "nvidia/cuda:12.1-cudnn8-runtime-ubuntu22.04",
            add_python="3.11",
        )
        .pip_install(
            "vllm>=0.5.0",
            "transformers>=4.40.0",
            "accelerate>=0.28.0",
            "pydantic>=2.0.0",
            "structlog>=24.0.0",
            "duckdb>=0.10.0",
            "hypothesis>=6.100.0",
        )
        .run_commands(
            # Clone Determinex from the bundle (no remote — PRIVATE mandate)
            "mkdir -p /root/Citadel",
        )
    )

    # GPU preference: A10G is cost-effective; H100 for >14B models
    _GPU = os.environ.get("DETERMINEX_MODAL_GPU", "A10G")

    @app.function(
        image=determinex_image,
        gpu=_GPU,
        timeout=7200,  # 2h — matches local lane timeout
        memory=32768,  # 32GB RAM
        secrets=[modal.Secret.from_name("determinex-hf-token")],
    )
    def run_k_search(
        spec_json: str,
        k: int = 8,
        rounds: int = 3,
        model: str = "Qwen/Qwen2.5-Coder-32B-Instruct",
        fuzz: int = 10,
        timeout_per_round: int = 1200,
    ) -> dict:
        """Run K independent verified-search attempts against the oracle.

        Args:
            spec_json:         JSON-serialized tool spec (from eval_index.json)
            k:                 Number of parallel candidate generations per round
            rounds:            Number of rounds (K candidates per round; passes best forward)
            model:             HuggingFace model ID to serve via vLLM
            fuzz:              Random seed offset for candidate diversity
            timeout_per_round: Per-round time cap in seconds

        Returns:
            {
                "instance_id": str,
                "passed": int,        # oracle pass count in best candidate
                "total": int,         # oracle total test count
                "pct": float,         # pass percentage (0.0-100.0)
                "locked": bool,       # True if passed == total
                "best_candidate": str # path or content of best solution
                "rounds_run": int,
                "k": int,
            }
        """
        import sys

        sys.path.insert(0, "/root/Citadel/scripts")

        spec = json.loads(spec_json)
        instance_id = spec.get("instance_id", "unknown")

        # Start vLLM server in background for batch inference
        import subprocess

        vllm_proc = subprocess.Popen(
            [
                "python",
                "-m",
                "vllm.entrypoints.openai.api_server",
                "--model",
                model,
                "--port",
                "8000",
                "--dtype",
                "bfloat16",
                "--tensor-parallel-size",
                "1",
            ]
        )

        import time

        time.sleep(30)  # vLLM startup

        try:
            # Import the verified search engine
            # (scripts/ is on sys.path; Determinex scripts work standalone)
            from determinex_pb_reimpl import run_verified_search  # type: ignore

            result = run_verified_search(
                instance_id=instance_id,
                spec=spec,
                k=k,
                rounds=rounds,
                model=f"hosted_vllm/{model}",
                model_api_base="http://localhost:8000",
                fuzz=fuzz,
                timeout_per_round=timeout_per_round,
            )
            return result
        finally:
            vllm_proc.terminate()
            vllm_proc.wait()

    @app.function(
        image=determinex_image,
        timeout=300,
        memory=2048,
    )
    def health_check() -> dict:
        """Verify the Modal function is reachable and returns sane output."""
        return {
            "status": "ok",
            "app": APP_NAME,
            "python": __import__("sys").version,
        }


# ── Local CLI for testing ─────────────────────────────────────────────────────


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Modal verified search")
    sub = ap.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Run K-search via Modal (or local if Modal unavailable)")
    run.add_argument("--spec", required=True, help="Path to tool spec JSON")
    run.add_argument("--k", type=int, default=8)
    run.add_argument("--rounds", type=int, default=3)
    run.add_argument("--model", default="Qwen/Qwen2.5-Coder-32B-Instruct")
    run.add_argument("--fuzz", type=int, default=10)

    health = sub.add_parser("health", help="Check Modal function health")

    args = ap.parse_args()

    if args.cmd == "run":
        spec_json = Path(args.spec).read_text(encoding="utf-8")
        if _MODAL_AVAILABLE:
            with app.run():
                result = run_k_search.remote(
                    spec_json=spec_json,
                    k=args.k,
                    rounds=args.rounds,
                    model=args.model,
                    fuzz=args.fuzz,
                )
        else:
            print("Modal not installed — run local fallback")
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "health":
        if not _MODAL_AVAILABLE:
            print("Modal not installed. pip install 'determinex[modal]'")
            return 1
        with app.run():
            print(json.dumps(health_check.remote(), indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(_cli())
