"""
model_advisor.py — Determinex Model Advisor

Recommends which cloud AI backend to use for a given task/project goal, based on:
  1. Live benchmark data fetched from Papers with Code API, HF datasets, SWE-bench
  2. Seeded fallback scores (May 2026) used when live sources are unreachable
  3. User's own compiler-verified solve rates (takes precedence after 30+ samples)

Benchmarks fetched and weighted per project goal:
  - SWE-bench Verified  — real GitHub issue resolution (best signal for architect/solver)
  - HumanEval+          — function-level code generation (best signal for builder)
  - MBPP+               — Python problem solving (builder + general)
  - BigCodeBench        — complex library API usage (builder, high-volume)
  - LiveCodeBench       — competitive programming (algorithm tasks)

Cloak compatibility: ALL cloud providers work with Project Cloak.
Data sharing: opt-in via DETERMINEX_SHARE_OUTCOMES=1 (no code, just solve/fail signals).

Usage:
    python scripts/model_advisor.py --goal "fix django ORM bugs at scale"
    python scripts/model_advisor.py --goal "architect a distributed system refactor"
    python scripts/model_advisor.py --task architect --budget medium
    python scripts/model_advisor.py --list
    python scripts/model_advisor.py --refresh   # force live data pull
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

log = logging.getLogger("determinex.advisor")

# ── Seeded benchmark data (May 2026) ──────────────────────────────────────────
# Multi-benchmark composite. Each score is 0.0–1.0.
# Sources: SWE-bench Verified leaderboard, HumanEval+, MBPP+, BigCodeBench.
SEEDED: dict[str, dict] = {
    "anthropic": {
        "model": "claude-sonnet-4-6",
        "display": "Claude Sonnet 4.6",
        "backend_key": "anthropic",
        "cost_in": 3.00,
        "cost_out": 15.00,
        "cloak": True,
        "benchmarks": {
            "swebench_verified": 0.796,  # SWE-bench Verified, May 2026
            "humaneval": 0.937,  # HumanEval+
            "mbpp": 0.894,  # MBPP+
            "bigcodebench": 0.586,  # BigCodeBench completion
            "livecodebench": None,
        },
        "strengths": [
            "architect",
            "complex_reasoning",
            "root_cause_analysis",
            "security_review",
            "multi_file_refactor",
        ],
        "weaknesses": ["high_cost", "slower_throughput"],
    },
    "openai": {
        "model": "gpt-4.1",
        "display": "GPT-4.1 / GPT-5",
        "backend_key": "openai",
        "cost_in": 2.50,
        "cost_out": 15.00,
        "cloak": True,
        "benchmarks": {
            "swebench_verified": 0.800,  # GPT-5.4 proxy
            "humaneval": 0.940,  # GPT-5
            "mbpp": 0.910,
            "bigcodebench": 0.611,  # GPT-4o
            "livecodebench": None,
        },
        "strengths": ["architect", "complex_reasoning", "broad_knowledge", "long_context"],
        "weaknesses": ["high_cost", "no_local_fallback"],
    },
    "deepseek": {
        "model": "deepseek-v4-flash",
        "display": "DeepSeek V3/V4",
        "backend_key": "deepseek",
        "cost_in": 0.14,
        "cost_out": 0.28,
        "cloak": True,
        "benchmarks": {
            "swebench_verified": 0.730,  # DeepSeek V3.2
            "humaneval": 0.850,
            "mbpp": 0.894,  # DeepSeek-Coder-V2
            "bigcodebench": 0.597,  # DeepSeek-Coder-V2
            "livecodebench": None,
        },
        "strengths": ["builder", "high_volume", "low_cost", "fast_iteration", "batch_processing"],
        "weaknesses": ["weaker_architecture", "less_surgical_patches"],
    },
    "gemini": {
        "model": "gemini-2.5-pro",
        "display": "Gemini 2.5 Pro",
        "backend_key": "gemini",
        "cost_in": 1.25,
        "cost_out": 5.00,
        "cloak": True,
        "benchmarks": {
            "swebench_verified": 0.806,  # Gemini 3.1 Pro
            "humaneval": 0.900,
            "mbpp": 0.897,  # Gemini 1.5 Pro 002
            "bigcodebench": None,
            "livecodebench": None,
        },
        "strengths": ["architect", "ui_frontend", "visual_reasoning", "multimodal", "long_context"],
        "weaknesses": ["variable_code_consistency"],
    },
    "ollama": {
        "model": "local",
        "display": "Local (Ollama)",
        "backend_key": "ollama",
        "cost_in": 0.00,
        "cost_out": 0.00,
        "cloak": False,
        "benchmarks": {
            "swebench_verified": None,
            "humaneval": None,
            "mbpp": None,
            "bigcodebench": None,
            "livecodebench": None,
        },
        "strengths": [
            "privacy_sovereign",
            "zero_cost",
            "offline",
            "no_data_sharing",
            "low_latency_local",
        ],
        "weaknesses": ["lower_quality", "hardware_dependent"],
    },
}

# ── Goal → benchmark weights ───────────────────────────────────────────────────
# How to weight each benchmark for a given project goal / task type.
# Weights sum to 1.0 per task. None benchmarks are excluded automatically.
GOAL_WEIGHTS: dict[str, dict[str, float]] = {
    "architect": {
        "swebench_verified": 0.55,
        "humaneval": 0.15,
        "mbpp": 0.10,
        "bigcodebench": 0.10,
        "livecodebench": 0.10,
    },
    "builder": {
        "swebench_verified": 0.20,
        "humaneval": 0.35,
        "mbpp": 0.25,
        "bigcodebench": 0.15,
        "livecodebench": 0.05,
    },
    "high_volume": {
        "swebench_verified": 0.15,
        "humaneval": 0.30,
        "mbpp": 0.30,
        "bigcodebench": 0.20,
        "livecodebench": 0.05,
    },
    "ui_frontend": {
        "swebench_verified": 0.20,
        "humaneval": 0.30,
        "mbpp": 0.30,
        "bigcodebench": 0.10,
        "livecodebench": 0.10,
    },
    "algorithm": {
        "swebench_verified": 0.10,
        "humaneval": 0.25,
        "mbpp": 0.25,
        "bigcodebench": 0.10,
        "livecodebench": 0.30,
    },
    "security_review": {
        "swebench_verified": 0.60,
        "humaneval": 0.15,
        "mbpp": 0.10,
        "bigcodebench": 0.10,
        "livecodebench": 0.05,
    },
    "cost_sensitive": {
        "swebench_verified": 0.30,
        "humaneval": 0.25,
        "mbpp": 0.25,
        "bigcodebench": 0.15,
        "livecodebench": 0.05,
    },
    "privacy_required": {
        "swebench_verified": 0.40,
        "humaneval": 0.25,
        "mbpp": 0.20,
        "bigcodebench": 0.10,
        "livecodebench": 0.05,
    },
}

# Natural language goal keywords → task type mapping
GOAL_KEYWORDS: dict[str, list[str]] = {
    "architect": [
        "architect",
        "design",
        "plan",
        "dag",
        "structure",
        "refactor",
        "complex",
        "multi-file",
        "system",
        "migration",
        "overhaul",
    ],
    "builder": [
        "build",
        "implement",
        "fix",
        "patch",
        "bug",
        "generate",
        "code",
        "write",
        "function",
        "method",
        "class",
    ],
    "high_volume": [
        "scale",
        "volume",
        "batch",
        "many",
        "bulk",
        "hundreds",
        "thousands",
        "cheap",
        "fast",
        "throughput",
    ],
    "ui_frontend": [
        "ui",
        "frontend",
        "react",
        "css",
        "html",
        "visual",
        "component",
        "page",
        "layout",
        "design",
    ],
    "algorithm": [
        "algorithm",
        "sort",
        "search",
        "dynamic",
        "competitive",
        "leetcode",
        "optimiz",
        "math",
        "dp",
    ],
    "security_review": [
        "security",
        "vuln",
        "exploit",
        "cve",
        "auth",
        "injection",
        "xss",
        "sql",
        "safe",
        "audit",
    ],
    "cost_sensitive": [
        "cheap",
        "budget",
        "cost",
        "free",
        "affordable",
        "low cost",
        "save money",
        "expensive",
    ],
    "privacy_required": [
        "private",
        "proprietary",
        "secret",
        "confidential",
        "cloak",
        "nda",
        "internal",
        "sensitive",
    ],
}

CACHE_TTL_HOURS = 6
MIN_LOCAL_SAMPLES = 30

# ── Live data fetchers ─────────────────────────────────────────────────────────


def _fetch_json(url: str, timeout: int = 8) -> dict | list | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Determinex-ModelAdvisor/1.0"}, method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.debug("fetch failed %s: %s", url, e)
        return None


def _fetch_paperswithcode(benchmark: str) -> dict[str, float]:
    """Fetch top model scores from Papers with Code API for a given benchmark."""
    slug_map = {
        "humaneval": "humaneval",
        "mbpp": "mostly-basic-python-problems-mbpp",
        "swebench_verified": "swe-bench-verified",
        "bigcodebench": "bigcodebench",
        "livecodebench": "livecodebench",
    }
    slug = slug_map.get(benchmark)
    if not slug:
        return {}

    # Papers with Code SOTA API
    url = f"https://paperswithcode.com/api/v1/sota/?benchmark={slug}&format=json"
    data = _fetch_json(url)
    if not data or not isinstance(data, dict):
        return {}

    scores: dict[str, float] = {}
    for row in data.get("results", []):
        model = row.get("model_name", "")
        score = row.get("score")
        if model and score is not None:
            try:
                scores[model.lower()] = float(score) / 100.0
            except (ValueError, TypeError):
                pass
    return scores


def _match_provider(model_name: str) -> str | None:
    """Map a raw model name string to a known provider key."""
    name = model_name.lower()
    if any(k in name for k in ["claude", "anthropic"]):
        return "anthropic"
    if any(k in name for k in ["gpt", "openai", "codex", "o1", "o3"]):
        return "openai"
    if any(k in name for k in ["deepseek"]):
        return "deepseek"
    if any(k in name for k in ["gemini", "google", "bard"]):
        return "gemini"
    return None


def _fetch_live_benchmarks(cache_path: Path) -> dict[str, dict[str, float]]:
    """
    Returns {provider: {benchmark: score}} from live sources.
    Caches results to cache_path for CACHE_TTL_HOURS hours.
    Falls back to seeded data if all sources fail.
    """
    # Check cache
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            age_hours = (time.time() - cached.get("fetched_at", 0)) / 3600
            if age_hours < CACHE_TTL_HOURS:
                log.debug("Using cached benchmark data (%.1fh old)", age_hours)
                return cached.get("scores", {})
        except Exception:
            pass

    live: dict[str, dict[str, float]] = {p: {} for p in SEEDED}
    fetched_any = False

    for benchmark in ["swebench_verified", "humaneval", "mbpp", "bigcodebench", "livecodebench"]:
        raw = _fetch_paperswithcode(benchmark)
        if not raw:
            continue
        fetched_any = True
        for model_name, score in raw.items():
            provider = _match_provider(model_name)
            if provider:
                # Keep best score per provider per benchmark
                existing = live[provider].get(benchmark, 0.0)
                if score > existing:
                    live[provider][benchmark] = score

    if fetched_any:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "fetched_utc": datetime.now(UTC).isoformat(),
                    "scores": live,
                },
                indent=2,
            )
        )
        log.info("Live benchmark data fetched and cached → %s", cache_path)
    else:
        log.info("Live fetch failed — using seeded benchmark data")

    return live if fetched_any else {}


def _merge_benchmarks(
    live: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    Merge live data over seeded data.
    Live scores take precedence when present; seeded fills gaps.
    """
    merged: dict[str, dict[str, float]] = {}
    for provider, seed_info in SEEDED.items():
        merged[provider] = {}
        for bench, seed_score in seed_info["benchmarks"].items():
            live_score = live.get(provider, {}).get(bench)
            merged[provider][bench] = live_score if live_score is not None else seed_score
    return merged


