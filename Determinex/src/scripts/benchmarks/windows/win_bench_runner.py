#!/usr/bin/env python3
"""
win_bench_runner.py — Determinex Windows Literacy Benchmark

Tests AI models (local GGUF, Claude, GPT, DeepSeek) on Windows-specific tasks.
Scores each response for Windows-correctness using the rubric in windows_literacy_tasks.py.
Outputs results to logs/windows_bench/TIMESTAMP_MODEL.json.

Usage:
    python scripts/benchmarks/windows/win_bench_runner.py --model deepseek
    python scripts/benchmarks/windows/win_bench_runner.py --model claude
    python scripts/benchmarks/windows/win_bench_runner.py --model all
    python scripts/benchmarks/windows/win_bench_runner.py --model local --local-model qwen2.5-coder:14b-instruct-q4_K_M
    python scripts/benchmarks/windows/win_bench_runner.py --model deepseek --category path
    python scripts/benchmarks/windows/win_bench_runner.py --model deepseek --extract-golden

Phase 1: Full eval → logs/windows_bench/<ts>_<model>.json
Phase 2: --extract-golden → derives the minimal golden test set from accumulated results
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Load .env from project root so API keys work when run as background subprocess
_env_file = Path(__file__).parents[3] / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# Add determinex scripts to path
sys.path.insert(0, str(Path(__file__).parents[2]))

try:
    from windows_literacy_tasks import TASK_BY_ID, TASKS
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from windows_literacy_tasks import TASK_BY_ID, TASKS

LOGS_DIR = Path(__file__).parents[3] / "logs" / "windows_bench"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """\
You are an expert Windows systems developer. You write PowerShell and Windows-native code.
Rules you follow absolutely:
- Always use Windows path conventions (backslash, drive letters, $env: variables)
- Never suggest Linux/Mac tools (apt, brew, chmod, ln -s, /usr/local, /tmp, ~/.config)
- Use Join-Path for path construction
- Use $env:APPDATA, $env:TEMP, $env:USERPROFILE — never ~/
- Use winget, choco, or scoop for package management — never apt/yum/brew
- Use Get-Process, Stop-Process — never kill/pkill
- Use icacls or Set-Acl — never chmod/chown
- Use the Windows Registry provider (HKLM:, HKCU:) — never /etc/
- Use .NET APIs when PowerShell cmdlets don't exist
Respond with working PowerShell code only. No markdown fences unless asked.\
"""


# ── Generation backends ────────────────────────────────────────────────────


def _gen_deepseek(prompt: str, system: str) -> str:
    import openai

    client = openai.OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def _gen_claude(prompt: str, system: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text if msg.content else ""


def _gen_gpt(prompt: str, system: str) -> str:
    import openai

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def _gen_local(prompt: str, system: str, model_tag: str) -> str:
    import requests

    payload = {
        "model": model_tag,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": False,
    }
    r = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def generate(prompt: str, model: str, local_model: str = "") -> tuple[str, float]:
    t0 = time.time()
    if model == "deepseek":
        out = _gen_deepseek(prompt, SYSTEM_PROMPT)
    elif model == "claude":
        out = _gen_claude(prompt, SYSTEM_PROMPT)
    elif model == "gpt":
        out = _gen_gpt(prompt, SYSTEM_PROMPT)
    elif model == "local":
        out = _gen_local(prompt, SYSTEM_PROMPT, local_model)
    else:
        raise ValueError(f"Unknown model: {model}")
    return out, round(time.time() - t0, 2)


# ── Scoring ───────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    pattern: str
    required: bool
    description: str
    matched: bool
    passed: bool  # required=True→matched must be True; required=False→matched must be False


@dataclass
class TaskResult:
    task_id: str
    category: str
    weight: int
    model: str
    prompt: str
    response: str
    latency_s: float
    checks: list[CheckResult] = field(default_factory=list)
    score: float = 0.0  # 0.0–1.0
    weighted_score: float = 0.0
    linux_ism_count: int = 0  # times a MUST NOT pattern matched (key metric)
    error: str = ""


LINUX_ISMS = [
    (r"/usr/(?:local|bin|lib|share)", "Unix /usr/ path"),
    (r"/home/\w+", "Unix home path"),
    (r"~/\.", "Unix dotfile path"),
    (r"/etc/\w+", "Unix /etc/ config"),
    (r"/tmp/", "Unix /tmp/ path"),
    (r"apt(?:-get)?\s+install", "apt package manager"),
    (r"yum\s+install", "yum package manager"),
    (r"brew\s+install", "Homebrew"),
    (r"dnf\s+install", "dnf package manager"),
    (r"\bchmod\b", "chmod"),
    (r"\bchown\b", "chown"),
    (r"\bln\s+-s\b", "ln -s symlink"),
    (r"\bpkill\b|\bkillall\b", "Unix kill commands"),
    (r"export\s+\w+=", "bash export"),
    (r"\bsystemctl\b", "systemctl"),
    (r"\bservice\s+\w+\s+(?:start|stop|restart)\b", "sysvinit service"),
    (r"\biptables\b|\bufw\s+\b", "Linux firewall"),
    (r"\bsed\s+-i\b", "sed -i in-place"),
    (r"\bgrep\s+-r\b", "grep -r (prefer Select-String)"),
    (r"inotifywait|fswatch\b", "Linux file watchers"),
    (r"#!/bin/bash|#!/usr/bin/env\s+bash", "bash shebang"),
]


def score_response(task: dict, response: str) -> TaskResult:
    checks = []
    for pattern, required, description in task["rubric"]:
        matched = bool(re.search(pattern, response, re.IGNORECASE))
        passed = matched if required else not matched
        checks.append(
            CheckResult(
                pattern=pattern,
                required=required,
                description=description,
                matched=matched,
                passed=passed,
            )
        )

    passed_checks = sum(1 for c in checks if c.passed)
    score = passed_checks / len(checks) if checks else 0.0

    linux_count = sum(1 for pat, _ in LINUX_ISMS if re.search(pat, response, re.IGNORECASE))

    return TaskResult(
        task_id=task["id"],
        category=task["category"],
        weight=task["weight"],
        model="",  # filled by caller
        prompt=task["prompt"],
        response=response,
        latency_s=0.0,
        checks=checks,
        score=score,
        weighted_score=score * task["weight"],
        linux_ism_count=linux_count,
    )


# ── Golden test extraction ─────────────────────────────────────────────────


def extract_golden(logs_dir: Path) -> dict:
    """
    Phase 2: Read all accumulated benchmark result files and extract the minimal
    golden test set — the tasks where at least one model failed AND where failure
    pattern is consistent (not model-specific noise).

    Golden test = catches real Windows-illiteracy, not just one bad generation.
    """
    all_results: dict[str, list[TaskResult]] = {}  # task_id → results across models/runs

    for f in logs_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for r in data.get("results", []):
                tid = r["task_id"]
                if tid not in all_results:
                    all_results[tid] = []
                all_results[tid].append(r)
        except Exception:
            continue

    golden = []
    for tid, results in all_results.items():
        if len(results) < 2:
            continue  # need multiple data points
        fail_rate = sum(1 for r in results if r["score"] < 1.0) / len(results)
        linux_rate = sum(1 for r in results if r["linux_ism_count"] > 0) / len(results)
        task = TASK_BY_ID.get(tid, {})
        if fail_rate >= 0.5 or linux_rate >= 0.3:
            golden.append(
                {
                    "task_id": tid,
                    "category": task.get("category", ""),
                    "weight": task.get("weight", 1),
                    "fail_rate": round(fail_rate, 2),
                    "linux_ism_rate": round(linux_rate, 2),
                    "models_tested": len(results),
                    "prompt": task.get("prompt", ""),
                }
            )

    golden.sort(key=lambda x: (-x["weight"], -x["fail_rate"]))
    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "golden_count": len(golden),
        "tasks": golden,
    }
    golden_path = logs_dir / "golden_test_set.json"
    golden_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Golden test set: {len(golden)} tasks -> {golden_path}")
    return out


# ── Main ───────────────────────────────────────────────────────────────────


def run_bench(model: str, local_model: str, category: str | None, verbose: bool) -> None:
    tasks = TASKS if not category else [t for t in TASKS if t["category"] == category]
    if not tasks:
        print(f"No tasks for category: {category}")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    model_label = model if model != "local" else f"local_{local_model.split(':')[0]}"
    out_path = LOGS_DIR / f"{ts}_{model_label}.json"

    print("\nDeterminex Windows Literacy Benchmark")
    print(f"Model: {model_label}  Tasks: {len(tasks)}")
    print("=" * 60)

    results = []
    total_score = 0.0
    total_weight = 0
    total_linux_isms = 0

    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task['id']} ({task['category']}, weight={task['weight']})")
        try:
            response, latency = generate(task["prompt"], model, local_model)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append(
                {
                    "task_id": task["id"],
                    "error": str(e),
                    "score": 0.0,
                    "weighted_score": 0.0,
                    "linux_ism_count": 0,
                    "checks": [],
                }
            )
            continue

        tr = score_response(task, response)
        tr.model = model_label
        tr.latency_s = latency

        total_score += tr.weighted_score
        total_weight += task["weight"]
        total_linux_isms += tr.linux_ism_count

        status = "PASS" if tr.score == 1.0 else ("WARN" if tr.score >= 0.6 else "FAIL")
        linux_flag = f" [{tr.linux_ism_count} linux-isms]" if tr.linux_ism_count else ""
        print(f"  [{status}] score={tr.score:.0%}{linux_flag}  ({latency:.1f}s)")

        if verbose or tr.score < 1.0:
            for c in tr.checks:
                mark = "OK" if c.passed else "XX"
                req = "MUST" if c.required else "MUST NOT"
                print(f"    [{mark}] {req}: {c.description}")

        results.append(asdict(tr))

    weighted_pct = (total_score / total_weight * 100) if total_weight else 0
    windows_illiteracy = total_linux_isms

    summary = {
        "model": model_label,
        "timestamp": ts,
        "tasks_run": len(results),
        "weighted_score_pct": round(weighted_pct, 1),
        "total_linux_isms": windows_illiteracy,
        "linux_ism_rate": round(windows_illiteracy / len(results), 2) if results else 0,
        "pass_count": sum(1 for r in results if r.get("score", 0) == 1.0),
        "fail_count": sum(1 for r in results if r.get("score", 0) < 0.6),
        "results": results,
    }

    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"RESULTS — {model_label}")
    print(f"  Windows Literacy Score: {weighted_pct:.1f}%")
    print(f"  Linux-ism injections:   {windows_illiteracy} ({summary['linux_ism_rate']:.1f}/task)")
    print(f"  Pass: {summary['pass_count']}  Fail: {summary['fail_count']}  Total: {len(results)}")
    print(f"  Results: {out_path}")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Determinex Windows Literacy Benchmark")
    ap.add_argument(
        "--model", choices=["deepseek", "claude", "gpt", "local", "all"], default="deepseek"
    )
    ap.add_argument("--local-model", default="qwen2.5-coder:14b-instruct-q4_K_M")
    ap.add_argument(
        "--category",
        choices=["path", "envvar", "process", "registry", "tools", "syntax", "filesystem"],
    )
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--extract-golden",
        action="store_true",
        help="Phase 2: derive golden test set from accumulated results",
    )
    args = ap.parse_args()

    if args.extract_golden:
        extract_golden(LOGS_DIR)
        return

    models = ["deepseek", "claude", "gpt", "local"] if args.model == "all" else [args.model]
    for m in models:
        run_bench(m, args.local_model, args.category, args.verbose)


if __name__ == "__main__":
    main()
