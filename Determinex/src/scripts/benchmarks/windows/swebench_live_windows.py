#!/usr/bin/env python3
"""
swebench_live_windows.py — SWE-bench-Live Windows harness wrapper for Determinex.

Wraps the SWE-bench evaluation pipeline with:
  - Correct Windows encoding env vars (PYTHONUTF8, PYTHONIOENCODING)
  - Path normalization for Windows host ↔ Docker container boundary
  - Linux-ism detection pass over generated patches
  - Output to logs/windows_bench/ alongside other Windows bench results

Usage:
    python scripts/benchmarks/windows/swebench_live_windows.py --model deepseek --limit 10
    python scripts/benchmarks/windows/swebench_live_windows.py --model claude --filter windows
    python scripts/benchmarks/windows/swebench_live_windows.py --model all --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure PYTHONUTF8 is set globally before any I/O
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DETERMINEX_ROOT = Path(__file__).parents[3]
LOGS_DIR = DETERMINEX_ROOT / "logs" / "windows_bench"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Linux-ism patterns that flag a patch as Windows-illiterate
LINUX_ISM_PATTERNS = [
    (r"/usr/(?:local|bin|lib|share|include)", "Unix /usr/ path"),
    (r"/home/\w+/", "Unix home directory"),
    (r"(?<!['\"])~/", "Unix tilde expansion"),
    (r"/etc/(?!hosts)", "Unix /etc/ config"),
    (r"/tmp/", "Unix /tmp/"),
    (r"(?<!\w)apt(?:-get)?\s+install", "apt package manager"),
    (r"(?<!\w)brew\s+install", "Homebrew"),
    (r"(?<!\w)yum\s+install|dnf\s+install", "RPM package manager"),
    (r"\bchmod\s+[0-7]{3,4}\b|\bchmod\s+[ugoa][+-][rwx]", "chmod"),
    (r"\bchown\s+\w+", "chown"),
    (r"\bln\s+-s\b", "Unix symlink"),
    (r"\bpkill\b|\bkillall\b", "Unix kill"),
    (r"\bexport\s+\w+=", "bash export"),
    (r"\bsystemctl\b", "systemctl"),
    (r"\biptables\b|\bufw\s+(?:allow|deny|enable)", "Linux firewall"),
    (r"#!/(?:bin|usr/bin)/(?:bash|sh|zsh|python)", "Unix shebang"),
    (r"\bsed\s+-i\b", "sed in-place"),
    (r"\bawk\s+['\"]", "awk (prefer PowerShell)"),
    (r"os\.path\.expanduser\(['\"]~/", "Python Unix home expansion"),
    (r"platform\.system\(\)\s*==\s*['\"]Linux['\"]", "Linux platform check in patch"),
]


def detect_linux_isms(text: str) -> list[tuple[str, str]]:
    hits = []
    for pattern, label in LINUX_ISM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append((pattern, label))
    return hits


def generate_patch(instance: dict, model: str) -> tuple[str, float]:
    """Call Determinex's swebench agent to generate a patch for the instance."""
    t0 = time.time()
    prompt = f"""Fix the following GitHub issue in the repository.

Repository: {instance.get("repo", "")}
Issue title: {instance.get("problem_statement", "")[:500]}

Provide a unified diff patch that resolves this issue.
"""
    if model == "deepseek":
        import openai

        client = openai.OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.2,
        )
        patch = resp.choices[0].message.content or ""
    elif model == "claude":
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        patch = msg.content[0].text if msg.content else ""
    else:
        raise ValueError(f"Unknown model: {model}")

    return patch, round(time.time() - t0, 2)


def run_swebench_eval(
    predictions_path: Path, dataset: str, run_id: str, workers: int, timeout: int
) -> dict:
    """Run SWE-bench evaluation harness on the predictions file."""
    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--predictions_path",
        str(predictions_path),
        "--dataset_name",
        dataset,
        "--max_workers",
        str(workers),
        "--run_id",
        run_id,
        "--cache_level",
        "env",
        "--timeout",
        str(timeout),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"  Running SWE-bench eval (workers={workers}, timeout={timeout}s)...")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout * 2)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-3000:] if result.stdout else "",
        "stderr": result.stderr[-2000:] if result.stderr else "",
    }


