"""
report.py

Cluster Investigation Report generator.

Formats and prints the final cluster health report after all
per-workload investigations are complete.
"""

import time


# ── ANSI color helpers (graceful fallback on Windows without color support) ──

def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"

def _green(text: str) -> str:
    return f"\033[92m{text}\033[0m"

def _yellow(text: str) -> str:
    return f"\033[93m{text}\033[0m"

def _red(text: str) -> str:
    return f"\033[91m{text}\033[0m"

def _cyan(text: str) -> str:
    return f"\033[96m{text}\033[0m"


def generate_report(
    results: list[dict],
    total_pods: int,
    unhealthy_count: int,
    cluster_start_time: float,
) -> str:
    """
    Generate and print the Cluster Investigation Report.

    Args:
        results:           List of investigation result dicts from investigate()
        total_pods:        Total pods scanned during discovery
        unhealthy_count:   Number of unhealthy pods found
        cluster_start_time: time.time() when the overall run started

    Returns:
        The report as a plain-text string (also printed to stdout).
    """
    healthy_count    = total_pods - unhealthy_count
    total_duration   = round(time.time() - cluster_start_time, 1)
    total_tool_calls = sum(len(r["tools_used"]) for r in results)
    avg_tool_calls   = (
        round(total_tool_calls / len(results), 1) if results else 0
    )
    total_iterations = sum(r["iterations"] for r in results)

    lines = []

    def line(text=""):
        lines.append(text)
        print(text)

    # ── Header ──────────────────────────────────────────────────────────────
    line()
    line(_bold("╔" + "═" * 58 + "╗"))
    line(_bold("║" + "   DevDas — Cluster Investigation Report".center(58) + "║"))
    line(_bold("╚" + "═" * 58 + "╝"))
    line()

    # ── Cluster Summary ──────────────────────────────────────────────────────
    line(_bold("  Cluster Summary"))
    line("  " + "─" * 40)
    line(f"  {'Total Pods Scanned':<28}: {total_pods}")
    line(f"  {'Unhealthy Workloads Investigated':<28}: {_red(str(unhealthy_count)) if unhealthy_count else _green('0')}")
    line(f"  {'Healthy Pods':<28}: {_green(str(healthy_count))}")
    line(f"  {'Total Investigations':<28}: {len(results)}")
    line(f"  {'Total Tool Calls':<28}: {total_tool_calls}")
    line(f"  {'Total Iterations':<28}: {total_iterations}")
    line(f"  {'Avg Tool Calls / Investigation':<28}: {avg_tool_calls}")
    line(f"  {'Total Duration':<28}: {total_duration}s")
    line()

    if not results:
        line(_green("  ✅ No unhealthy workloads found. Cluster appears healthy."))
        line()
        report_text = "\n".join(lines)
        return report_text

    # ── Per-Workload Results ─────────────────────────────────────────────────
    line(_bold("  Investigation Results"))
    line("  " + "─" * 56)

    for idx, result in enumerate(results, start=1):
        wl       = result["workload"]
        pod      = wl["pod_name"]
        ns       = wl["namespace"]
        status   = wl["status"]
        owner    = f"{wl['owner_kind']}/{wl['owner_name']}"
        restarts = wl["restart_count"]

        root_cause    = result.get("root_cause", "Unknown")
        recovery_plan = result.get("recovery_plan", [])
        tools_used    = result.get("tools_used", [])
        iterations    = result.get("iterations", 0)
        duration      = result.get("duration_seconds", 0)
        inv_status    = result.get("status", "complete")

        status_badge = (
            _yellow("⚠ complete_forced")
            if inv_status == "complete_forced"
            else _green("✅ complete")
        )

        line()
        line(f"  [{idx}] {_bold(pod)}  ({ns})")
        line(f"       Pod Status   : {_red(status)}")
        line(f"       Owner        : {owner}")
        line(f"       Restarts     : {restarts}")
        line(f"       Inv. Status  : {status_badge}")
        line(f"       Tool Calls   : {len(tools_used)}")
        line(f"       Iterations   : {iterations}")
        line(f"       Duration     : {duration}s")
        line()
        line(f"       {_bold('Root Cause')}")
        line(f"       {root_cause}")
        line()

        if recovery_plan:
            line(f"       {_bold('Recovery Plan')}")
            for step_num, step in enumerate(recovery_plan, start=1):
                line(f"       {step_num}. {step}")
        else:
            line(f"       {_yellow('Recovery plan: None provided.')}")

        if tools_used:
            line()
            line(f"       {_bold('Tools Used')}  : {', '.join(tools_used)}")

        line()
        line("  " + "─" * 56)

    # ── Footer ───────────────────────────────────────────────────────────────
    line()
    line(_cyan("  DevDas investigation complete."))
    line(_cyan("  This report was generated autonomously by the DevDas SRE agent."))
    line()

    report_text = "\n".join(lines)
    return report_text


def save_report(report_text: str, output_path: str = "devdas_report.txt"):
    """Save the plain-text report to a file (ANSI codes stripped)."""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_text = ansi_escape.sub('', report_text)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(clean_text)
    print(f"\n  Report saved to: {output_path}")
