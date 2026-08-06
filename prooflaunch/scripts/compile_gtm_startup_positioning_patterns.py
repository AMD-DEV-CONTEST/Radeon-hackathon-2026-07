#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_startup_landscape import (
    compile_startup_positioning_patterns,
    verify_startup_positioning_patterns,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile aggregate startup positioning patterns without copying company voice or claiming effectiveness.")
    parser.add_argument("--landscape", type=Path, default=Path("evidence/v10/gtm-startup-landscape-yc-v1.json"))
    parser.add_argument(
        "--standard",
        type=Path,
        default=Path("evidence/v10/gtm-global-organic-signal-sampling-standard-v1.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-startup-positioning-patterns-yc-v1.json"))
    args = parser.parse_args()
    landscape = json.loads(args.landscape.read_text(encoding="utf-8"))
    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    patterns = compile_startup_positioning_patterns(landscape, standard)
    verify_startup_positioning_patterns(patterns, landscape, standard)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(patterns, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "profile_count": patterns["profile_count"],
                "positioning_frame_count": patterns["positioning_frame_count"],
                "content_sha256": patterns["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
