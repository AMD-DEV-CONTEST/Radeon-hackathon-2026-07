#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_breakout_evidence import compile_evidence_ledger, verify_evidence_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the bounded 2020-2026 GTM breakout evidence ledger.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("config/gtm-breakout-evidence-cases-v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/v10/gtm-breakout-evidence-ledger-v1.json"),
    )
    args = parser.parse_args()
    with args.source.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    ledger = compile_evidence_ledger(source)
    verify_evidence_ledger(ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **ledger["audit"], "content_sha256": ledger["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
