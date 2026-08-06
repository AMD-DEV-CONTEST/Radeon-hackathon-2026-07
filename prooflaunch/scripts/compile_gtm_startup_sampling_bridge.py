#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_startup_landscape import (
    compile_startup_sampling_bridge,
    verify_startup_sampling_bridge,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge the startup directory population into the 140-cell/168-lane sampling standard.")
    parser.add_argument("--landscape", type=Path, default=Path("evidence/v10/gtm-startup-landscape-yc-v1.json"))
    parser.add_argument(
        "--standard",
        type=Path,
        default=Path("evidence/v10/gtm-global-organic-signal-sampling-standard-v1.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-startup-sampling-bridge-yc-v1.json"))
    args = parser.parse_args()
    landscape = json.loads(args.landscape.read_text(encoding="utf-8"))
    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    bridge = compile_startup_sampling_bridge(landscape, standard)
    verify_startup_sampling_bridge(bridge, landscape, standard)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bridge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "mapped_company_count": bridge["mapped_company_count"],
                "unmapped_market_company_count": bridge["unmapped_market_company_count"],
                "populated_segment_market_cell_count": bridge["populated_segment_market_cell_count"],
                "empty_segment_market_cell_count": bridge["empty_segment_market_cell_count"],
                "platform_market_lane_count": bridge["platform_market_lane_count"],
                "content_sha256": bridge["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
