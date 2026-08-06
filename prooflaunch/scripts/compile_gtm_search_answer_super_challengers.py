#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_search_answer_named_pk import GEO_SCHEMA, SEO_SCHEMA, compile_search_answer, verify


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/search-answer-super-challengers-v1"


def _binding(role: str, relative: str) -> dict[str, object]:
    path = ROOT / relative
    return {"role": role, "path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def main() -> int:
    config = json.loads((ROOT / "config/codex-search-answer-super-challengers-v1.json").read_text(encoding="utf-8"))
    evidence = [
        _binding("approved_claim_and_assets", "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"),
        _binding("lifecycle_authority", "artifacts/gtm-last-mile-pk-v1/gtm-lifecycle-super-challenger-v1/gtm-lifecycle-execution-dossier.json"),
        _binding("measurement_boundary", "artifacts/gtm-last-mile-pk-v1/decision-intelligence-super-challengers-v1/product-analytics-measurement-system.json"),
    ]
    seo, geo, document = compile_search_answer(config, evidence=evidence)
    verify(seo, SEO_SCHEMA)
    verify(geo, GEO_SCHEMA)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    seo_path = OUTPUT / "seo-technical-execution.json"
    geo_path = OUTPUT / "seo-geo-faq-drafts.json"
    page_path = OUTPUT / "ai-gtm-agent-evaluation.html"
    atomic_write_text(seo_path, json.dumps(seo, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(geo_path, json.dumps(geo, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(page_path, document)
    print(json.dumps({"outputs": [str(seo_path), str(geo_path), str(page_path)], "seo_products": 10, "geo_products": 10, "faq_count": 6, "completed_named_product_pk_count": 0, "seo_sha256": seo["content_sha256"], "geo_sha256": geo["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
