#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_unrouted_lead_classifier_v2 import classify_unrouted_leads, verify_unrouted_lead_classification


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / "evidence/v10/gtm-all-subvertical-discovery-v2.json"
BASELINE_DISCOVERY = ROOT / "evidence/v10/gtm-all-subvertical-discovery-pre-wave4-v2.json"
ONTOLOGY = ROOT / "evidence/v10/gtm-subvertical-ontology-v1.json"
OUTPUT = ROOT / "evidence/v10/gtm-unrouted-lead-classification-v2.json"
LEADS = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave4-classified-v2.json"
ALL_UNROUTED = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave4-unrouted-source-v2.json"
CAPTURE = ROOT / "evidence/v10/gtm-all-subvertical-wave4-unrouted-public-capture-v2.json"


def main() -> int:
    if not BASELINE_DISCOVERY.exists():
        atomic_write_text(BASELINE_DISCOVERY, DISCOVERY.read_text(encoding="utf-8"))
    discovery = json.loads(BASELINE_DISCOVERY.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    capture = json.loads(CAPTURE.read_text(encoding="utf-8")) if CAPTURE.exists() else None
    allowed = {row["subvertical_id"] for row in ontology["subverticals"]}
    payload = classify_unrouted_leads(discovery, allowed, capture)
    verify_unrouted_lead_classification(payload, discovery, allowed, capture)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lead_set = {
        "schema": "ProofLaunchGTMAllSubverticalPublicLeadSetV2",
        "wave_id": "wave4-classified-unrouted",
        "record_count": len(payload["records"]),
        "source_classification_sha256": payload["content_sha256"],
        "records": payload["records"],
        "formal_candidate_quota_credit": 0,
        "truth_boundary": payload["truth_boundary"],
    }
    atomic_write_text(LEADS, json.dumps(lead_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    unrouted_records = [row for row in discovery["records"] if not row["provisional_subvertical_ids"]]
    all_unrouted = {
        "schema": "ProofLaunchGTMUnroutedPublicLeadSourceSetV2",
        "wave_id": "wave4-unrouted-source",
        "record_count": len(unrouted_records),
        "source_discovery_sha256": discovery["content_sha256"],
        "records": unrouted_records,
        "formal_candidate_quota_credit": 0,
        "truth_boundary": "These are previously unrouted public discovery leads prepared only for bounded metadata capture. They grant no route or candidate credit.",
    }
    atomic_write_text(ALL_UNROUTED, json.dumps(all_unrouted, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "leads": str(LEADS),
        "all_unrouted_leads": str(ALL_UNROUTED),
        "unrouted_input_count": payload["unrouted_input_count"],
        "provisional_route_suggestion_count": payload["provisional_route_suggestion_count"],
        "classification_gap_count": payload["classification_gap_count"],
        "represented_subvertical_count": payload["represented_subvertical_count"],
        "formal_candidate_quota_credit": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
