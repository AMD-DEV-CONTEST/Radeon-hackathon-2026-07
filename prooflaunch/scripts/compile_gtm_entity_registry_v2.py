#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_entity_registry_v2 import compile_entity_registry, stable_entity_id, verify_entity_registry


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    corpus = json.loads((ROOT / "data/gtm_case_funnel_v2/candidates.json").read_text(encoding="utf-8"))
    entities = []
    relationships = []
    for candidate in corpus["candidates"]:
        receipts = [row["content_sha256"] for row in candidate["source_receipts"]]
        company_id = stable_entity_id("company", candidate["company"])
        product_name = f"{candidate['company']} · {candidate['product']}"
        product_id = stable_entity_id("product", product_name)
        campaign_name = f"{candidate['company']} · {candidate['campaign_or_motion']} · {candidate['observed_start']}"
        campaign_id = stable_entity_id("campaign", campaign_name)
        entities.extend([
            {"entity_id": company_id, "entity_kind": "company", "canonical_name": candidate["company"], "market_scope": [candidate["quota_market"]], "source_receipt_sha256s": receipts, "aliases": []},
            {"entity_id": product_id, "entity_kind": "product", "canonical_name": product_name, "market_scope": [candidate["quota_market"]], "source_receipt_sha256s": receipts, "aliases": []},
            {"entity_id": campaign_id, "entity_kind": "campaign", "canonical_name": campaign_name, "market_scope": [candidate["quota_market"]], "source_receipt_sha256s": receipts, "aliases": []},
        ])
        relationships.extend([
            {"source_entity_id": product_id, "target_entity_id": company_id, "relationship_type": "product_of", "valid_from": candidate["observed_start"], "valid_to": candidate["observed_end"], "market_scope": [candidate["quota_market"]], "source_receipt_sha256s": receipts, "human_review_status": "candidate_source_bound"},
            {"source_entity_id": campaign_id, "target_entity_id": company_id, "relationship_type": "campaign_of", "valid_from": candidate["observed_start"], "valid_to": candidate["observed_end"], "market_scope": [candidate["quota_market"]], "source_receipt_sha256s": receipts, "human_review_status": "candidate_source_bound"},
        ])
    payload = compile_entity_registry(entities, relationships)
    verify_entity_registry(payload)
    output = ROOT / "evidence/v10/gtm-entity-registry-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "entity_count": payload["entity_count"], "relationship_count": payload["relationship_count"], "ambiguous_alias_count": len(payload["ambiguous_aliases"]), "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