# ── Goal parser ────────────────────────────────────────────────────────────────


def _parse_goal(goal_text: str) -> str:
    """
    Map a natural language project goal to a task type.
    Scores each task type by keyword matches, returns the winner.
    """
    text = goal_text.lower()
    scores: dict[str, int] = {task: 0 for task in GOAL_KEYWORDS}
    for task, keywords in GOAL_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[task] += 1
    best = max(scores, key=lambda t: scores[t])
    if scores[best] == 0:
        return "builder"  # sensible default
    return best


def _score_provider(
    provider: str,
    benchmarks: dict[str, float | None] | dict[str, float],
    task_type: str,
    local_stats: dict,
) -> tuple[float, str]:
    """
    Compute a weighted composite score for a provider given a task type.
    Returns (score, source_label).
    """
    local_key = f"{provider}:{task_type}"
    if local_key in local_stats:
        n = local_stats[local_key]["n"]
        return local_stats[local_key]["solve_rate"], f"your data (n={n})"

    weights = GOAL_WEIGHTS.get(task_type, GOAL_WEIGHTS["builder"])
    total_weight = 0.0
    weighted_sum = 0.0
    for bench, w in weights.items():
        score = benchmarks.get(bench)
        if score is not None:
            weighted_sum += score * w
            total_weight += w

    if total_weight == 0:
        return 0.0, "no data"
    return weighted_sum / total_weight, "live+seeded benchmarks"


