#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.agentic_product_readiness import (
    compile_agentic_product_readiness,
)
from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the evidence-bound 12-point agentic product readiness audit."
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/agentic-product-readiness-audit.json"),
    )
    args = parser.parse_args()
    receipt = compile_agentic_product_readiness(ROOT)
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(
        output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": receipt["passed_item_count"],
                "gaps": receipt["gap_item_count"],
                "content_sha256": receipt["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
