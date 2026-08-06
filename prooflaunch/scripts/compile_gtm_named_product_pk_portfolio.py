#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_named_product_pk import (  # noqa: E402
    NamedProductPKError,
    compile_named_product_pk_portfolio,
)


DEFAULT_MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
DEFAULT_LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
DEFAULT_AGGREGATES = ROOT / "evidence/v10/named-product-pk-reviews-v1"
DEFAULT_OUTPUT = ROOT / "evidence/v10/named-product-pk-portfolio-v1.json"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the 13-category/130-product named PK truth state.")
    parser.add_argument("--capture-manifest", default=str(DEFAULT_MANIFEST), type=_inside_project)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER), type=_inside_project)
    parser.add_argument("--aggregate-root", default=str(DEFAULT_AGGREGATES), type=_inside_project)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), type=_inside_project)
    args = parser.parse_args()
    try:
        portfolio = compile_named_product_pk_portfolio(
            capture_manifest_path=args.capture_manifest,
            ledger_path=args.ledger,
            aggregate_root=args.aggregate_root,
        )
    except NamedProductPKError as error:
        parser.error(str(error))
    atomic_write_text(args.output, json.dumps(portfolio, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "completed_product_pk_rows": portfolio["completed_product_pk_rows"],
        "candidate_won_product_pk_rows": portfolio["candidate_won_product_pk_rows"],
        "effect_aligned_category_count": portfolio["effect_aligned_category_count"],
        "content_sha256": portfolio["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
