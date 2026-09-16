"""Run a repeated full Agent benchmark on AMD Radeon GPU and ROCm."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.orchestrator import PhotographerAgent


REQUESTS = (
    "Show me how to recreate this portrait, including camera geometry, body action, and gaze.",
    "Analyze the subject-environment relationship and provide a natural shooting sequence.",
    "Identify the primary subject and create a concise contour-based action guidance card.",
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(
        ordered[lower] * (1 - fraction) + ordered[upper] * fraction,
        3,
    )


def _summary(results: list[dict[str, Any]], runs: int) -> dict[str, Any]:
    passed = [result for result in results if result["status"] == "pass"]
    totals = [float(result["total_agent_seconds"]) for result in passed]
    warm = totals[1:] if len(totals) > 1 else []
    return {
        "requested_runs": runs,
        "passed_runs": len(passed),
        "failed_runs": runs - len(passed),
        "success_rate": round(len(passed) / runs, 4) if runs else 0.0,
        "first_request_seconds": totals[0] if totals else None,
        "warm_p50_seconds": _percentile(warm, 0.50),
        "warm_p95_seconds": _percentile(warm, 0.95),
        "all_p50_seconds": _percentile(totals, 0.50),
        "all_p95_seconds": _percentile(totals, 0.95),
        "max_peak_vram_gib": (
            max(float(result["peak_vram_gib"]) for result in passed)
            if passed
            else None
        ),
        "model_reused_after_first": (
            all(bool(result["model_reused"]) for result in passed[1:])
            if len(passed) > 1
            else None
        ),
        "pure_vlm_pose_runs": sum(
            result["pose_source"] == "vlm" for result in passed
        ),
        "validated_fallback_runs": sum(
            "fallback" in result["pose_source"] for result in passed
        ),
        "tool_failures": sum(
            result.get("tool_failures", 0) for result in results
        ),
        "permission_denials": sum(
            result.get("permission_denials", 0) for result in results
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        action="append",
        required=True,
        help="Input image. Repeat --image to cycle through multiple scenes.",
    )
    parser.add_argument("--runs", type=int, default=10, choices=range(1, 51))
    parser.add_argument(
        "--output",
        default="demo/full_agent_benchmark.json",
    )
    args = parser.parse_args()
    images = [Path(value).expanduser().resolve() for value in args.image]
    missing = [str(image) for image in images if not image.is_file()]
    if missing:
        raise FileNotFoundError("Missing benchmark images: " + ", ".join(missing))

    agent = PhotographerAgent()
    results: list[dict[str, Any]] = []
    benchmark_started = time.perf_counter()
    for index in range(args.runs):
        image = images[index % len(images)]
        request = REQUESTS[index % len(REQUESTS)]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            contour_path = Path(temporary.name)
        try:
            print(
                f"[full benchmark] run {index + 1}/{args.runs}: {image.name}",
                flush=True,
            )
            result = agent.run(
                image,
                request,
                generate_overlay=True,
                overlay_path=contour_path,
            )
            tool_failures = sum(
                call["status"] != "completed"
                for call in result["tool_calls"]
            )
            permission_denials = sum(
                entry["decision"] == "deny"
                for entry in result["permission_audit"]
            )
            if not result["metrics"].get("hip"):
                raise AssertionError("HIP runtime was not reported.")
            if result["critic"]["status"] != "pass":
                raise AssertionError(f"Critic failed: {result['critic']}")
            if not contour_path.is_file() or contour_path.stat().st_size < 100:
                raise AssertionError("Photography execution card was not generated.")
            if result["pose_card"]["image_generation_model_used"]:
                raise AssertionError("A forbidden image-generation model was used.")
            if result["pose_card"]["render_mode"] != "ai_photography_execution_card":
                raise AssertionError("Unexpected execution-card render mode.")
            if tool_failures:
                raise AssertionError(f"{tool_failures} tool calls failed.")
            results.append(
                {
                    "run": index + 1,
                    "status": "pass",
                    "image": image.name,
                    "total_agent_seconds": result["metrics"][
                        "total_agent_seconds"
                    ],
                    "vision_seconds": result["metrics"].get(
                        "inference_seconds"
                    ),
                    "pose_card_seconds": result["pose_card"]["seconds"],
                    "peak_vram_gib": result["metrics"].get(
                        "peak_allocated_vram_gib", 0
                    ),
                    "model_reused": result["metrics"].get(
                        "model_reused", False
                    ),
                    "pose_source": result["pose_card"]["pose_source"],
                    "tools_called": len(result["tool_calls"]),
                    "tool_failures": tool_failures,
                    "permission_denials": permission_denials,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "run": index + 1,
                    "status": "fail",
                    "image": image.name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "tool_failures": 1,
                    "permission_denials": 0,
                }
            )
        finally:
            contour_path.unlink(missing_ok=True)

    report = {
        "schema_version": "2.0",
        "platform": "AMD Radeon GPU + ROCm/HIP",
        "benchmark": "full_agent_with_deterministic_pose_card",
        "wall_seconds": round(time.perf_counter() - benchmark_started, 3),
        "summary": _summary(results, args.runs),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"[full benchmark] report -> {output}", flush=True)
    if report["summary"]["failed_runs"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
