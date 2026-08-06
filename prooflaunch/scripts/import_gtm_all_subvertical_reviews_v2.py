#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import compile_unified_review_receipt, verify_unified_review_receipt


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate source-bound unified case review intake without granting quota.")
    parser.add_argument("intake")
    parser.add_argument("--ledger", default=str(ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json"))
    parser.add_argument("--output", default=str(ROOT / "evidence/v10/gtm-all-subvertical-human-review-receipt-v2.json"))
    args = parser.parse_args()
    intake = json.loads(Path(args.intake).read_text(encoding="utf-8"))
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    receipt = compile_unified_review_receipt(intake, ledger)
    verify_unified_review_receipt(receipt)
    atomic_write_text(Path(args.output), json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": args.output, "review_count": receipt["review_count"], "formal_candidate_quota_credit": 0, "content_sha256": receipt["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
