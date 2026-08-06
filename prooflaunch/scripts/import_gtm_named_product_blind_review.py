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

from prooflaunch_remix.gtm_named_product_pk import (  # noqa: E402
    NamedProductPKError,
    NamedProductPKReviewService,
)


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Import one hash-bound named-product human blind review.")
    parser.add_argument("--packet-dir", required=True, type=_inside_project)
    parser.add_argument("--review", required=True, type=_inside_project)
    parser.add_argument("--store-dir", required=True, type=_inside_project)
    args = parser.parse_args()
    try:
        service = NamedProductPKReviewService(packet_root=args.packet_dir, store_root=args.store_dir)
        receipt = service.submit(args.review)
    except NamedProductPKError as error:
        parser.error(str(error))
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
