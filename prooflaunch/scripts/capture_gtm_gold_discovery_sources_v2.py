#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_gold_case_discovery_v2 import verify_gold_case_discovery
from prooflaunch_remix.gtm_public_source_capture import (
    capture_public_sources,
    robots_permission,
    verify_public_source_capture,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture public metadata receipts for provisionally routed gold-case leads.")
    parser.add_argument(
        "--discovery",
        default=str(ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-gold-case-public-source-capture-v2.json"),
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    discovery = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
    verify_gold_case_discovery(discovery)
    routed = [row for row in discovery["records"] if row["provisional_subvertical_ids"]]
    if args.limit is not None:
        routed = routed[: max(0, args.limit)]
    source_rows = [{
        "url": row["source_url"],
        "context_ids": [row["lead_id"], *row["provisional_subvertical_ids"]],
    } for row in routed]

    robots_cache: dict[str, tuple[str, bool]] = {}
    robots_lock = Lock()

    def cached_robots(url: str) -> tuple[str, bool]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with robots_lock:
            if origin not in robots_cache:
                robots_cache[origin] = robots_permission(url)
            return robots_cache[origin]

    capture = capture_public_sources(
        source_rows,
        robots_checker=cached_robots,
        max_workers=args.max_workers,
    )
    verify_public_source_capture(capture)
    capture["source_discovery_sha256"] = discovery["content_sha256"]
    capture["routed_lead_count"] = len(routed)
    capture["robots_origin_count"] = len(robots_cache)
    # Re-seal after provenance fields are attached.
    import hashlib
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
        "routed_lead_count": len(routed),
        "status_counts": capture["status_counts"],
        "robots_origin_count": len(robots_cache),
        "content_sha256": capture["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
