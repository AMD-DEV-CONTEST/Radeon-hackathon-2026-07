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

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_platform_native_publication_audit import (  # noqa: E402
    compile_platform_native_publication_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit B2B/B2C local platform challengers for direct-publication blockers."
    )
    parser.add_argument(
        "--root",
        default="artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1",
    )
    parser.add_argument(
        "--output",
        default="evidence/v10/gtm-platform-native-publication-audit-v1.json",
    )
    parser.add_argument("--b2b-plan")
    parser.add_argument("--b2b-receipt")
    parser.add_argument("--b2c-plan")
    parser.add_argument("--b2c-receipt")
    args = parser.parse_args()
    source_root = (ROOT / args.root).resolve()
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT)
    inputs = (
        (
            (ROOT / args.b2b_plan).resolve() if args.b2b_plan else source_root / "b2b-plan.json",
            (ROOT / args.b2b_receipt).resolve() if args.b2b_receipt else source_root / "b2b-local-gemma3-final-receipt.json",
        ),
        (
            (ROOT / args.b2c_plan).resolve() if args.b2c_plan else source_root / "b2c-plan.json",
            (ROOT / args.b2c_receipt).resolve() if args.b2c_receipt else source_root / "b2c-local-gemma3-v1-receipt.json",
        ),
    )
    for plan, receipt in inputs:
        plan.relative_to(ROOT)
        receipt.relative_to(ROOT)
    bundles = [
        (
            json.loads(plan.read_text(encoding="utf-8")),
            json.loads(receipt.read_text(encoding="utf-8")),
        )
        for plan, receipt in inputs
    ]
    audit = compile_platform_native_publication_audit(bundles)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "row_count": audit["row_count"],
                "mechanically_publication_ready_count": audit[
                    "mechanically_publication_ready_count"
                ],
                "blocked_count": audit["blocked_count"],
                "cross_surface_duplicate_pair_count": audit[
                    "cross_surface_duplicate_pair_count"
                ],
                "content_sha256": audit["content_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
