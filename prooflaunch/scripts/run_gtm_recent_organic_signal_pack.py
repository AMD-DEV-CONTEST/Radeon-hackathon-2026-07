#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_recent_organic_signal_pack import compile_recent_organic_signal_pack


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a 90–180 day rights-safe public organic signal pack.")
    parser.add_argument("--collection-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preferred-age-days", type=int, default=90)
    parser.add_argument("--maximum-age-days", type=int, default=180)
    parser.add_argument("--sampling-standard", type=Path)
    args = parser.parse_args()
    sampling_standard = (
        json.loads(args.sampling_standard.read_text(encoding="utf-8"))
        if args.sampling_standard is not None
        else None
    )
    result = compile_recent_organic_signal_pack(
        args.collection_dir,
        preferred_age_days=args.preferred_age_days,
        maximum_age_days=args.maximum_age_days,
        sampling_standard=sampling_standard,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "source_count": result["source_count"],
        "recent_90d": result["recent_item_count_preferred_window"],
        "recent_180d": result["recent_item_count_maximum_window"],
        "content_sha256": result["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
