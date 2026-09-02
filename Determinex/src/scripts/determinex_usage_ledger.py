#!/usr/bin/env python3
"""
determinex_usage_ledger.py -- spend/usage summary from logs/api_ledger/providers.jsonl
=============================================================================
Ryan: "we need to also add the token limits for those api's like their
level and how much til they end of credits and all that fun stuff, the gas
gauge if you will."

Honest scope: this summarizes REAL, already-tracked spend for calls made
through determinex_providers.py's litellm-based generate() (Hive/PB/
SWE-bench pipelines, etc.) -- tokens in/out + estimated USD per call, logged
by determinex_providers._ledger_append(). It does NOT (and can't safely)
report remaining credit balance for the claude-code/codex/gemini-cli
SUBSCRIPTION CLIs run in the Agent Chat Room -- none of those expose a
simple, safely-queryable "remaining usage" API via the OAuth session
credentials already on this machine; that would need a separate,
admin-scoped API key the user would have to supply explicitly.
cli_subscription_status() says so plainly rather than fabricating a number.

Streams the ledger line-by-line rather than loading it fully into memory --
same convention as determinex_corpus_api.py's verdict_corpus_stats() for the
much larger (9GB) training corpus.

CLI
---
    python scripts/determinex_usage_ledger.py summary [--window-hours 24]
    python scripts/determinex_usage_ledger.py cli-status
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "logs" / "api_ledger" / "providers.jsonl"


def summarize_ledger(window_hours: float | None = 24.0) -> dict:
    """Aggregate real spend from the ledger, optionally windowed to the last
    N hours (None = all-time). Streams the file rather than loading it whole."""
    if not LEDGER_PATH.exists():
        return {"exists": False, "providers": {}, "total_est_usd": 0.0, "total_calls": 0}

    cutoff = None
    if window_hours is not None:
        cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=window_hours)

    providers: dict = {}
    total_usd = 0.0
    total_calls = 0
    malformed = 0

    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if cutoff is not None:
                try:
                    ts = _dt.datetime.fromisoformat(row.get("ts", ""))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
            model = row.get("model", "unknown")
            provider = model.split("/", 1)[0] if "/" in model else model
            entry = providers.setdefault(
                provider,
                {
                    "calls": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "est_usd": 0.0,
                    "models": set(),
                },
            )
            entry["calls"] += 1
            entry["tokens_in"] += int(row.get("tokens_in", 0) or 0)
            entry["tokens_out"] += int(row.get("tokens_out", 0) or 0)
            entry["est_usd"] += float(row.get("est_usd", 0) or 0)
            entry["models"].add(model)
            total_usd += float(row.get("est_usd", 0) or 0)
            total_calls += 1

    for p in providers.values():
        p["models"] = sorted(p["models"])
        p["est_usd"] = round(p["est_usd"], 4)

    return {
        "exists": True,
        "window_hours": window_hours,
        "providers": providers,
        "total_est_usd": round(total_usd, 4),
        "total_calls": total_calls,
        "malformed_lines_skipped": malformed,
    }


def cli_subscription_status() -> dict:
    """Honest placeholder for the CLI-subscription half of the ask: these
    tools don't expose a safely-queryable remaining-usage API via the OAuth
    session already on this machine. Returns a clearly-labeled
    "not available" entry per CLI rather than a fabricated number."""
    reason = (
        "This CLI's subscription usage isn't exposed via a simple API with the "
        "session credentials already on this machine -- would need a separate, "
        "explicitly-provided admin/org-scoped API key for that provider."
    )
    return {
        name: {"available": False, "reason": reason}
        for name in ("claude-code", "codex", "gemini-cli")
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Determinex API spend/usage ledger summary")
    sub = parser.add_subparsers(dest="cmd")

    p_summary = sub.add_parser("summary")
    p_summary.add_argument("--window-hours", type=float, default=24.0)
    p_summary.add_argument(
        "--all-time", action="store_true", help="ignore --window-hours, summarize everything"
    )

    sub.add_parser("cli-status")

    args = parser.parse_args()

    if args.cmd == "summary":
        window = None if args.all_time else args.window_hours
        print(json.dumps(summarize_ledger(window)))
        return 0

    if args.cmd == "cli-status":
        print(json.dumps(cli_subscription_status()))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
