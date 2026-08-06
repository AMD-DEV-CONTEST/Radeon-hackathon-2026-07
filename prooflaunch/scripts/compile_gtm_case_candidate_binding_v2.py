#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_candidate_binding_v2 import (
    compile_case_candidate_binding_packets,
    verify_case_candidate_binding_packets,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    payload = compile_case_candidate_binding_packets(
        _read("evidence/v10/gtm-gold-case-discovery-v2.json"),
        _read("evidence/v10/gtm-gold-case-public-source-capture-v2.json"),
        _read("evidence/v10/gtm-gold-case-claim-surfaces-v2.json"),
        _read("evidence/v10/gtm-gold-lead-review-queue-v2.json"),
    )
    verify_case_candidate_binding_packets(payload)
    output = ROOT / "evidence/v10/gtm-case-candidate-binding-packets-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "packet_count": payload["packet_count"],
        "status_counts": payload["status_counts"],
        "candidate_quota_credit": payload["candidate_quota_credit"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
