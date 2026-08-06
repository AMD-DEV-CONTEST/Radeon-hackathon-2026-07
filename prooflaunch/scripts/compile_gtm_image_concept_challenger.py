#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-image-concept-challenger-v1.json"
ASSETS = (
    ("hero_landscape", "artifacts/gtm-last-mile-pk-v1/image-super-challenger-v1/prooflaunch-rejection-rule-key-visual-v1.png", [1672, 941]),
    ("social_4x5", "artifacts/gtm-last-mile-pk-v1/image-super-challenger-v1/prooflaunch-rejection-rule-social-4x5-v1.png", [1122, 1402]),
)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    assets = []
    for role, relative, expected in ASSETS:
        path = ROOT / relative
        with Image.open(path) as image:
            dimensions = list(image.size)
            image.verify()
        if dimensions != expected:
            raise SystemExit(f"image dimensions drifted for {relative}: {dimensions}")
        assets.append({"role": role, "path": relative, "dimensions": dimensions, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    payload = {
        "schema": "ProofLaunchImageConceptChallengerV1",
        "campaign": "The Rejection Rule Is the Product",
        "concept": "A physical decision gate diverts one seductive unsupported line into a visible quarantine tray while the approved brief continues intact.",
        "creative_rejection": "Retire the generic GPU/server/light-trail visual language for this campaign; it does not encode the organizing idea and collapses across formats.",
        "assets": assets,
        "asset_count": 2,
        "tool_mode": "built_in_image_generation",
        "generation_call_count": 2,
        "open_source_next_pass": [
            "ComfyUI graph for deterministic resize/crop/text-safe zones and reproducible export",
            "Qwen-Image or FLUX shadow regeneration against the same source-hidden concept brief",
            "OpenCLIP anti-collapse and semantic-fit checks as rejection signals only",
            "PaddleOCR and layout checks after typography is composed",
            "source-hidden five-human preference review before any replacement"
        ],
        "opponent_stress_tests": {
            "Midjourney": "ownable visual idea and art-direction finish rather than style spectacle",
            "Adobe Firefly": "editable production workflow, rights and cross-format control",
            "OpenAI Image": "prompt adherence, physical metaphor clarity and coherent reframing",
            "Imagen": "photoreal material and lighting control without generic advertising gloss",
            "FLUX": "open reproducibility and identity preservation across variants",
            "Ideogram": "typography-safe composition and later exact-copy integration",
            "Recraft": "systematic brand adaptation and vector-friendly campaign extensions",
            "Leonardo": "production controls, variants and art-direction consistency",
            "Qwen-Image": "open text/image editing route and deployable local workflow",
            "Canva": "fast editable handoff without flattening the organizing idea into a template"
        },
        "native_4k_master_present": False,
        "required_three_format_set_complete": False,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "ledger_replacement_authorized": False,
        "truth_boundary": "These are two source-bound art-direction candidates, not native-4K production masters. They have no typography, named-product baseline, human preference, publication, effect, 4A or Top-1 evidence and therefore do not replace the admitted image challenger."
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "asset_count": 2, "native_4k_master_present": False, "completed_named_product_pk_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
