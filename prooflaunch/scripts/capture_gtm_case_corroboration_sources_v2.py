#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_public_source_capture import capture_public_sources, verify_public_source_capture


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture bounded public metadata for corroboration leads.")
    parser.add_argument(
        "--sources",
        default=str(ROOT / "data/gtm_case_funnel_v2/corroboration-public-leads-v2.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-case-corroboration-public-capture-v2.json"),
    )
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()
    source_payload = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    records = source_payload.get("records", source_payload)
    capture = capture_public_sources(
        ({"url": row["source_url"], "context_ids": [row["lead_id"]]} for row in records),
        max_workers=args.max_workers,
    )
    capture["source_input_sha256"] = hashlib.sha256(
        json.dumps(source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    unsigned = dict(capture)
    unsigned.pop("content_sha256", None)
    capture["content_sha256"] = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    verify_public_source_capture(capture)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "record_count": capture["record_count"],
        "status_counts": capture["status_counts"],
        "content_sha256": capture["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
