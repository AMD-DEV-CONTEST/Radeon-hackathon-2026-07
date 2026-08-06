#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_breakout_evidence import (
    compile_case_promotion_queue,
    verify_case_promotion_queue,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the five-evidence audit queue for breakout discovery cases.")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("evidence/v10/gtm-breakout-expanded-case-index-v2.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/v10/gtm-breakout-case-promotion-queue-v2.json"),
    )
    args = parser.parse_args()
    index = json.loads(args.index.read_text(encoding="utf-8"))
    queue = compile_case_promotion_queue(index)
    verify_case_promotion_queue(queue, index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": queue["case_count"],
                "audit_unit_count": queue["audit_unit_count"],
                "priority_band_counts": queue["priority_band_counts"],
                "content_sha256": queue["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
