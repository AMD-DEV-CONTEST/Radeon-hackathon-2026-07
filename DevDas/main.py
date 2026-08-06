"""
main.py

DevDas — Autonomous Kubernetes SRE Investigation Agent

Entry point. Orchestrates the full investigation pipeline:

    1. Discovery Phase  (pure Python, no LLM)
       kubectl get pods --all-namespaces
       → filter unhealthy workloads

    2. Investigation Phase  (LLM reasoning loop per workload)
       For each unhealthy workload:
           investigate(workload) → result

    3. Report Phase
       generate_report(results) → print cluster investigation report

Usage:
    python main.py
    python main.py --namespace devdas
    python main.py --namespace devdas --save-report
"""

import sys
import time
import argparse

from discovery import run_discovery
from investigate import investigate
from report import generate_report, save_report
from system_prompt import system_prompt
from itertools import groupby


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = (
    "\n"
    "  +----------------------------------------------------------+\n"
    "  |                                                          |\n"
    "  |   DevDas -- Autonomous Kubernetes SRE Agent              |\n"
    "  |   Powered by Groq (llama-3.3-70b-versatile)              |\n"
    "  |   AMD AI Hackathon                                       |\n"
    "  |                                                          |\n"
    "  +----------------------------------------------------------+\n"
)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="DevDas — Autonomous Kubernetes SRE Investigation Agent"
    )
    parser.add_argument(
        "--namespace", "-n",
        default="--all-namespaces",
        help="Kubernetes namespace to scan. Default: --all-namespaces"
    )
    parser.add_argument(
        "--save-report",
        action="store_true",
        help="Save the investigation report to devdas_report.txt"
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cluster_start_time = time.time()

    print(BANNER)
    print(f"  Starting cluster investigation...")
    print(f"  Namespace scope : {args.namespace}")
    print()

    # ── Phase 1: Discovery ─────────────────────────────────────────────────
    unhealthy_workloads, total_pods = run_discovery(namespace=args.namespace)
    unhealthy_workloads.sort(key=lambda w: w["owner_name"])
    results = []
    for owner_name, group in groupby(unhealthy_workloads, key=lambda w: w["owner_name"]):
        group = list(group)
        representative = group[0]
        result = investigate(representative, system_prompt)
        results.append(result)
        # apply same result to sibling pods of the same owner
        for sibling in group[1:]:
            sibling_result = dict(result)
            sibling_result["workload"] = sibling
            sibling_result["reasoning"] += " (Same root cause as sibling pod under identical owner.)"
            results.append(sibling_result)

    if not unhealthy_workloads:
        print("\n  ✅ Cluster is healthy. No investigations needed.\n")
        generate_report(
            results=[],
            total_pods=total_pods,
            unhealthy_count=0,
            cluster_start_time=cluster_start_time,
        )
        return

    print(f"\n  Found {len(unhealthy_workloads)} unhealthy workload(s).")
    print(f"  Starting per-workload investigations...\n")

    # ── Phase 2: Investigation (one per unhealthy workload) ────────────────
    # results = []

    # for idx, workload in enumerate(unhealthy_workloads, start=1):
    #     print(f"\n{'═' * 60}")
    #     print(f"  Investigation {idx} / {len(unhealthy_workloads)}")
    #     print(f"{'═' * 60}")

    #     result = investigate(workload, system_prompt)
    #     results.append(result)

    #     # Brief summary after each investigation
    #     print(f"\n  📌 Result: {result.get('root_cause', 'Unknown root cause')}")
    #     print(f"  🔧 Tools: {len(result.get('tools_used', []))}  "
    #           f"| ⏱ Duration: {result.get('duration_seconds', 0)}s")

    # ── Phase 3: Report ────────────────────────────────────────────────────
    print(f"\n\n{'═' * 60}")
    print(f"  Generating Cluster Investigation Report...")
    print(f"{'═' * 60}\n")

    report_text = generate_report(
        results=results,
        total_pods=total_pods,
        unhealthy_count=len(unhealthy_workloads),
        cluster_start_time=cluster_start_time,
    )

    if args.save_report:
        save_report(report_text)


if __name__ == "__main__":
    main()