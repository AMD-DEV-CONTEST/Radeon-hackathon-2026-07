"""
scripts/benchmark_runner.py — Determinex Universal Benchmark Dispatcher
======================================================================
Routes Determinex against every major AI coding / reasoning benchmark.

Usage:
    python scripts/benchmark_runner.py --list
    python scripts/benchmark_runner.py --bench swebench-lite --config d --cloak
    python scripts/benchmark_runner.py --bench swebench-verified --config d --cloak --parallel 4
    python scripts/benchmark_runner.py --bench swebench-full --config b
    python scripts/benchmark_runner.py --bench all-swebench --config d --cloak

Benchmark status legend:
    READY     — dataset available, harness wired, can run today
    PENDING   — dataset ID or access needs verification before first run
    ADAPTER   — needs a new adapter script (harness differs from SWE-bench)
    EXTERNAL  — requires separate eval service / leaderboard submission

Related scripts (pick the right one):
  benchmark_runner.py           — THIS FILE. Universal dispatcher for CI / overnight runs.
                                  Wraps SWE-bench, bigcode, and role-assignment benchmarks
                                  under one CLI. Use for cross-suite comparisons.
  determinex_benchmark.py          — Role assignment scoring only.
                                  Use after registering a new model to pick its role.
  determinex_benchmark_5run.py     — Statistical 5-run harness around determinex_benchmark.py.
                                  Use when you need mean ± std for publication tables.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
_LOGS = _ROOT / "logs" / "benchmarks"

logging.basicConfig(
    level=logging.INFO,
    format="[BENCH] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bench_runner")


# ---------------------------------------------------------------------------
# Benchmark registry
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkDef:
    id: str  # canonical slug used with --bench
    name: str  # human-readable name
    category: str  # "coding" | "agent" | "reasoning" | "multimodal"
    status: str  # READY | PENDING | ADAPTER | EXTERNAL
    instances: int  # dataset size (0 = unknown)
    description: str
    dataset_id: str = ""  # HuggingFace dataset ID (for READY/PENDING)
    split: str = "test"  # HF split name
    swebench_split: str = ""  # maps to determinex_swebench_run.py --split (lite/verified/full)
    adapter_script: str = ""  # future: path to non-SWE-bench adapter
    leaderboard_url: str = ""
    notes: str = ""

    @property
    def runnable(self) -> bool:
        return self.status == "READY"


BENCHMARKS: list[BenchmarkDef] = [
    # -----------------------------------------------------------------------
    # SWE-bench family — all route through determinex_swebench_run.py
    # -----------------------------------------------------------------------
    BenchmarkDef(
        id="swebench-lite",
        name="SWE-bench Lite",
        category="coding",
        status="READY",
        instances=300,
        description="300 Python GitHub issues from 11 repos. The canonical leaderboard for AI code repair.",
        dataset_id="princeton-nlp/SWE-bench_Lite",
        swebench_split="lite",
        leaderboard_url="https://www.swebench.com",
        notes="Primary ablation benchmark for Determinex. Config D (Claude+DeepSeek+Cloak) target: >12%.",
    ),
    BenchmarkDef(
        id="swebench-verified",
        name="SWE-bench Verified",
        category="coding",
        status="READY",
        instances=500,
        description="500 human-verified Python instances. Harder quality bar than Lite. Official leaderboard.",
        dataset_id="princeton-nlp/SWE-bench_Verified",
        swebench_split="verified",
        leaderboard_url="https://www.swebench.com",
        notes="Next benchmark after Lite ablation completes. Same harness, higher difficulty.",
    ),
    BenchmarkDef(
        id="swebench-full",
        name="SWE-bench Full",
        category="coding",
        status="READY",
        instances=2294,
        description="Full 2294-instance SWE-bench dataset across many repos.",
        dataset_id="princeton-nlp/SWE-bench",
        swebench_split="full",
        leaderboard_url="https://www.swebench.com",
        notes="Run after Verified. Requires ~8× more compute than Lite.",
    ),
    BenchmarkDef(
        id="swebench-pro",
        name="SWE-bench Pro",
        category="coding",
        status="PENDING",
        instances=0,
        description="Extended, harder SWE-bench variant with more complex multi-file issues.",
        dataset_id="princeton-nlp/SWE-bench_Pro",  # verify before first run
        swebench_split="lite",  # override if Pro has own split
        leaderboard_url="https://www.swebench.com",
        notes="Dataset ID unverified — run `python -c \"from datasets import load_dataset; load_dataset('princeton-nlp/SWE-bench_Pro')\"` to confirm before enabling.",
    ),
    BenchmarkDef(
        id="swebench-multilingual",
        name="SWE-bench Multilingual",
        category="coding",
        status="PENDING",
        instances=0,
        description="Multi-language SWE-bench: Python + JavaScript + TypeScript + Java + Go.",
        dataset_id="princeton-nlp/SWE-bench_Multilingual",  # verify before first run
        swebench_split="lite",
        leaderboard_url="https://www.swebench.com",
        notes="Determinex validators need JS/TS/Java/Go variants. Adapter extension required before running.",
    ),
    # -----------------------------------------------------------------------
    # Agent / coding — non-SWE-bench (need adapter scripts)
    # -----------------------------------------------------------------------
    BenchmarkDef(
        id="terminal-bench",
        name="Terminal-Bench 2.0",
        category="agent",
        status="ADAPTER",
        instances=0,
        description="CLI agent tasks: file manipulation, shell pipelines, cron, sysadmin tasks.",
        dataset_id="terminal-bench/terminal-bench",  # unverified
        adapter_script="scripts/adapters/terminal_bench_adapter.py",
        leaderboard_url="https://github.com/terminal-bench/terminal-bench",
        notes="Harness runs in Docker shell. Needs adapter that wraps DeterminexSWEAgent in a shell-task loop.",
    ),
    BenchmarkDef(
        id="nl2repo",
        name="NL2Repo",
        category="coding",
        status="ADAPTER",
        instances=0,
        description="Generate an entire repository from a natural language spec.",
        dataset_id="",
        adapter_script="scripts/adapters/nl2repo_adapter.py",
        leaderboard_url="",
        notes="Requires multi-file generation harness. Route through DeterminexHive DAG builder, not SWE-bench agent.",
    ),
    BenchmarkDef(
        id="skillsbench",
        name="SkillsBench",
        category="agent",
        status="ADAPTER",
        instances=0,
        description="Tool-use skill evaluation: web search, code execution, file I/O, calendar, API calls.",
        dataset_id="",
        adapter_script="scripts/adapters/skillsbench_adapter.py",
        leaderboard_url="",
        notes="Requires tool-call harness (MCP or custom). Agent must be wrapped with tool scaffolding.",
    ),
    BenchmarkDef(
        id="claw-eval",
        name="Claw-Eval",
        category="coding",
        status="ADAPTER",
        instances=0,
        description="Code generation eval with execution-verified outputs.",
        dataset_id="",
        adapter_script="scripts/adapters/claw_eval_adapter.py",
        leaderboard_url="",
        notes="Needs execution harness for generated code. Map to Determinex Compiler Oracle for verification.",
    ),
    BenchmarkDef(
        id="qwenclawbench",
        name="QwenClawBench",
        category="coding",
        status="ADAPTER",
        instances=0,
        description="Qwen-curated coding benchmark emphasizing algorithm implementation.",
        dataset_id="Qwen/QwenClawBench",  # unverified
        adapter_script="scripts/adapters/qwenclawbench_adapter.py",
        leaderboard_url="https://github.com/QwenLM",
        notes="Likely HuggingFace-hosted. Verify dataset ID and task format before adapting.",
    ),
    # -----------------------------------------------------------------------
    # Web / browser agent
    # -----------------------------------------------------------------------
    BenchmarkDef(
        id="qwenwebbench",
        name="QwenWebBench (Elo)",
        category="agent",
        status="EXTERNAL",
        instances=0,
        description="Elo-rated web browsing benchmark. Agents compete on live web tasks.",
        dataset_id="",
        adapter_script="",
        leaderboard_url="https://github.com/QwenLM",
        notes="Requires browser automation (Playwright/Puppeteer) and live Elo submission. No local harness today.",
    ),
    # -----------------------------------------------------------------------
    # Reasoning / multimodal (non-coding)
    # -----------------------------------------------------------------------
    BenchmarkDef(
        id="gpqa-diamond",
        name="GPQA Diamond",
        category="reasoning",
        status="ADAPTER",
        instances=198,
        description="Graduate-level PhD science multiple-choice. Diamond subset = hardest 198 questions.",
        dataset_id="Idavidrein/gpqa",
        adapter_script="scripts/adapters/gpqa_adapter.py",
        leaderboard_url="https://github.com/idavidrein/gpqa",
        notes="Multiple-choice QA — Determinex models are too small for this without RAG. Good Sentinel/Claude-Architect eval.",
    ),
    BenchmarkDef(
        id="mmmu",
        name="MMMU",
        category="multimodal",
        status="EXTERNAL",
        instances=11500,
        description="Massive Multitask Multimodal Understanding — images + text across 30 subjects.",
        dataset_id="MMMU/MMMU",
        adapter_script="",
        leaderboard_url="https://mmmu-benchmark.github.io",
        notes="Requires vision input. Determinex models are text-only — route to Claude/GPT-4V for this eval.",
    ),
    BenchmarkDef(
        id="realworldqa",
        name="RealWorldQA",
        category="reasoning",
        status="EXTERNAL",
        instances=765,
        description="Real-world visual understanding from xAI (Grok). Spatial reasoning from photos.",
        dataset_id="xai-org/RealWorldQA",
        adapter_script="",
        leaderboard_url="https://github.com/xai-org/RealWorldQA",
        notes="Vision benchmark. Cannot run with text-only Determinex models. Requires frontier vision API.",
    ),
]

# Index by ID for fast lookup
BENCH_BY_ID: dict[str, BenchmarkDef] = {b.id: b for b in BENCHMARKS}
# Groups for --bench all-swebench etc.
GROUPS: dict[str, list[str]] = {
    "all-swebench": ["swebench-lite", "swebench-verified", "swebench-full"],
    "all-ready": [b.id for b in BENCHMARKS if b.status == "READY"],
    "all-coding": [b.id for b in BENCHMARKS if b.category == "coding"],
    "all": [b.id for b in BENCHMARKS],
}


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

STATUS_ICON = {
    "READY": "✅",
    "PENDING": "⚠️ ",
    "ADAPTER": "🔧",
    "EXTERNAL": "🌐",
}

CATEGORY_ICON = {
    "coding": "🐍",
    "agent": "🤖",
    "reasoning": "🧠",
    "multimodal": "👁️ ",
}


def print_list() -> None:
    """Print all benchmarks in a formatted table."""
    cols = {
        "READY": [],
        "PENDING": [],
        "ADAPTER": [],
        "EXTERNAL": [],
    }
    for b in BENCHMARKS:
        cols[b.status].append(b)

    def section(label: str, items: list[BenchmarkDef]) -> None:
        if not items:
            return
        print(f"\n{STATUS_ICON[label]} {label}")
        print("─" * 72)
        for b in items:
            size = f"{b.instances:,}inst" if b.instances else "?inst"
            cat = CATEGORY_ICON.get(b.category, "  ")
            print(f"  {cat}  {b.id:<28} {size:<10}  {b.name}")
            if b.notes:
                for line in textwrap.wrap(b.notes, width=64):
                    print(f"             {line}")

    print("\n" + "=" * 72)
    print("  Determinex Benchmark Registry")
    print("=" * 72)
    section("READY", cols["READY"])
    section("PENDING", cols["PENDING"])
    section("ADAPTER", cols["ADAPTER"])
    section("EXTERNAL", cols["EXTERNAL"])
    print("\n" + "─" * 72)
    print("  Groups: " + "  ".join(f"--bench {g}" for g in GROUPS))
    print("─" * 72)
    print()


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------


def _build_configs(args: argparse.Namespace) -> list[str]:
    """Expand --config a,b,d into list of config slugs."""
    if not args.config:
        return ["d"]
    configs = []
    for raw in args.config.split(","):
        raw = raw.strip().lower()
        if raw == "b":
            configs.append("b")
        elif raw == "d":
            configs.append("d")
        else:
            log.warning("Unknown config '%s' — skipping", raw)
    return configs or ["d"]


def run_swebench(bench: BenchmarkDef, args: argparse.Namespace) -> int:
    """Launch determinex_swebench_run.py for a SWE-bench variant."""
    configs = _build_configs(args)
    results: list[int] = []

    for config in configs:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        cmd = [
            sys.executable,
            str(_SCRIPTS / "determinex_swebench_run.py"),
            "--config",
            config,
            "--split",
            bench.swebench_split,
        ]
        if args.cloak:
            cmd.append("--cloak")
        if args.parallel:
            cmd += ["--parallel", str(args.parallel)]
        if args.instances:
            cmd += ["--instances", str(args.instances)]
        elif args.all:
            cmd.append("--all")
        if args.repos_dir:
            cmd += ["--repos-dir", args.repos_dir]
        if args.instance_ids:
            cmd += ["--instance-ids"] + args.instance_ids

        log.info("Launching: %s", " ".join(cmd))
        ret = subprocess.run(cmd, cwd=str(_ROOT)).returncode
        results.append(ret)
        if ret != 0:
            log.error("Run failed (config=%s, bench=%s, exit=%d)", config, bench.id, ret)

    return max(results) if results else 1


def run_benchmark(bench: BenchmarkDef, args: argparse.Namespace) -> int:
    if not bench.runnable:
        log.error(
            "Benchmark '%s' is not yet runnable (status=%s). %s",
            bench.id,
            bench.status,
            bench.notes,
        )
        return 1

    if bench.swebench_split:
        return run_swebench(bench, args)

    # Future: dispatch to adapter scripts
    if bench.adapter_script:
        adapter = _ROOT / bench.adapter_script
        if adapter.exists():
            log.info("Dispatching to adapter: %s", adapter)
            cmd = [sys.executable, str(adapter), "--bench", bench.id]
            return subprocess.run(cmd, cwd=str(_ROOT)).returncode
        else:
            log.error("Adapter script not yet created: %s", adapter)
            return 1

    log.error("No runner available for %s", bench.id)
    return 1


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------


def run_status(bench: BenchmarkDef, args: argparse.Namespace) -> None:
    """Show the latest run results for a benchmark."""
    swebench_logs = _ROOT / "logs" / "swebench"
    if not swebench_logs.exists():
        log.info("No logs found at %s", swebench_logs)
        return

    prefix = bench.id.replace("swebench-", "").upper()
    runs = sorted(
        [d for d in swebench_logs.iterdir() if d.is_dir() and prefix in d.name.upper()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        log.info("No runs found for %s", bench.id)
        return

    latest = runs[0]
    pred_path = latest / "predictions.jsonl"
    result_path = latest / "results.json"

    pred_count = 0
    if pred_path.exists():
        with pred_path.open(encoding="utf-8") as f:
            pred_count = sum(1 for line in f if line.strip())

    print(f"\n{'─' * 60}")
    print(f"  Latest run: {latest.name}")
    print(f"  Predictions: {pred_count}")
    if result_path.exists():
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            print(f"  Results: {json.dumps(data, indent=2)}")
        except Exception:
            pass
    print(f"{'─' * 60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="benchmark_runner.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List all benchmarks and their status, then exit.",
    )
    p.add_argument(
        "--bench",
        metavar="BENCH_ID",
        help="Benchmark(s) to run. Single ID, comma-separated, or a group name (all-swebench, all-ready, all).",
    )
    p.add_argument(
        "--status",
        metavar="BENCH_ID",
        help="Show latest run status for a benchmark.",
    )
    p.add_argument(
        "--config",
        metavar="a,b,d",
        help="Determinex config(s) to evaluate: b=DeepSeek both, d=Claude+DeepSeek. Default: d.",
    )
    p.add_argument("--cloak", action="store_true", help="Enable Project Cloak (AST obfuscation).")
    p.add_argument(
        "--parallel", type=int, default=4, metavar="N", help="Parallel workers. Default: 4."
    )
    p.add_argument("--instances", type=int, metavar="N", help="Limit to first N instances.")
    p.add_argument("--all", action="store_true", help="Run all instances in the split.")
    p.add_argument(
        "--repos-dir",
        metavar="PATH",
        default="T:/determinex-swebench",
        help="Pre-cloned repos directory. Default: T:/determinex-swebench.",
    )
    p.add_argument(
        "--instance-ids", nargs="+", metavar="ID", help="Run specific instance IDs only."
    )
    return p


def resolve_bench_ids(raw: str) -> list[str]:
    """Expand group names and comma-separated IDs."""
    if raw in GROUPS:
        return GROUPS[raw]
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    unknown = [i for i in ids if i not in BENCH_BY_ID]
    if unknown:
        log.error("Unknown benchmark IDs: %s", ", ".join(unknown))
        log.info("Available IDs: %s", ", ".join(BENCH_BY_ID))
        sys.exit(1)
    return ids


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        print_list()
        return 0

    if args.status:
        ids = resolve_bench_ids(args.status)
        for bid in ids:
            run_status(BENCH_BY_ID[bid], args)
        return 0

    if not args.bench:
        parser.print_help()
        return 0

    bench_ids = resolve_bench_ids(args.bench)
    exit_codes: list[int] = []

    for bid in bench_ids:
        bench = BENCH_BY_ID[bid]
        log.info("=" * 60)
        log.info("Running: %s (%s instances)", bench.name, bench.instances or "?")
        log.info("Status: %s | Category: %s", bench.status, bench.category)
        log.info("=" * 60)
        code = run_benchmark(bench, args)
        exit_codes.append(code)
        if code != 0:
            log.error("FAILED: %s (exit %d)", bid, code)
        else:
            log.info("COMPLETE: %s", bid)

    failed = [bench_ids[i] for i, c in enumerate(exit_codes) if c != 0]
    if failed:
        log.error("Failed benchmarks: %s", ", ".join(failed))
        return 1

    log.info("All benchmarks completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