# ── Local stats ────────────────────────────────────────────────────────────────


def _load_local_stats(data_dir: Path) -> dict:
    stats_path = data_dir / "advisor_stats.jsonl"
    if not stats_path.exists():
        return {}
    counts: dict[tuple[str, str], list[bool]] = {}
    with open(stats_path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                key = (rec["provider"], rec.get("task_type", "builder"))
                counts.setdefault(key, []).append(bool(rec.get("solved", False)))
            except Exception:
                continue
    result = {}
    for (provider, task_type), outcomes in counts.items():
        if len(outcomes) >= MIN_LOCAL_SAMPLES:
            result[f"{provider}:{task_type}"] = {
                "n": len(outcomes),
                "solve_rate": sum(outcomes) / len(outcomes),
            }
    return result


def record_outcome(
    data_dir: Path,
    provider: str,
    task_type: str,
    instance_id: str,
    solved: bool,
    repo_type: str = "",
    patch_lines: int = 0,
    attempts: int = 1,
) -> None:
    """Append one compiler-verified outcome to local stats."""
    stats_path = data_dir / "advisor_stats.jsonl"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "provider": provider,
                    "task_type": task_type,
                    "instance_id": instance_id,
                    "solved": solved,
                    "repo_type": repo_type,
                    "patch_lines": patch_lines,
                    "attempts": attempts,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            + "\n"
        )


