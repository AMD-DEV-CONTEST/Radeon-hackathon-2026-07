from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_public_source_capture import capture_public_sources, verify_public_source_capture


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture bounded public metadata for an all-subvertical targeted lead set.")
    parser.add_argument(
        "--leads",
        default=str(ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave1-v2.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-all-subvertical-wave1-public-capture-v2.json"),
    )
    parser.add_argument("--max-workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    leads_path = Path(args.leads).resolve()
    source = json.loads(leads_path.read_text(encoding="utf-8"))
    rows = source.get("records", source)
    if not isinstance(rows, list):
        raise SystemExit("lead input must contain a records list")
    capture_rows = [
        {"source_url": row["source_url"], "context_ids": row["provisional_subvertical_ids"]}
        for row in rows
    ]
    payload = capture_public_sources(
        capture_rows,
        captured_at=datetime.now(timezone.utc).isoformat(),
        max_workers=args.max_workers,
    )
    payload["source_lead_set"] = str(leads_path.relative_to(ROOT)) if leads_path.is_relative_to(ROOT) else str(leads_path)
    payload["source_lead_set_record_count"] = len(rows)
    unsigned = dict(payload)
    unsigned.pop("content_sha256")
    import hashlib
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    verify_public_source_capture(payload)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "requested": payload["requested_unique_source_count"],
        "status_counts": payload["status_counts"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
