#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_gold_lead_review_queue_v2 import (
    compile_gold_lead_review_queue,
    verify_gold_lead_review_queue,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    discovery = json.loads((ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json").read_text(encoding="utf-8"))
    capture = json.loads((ROOT / "evidence/v10/gtm-gold-case-public-source-capture-v2.json").read_text(encoding="utf-8"))
    surfaces = json.loads((ROOT / "evidence/v10/gtm-gold-case-claim-surfaces-v2.json").read_text(encoding="utf-8"))
    payload = compile_gold_lead_review_queue(discovery, capture, surfaces)
    verify_gold_lead_review_queue(payload)
    output = ROOT / "evidence/v10/gtm-gold-lead-review-queue-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "review_item_count": payload["review_item_count"],
        "human_binding_ready_count": payload["human_binding_ready_count"],
        "status_counts": payload["status_counts"],
        "subvertical_queues": payload["subvertical_queues"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
