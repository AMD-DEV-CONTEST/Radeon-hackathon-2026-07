"""Terminal demo for environments where browser port forwarding is unavailable."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from agent import RequirementGuardian


def gpu_snapshot() -> str:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (result.stdout or result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"rocm-smi unavailable: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Radeon agent demo")
    parser.add_argument("--file", default="sample_requirements.txt")
    parser.add_argument(
        "--task",
        default="Extract mandatory requirements and create a submission-ready checklist.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("RADEON REQUIREMENT GUARDIAN - LOCAL AGENTIC AI DEMO")
    print("=" * 72)
    print("\n[AMD GPU EVIDENCE]\n" + gpu_snapshot())
    print("\n[AGENT RUN]")
    result = RequirementGuardian().run(str(Path(args.file)), args.task)
    print("\n[FINAL REPORT]\n" + result["report"])
    print("\n[INDEPENDENT VERIFICATION]\n" + result["verification"])
    print("\n[PLAN AND TOOL TRACE]\n" + result["trace"])
    print("\n[PERFORMANCE METRICS]\n" + result["metrics"])
    print("\nAll model calls used the local vLLM endpoint; no cloud AI API was used.")


if __name__ == "__main__":
    main()
