#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_evidence_packet_v2 import compile_evidence_packets, verify_evidence_packets


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    capture = json.loads((ROOT / "evidence/v10/gtm-wave1-public-source-capture-v2.json").read_text(encoding="utf-8"))
    records = []
    for index, source in enumerate(capture["records"], start=1):
        records.append({
            "packet_id": f"wave1-evidence-{index:04d}",
            "source_url": source["final_url"],
            "source_class": "official_platform",
            "access_method": source["access_method"],
            "captured_at": source["captured_at"],
            "primary_content_sha256": source["content_sha256"],
            "authentication_used": source["authentication_used"],
            "captcha_bypass_used": source["captcha_bypass_used"],
            "paywall_bypass_used": source["paywall_bypass_used"],
            "rights": {
                "publicity_status": "ordinary_public_page_at_capture_time",
                "license_status": "no_republication_license_claimed",
                "permitted_use": "bounded factual research metadata and fingerprints",
                "retention_boundary": "no raw page retained; bounded excerpt remains in the upstream capture ledger",
            },
            "surfaces": {},
        })
    payload = compile_evidence_packets(records)
    verify_evidence_packets(payload)
    output = ROOT / "evidence/v10/gtm-evidence-packets-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "packet_count": payload["packet_count"],
        "complete_packet_count": payload["complete_packet_count"],
        "surface_status_counts": payload["surface_status_counts"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
