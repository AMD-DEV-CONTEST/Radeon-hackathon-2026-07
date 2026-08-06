#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_cross_platform_dedup_v2 import compile_cross_platform_dedup, verify_cross_platform_dedup


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    corpus = json.loads((ROOT / "data/gtm_case_funnel_v2/candidates.json").read_text(encoding="utf-8"))
    records = []
    for candidate in corpus["candidates"]:
        records.append({
            "record_id": candidate["case_id"], "platform": candidate["platforms"][0],
            "source_url": candidate["source_receipts"][0]["source_url"], "language": "en",
            "text": f"{candidate['campaign_or_motion']} {candidate['mechanism_hypothesis']} {candidate['result_summary']}",
            "transcript": "", "perceptual_frame_hashes": [], "audio_landmark_hashes": [],
        })
    payload = compile_cross_platform_dedup(records)
    verify_cross_platform_dedup(payload)
    output = ROOT / "evidence/v10/gtm-cross-platform-dedup-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "record_count": payload["record_count"], "pair_count": payload["pair_count"], "decision_counts": payload["decision_counts"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
