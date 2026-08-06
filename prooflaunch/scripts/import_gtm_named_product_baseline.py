#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_named_product_baseline import import_capture


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v2/manifest.json"
DEFAULT_STORE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    path.relative_to(ROOT)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=_inside_project, default=DEFAULT_MANIFEST)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--store", type=_inside_project, default=DEFAULT_STORE)
    args = parser.parse_args()
    registry = import_capture(
        manifest_path=args.manifest,
        capture_path=args.capture.expanduser().resolve(),
        artifact_path=args.artifact.expanduser().resolve(),
        store_root=args.store,
    )
    print(json.dumps({"authorized_baselines": registry["authorized_baseline_count"], "remaining": registry["remaining_baseline_count"], "content_sha256": registry["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
