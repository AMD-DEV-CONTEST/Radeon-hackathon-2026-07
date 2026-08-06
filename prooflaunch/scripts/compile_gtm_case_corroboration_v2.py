#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_corroboration_v2 import compile_case_corroboration


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    sources = _read("data/gtm_case_funnel_v2/corroboration-public-leads-v2.json")
    payload = compile_case_corroboration(
        _read("evidence/v10/gtm-gold-lead-review-queue-v2.json"),
        _read("evidence/v10/gtm-case-corroboration-public-capture-v2.json"),
        sources["records"],
        research_cutoff=sources["research_cutoff"],
    )
    output = ROOT / "evidence/v10/gtm-case-corroboration-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "query_count": payload["query_count"],
        "query_status_counts": payload["query_status_counts"],
        "record_count": payload["record_count"],
        "source_class_counts": payload["source_class_counts"],
        "independent_same_claim_candidate_count": payload["independent_same_claim_candidate_count"],
        "human_confirmed_independent_evidence_count": payload["human_confirmed_independent_evidence_count"],
        "candidate_quota_credit": payload["candidate_quota_credit"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
