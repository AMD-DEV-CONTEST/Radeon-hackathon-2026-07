#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_public_case_index_enumerator_v2 import (
    enumerate_public_case_indexes,
    verify_public_case_index_enumeration,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/gtm_case_funnel_v2/public-case-index-source-registry-v2.json"
OUTPUT = ROOT / "evidence/v10/gtm-public-case-index-enumeration-v2.json"
LEADS = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave5-indexes-v2.json"


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload = enumerate_public_case_indexes(registry["sources"])
    verify_public_case_index_enumeration(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lead_set = {
        "schema": "ProofLaunchGTMAllSubverticalPublicLeadSetV2",
        "wave_id": "wave5-public-case-indexes",
        "record_count": len(payload["records"]),
        "source_enumeration_sha256": payload["content_sha256"],
        "records": payload["records"],
        "formal_candidate_quota_credit": 0,
        "truth_boundary": payload["truth_boundary"],
    }
    atomic_write_text(LEADS, json.dumps(lead_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "leads": str(LEADS),
        "source_count": payload["source_count"],
        "status_counts": payload["status_counts"],
        "enumerated_unique_lead_count": payload["enumerated_unique_lead_count"],
        "formal_candidate_quota_credit": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
