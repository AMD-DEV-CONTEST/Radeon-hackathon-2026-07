#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_gold_case_discovery_v2 import (
    compile_gold_case_discovery,
    verify_gold_case_discovery,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile zero-credit public case-directory discoveries for the ten golden GTM subverticals."
    )
    parser.add_argument(
        "--hubspot-html",
        action="append",
        required=True,
        help="A locally captured public HubSpot case-directory HTML file; may be repeated.",
    )
    parser.add_argument("--tiktok-html", action="append", default=[])
    parser.add_argument("--tiktok-url", action="append", default=[])
    parser.add_argument("--gorilla76-html", action="append", default=[])
    parser.add_argument("--gorilla76-url", action="append", default=[])
    parser.add_argument("--athena-html", action="append", default=[])
    parser.add_argument("--athena-url", action="append", default=[])
    parser.add_argument(
        "--targeted-leads-json",
        help="Optional zero-credit operator-reviewed public case-page lead list.",
    )
    parser.add_argument(
        "--hubspot-url",
        action="append",
        required=True,
        help="The public directory URL corresponding to each --hubspot-html input.",
    )
    parser.add_argument(
        "--captured-at",
        default=datetime.now(timezone.utc).isoformat(),
        help="UTC capture timestamp recorded in the derived receipt.",
    )
    parser.add_argument("--research-cutoff", default="2026-08-05")
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if len(args.hubspot_html) != len(args.hubspot_url):
        raise SystemExit("each --hubspot-html requires one corresponding --hubspot-url")
    if len(args.tiktok_html) != len(args.tiktok_url):
        raise SystemExit("each --tiktok-html requires one corresponding --tiktok-url")
    if len(args.gorilla76_html) != len(args.gorilla76_url):
        raise SystemExit("each --gorilla76-html requires one corresponding --gorilla76-url")
    if len(args.athena_html) != len(args.athena_url):
        raise SystemExit("each --athena-html requires one corresponding --athena-url")
    snapshots = []
    for html_path, source_url in zip(args.hubspot_html, args.hubspot_url, strict=True):
        path = Path(html_path)
        html_text = path.read_text(encoding="utf-8", errors="replace")
        snapshots.append({
            "source_family_id": "hubspot_case_directory",
            "source_url": source_url,
            "captured_at": args.captured_at,
            "content_sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            "html_text": html_text,
        })
    for html_path, source_url in zip(args.tiktok_html, args.tiktok_url, strict=True):
        path = Path(html_path)
        html_text = path.read_text(encoding="utf-8", errors="replace")
        snapshots.append({
            "source_family_id": "tiktok_business_success_stories",
            "source_url": source_url,
            "captured_at": args.captured_at,
            "content_sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            "html_text": html_text,
        })
    for html_path, source_url in zip(args.gorilla76_html, args.gorilla76_url, strict=True):
        path = Path(html_path)
        html_text = path.read_text(encoding="utf-8", errors="replace")
        snapshots.append({
            "source_family_id": "gorilla76_industrial_case_directory",
            "source_url": source_url,
            "captured_at": args.captured_at,
            "content_sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            "html_text": html_text,
        })
    for html_path, source_url in zip(args.athena_html, args.athena_url, strict=True):
        path = Path(html_path)
        html_text = path.read_text(encoding="utf-8", errors="replace")
        snapshots.append({
            "source_family_id": "athena_manufacturing_case_directory",
            "source_url": source_url,
            "captured_at": args.captured_at,
            "content_sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            "html_text": html_text,
        })
    targeted_leads = []
    if args.targeted_leads_json:
        targeted_payload = json.loads(Path(args.targeted_leads_json).read_text(encoding="utf-8"))
        targeted_leads = targeted_payload.get("records", targeted_payload)
        if not isinstance(targeted_leads, list):
            raise SystemExit("--targeted-leads-json must contain a list or a records list")
    payload = compile_gold_case_discovery(
        snapshots,
        research_cutoff=args.research_cutoff,
        targeted_leads=targeted_leads,
    )
    verify_gold_case_discovery(payload)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "unique_discovery_lead_count": payload["unique_discovery_lead_count"],
        "provisionally_routed_lead_count": payload["provisionally_routed_lead_count"],
        "unrouted_lead_count": payload["unrouted_lead_count"],
        "query_matrix_count": payload["query_matrix_count"],
        "targeted_lead_count": payload["targeted_lead_count"],
        "routing_counts": payload["routing_counts"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