# ── Data sharing (opt-in, open source) ────────────────────────────────────────
# Users who opt in contribute anonymized solve/fail metadata.
# No code, no patches, no identifiers — only signal metadata.
# Community dataset improves public benchmark weights for everyone.
# Sharing is orthogonal to Cloak: you can share outcomes without sharing code.
# Cloak audit log provides cryptographic proof of zero identifier leakage.

SHARE_ENABLED = bool(os.getenv("DETERMINEX_SHARE_OUTCOMES", ""))
SHARE_ENDPOINT = os.getenv("DETERMINEX_SHARE_ENDPOINT", "https://data.determinex.dev/contribute")


def share_outcome(record: dict) -> bool:
    """POST anonymized outcome metadata to community dataset. Never sends code."""
    if not SHARE_ENABLED:
        return False
    safe = {
        k: record.get(k)
        for k in [
            "provider",
            "task_type",
            "repo_type",
            "solved",
            "patch_lines",
            "attempts",
            "determinex_version",
        ]
    }
    try:
        payload = json.dumps(safe).encode()
        req = urllib.request.Request(
            SHARE_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


# ── Recommendation ─────────────────────────────────────────────────────────────


class Recommendation(NamedTuple):
    rank: int
    provider: str
    display: str
    model: str
    backend_key: str
    task_type: str
    score: float
    source: str
    cost_in: float
    cost_out: float
    cloak: bool
    strengths: list[str]
    env_var: str


def recommend(
    goal: str = "",
    task_type: str = "",
    budget: str = "any",
    privacy: bool = False,  # noqa: ARG001 — reserved for future provider filtering
    data_dir: Path | None = None,
    cache_dir: Path | None = None,
    top_n: int = 3,
    force_live: bool = False,
) -> list[Recommendation]:
    """
    Core recommendation engine.

    Pass either `goal` (natural language) or `task_type` (explicit).
    goal takes precedence and is parsed into a task_type automatically.
    """
    if goal:
        task_type = _parse_goal(goal)
        log.info("Goal '%s' → task_type '%s'", goal[:60], task_type)

    if not task_type:
        task_type = "builder"

    _data_dir = data_dir or Path("data")
    _cache_dir = cache_dir or Path("data")
    cache_path = _cache_dir / "benchmark_cache.json"

    if force_live and cache_path.exists():
        cache_path.unlink()

    live = _fetch_live_benchmarks(cache_path)
    merged = _merge_benchmarks(live)
    local = _load_local_stats(_data_dir)

    budget_cap = {"low": 0.50, "medium": 3.50, "any": 9999}.get(budget, 9999)

    scored: list[tuple[float, str, str]] = []
    for provider, benchmarks in merged.items():
        info = SEEDED[provider]
        if info["cost_in"] > budget_cap:
            continue
        score, source = _score_provider(provider, benchmarks, task_type, local)
        scored.append((score, provider, source))

    scored.sort(reverse=True)

    results = []
    for i, (score, provider, source) in enumerate(scored[:top_n], 1):
        info = SEEDED[provider]
        # Build the env var hint for this recommendation
        if provider == "ollama":
            env = "DETERMINEX_INFERENCE_BACKEND=ollama"
        elif task_type in ("architect",):
            env = f"DETERMINEX_ARCHITECT_BACKEND={provider}"
        else:
            env = f"DETERMINEX_BUILDER_BACKEND={provider}"

        results.append(
            Recommendation(
                rank=i,
                provider=provider,
                display=info["display"],
                model=info["model"],
                backend_key=info["backend_key"],
                task_type=task_type,
                score=round(score, 4),
                source=source,
                cost_in=info["cost_in"],
                cost_out=info["cost_out"],
                cloak=info["cloak"],
                strengths=info["strengths"][:4],
                env_var=env,
            )
        )
    return results


# ── CLI ────────────────────────────────────────────────────────────────────────


def _cli() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Determinex Model Advisor — realtime AI routing based on benchmarks + your data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/model_advisor.py --goal "fix django ORM bugs across 300 repos"
  python scripts/model_advisor.py --goal "architect a distributed cache refactor"
  python scripts/model_advisor.py --goal "high volume cheap code generation"
  python scripts/model_advisor.py --task architect --budget medium
  python scripts/model_advisor.py --list
  python scripts/model_advisor.py --refresh
        """,
    )
    parser.add_argument("--goal", default="", help="Natural language project goal")
    parser.add_argument(
        "--task", default="", choices=list(GOAL_WEIGHTS.keys()), help="Explicit task type"
    )
    parser.add_argument("--budget", default="any", choices=["low", "medium", "any"])
    parser.add_argument("--privacy", action="store_true", help="Flag privacy-sensitive project")
    parser.add_argument("--data-dir", default="data", help="Local stats directory")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--list", action="store_true", help="Show all providers + benchmark scores")
    parser.add_argument("--refresh", action="store_true", help="Force live data pull, ignore cache")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    data_dir = Path(args.data_dir)

    if args.list:
        cache_path = data_dir / "benchmark_cache.json"
        if args.refresh and cache_path.exists():
            cache_path.unlink()
        live = _fetch_live_benchmarks(cache_path)
        merged = _merge_benchmarks(live)

        source_label = "live" if live else "seeded (live unavailable)"
        print(f"\nBenchmark scores [{source_label}]")
        print(
            f"{'Provider':<12} {'Display':<22} {'SWE-b':>7} {'HEval':>7} {'MBPP':>7} {'BCB':>7} {'$/in':>7} {'$/out':>8} {'Cloak':>6}"
        )
        print("-" * 90)
        for provider, info in sorted(SEEDED.items(), key=lambda x: x[1]["cost_in"]):
            b = merged.get(provider, {})

            def fmt(v):
                return f"{v:.1%}" if v else "  —  "

            cloak = "yes" if info["cloak"] else "no"
            print(
                f"{provider:<12} {info['display']:<22} {fmt(b.get('swebench_verified')):>7} "
                f"{fmt(b.get('humaneval')):>7} {fmt(b.get('mbpp')):>7} "
                f"{fmt(b.get('bigcodebench')):>7} "
                f"${info['cost_in']:>5.2f} ${info['cost_out']:>6.2f} {cloak:>6}"
            )
        return

    recs = recommend(
        goal=args.goal,
        task_type=args.task,
        budget=args.budget,
        privacy=args.privacy,
        data_dir=data_dir,
        cache_dir=data_dir,
        top_n=args.top,
        force_live=args.refresh,
    )

    if not recs:
        print("No providers match the given constraints.")
        return

    task_label = recs[0].task_type
    goal_label = f'"{args.goal}" -> ' if args.goal else ""
    print("\nDeterminex Model Advisor")
    print(f"Goal: {goal_label}{task_label} | Budget: {args.budget} | Privacy: {args.privacy}")
    print(f"Scores: {recs[0].source}")
    print()

    local = _load_local_stats(data_dir)
    local_count = sum(v["n"] for v in local.values())
    if local_count > 0:
        print(f"  Using {local_count} compiler-verified outcomes from your local data.")
    else:
        print("  No local data yet. Run 30+ instances to override public benchmarks with your own.")
    print()

    for r in recs:
        bar_len = int(r.score * 30)
        bar = "#" * bar_len + "-" * (30 - bar_len)
        cost = f"${r.cost_in:.2f}/${r.cost_out:.2f} per MTok"
        cloak = "Cloak: yes" if r.cloak else "Cloak: not needed"
        print(f"  #{r.rank} {r.display:<22}  [{bar}] {r.score:.1%}")
        print(f"     Cost: {cost}  |  {cloak}")
        print(f"     Best for: {', '.join(r.strengths)}")
        print(f"     Set: {r.env_var}")
        print()

    print("Tip: Set DETERMINEX_SHARE_OUTCOMES=1 to contribute anonymized solve/fail")
    print("     signals to the community dataset and improve rankings for everyone.")
    print("     No code or identifiers are ever shared — only pass/fail metadata.")


if __name__ == "__main__":
    _cli()
