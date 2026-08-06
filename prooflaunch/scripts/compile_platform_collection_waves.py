#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.ledger import canonical_json


PLATFORM_ORDER = (
    "tiktok", "pinterest", "reddit", "bluesky", "mastodon",
    "linkedin", "instagram", "x", "facebook",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--maximum-items", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--only-unexecuted", action="store_true")
    args = parser.parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    if queue.get("schema") != "ProofLaunchPlatformMarketExpansionQueueV1":
        raise SystemExit("unsupported platform expansion queue")
    candidates = {platform: [] for platform in PLATFORM_ORDER}
    seen_sha = set()
    for lane in queue.get("lanes", []):
        platform = lane.get("platform")
        if platform not in candidates:
            continue
        for slot in lane.get("source_slots", []):
            url = slot.get("source_url")
            source_sha = slot.get("source_url_sha256")
            if args.only_unexecuted and str(slot.get("status", "")).startswith("executed_"):
                continue
            if not url or source_sha in seen_sha:
                continue
            seen_sha.add(source_sha)
            candidates[platform].append({
                "url": url,
                "context": {
                    "business_model": lane["business_model"],
                    "vertical": slot["vertical"],
                    "company_scale": slot["company_scale"],
                    "lifecycle": slot["lifecycle"],
                    "market": lane["market"],
                },
                "organization_id": slot["organization_id"],
                "source_url_sha256": source_sha,
            })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    waves = []
    for platform in PLATFORM_ORDER:
        rows = candidates[platform]
        if not rows:
            continue
        request = {
            "urls": [row["url"] for row in rows],
            "platform_hints": [platform] * len(rows),
            "source_contexts": [row["context"] for row in rows],
            "modalities": ["content", "metadata"],
            "rights": "public_measurement",
            "maximum_items": args.maximum_items,
            "maximum_bytes": 50_000_000,
            "timeout_seconds": args.timeout_seconds,
            "retention_days": 30,
        }
        filename = f"wave-{PLATFORM_ORDER.index(platform) + 1:02d}-{platform}.json"
        atomic_write_text(
            args.output_dir / filename,
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        waves.append({
            "platform": platform,
            "request_file": filename,
            "source_count": len(rows),
            "source_url_sha256s": [row["source_url_sha256"] for row in rows],
            "status": "planned_not_executed",
        })
    manifest = {
        "schema": "ProofLaunchPlatformCollectionWaveManifestV1",
        "queue_sha256": queue["content_sha256"],
        "wave_count": len(waves),
        "source_count": sum(row["source_count"] for row in waves),
        "maximum_items_per_source": args.maximum_items,
        "timeout_seconds_per_source": args.timeout_seconds,
        "only_unexecuted": args.only_unexecuted,
        "waves": waves,
        "truth_boundary": "These waves contain homepage-discovered public candidates. Planning a wave is not a completed crawl or observed coverage.",
    }
    manifest["content_sha256"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    atomic_write_text(
        args.output_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "wave_count": manifest["wave_count"],
        "source_count": manifest["source_count"],
        "content_sha256": manifest["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
