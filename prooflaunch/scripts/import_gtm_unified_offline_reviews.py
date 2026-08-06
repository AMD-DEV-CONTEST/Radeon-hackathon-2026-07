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

from prooflaunch_remix.gtm_unified_offline_review import (  # noqa: E402
    UnifiedOfflineReviewError,
    UnifiedOfflineReviewService,
)


DEFAULT_KIT = ROOT / "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2"
DEFAULT_STORE = ROOT / "evidence/v10/gtm-unified-human-review-v2"
GENERIC_MAPPINGS = [
    ROOT / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3/private/role-mapping.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/audio/private/role-mapping.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/video/private/role-mapping.json",
]
VISUAL_MAPPING = ROOT / "artifacts/campaign-pack-visual-blind-review-v1/campaign-pack-blind-review-private.json"
UNIFIED = ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/unified-last-mile-review.json"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import one qualified reviewer's sixteen hash-bound offline judgments. "
            "Five complete bundles produce a recommendation-only aggregate."
        )
    )
    parser.add_argument("--generic-reviews", required=True, type=_inside_project)
    parser.add_argument("--visual-review", required=True, type=_inside_project)
    parser.add_argument("--kit-dir", default=str(DEFAULT_KIT), type=_inside_project)
    parser.add_argument("--store-dir", default=str(DEFAULT_STORE), type=_inside_project)
    args = parser.parse_args()
    try:
        service = UnifiedOfflineReviewService(
            kit_root=args.kit_dir,
            store_root=args.store_dir,
            generic_mapping_paths=GENERIC_MAPPINGS,
            visual_private_path=VISUAL_MAPPING,
            unified_review_path=UNIFIED,
        )
        receipt = service.import_reviewer(
            generic_reviews_path=args.generic_reviews,
            visual_review_path=args.visual_review,
        )
    except UnifiedOfflineReviewError as error:
        parser.error(str(error))
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
