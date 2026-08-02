"""Backfill the local multi-bout semantic index from outputs/*/events.json."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fencing_analysis.rag.session_store import SessionStore


def main():
    store = SessionStore("outputs")
    count = 0
    for name in sorted(os.listdir("outputs")) if os.path.isdir("outputs") else []:
        path = os.path.join("outputs", name, "events.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            store.upsert(name, json.load(f))
        count += 1
    print(f"Indexed {count} sessions -> outputs/.session_index")


if __name__ == "__main__":
    main()
