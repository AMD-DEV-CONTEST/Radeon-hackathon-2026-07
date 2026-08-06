#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_platform_source_discovery import (
    discover_platform_source_registry,
    load_organization_seeds,
    registry_json,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum-workers", type=int, default=8)
    args = parser.parse_args()
    source = json.loads(args.seeds.read_text(encoding="utf-8"))
    registry = discover_platform_source_registry(
        load_organization_seeds(source),
        maximum_workers=args.maximum_workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, registry_json(registry))
    print(json.dumps({
        "output": str(args.output),
        "organization_seed_count": registry["organization_seed_count"],
        "completed_homepage_count": registry["completed_homepage_count"],
        "discovered_source_count": registry["discovered_source_count"],
        "content_sha256": registry["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

