#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_identity_resolution_v2 import (
    compile_case_identity_resolution,
    verify_case_identity_resolution,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    source_path = ROOT / "data/gtm_case_funnel_v2/candidates.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    records = []
    for candidate in source.get("candidates", []):
        records.append({
            "record_id": candidate["case_id"],
            "company": candidate["company"],
            "company_domain": candidate.get("company_domain", ""),
            "product": candidate["product"],
            "campaign_or_motion": candidate["campaign_or_motion"],
            "primary_market": candidate["quota_market"],
            "observed_start": candidate["observed_start"],
            "observed_end": candidate["observed_end"],
            "source_urls": [row["source_url"] for row in candidate.get("source_receipts", [])],
            "quota_credit": candidate.get("quota_credit", 0),
        })
    payload = compile_case_identity_resolution(records)
    verify_case_identity_resolution(payload)
    output = ROOT / "evidence/v10/gtm-case-identity-resolution-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "record_count": payload["record_count"],
        "unique_entity_count": payload["unique_entity_count"],
        "unique_episode_count": payload["unique_episode_count"],
        "exact_mirror_count": payload["exact_mirror_count"],
        "fuzzy_review_count": payload["fuzzy_review_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
