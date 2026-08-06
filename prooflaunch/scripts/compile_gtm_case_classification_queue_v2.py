#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_classification_queue_v2 import (
    compile_case_classification_queue,
    verify_case_classification_queue,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    discovery = json.loads((ROOT / "evidence/v10/gtm-wave1-discovery-leads-v2.json").read_text(encoding="utf-8"))
    payload = compile_case_classification_queue(discovery)
    verify_case_classification_queue(payload)
    output = ROOT / "evidence/v10/gtm-case-classification-queue-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "lead_count": payload["lead_count"], "work_item_count": payload["work_item_count"], "priority_counts": payload["priority_counts"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
