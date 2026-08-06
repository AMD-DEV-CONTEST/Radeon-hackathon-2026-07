#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard
from prooflaunch_remix.gtm_subvertical_ontology_v1 import build_ontology, verify_ontology


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    standard = build_case_evidence_funnel_standard()
    payload = build_ontology(standard["subverticals"])
    verify_ontology(payload)
    output = ROOT / "evidence/v10/gtm-subvertical-ontology-v1.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "ontology_version": payload["ontology_version"], "subvertical_count": payload["subvertical_count"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
