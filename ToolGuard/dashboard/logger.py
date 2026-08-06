import json
import os
import time

LOG_FILE = os.path.join(os.path.dirname(__file__), "call_log.jsonl")


def log_call(outcome, detail, fixed_by_toolguard, final_call):
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "outcome": outcome,
        "detail": detail,
        "fixed_by_toolguard": fixed_by_toolguard,
        "final_call": final_call,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
