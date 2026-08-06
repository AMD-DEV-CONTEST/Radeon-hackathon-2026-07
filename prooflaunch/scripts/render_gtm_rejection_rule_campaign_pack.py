#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.local_campaign_pack import LocalCampaignPackSpec, render_local_campaign_pack


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/image-super-challenger-v1"
DELIVERY = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v9-rejection-rule"


def main() -> int:
    source_image = SOURCE_ROOT / "prooflaunch-rejection-rule-key-visual-v1.png"
    source_metadata = SOURCE_ROOT / "prooflaunch-rejection-rule-key-visual-v1.metadata.json"
    evidence = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"
    spec = LocalCampaignPackSpec(
        campaign_id="prooflaunch-rejection-rule-v9",
        brand_name="ProofLaunch",
        eyebrow="The AI GTM employee with a visible no",
        headline="Give your GTM agent a brief it should refuse.",
        proof=(
            "ProofLaunch Cortex-X compiles a rights-bound brief into review-ready "
            "GTM assets. Every market outcome stays unproven until observed."
        ),
        call_to_action="Run the rejection test. See what remains unproven.",
        evidence_sha256=sha256_file(evidence),
        source_image_sha256=sha256_file(source_image),
        source_metadata_sha256=sha256_file(source_metadata),
        expected_model_id="openai/builtin-imagegen-unreported-model",
        rights_locator="project-owned://prooflaunch/rejection-rule-key-visual-v1",
        seed=0,
    )
    manifest = render_local_campaign_pack(
        spec,
        project_root=ROOT,
        source_image=source_image,
        source_metadata=source_metadata,
        output_dir=DELIVERY,
        encode_video=False,
    )
    print(json.dumps({
        "output": str(DELIVERY),
        "artifact_count": len(manifest["artifacts"]),
        "content_sha256": manifest["content_sha256"],
        "mechanical_campaign_pack_ready": manifest["quality_gates"]["mechanical_campaign_pack_ready"],
        "product_admission_passed": manifest["quality_gates"]["product_admission_passed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
