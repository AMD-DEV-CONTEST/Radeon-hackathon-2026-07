#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_decision_intelligence_named_pk import MEMO_SCHEMA, MEASUREMENT_SCHEMA, compile_decision_intelligence, verify


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/decision-intelligence-super-challengers-v1"


def _binding(role: str, relative: str) -> dict[str, object]:
    path = ROOT / relative
    return {"role": role, "path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def main() -> int:
    config = json.loads((ROOT / "config/codex-decision-intelligence-super-challengers-v1.json").read_text(encoding="utf-8"))
    lineage = [
        _binding("text_candidate", "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"),
        _binding("content_schedule", "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v1/content-calendar.json"),
        _binding("image_candidate", "evidence/v10/local-campaign-pack-v1/delivery-v9-rejection-rule/campaign-pack-manifest.json"),
        _binding("video_candidate", "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json"),
        _binding("public_named_product_distribution_baseline", "artifacts/gtm-last-mile-pk-v1/public-youtube-ai-product-baseline-v1/named-product-youtube-baseline.json"),
    ]
    memo, measurement = compile_decision_intelligence(config, lineage=lineage)
    verify(memo, MEMO_SCHEMA)
    verify(measurement, MEASUREMENT_SCHEMA)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    memo_path = OUTPUT / "data-strategy-decision-memo.json"
    measurement_path = OUTPUT / "product-analytics-measurement-system.json"
    atomic_write_text(memo_path, json.dumps(memo, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(measurement_path, json.dumps(measurement, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outputs": [str(memo_path), str(measurement_path)], "data_strategy_products": 10, "analytics_products": 10, "completed_named_product_pk_count": 0, "memo_sha256": memo["content_sha256"], "measurement_sha256": measurement["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
