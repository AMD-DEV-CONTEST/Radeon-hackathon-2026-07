#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_claim_surface_v2 import (
    compile_case_claim_surfaces,
    verify_case_claim_surfaces,
)
from prooflaunch_remix.gtm_gold_case_discovery_v2 import verify_gold_case_discovery
from prooflaunch_remix.gtm_public_source_capture import (
    default_fetch,
    robots_permission,
    verify_public_source_capture,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract bounded review surfaces from public gold-case pages.")
    parser.add_argument("--discovery", default=str(ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json"))
    parser.add_argument(
        "--source-capture",
        default=str(ROOT / "evidence/v10/gtm-gold-case-public-source-capture-v2.json"),
    )
    parser.add_argument("--output", default=str(ROOT / "evidence/v10/gtm-gold-case-claim-surfaces-v2.json"))
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.max_workers <= 16:
        raise SystemExit("--max-workers must be in [1, 16]")
    discovery = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
    source_capture = json.loads(Path(args.source_capture).read_text(encoding="utf-8"))
    verify_gold_case_discovery(discovery)
    verify_public_source_capture(source_capture)
    successful_urls = [
        row["source_url"] for row in source_capture["records"]
        if row["capture_status"] == "captured_metadata_only"
    ]
    if args.limit is not None:
        successful_urls = successful_urls[: max(0, args.limit)]
    captured_at = datetime.now(timezone.utc).isoformat()

    robots_cache: dict[str, tuple[str, bool]] = {}
    robots_lock = Lock()

    def fetch_one(url: str) -> tuple[str, dict]:
        origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
        try:
            with robots_lock:
                if origin not in robots_cache:
                    robots_cache[origin] = robots_permission(url)
                robots_status, allowed = robots_cache[origin]
            if not allowed:
                return "failure", {"source_url": url, "failure_type": "blocked_by_robots", "robots_status": robots_status, "quota_credit": 0}
            response = default_fetch(url)
            if response.status != 200 or "html" not in response.content_type.casefold():
                return "failure", {
                    "source_url": url,
                    "failure_type": "unsupported_response",
                    "http_status": response.status,
                    "content_type": response.content_type,
                    "quota_credit": 0,
                }
            html_text = response.body.decode("utf-8", errors="replace")
            return "success", {
                "source_url": url,
                "captured_at": captured_at,
                "content_sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
                "html_text": html_text,
            }
        except Exception as error:
            return "failure", {
                "source_url": url,
                "failure_type": type(error).__name__,
                "error_summary": str(error)[:300],
                "quota_credit": 0,
            }

    captures: list[dict] = []
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.max_workers, thread_name_prefix="gtm-claim-surface") as executor:
        for status, row in executor.map(fetch_one, successful_urls):
            (captures if status == "success" else failures).append(row)
    payload = compile_case_claim_surfaces(discovery, captures, failures)
    payload["source_public_capture_sha256"] = source_capture["content_sha256"]
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    verify_case_claim_surfaces(payload)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "record_count": payload["record_count"],
        "capture_failure_count": payload["capture_failure_count"],
        "four_surface_signal_count": payload["four_surface_signal_count"],
        "status_counts": payload["status_counts"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
