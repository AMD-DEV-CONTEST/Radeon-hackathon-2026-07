#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
import sys

if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.local_multimodal_renderer import (
    LocalMultimodalRenderer,
    MultimodalRenderSpec,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/aug3-multimodal-demo"),
    )
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error

    readiness = ROOT / "evidence/v10/aug3-product-readiness.json"
    effect_contract = ROOT / "docs/product/GTM_EFFECT_FIRST_EXECUTION_CONTRACT_V1.md"
    spec = MultimodalRenderSpec(
        campaign_id="prooflaunch-aug3-zero-budget",
        brand_name="ProofLaunch",
        headline="A GTM plan should earn the next decision—not merely generate more content.",
        proof=(
            "The frozen Aug 3 readiness receipt seals 211 passing product-critical local "
            "tests while keeping human-effect and Radeon gates explicitly unproven."
        ),
        call_to_action="Inspect the proof. Challenge the gap. Approve manually.",
        evidence_sha256=sha256_file(readiness),
        source_pack_sha256=sha256_file(effect_contract),
        rights_locator="project-owned://prooflaunch/aug3-demo-v1",
        voiceover_script=(
            "A GTM plan should earn the next decision, not merely generate more content. "
            "ProofLaunch puts approved evidence before the promise, turns every campaign "
            "into a measurable learning loop, and keeps release in human hands. "
            "Inspect the proof. Challenge the gap. Approve manually."
        ),
        accent_hex="#7C5CFF",
    )
    receipt = LocalMultimodalRenderer(project_root=ROOT).render(
        spec,
        output,
        encode_video=not args.no_video,
        synthesize_audio=not args.no_audio,
        seconds_per_scene=4.1,
    )
    summary = {
        "schema": "ProofLaunchAug3MultimodalDemoReceiptV1",
        "campaign_id": receipt.campaign_id,
        "manifest_path": str(Path(receipt.manifest_path).relative_to(ROOT)),
        "manifest_sha256": receipt.manifest_sha256,
        "rendered_modalities": receipt.rendered_modalities,
        "artifacts": [artifact.__dict__ for artifact in receipt.artifacts],
        "source_evidence": {
            "readiness_path": str(readiness.relative_to(ROOT)),
            "readiness_sha256": sha256_file(readiness),
            "effect_contract_path": str(effect_contract.relative_to(ROOT)),
            "effect_contract_sha256": sha256_file(effect_contract),
        },
        "external_publish_executed": False,
        "human_blind_review_completed": False,
        "four_a_effect_proven": False,
        "radeon_inference_executed": False,
        "truth_boundary": (
            "This receipt proves that local image, video, audio, and caption files were "
            "rendered and content-addressed. It does not prove 4A preference, production "
            "effect, external publication, business lift, or Radeon-local inference."
        ),
    }
    summary_path = output / "demo-receipt.json"
    atomic_write_text(
        summary_path,
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    summary_path.chmod(0o600)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
