#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main() -> None:
    html_path = OUTPUT / "card.html"
    scene_path = OUTPUT / "performance-review-scene.png"
    card_path = OUTPUT / "prooflaunch-performance-review-1080x1350.png"
    for path in (html_path, scene_path, card_path):
        if not path.is_file():
            raise SystemExit(f"missing share-card dependency: {path}")
    html = html_path.read_text(encoding="utf-8")
    for marker in (
        "We put our own AI",
        "on probation.",
        "INDEPENDENT",
        "Grade the",
        "Not the model.",
        "NO PREFERENCE · VIRALITY · CONVERSION · REVENUE EVIDENCE YET",
    ):
        if marker not in html:
            raise SystemExit(f"share-card craft contract drifted: {marker}")
    receipt = {
        "schema": "ProofLaunchClaimTrialShareCardReceiptV2",
        "artifact_id": "claim-trial-share-card-v2",
        "format": "social_feed_4x5",
        "width": 1080,
        "height": 1350,
        "concept": "AI employee performance review",
        "campaign_tension": "The product applies its evidence standard to its own 4A claim.",
        "verified_candidate_count": 26,
        "selected_campaign_nucleus_count": 1,
        "image_generation_role": "original_textless_editorial_scene_only",
        "typography_rendering_role": "deterministic_html_css_overlay",
        "automatic_publish_enabled": False,
        "human_preference_observed": False,
        "named_product_win_observed": False,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (html_path, scene_path, card_path)
        ],
        "truth_boundary": (
            "This is an original candidate key visual rendered from a generated textless scene and deterministic "
            "typography. It has not yet received independent human preference, publication, organic breakout, "
            "conversion, revenue, 4A quality or named-product superiority evidence."
        ),
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(card_path), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
