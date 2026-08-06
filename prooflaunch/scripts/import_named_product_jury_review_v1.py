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


LANES = {
    "image": "named-product-pk-qwen-image-v2",
    "image_openai": "named-product-pk-openai-image-v1",
    "audio": "named-product-pk-qwen3-tts-v1",
    "memory": "named-product-pk-mem0-v2",
    "memory_letta": "named-product-pk-letta-v1",
    "memory_memos": "named-product-pk-memos-v2",
    "scheduling_postiz": "named-product-pk-postiz-v1",
}
ARTIFACT_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1"
REVIEW_ROOT = ROOT / "evidence/v10/named-product-pk-reviews-v1"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "review JSON must be copied inside the project before import"
        ) from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import one real, hash-bound human review into a named-product jury lane."
    )
    parser.add_argument("--lane", required=True, choices=sorted(LANES))
    parser.add_argument("--review", required=True, type=_inside_project)
    args = parser.parse_args()

    packet_root = ARTIFACT_ROOT / LANES[args.lane] / "review-packet"
    receipt = json.loads((packet_root / "packet-receipt.json").read_text(encoding="utf-8"))
    store_root = REVIEW_ROOT / receipt["capture_slot_id"]
    try:
        result = NamedProductPKReviewService(
            packet_root=packet_root,
            store_root=store_root,
        ).submit(args.review)
    except NamedProductPKError as error:
        parser.error(str(error))

    print(json.dumps({"lane": args.lane, **result}, ensure_ascii=False, indent=2, sort_keys=True))
    print("Run: .venv/bin/python scripts/compile_gtm_named_product_pk_live_status.py")
    print("Run: .venv/bin/python scripts/compile_named_product_blind_jury_console_v1.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
