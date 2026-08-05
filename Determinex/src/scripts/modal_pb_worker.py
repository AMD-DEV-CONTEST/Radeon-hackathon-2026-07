"""
scripts/modal_pb_worker.py — Modal burst compute for ProgramBench eval workers
===============================================================================
Wraps the ProgramBench inner eval loop as a Modal cloud function. Each instance
evaluates one tool's test suite in an isolated Docker-compatible container,
enabling the churn loop to fan out across multiple tools simultaneously.

This eliminates the Hetzner single-machine bottleneck where:
  - K=8 reimpl attempts are sequential (Ollama single-request)
  - Multiple tools are also sequential (single eval shard)

With Modal, the fan-out becomes:
  pb_churn.py → dispatches N tools in parallel → N Modal workers → collect results

Usage:
    # One-time setup:
    pip install modal>=0.62.0
    modal token new
    modal deploy scripts/modal_pb_worker.py

    # From pb_churn.py:
    import modal
    worker = modal.Function.lookup("determinex-pb-worker", "run_pb_eval")
    result = worker.remote(instance_id="burntsushi__ripgrep", spec_json=...)

    # Bulk: evaluate N tools in parallel
    results = list(worker.map([...specs_list...]))

Environment:
    DETERMINEX_MODAL_SECRET    — Modal secret name
    DETERMINEX_PB_DOCKER_TAG   — Docker image tag for PB eval containers
    MODAL_APP_NAME_PB          — overrides default PB worker app name
"""

from __future__ import annotations

import json
import os

PB_APP_NAME = os.environ.get("MODAL_APP_NAME_PB", "determinex-pb-worker")

try:
    import modal

    _MODAL_AVAILABLE = True
except ImportError:
    _MODAL_AVAILABLE = False


if _MODAL_AVAILABLE:
    app = modal.App(PB_APP_NAME)

    # Lightweight image: just needs Python + the eval scripts
    # PB eval containers themselves are Docker images pulled at eval time
    pb_worker_image = (
        modal.Image.debian_slim(python_version="3.11")
        .pip_install(
            "duckdb>=0.10.0",
            "pydantic>=2.0.0",
            "structlog>=24.0.0",
            "pyyaml>=6.0",
            "requests>=2.31.0",
        )
        .apt_install("docker.io", "curl")
    )

    @app.function(
        image=pb_worker_image,
        timeout=3600,
        memory=8192,
        cpu=4.0,
        secrets=[modal.Secret.from_name("determinex-hf-token")],
    )
    def run_pb_eval(
        instance_id: str,
        spec_json: str,
        version: str = "v1",
        timeout_s: int = 1800,
    ) -> dict:
        """Evaluate one ProgramBench tool against its full test suite.

        Args:
            instance_id: e.g. "burntsushi__ripgrep.313114f"
            spec_json:   JSON tool spec from eval_index.json
            version:     eval version tag (for result provenance)
            timeout_s:   per-eval timeout in seconds

        Returns:
            {
                "instance_id": str,
                "passed": int,
                "total": int,
                "pct": float,
                "locked": bool,
                "rc": int,
                "error": str or None,
                "duration_s": float,
                "version": str,
            }
        """
        import subprocess
        import time

        spec = json.loads(spec_json)
        t0 = time.time()

        # Each PB tool has a Docker image: programbench/<owner>_<repo>_<hash>:task
        docker_image = (
            spec.get("docker_image") or f"programbench/{instance_id.replace('.', '_')}:task"
        )
        cmd = spec.get("eval_cmd", ["pytest", "/solution/", "-x", "--timeout=300"])

        try:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--memory=4g",
                    "--cpus=2",
                    "-v",
                    "/solution:/solution:ro",
                    docker_image,
                ]
                + (cmd if isinstance(cmd, list) else cmd.split()),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            # Parse pytest output for pass/fail counts
            passed, total = _parse_pytest_output(result.stdout + result.stderr)
            pct = (passed / total * 100) if total > 0 else 0.0
            return {
                "instance_id": instance_id,
                "passed": passed,
                "total": total,
                "pct": pct,
                "locked": passed == total and total > 0,
                "rc": result.returncode,
                "error": None,
                "duration_s": time.time() - t0,
                "version": version,
            }
        except subprocess.TimeoutExpired:
            return {
                "instance_id": instance_id,
                "passed": 0,
                "total": 0,
                "pct": 0.0,
                "locked": False,
                "rc": -1,
                "error": f"timeout after {timeout_s}s",
                "duration_s": time.time() - t0,
                "version": version,
            }
        except Exception as e:
            return {
                "instance_id": instance_id,
                "passed": 0,
                "total": 0,
                "pct": 0.0,
                "locked": False,
                "rc": -2,
                "error": str(e),
                "duration_s": time.time() - t0,
                "version": version,
            }

    @app.function(
        image=pb_worker_image,
        timeout=7200,
        memory=8192,
        cpu=4.0,
    )
    def run_pb_eval_batch(specs: list[dict]) -> list[dict]:
        """Evaluate multiple tools in parallel (modal.starmap fan-out).

        Args:
            specs: list of {"instance_id": str, "spec_json": str, "version": str}

        Returns:
            list of eval result dicts (same shape as run_pb_eval)
        """
        return list(
            run_pb_eval.starmap(
                [(s["instance_id"], s["spec_json"], s.get("version", "v1")) for s in specs]
            )
        )

    def _parse_pytest_output(output: str) -> tuple[int, int]:
        """Parse pytest stdout for pass/fail counts."""
        import re

        m = re.search(r"(\d+) passed", output)
        m_total = re.search(r"(\d+) (?:passed|failed|error)", output)
        passed = int(m.group(1)) if m else 0
        # Total = count all outcome lines
        total_matches = re.findall(r"(\d+) (?:passed|failed|error|skipped)", output)
        total = sum(int(x) for x in total_matches) if total_matches else passed
        return passed, total


# ── CLI ───────────────────────────────────────────────────────────────────────


def _cli() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex PB Modal worker")
    sub = ap.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Eval one tool via Modal")
    run.add_argument("--instance-id", required=True)
    run.add_argument("--spec", required=True)
    run.add_argument("--version", default="v1")

    args = ap.parse_args()
    if args.cmd == "run":
        if not _MODAL_AVAILABLE:
            print("Modal not installed. pip install 'determinex[modal]'")
            return 1
        spec_json = open(args.spec).read()
        with app.run():
            result = run_pb_eval.remote(args.instance_id, spec_json, args.version)
        print(json.dumps(result, indent=2))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(_cli())
