#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_public_source_capture import (
    capture_public_sources,
    default_fetch,
    robots_permission,
    verify_public_source_capture,
)


ROOT = Path(__file__).resolve().parents[1]


def _source_rows(seed_path: Path, award_path: Path) -> list[dict]:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    awards = json.loads(award_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for team in seed.get("teams", []):
        for source in team.get("sources", []):
            rows.append({"url": source.get("url"), "context_ids": [f"team:{team.get('team_id')}"]})
    for case in awards.get("cases", []):
        rows.append({"url": case.get("source_url"), "context_ids": [f"award:{case.get('case_id')}"]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture bounded metadata and hashes for approved public GTM case sources.")
    parser.add_argument("--seed", type=Path, default=ROOT / "evidence/v10/gtm-breakout-quality-team-seed-v1.json")
    parser.add_argument("--awards", type=Path, default=ROOT / "evidence/v10/gtm-breakout-expanded-case-index-v2.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/v10/gtm-public-case-source-capture-v1.json")
    args = parser.parse_args()
    ledger = capture_public_sources(
        _source_rows(args.seed, args.awards),
        fetcher=lambda url: default_fetch(url, timeout=8.0),
        robots_checker=lambda url: robots_permission(url, timeout=4.0),
        max_workers=8,
    )
    verify_public_source_capture(ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "requested_unique_source_count": ledger["requested_unique_source_count"],
        "status_counts": ledger["status_counts"],
        "content_sha256": ledger["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
