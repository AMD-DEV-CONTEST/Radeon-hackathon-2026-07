#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import (
    build_unified_review_ledger,
    verify_unified_review_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json"


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    binding = _load("evidence/v10/gtm-case-candidate-binding-packets-v2.json")
    queues = [
        _load("evidence/v10/gtm-all-subvertical-review-queue-v2.json"),
        _load("evidence/v10/gtm-all-subvertical-wave2-b2b-review-queue-v2.json"),
        _load("evidence/v10/gtm-all-subvertical-wave3-b2c-review-queue-v2.json"),
        _load("evidence/v10/gtm-all-subvertical-wave4-classified-review-queue-v2.json"),
        _load("evidence/v10/gtm-all-subvertical-wave7-classified-review-queue-v2.json"),
        _load("evidence/v10/gtm-high-transparency-wave8-review-queue-v2.json"),
    ]
    payload = build_unified_review_ledger(binding, queues)
    verify_unified_review_ledger(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "review_packet_count": payload["review_packet_count"],
        "machine_ready_for_named_review_count": payload["machine_ready_for_named_review_count"],
        "evidence_gap_count": payload["evidence_gap_count"],
        "represented_subvertical_count": payload["represented_subvertical_count"],
        "formal_candidate_quota_credit": payload["formal_candidate_quota_credit"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
