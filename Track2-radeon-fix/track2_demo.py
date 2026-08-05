"""Render a leakage-safe Track 2 CLI dashboard from a frozen agent run."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


GPU_METRIC_LABELS = {
    "gpu_model": "GPU",
    "rocm_version": "ROCm",
    "vllm_version": "vLLM",
    "ttft_ms": "TTFT",
    "tokens_per_second": "Tokens/s",
    "p50_latency_ms": "P50 latency",
    "p95_latency_ms": "P95 latency",
    "vram_gb": "VRAM",
    "gpu_utilization_percent": "GPU utilization",
}


def read_gpu_metrics() -> dict[str, Any]:
    """Read a small, best-effort ROCm snapshot for the live demo."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showuse", "--showmeminfo", "vram", "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        raw = result.stdout
        try:
            decoded = json.loads(raw)
            device = next(iter(decoded.values())) if isinstance(decoded, dict) else {}
            return {
                "gpu_model": device.get("Card series", device.get("Card model", "AMD Radeon")),
                "gpu_utilization_percent": device.get("GPU use (%)"),
                "vram_gb": round(float(device.get("VRAM Total Memory (B)", 0)) / 1e9, 2)
                if device.get("VRAM Total Memory (B)") else None,
            }
        except (json.JSONDecodeError, TypeError, ValueError):
            model = re.search(r"Card Model:\s+(.+)", raw)
            use = re.search(r"GPU use \(%\):\s*(\d+)", raw)
            return {
                "gpu_model": model.group(1).strip() if model else "AMD Radeon",
                "gpu_utilization_percent": int(use.group(1)) if use else None,
            }
    except (FileNotFoundError, subprocess.SubprocessError):
        return {}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def choose_result(
    rows: list[dict[str, Any]], *, harness: str, task_id: str, repeat: int
) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row.get("harness") == harness
        and row.get("task_id") == task_id
        and int(row.get("repeat", 1)) == repeat
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one frozen result for {harness}/{task_id}/repeat-{repeat:02d}, "
            f"found {len(matches)}"
        )
    return matches[0]


