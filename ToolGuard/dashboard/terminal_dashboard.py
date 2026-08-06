import json
import os
import time

LOG_FILE = os.path.join(os.path.dirname(__file__), "call_log.jsonl")

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR = "\033[2J\033[H"


def load_calls(limit=15):
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE) as f:
        lines = f.readlines()
    entries = [json.loads(line) for line in lines[-limit:]]
    entries.reverse()
    return entries


def truncate(text, width):
    text = str(text)
    return text if len(text) <= width else text[: width - 3] + "..."


def render(calls_all, calls_shown):
    total = len(calls_all)
    normal = sum(1 for c in calls_all if c["outcome"] == "NORMAL")
    caught = total - normal
    fixed = sum(1 for c in calls_all if c["fixed_by_toolguard"])
    reliability = (100 * (normal + fixed) / total) if total else 0

    out = []
    out.append(f"{BOLD}{CYAN}TOOLGUARD - LIVE RELIABILITY DASHBOARD{RESET}")
    out.append("=" * 78)
    out.append(
        f"Total calls: {BOLD}{total}{RESET}   "
        f"Normal: {GREEN}{normal}{RESET}   "
        f"Caught failures: {YELLOW}{caught}{RESET}   "
        f"Fixed by ToolGuard: {GREEN}{fixed}{RESET}"
    )
    out.append(f"Effective reliability: {BOLD}{GREEN if reliability >= 90 else YELLOW}{reliability:.1f}%{RESET}")
    out.append("=" * 78)
    out.append(f"{BOLD}{'TIME':<20}{'OUTCOME':<23}{'FIXED':<8}{'CALL':<30}{RESET}")
    out.append("-" * 78)

    if not calls_shown:
        out.append("  (waiting for calls...)")
    for c in calls_shown:
        fixed_str = f"{GREEN}YES{RESET}" if c["fixed_by_toolguard"] else (
            f"{RED}NO{RESET}" if c["outcome"] != "NORMAL" else "-"
        )
        call_str = truncate(c["final_call"], 28) if c["final_call"] else "-"
        color = GREEN if c["outcome"] == "NORMAL" else (GREEN if c["fixed_by_toolguard"] else RED)
        out.append(
            f"{c['timestamp']:<20}{color}{c['outcome']:<23}{RESET}{fixed_str:<17}{call_str:<30}"
        )

    out.append("-" * 78)
    out.append("(Refreshes every 2 seconds. To stop: from another terminal, run: pkill -f terminal_dashboard.py)")
    return "\n".join(out)


if __name__ == "__main__":
    try:
        while True:
            all_calls = load_calls(limit=1000)
            shown_calls = all_calls[:15]
            print(CLEAR + render(all_calls, shown_calls), flush=True)
            for _ in range(20):  # sleep in small steps so Ctrl+C responds fast
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDashboard stopped.", flush=True)
