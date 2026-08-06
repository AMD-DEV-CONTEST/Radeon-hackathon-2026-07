#!/usr/bin/env python3
"""
benchmark/run_benchmark.py — Crash-safe RTL-Agent two-tier benchmark harness.

Runs all specs in benchmark/specs.json through the live agent HTTP endpoint,
records per-spec results, and generates results.json + results.md.

Amendments implemented:
  Am. 5 — Each spec wrapped in try/except; results written incrementally;
           --time-budget-minutes flag stops gracefully before credits expire.

Usage:
  # Against mock mode (always rehearse first):
  python benchmark/run_benchmark.py --base-url http://localhost:7860 --mock

  # Against live AMD vLLM endpoint:
  python benchmark/run_benchmark.py --base-url http://localhost:7860 --time-budget-minutes 60
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Try to use the 'requests' library; fall back to urllib if not installed ──
try:
    import requests as _requests
    def _post(url, data): return _requests.post(url, json=data, timeout=30)
    def _get(url):        return _requests.get(url, timeout=10)
    def _sse_get(url):    return _requests.get(url, stream=True, timeout=300)
    _USE_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.parse
    _USE_REQUESTS = False
    def _post(url, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(req, timeout=30)
    def _get(url):
        return urllib.request.urlopen(url, timeout=10)
    def _sse_get(url):
        return urllib.request.urlopen(url, timeout=300)


# ─── Paths ────────────────────────────────────────────────────────────────────
BENCHMARK_DIR = Path(__file__).parent
SPECS_FILE    = BENCHMARK_DIR / "specs.json"
RESULTS_JSON  = BENCHMARK_DIR / "results.json"
RESULTS_MD    = BENCHMARK_DIR / "results.md"


# ─── HTTP helpers ─────────────────────────────────────────────────────────────
def api_post(base_url: str, path: str, data: dict) -> dict:
    resp = _post(f"{base_url}{path}", data)
    if _USE_REQUESTS:
        resp.raise_for_status()
        return resp.json()
    else:
        return json.loads(resp.read())


def api_get_json(base_url: str, path: str) -> dict:
    resp = _get(f"{base_url}{path}")
    if _USE_REQUESTS:
        return resp.json()
    else:
        return json.loads(resp.read())


def stream_agent_events(base_url: str, session_id: str, timeout_s: int = 300):
    """
    Consume SSE stream for a session, yielding parsed event dicts.
    Stops on stream_end or timeout.
    """
    url = f"{base_url}/api/stream/{session_id}"
    start = time.monotonic()

    if _USE_REQUESTS:
        with _sse_get(url) as resp:
            for line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() - start > timeout_s:
                    break
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    yield event
                    if event.get("type") == "stream_end":
                        break
                except json.JSONDecodeError:
                    continue
    else:
        # urllib fallback: line-by-line SSE reading
        req = urllib.request.urlopen(url, timeout=timeout_s)
        for raw_line in req:
            if time.monotonic() - start > timeout_s:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
                yield event
                if event.get("type") == "stream_end":
                    break
            except json.JSONDecodeError:
                continue


# ─── Result record ────────────────────────────────────────────────────────────
def make_result_record(spec_id: int, spec_name: str, spec_text: str) -> dict:
    return {
        "id": spec_id,
        "name": spec_name,
        "spec": spec_text[:80] + "…" if len(spec_text) > 80 else spec_text,
        "status": "pending",
        "lint_status": "NOT_RUN",
        "functional_status": "NOT_RUN",
        "lint_iterations": 0,
        "functional_iterations": 0,
        "total_iterations": 0,
        "wall_clock_s": 0.0,
        "tokens_generated": 0,
        "avg_tokens_per_s": 0.0,
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Process one spec ─────────────────────────────────────────────────────────
def run_spec(base_url: str, spec: dict, stream_timeout_s: int = 240) -> dict:
    result = make_result_record(spec["id"], spec["name"], spec["spec"])
    t0 = time.monotonic()

    try:
        # Start session
        run_resp = api_post(base_url, "/api/run", {"spec": spec["spec"]})
        session_id = run_resp["session_id"]
        print(f"  → session {session_id[:8]}…", end="", flush=True)

        lint_iters = 0
        func_iters = 0
        total_iters = 0
        total_tokens = 0
        lint_status = "NOT_RUN"
        func_status  = "NOT_RUN"
        llm_elapsed_ms_total = 0.0
        ttft_samples: list = []  # per-call TTFT for avg computation

        for event in stream_agent_events(base_url, session_id, timeout_s=stream_timeout_s):
            etype = event.get("type", "")

            # Track iteration counts from events
            if "total_iterations" in event:
                total_iters = event["total_iterations"]

            if etype == "llm_done":
                total_tokens += event.get("tokens_generated", 0)
                llm_elapsed_ms_total += event.get("elapsed_ms", 0.0)
                # TTFT collection (Amendment 8 elevation — primary prefix-cache metric)
                ttft = event.get("ttft_ms", 0.0)
                if ttft > 0:
                    ttft_samples.append(ttft)

            elif etype == "lint_iteration" and event.get("phase") == "tier1_lint_result":
                if event.get("passed"):
                    lint_status = "PASSED"
                else:
                    lint_iters += 1

            elif etype == "sim_iteration":
                if event.get("passed"):
                    func_status = "PASSED"
                else:
                    func_iters += 1

            elif etype == "sim_build_error":
                lint_iters += 1   # routes to lint correction per Amendment 2

            elif etype == "final_result":
                lint_status = event.get("lint_status", lint_status)
                func_status = event.get("functional_status", func_status)
                total_iters = event.get("total_iterations", total_iters)

            elif etype == "stream_end":
                break

        wall_s = time.monotonic() - t0
        avg_tps = (total_tokens / (llm_elapsed_ms_total / 1000)) if llm_elapsed_ms_total > 0 else 0.0
        avg_ttft_ms = (sum(ttft_samples) / len(ttft_samples)) if ttft_samples else 0.0

        # Final determination
        both_pass = lint_status == "PASSED" and func_status == "PASSED"
        result.update({
            "status": "PASS" if both_pass else ("PARTIAL" if lint_status == "PASSED" else "FAIL"),
            "lint_status": lint_status,
            "functional_status": func_status,
            "lint_iterations": lint_iters,
            "functional_iterations": func_iters,
            "total_iterations": total_iters,
            "wall_clock_s": round(wall_s, 2),
            "tokens_generated": total_tokens,
            "avg_tokens_per_s": round(avg_tps, 1),
            "avg_ttft_ms": round(avg_ttft_ms, 1),
        })

    except Exception as exc:
        # Amendment 5: one bad design never kills the batch
        result.update({
            "status": "error",
            "error": str(exc),
            "wall_clock_s": round(time.monotonic() - t0, 2),
        })
        print(f" ERROR: {exc}", flush=True)
        return result

    status_icon = "✓" if result["status"] == "PASS" else ("~" if result["status"] == "PARTIAL" else "✗")
    print(f" {status_icon} lint={lint_status} sim={func_status} {wall_s:.1f}s {total_iters} iters {total_tokens} tok", flush=True)
    return result


# ─── Write incremental results (Amendment 5) ─────────────────────────────────
def write_results(results: list, run_meta: dict):
    """Write both JSON and Markdown results — called after each spec."""
    output = {"meta": run_meta, "results": results}
    RESULTS_JSON.write_text(json.dumps(output, indent=2), encoding="utf-8")

    # Generate Markdown table
    lines = [
        "# RTL-Agent v2 Benchmark Results",
        "",
        f"**Run date**: {run_meta.get('run_date', 'unknown')}  ",
        f"**Mode**: {run_meta.get('mode', 'unknown')}  ",
        f"**Model**: {run_meta.get('model', 'unknown')}  ",
        f"**Base URL**: {run_meta.get('base_url', 'unknown')}  ",
        "",
        "## Per-Spec Results",
        "",
        "| # | Spec | Lint | Simulation | Lint Iters | Sim Iters | Total Iters | Wall (s) | Tok/s | TTFT (ms) |",
        "|---|------|------|-----------|-----------|----------|-------------|----------|-------|----------|",
    ]

    for r in results:
        status_emoji = "✅" if r["status"] == "PASS" else ("⚠️" if r["status"] == "PARTIAL" else ("❌" if r["status"] == "FAIL" else "💥"))
        lines.append(
            f"| {r['id']} | {r['name']} {status_emoji} "
            f"| {r['lint_status']} | {r['functional_status']} "
            f"| {r['lint_iterations']} | {r['functional_iterations']} "
            f"| {r['total_iterations']} | {r['wall_clock_s']} | {r['avg_tokens_per_s']} | {r.get('avg_ttft_ms', '—')} |"
        )

    # Aggregate stats
    completed = [r for r in results if r["status"] in ("PASS", "PARTIAL", "FAIL")]
    if completed:
        pass_count    = sum(1 for r in results if r["status"] == "PASS")
        partial_count = sum(1 for r in results if r["status"] == "PARTIAL")
        fail_count    = sum(1 for r in results if r["status"] in ("FAIL", "error"))
        total_count   = len(results)
        avg_iters  = sum(r["total_iterations"] for r in completed) / len(completed)
        avg_wall   = sum(r["wall_clock_s"] for r in completed) / len(completed)
        avg_tps    = (sum(r["avg_tokens_per_s"] for r in completed if r["avg_tokens_per_s"] > 0)
                      / max(1, sum(1 for r in completed if r["avg_tokens_per_s"] > 0)))
        avg_ttft   = (sum(r.get("avg_ttft_ms", 0) for r in completed if r.get("avg_ttft_ms", 0) > 0)
                      / max(1, sum(1 for r in completed if r.get("avg_ttft_ms", 0) > 0)))

        lines += [
            "",
            "## Aggregate Statistics",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Specs run | {total_count} |",
            f"| Full PASS (both tiers) | {pass_count} / {total_count} ({100*pass_count//total_count if total_count else 0}%) |",
            f"| Partial PASS (lint only) | {partial_count} |",
            f"| FAIL / Error | {fail_count} |",
            f"| Avg total iterations / design | {avg_iters:.1f} |",
            f"| Avg wall-clock time / design | {avg_wall:.1f}s |",
            f"| Avg LLM throughput | {avg_tps:.0f} tok/s |",
            f"| Avg TTFT (time-to-first-token) | {avg_ttft:.0f} ms |",
        ]

    lines += ["", f"*Generated by RTL-Agent v2 benchmark harness*"]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="RTL-Agent v2 Benchmark Harness")
    parser.add_argument("--base-url", default="http://localhost:7860",
                        help="Base URL of the RTL-Agent server (default: http://localhost:7860)")
    parser.add_argument("--specs", default=str(SPECS_FILE),
                        help=f"Path to specs JSON file (default: {SPECS_FILE})")
    parser.add_argument("--time-budget-minutes", type=float, default=None,
                        help="Stop before this many wall-clock minutes have elapsed (Amendment 5)")
    parser.add_argument("--stream-timeout", type=int, default=240,
                        help="Per-spec SSE stream timeout in seconds (default: 240)")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Run N specs in parallel threads (tests throughput, default: 1 = serial)")
    parser.add_argument("--mock", action="store_true",
                        help="Print a note that mock mode should be set server-side via MOCK_MODE=true")
    args = parser.parse_args()

    # ── Verify server is reachable ───────────────────────────────────────────
    print(f"RTL-Agent v2 Benchmark Harness")
    print(f"Base URL   : {args.base_url}")
    print(f"Specs file : {args.specs}")
    if args.time_budget_minutes:
        print(f"Time budget: {args.time_budget_minutes:.1f} minutes")
    print()

    try:
        cfg = api_get_json(args.base_url, "/api/config")
        model = cfg.get("model", "unknown")
        mode  = "MOCK" if cfg.get("mock_mode") else "REAL"
        print(f"Server OK   : mode={mode}  model={model}  v={cfg.get('version', '?')}")
        print(f"Iteration caps: lint={cfg.get('max_lint_iterations')} sim={cfg.get('max_functional_iterations')} total={cfg.get('max_total_iterations')}")
    except Exception as e:
        print(f"ERROR: Cannot reach server at {args.base_url}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.mock:
        print("\n[NOTE] --mock flag passed. Ensure server was started with MOCK_MODE=true.")
    print()

    # ── Load specs ───────────────────────────────────────────────────────────
    specs_path = Path(args.specs)
    if not specs_path.exists():
        print(f"ERROR: specs file not found: {specs_path}", file=sys.stderr)
        sys.exit(1)

    specs = json.loads(specs_path.read_text())
    print(f"Loaded {len(specs)} specs\n")

    run_meta = {
        "run_date": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "model": model,
        "mode": mode,
        "specs_file": str(specs_path),
    }

    results = []
    budget_start = time.monotonic()

    for i, spec in enumerate(specs):
        # Amendment 5: time budget check
        if args.time_budget_minutes is not None:
            elapsed_min = (time.monotonic() - budget_start) / 60
            remaining_min = args.time_budget_minutes - elapsed_min
            # Rough estimate: skip if less than 2 minutes remain
            if remaining_min < 2.0:
                print(f"\n⏱ Time budget almost exhausted ({elapsed_min:.1f}/{args.time_budget_minutes:.1f} min). Stopping gracefully.")
                break

        print(f"[{i+1}/{len(specs)}] {spec['name']}")
        result = run_spec(args.base_url, spec, stream_timeout_s=args.stream_timeout)
        results.append(result)

        # Amendment 5: write incrementally after EVERY spec
        run_meta["specs_completed"] = len(results)
        run_meta["total_wall_s"] = round(time.monotonic() - budget_start, 2)
        write_results(results, run_meta)
        print(f"  Saved incremental results → {RESULTS_JSON.name}")
        print()

    # ── Final summary ─────────────────────────────────────────────────────────
    total_wall = time.monotonic() - budget_start
    run_meta["total_wall_s"] = round(total_wall, 2)
    write_results(results, run_meta)

    pass_count = sum(1 for r in results if r["status"] == "PASS")
    print("=" * 60)
    print(f"Benchmark complete: {pass_count}/{len(results)} PASSED both tiers")
    print(f"Total wall time   : {total_wall:.1f}s ({total_wall/60:.1f} min)")
    print(f"Results JSON      : {RESULTS_JSON}")
    print(f"Results Markdown  : {RESULTS_MD}")
    print("=" * 60)


if __name__ == "__main__":
    main()