def public_task(manifest: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    match = next((row for row in manifest if row.get("instance_id") == task_id), None)
    if match is None:
        raise ValueError(f"task is absent from public manifest: {task_id}")
    forbidden = {"patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"} & set(match)
    if forbidden:
        raise ValueError("public manifest contains evaluator-only fields: " + ", ".join(sorted(forbidden)))
    return match


def official_outcome(
    summary: dict[str, Any], *, harness: str, task_id: str, repeat: int
) -> dict[str, Any]:
    for evaluation in summary.get("evaluations", []):
        if evaluation.get("harness") != harness or int(evaluation.get("repeat", 1)) != repeat:
            continue
        for outcome in evaluation.get("instance_reports", []):
            if outcome.get("instance_id") == task_id:
                return outcome
    return {}


def metric_value(key: str, value: Any) -> str:
    if key.endswith("_ms"):
        return f"{value} ms"
    if key == "vram_gb":
        return f"{value} GB"
    if key == "gpu_utilization_percent":
        return f"{value}%"
    return str(value)


def render_dashboard(
    *,
    task: dict[str, Any],
    result: dict[str, Any],
    outcome: dict[str, Any],
    patch: str,
    gpu_metrics: dict[str, Any] | None = None,
) -> str:
    diagnostics = result.get("trajectory_diagnostics", {})
    usage = result.get("usage", {})
    api_errors = result.get("api_errors", [])
    lines = [
        "# Private Code Repair Agent",
        "",
        f"- Task: `{task['instance_id']}`",
        f"- Repository: `{task['repo']}`",
        f"- Harness: `{result['harness']}` (repeat {int(result.get('repeat', 1))})",
        f"- Model: `{result.get('model', 'unknown')}`",
        "",
        "## Issue",
        "",
        str(task.get("problem_statement", "")).strip(),
        "",
        "## Agent trajectory summary",
        "",
        f"- Model turns: {int(result.get('model_turns', result.get('semantic_calls', 0)))}",
        f"- Tool calls: {int(diagnostics.get('tool_calls', 0))}",
        f"- Edit calls: {int(diagnostics.get('edit_tool_calls', 0))}",
        f"- Tests after edit: {'yes' if diagnostics.get('tests_after_edit') else 'no'}",
        f"- Tool errors: {int(diagnostics.get('tool_errors', 0))}",
        f"- API errors: {len(api_errors)}",
        f"- Total tokens: {int(usage.get('total_tokens', 0) or 0)}",
        f"- Wall time: {float(result.get('wall_time_ms', 0)) / 1000:.1f} s",
        f"- Integrity eligible: {'yes' if diagnostics.get('integrity_eligible', True) else 'no'}",
        "",
        "## Verifier evidence",
        "",
    ]
    if outcome:
        lines.extend(
            [
                f"- Patch applied: {'yes' if outcome.get('patch_applied') else 'no'}",
                f"- Resolution: {outcome.get('resolution_status', 'NO')}",
                "- FAIL_TO_PASS: "
                f"{int(outcome.get('fail_to_pass_success', 0))}/{int(outcome.get('fail_to_pass_total', 0))}",
                "- PASS_TO_PASS: "
                f"{int(outcome.get('pass_to_pass_success', 0))}/{int(outcome.get('pass_to_pass_total', 0))}",
            ]
        )
    else:
        lines.append("- Official evaluation is not available for this frozen candidate.")

    lines.extend(["", "## Patch", "", "```diff", patch.rstrip() or "(empty patch)", "```"])
    if gpu_metrics:
        lines.extend(["", "## AMD GPU inference", ""])
        for key, label in GPU_METRIC_LABELS.items():
            if key in gpu_metrics:
                lines.append(f"- {label}: {metric_value(key, gpu_metrics[key])}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--harness", default="mini-original")
    parser.add_argument("--task-id")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--gpu-metrics", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live", action="store_true", help="run one live repair instead of reading a frozen run")
    parser.add_argument("--repo", type=Path, help="repository directory for --live")
    parser.add_argument("--issue", help="issue text for --live")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--context-variant", default="C0")
    parser.add_argument("--json-mode", default="J0")
    parser.add_argument("--controller-policy", default="A1")
    parser.add_argument("--verifier-mode", default="V1R1")
    args = parser.parse_args()

    if args.live:
        if not args.repo or not args.issue:
            parser.error("--live requires --repo and --issue")
        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            env_type="local",
            cwd=str(args.repo.resolve()),
            max_model_turns=12,
            max_tool_calls=30,
            max_wall_time_seconds=900,
            context_variant=args.context_variant,
            json_mode=args.json_mode,
            controller_policy=args.controller_policy,
            verifier_mode=args.verifier_mode,
        )
        raw = runner.run_task(args.issue)
        metadata = raw.get("metadata", {})
        result = {
            "harness": "mini-swe-live",
            "model": metadata.get("model", args.model or "unknown"),
            "model_turns": raw.get("api_calls", 0),
            "usage": metadata.get("api", {}).get("usage", {}),
            "wall_time_ms": metadata.get("wall_time_ms", 0),
            "trajectory_diagnostics": {
                "tool_calls": metadata.get("tool_calls", 0),
                "edit_tool_calls": sum(metadata.get("patch_apply_results", [])),
                "tests_after_edit": False,
                "tool_errors": metadata.get("tool_budget_rejections", 0),
                "integrity_eligible": True,
            },
        }
        rendered = render_dashboard(
            task={"instance_id": "live-demo", "repo": str(args.repo), "problem_statement": args.issue},
            result=result,
            outcome={},
            patch=str(metadata.get("final_patch", "")),
            gpu_metrics=read_gpu_metrics(),
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered)
        else:
            print(rendered, end="")
        return

    if not args.run_dir or not args.task_id:
        parser.error("frozen dashboard mode requires --run-dir and --task-id")

    rows = load_jsonl(args.run_dir / "results.jsonl")
    result = choose_result(rows, harness=args.harness, task_id=args.task_id, repeat=args.repeat)
    task = public_task(load_json(args.run_dir / "public-manifest.json"), args.task_id)
    summary_path = args.run_dir / "summary.json"
    summary = load_json(summary_path) if summary_path.exists() else {}
    outcome = official_outcome(summary, harness=args.harness, task_id=args.task_id, repeat=args.repeat)
    patch_path = Path(str(result.get("patch_path", "")))
    patch = patch_path.read_text() if patch_path.is_file() else ""
    gpu_metrics = load_json(args.gpu_metrics) if args.gpu_metrics else None
    rendered = render_dashboard(
        task=task,
        result=result,
        outcome=outcome,
        patch=patch,
        gpu_metrics=gpu_metrics,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
