#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_gold_case_discovery_v2 import (
    extend_gold_case_discovery,
    verify_gold_case_discovery,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append public, zero-credit targeted leads without discarding sealed directory lineage."
    )
    parser.add_argument(
        "--discovery",
        default=str(ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json"),
    )
    parser.add_argument(
        "--targeted-leads-json",
        required=True,
        help="A JSON list, or an object containing a records list, of public case-page leads.",
    )
    parser.add_argument("--research-cutoff", default="2026-08-05")
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    discovery = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
    verify_gold_case_discovery(discovery)
    targeted_payload = json.loads(Path(args.targeted_leads_json).read_text(encoding="utf-8"))
    targeted_leads = targeted_payload.get("records", targeted_payload)
    if not isinstance(targeted_leads, list):
        raise SystemExit("--targeted-leads-json must contain a list or a records list")
    before_counts = dict(discovery["routing_counts"])
    before_leads = discovery["unique_discovery_lead_count"]
    payload = extend_gold_case_discovery(
        discovery,
        targeted_leads,
        research_cutoff=args.research_cutoff,
    )
    verify_gold_case_discovery(payload)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "before_unique_discovery_lead_count": before_leads,
        "after_unique_discovery_lead_count": payload["unique_discovery_lead_count"],
        "new_unique_discovery_leads": payload["unique_discovery_lead_count"] - before_leads,
        "targeted_receipt_count": payload["targeted_lead_count"],
        "routing_deltas": {
            key: payload["routing_counts"][key] - before_counts.get(key, 0)
            for key in payload["routing_counts"]
        },
        "candidate_quota_credit": 0,
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
