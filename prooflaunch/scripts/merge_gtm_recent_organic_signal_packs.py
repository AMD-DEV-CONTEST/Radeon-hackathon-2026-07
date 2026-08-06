#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_recent_organic_signal_pack import merge_recent_organic_signal_packs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-pack", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    packs = [json.loads(path.read_text(encoding="utf-8")) for path in args.signal_pack]
    result = merge_recent_organic_signal_packs(packs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output), "sources": result["source_count"],
        "recent_90d": result["recent_item_count_preferred_window"],
        "recent_180d": result["recent_item_count_maximum_window"],
        "normalized_items": result["organic_measurement_coverage"]["same_source_normalized_item_count"],
        "relative_attention_candidates": result["organic_measurement_coverage"]["relative_attention_index_ge_2_count"],
        "content_sha256": result["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
