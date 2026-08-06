#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_discovery_delta_v2 import build_discovery_delta, verify_discovery_delta


ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "evidence/v10/gtm-all-subvertical-discovery-pre-wave7-classification-v2.json"
BASELINE = ROOT / "evidence/v10/gtm-all-subvertical-discovery-pre-wave4-v2.json"
OUTPUT = ROOT / "evidence/v10/gtm-public-case-enumeration-delta-v2.json"
LEADS = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave7-capture-delta-v2.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    current, baseline = _load(CURRENT), _load(BASELINE)
    payload = build_discovery_delta(current, baseline)
    verify_discovery_delta(payload, current, baseline)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lead_set = {
        "schema": "ProofLaunchGTMUnroutedPublicLeadSourceSetV2",
        "wave_id": "wave7-public-case-enumeration-capture-delta",
        "record_count": len(payload["records"]),
        "source_delta_sha256": payload["content_sha256"],
        "records": payload["records"],
        "formal_candidate_quota_credit": 0,
        "truth_boundary": payload["truth_boundary"],
    }
    atomic_write_text(LEADS, json.dumps(lead_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "leads": str(LEADS),
        "baseline_unique_lead_count": payload["baseline_unique_lead_count"],
        "current_unique_lead_count": payload["current_unique_lead_count"],
        "new_unique_lead_count": payload["new_unique_lead_count"],
        "formal_candidate_quota_credit": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
