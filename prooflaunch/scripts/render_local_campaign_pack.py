#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.local_campaign_pack import (
    LocalCampaignPackSpec,
    render_local_campaign_pack,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "evidence/v10/local-campaign-pack-v1"
DELIVERY = SOURCE_ROOT / "delivery-v8"
FFMPEG = (
    ROOT.parent
    / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
)
VOICE = ROOT / "artifacts/local-multimodal-qualification-v1/qwen3-tts/proof-before-promise-master.wav"
MUSIC = (
    ROOT.parent
    / "tapnow-libtv-local-studio/mlx-worker/state/outputs/audio-f234ca65ab60.wav"
)


def main() -> int:
    source_image = SOURCE_ROOT / "openai-imagegen-proof-observatory-challenger-v2.png"
    source_metadata = (
        SOURCE_ROOT / "openai-imagegen-proof-observatory-challenger-v2.metadata.json"
    )
    readiness = ROOT / "evidence/v10/aug3-product-readiness.json"
    spec = LocalCampaignPackSpec(
        campaign_id="prooflaunch-evidence-to-momentum-v8",
        brand_name="ProofLaunch",
        eyebrow="Autonomous GTM employee · from evidence to momentum",
        headline="Make every growth move earn its momentum.",
        proof=(
            "456 governed GTM contexts. 130 named-product PK jobs frozen. "
            "Every outward action remains human-governed."
        ),
        call_to_action=(
            "See the proof. Pressure-test the plan. Release only what earns trust."
        ),
        evidence_sha256=sha256_file(readiness),
        source_image_sha256=sha256_file(source_image),
        source_metadata_sha256=sha256_file(source_metadata),
        expected_model_id="openai/builtin-imagegen-unreported-model",
        rights_locator=(
            "project-owned://prooflaunch/openai-imagegen-proof-observatory-challenger-v2"
        ),
        seed=0,
    )
    manifest = render_local_campaign_pack(
        spec,
        project_root=ROOT,
        source_image=source_image,
        source_metadata=source_metadata,
        output_dir=DELIVERY,
        voice_master=VOICE,
        music_source=MUSIC,
        ffmpeg=FFMPEG,
        encode_video=True,
    )
    print(
        json.dumps(
            {
                "output": str(DELIVERY),
                "artifact_count": len(manifest["artifacts"]),
                "content_sha256": manifest["content_sha256"],
                "mechanical_campaign_pack_ready": manifest["quality_gates"][
                    "mechanical_campaign_pack_ready"
                ],
                "product_admission_passed": manifest["quality_gates"][
                    "product_admission_passed"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
