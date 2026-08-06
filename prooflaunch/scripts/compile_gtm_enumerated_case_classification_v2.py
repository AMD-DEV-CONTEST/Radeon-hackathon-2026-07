#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_enumerated_case_classifier_v2 import (
    classify_enumerated_cases,
    verify_enumerated_case_classification,
)


ROOT = Path(__file__).resolve().parents[1]
DELTA = ROOT / "evidence/v10/gtm-public-case-enumeration-delta-v2.json"
CAPTURE = ROOT / "evidence/v10/gtm-all-subvertical-wave7-enumerated-public-capture-v2.json"
ONTOLOGY = ROOT / "evidence/v10/gtm-subvertical-ontology-v1.json"
OUTPUT = ROOT / "evidence/v10/gtm-enumerated-case-classification-v2.json"
LEADS = ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave7-classified-v2.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    delta, capture, ontology = _load(DELTA), _load(CAPTURE), _load(ONTOLOGY)
    allowed = {row["subvertical_id"] for row in ontology["subverticals"]}
    payload = classify_enumerated_cases(delta, capture, allowed)
    verify_enumerated_case_classification(payload, delta, capture, allowed)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lead_set = {
        "schema": "ProofLaunchGTMAllSubverticalPublicLeadSetV2",
        "wave_id": "wave7-classified-public-case-metadata",
        "record_count": len(payload["records"]),
        "source_classification_sha256": payload["content_sha256"],
        "records": payload["records"],
        "formal_candidate_quota_credit": 0,
        "truth_boundary": payload["truth_boundary"],
    }
    atomic_write_text(LEADS, json.dumps(lead_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "leads": str(LEADS),
        "input_count": payload["input_count"],
        "provisional_route_suggestion_count": payload["provisional_route_suggestion_count"],
        "classification_gap_count": payload["classification_gap_count"],
        "represented_subvertical_count": payload["represented_subvertical_count"],
        "route_counts": payload["route_counts"],
        "formal_candidate_quota_credit": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