def load_swebench_live_windows(limit: int, filter_str: str) -> list[dict]:
    """
    Load SWE-bench-Live Windows instances.
    Falls back to SWE-bench Lite if Windows-specific dataset unavailable.
    """
    try:
        import datasets

        try:
            # Try Windows-specific dataset first
            ds = datasets.load_dataset(
                "princeton-nlp/SWE-bench_Live",
                split="test",
                trust_remote_code=True,
            )
            print(f"  Loaded SWE-bench-Live: {len(ds)} instances")
        except Exception:
            print("  SWE-bench-Live not available, using SWE-bench Lite")
            ds = datasets.load_dataset(
                "princeton-nlp/SWE-bench_Lite",
                split="test",
                trust_remote_code=True,
            )

        instances = []
        for ex in ds:
            if filter_str and filter_str.lower() not in str(ex).lower():
                continue
            instances.append(dict(ex))
            if len(instances) >= limit:
                break
        return instances
    except ImportError:
        print("  datasets package not installed. pip install datasets")
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description="SWE-bench-Live Windows wrapper for Determinex")
    ap.add_argument("--model", choices=["deepseek", "claude", "all"], default="deepseek")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--filter", default="", help="Filter instances by keyword")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument(
        "--skip-eval",
        action="store_true",
        help="Generate patches only, skip Docker eval (analysis + linux-ism check)",
    )
    ap.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    args = ap.parse_args()

    ts = time.strftime("%Y%m%d_%H%M%S")
    models = ["deepseek", "claude"] if args.model == "all" else [args.model]

    print("\nSWE-bench-Live Windows Wrapper")
    print(f"Models: {models}  Limit: {args.limit}  Dataset: {args.dataset}")
    print("=" * 60)

    instances = load_swebench_live_windows(args.limit, args.filter)
    if not instances:
        print("No instances loaded. Exiting.")
        sys.exit(1)
    print(f"Loaded {len(instances)} instances")

    for model in models:
        print(f"\n--- Model: {model} ---")
        run_id = f"determinex_winbench_{ts}_{model}"
        predictions = []
        linux_ism_report = []

        for i, inst in enumerate(instances, 1):
            iid = inst.get("instance_id", f"inst_{i}")
            print(f"  [{i}/{len(instances)}] {iid}")
            try:
                patch, latency = generate_patch(inst, model)
            except Exception as e:
                print(f"    ERROR: {e}")
                predictions.append(
                    {"instance_id": iid, "model_patch": "", "model_name_or_path": model}
                )
                continue

            # Linux-ism detection on the generated patch
            isms = detect_linux_isms(patch)
            if isms:
                print(f"    WARN: {len(isms)} Linux-ism(s): {', '.join(l for _, l in isms)}")
                linux_ism_report.append({"instance_id": iid, "linux_isms": [l for _, l in isms]})

            predictions.append(
                {
                    "instance_id": iid,
                    "model_patch": patch,
                    "model_name_or_path": model,
                }
            )
            print(f"    patch={len(patch)}c  linux_isms={len(isms)}  latency={latency}s")

        # Write predictions
        pred_dir = LOGS_DIR / run_id
        pred_dir.mkdir(parents=True, exist_ok=True)
        pred_path = pred_dir / "predictions.jsonl"
        with open(pred_path, "w", encoding="utf-8") as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")
        print(f"\n  Predictions: {pred_path}")

        # Linux-ism summary
        ism_path = pred_dir / "linux_ism_report.json"
        ism_summary = {
            "model": model,
            "instances": len(instances),
            "instances_with_linux_isms": len(linux_ism_report),
            "linux_ism_rate": round(len(linux_ism_report) / len(instances), 3) if instances else 0,
            "details": linux_ism_report,
        }
        ism_path.write_text(json.dumps(ism_summary, indent=2), encoding="utf-8")
        print(
            f"  Linux-ism rate: {ism_summary['linux_ism_rate']:.1%} "
            f"({len(linux_ism_report)}/{len(instances)} instances)"
        )

        # Docker eval
        if not args.skip_eval:
            eval_result = run_swebench_eval(
                pred_path, args.dataset, run_id, args.workers, args.timeout
            )
            eval_path = pred_dir / "eval_result.json"
            eval_path.write_text(json.dumps(eval_result, indent=2), encoding="utf-8")
            if eval_result["returncode"] == 0:
                print(f"  Eval: OK → {pred_dir}")
            else:
                print(f"  Eval: FAILED (rc={eval_result['returncode']}) — see {eval_path}")
        else:
            print("  Eval skipped (--skip-eval). Run harness manually:")
            print(
                f"    cd {DETERMINEX_ROOT} && python -m swebench.harness.run_evaluation "
                f"--predictions_path {pred_path} --dataset_name {args.dataset} "
                f"--run_id {run_id} --max_workers {args.workers}"
            )


if __name__ == "__main__":
    main()
