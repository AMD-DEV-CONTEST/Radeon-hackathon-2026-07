#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_admission_acceleration_queue_v2 import build_admission_acceleration_queue, verify_admission_acceleration_queue


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    payload = build_admission_acceleration_queue(ledger)
    verify_admission_acceleration_queue(payload, ledger)
    output = ROOT / "evidence/v10/gtm-admission-acceleration-queue-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "task_count": payload["task_count"], "priority_lane_counts": payload["priority_lane_counts"], "represented_subvertical_count": payload["represented_subvertical_count"], "formal_candidate_quota_credit": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
