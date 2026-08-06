#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_named_product_baseline import content_sha256


MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/qwen-image"
MODEL_ID = "AbstractFramework/qwen-image-2512-8bit"
MODEL_REVISION = "f70648e7146ce762557dcebd40809586c32ec558"
MODEL_SNAPSHOT = (
    Path.home()
    / ".cache/huggingface/hub/models--AbstractFramework--qwen-image-2512-8bit/snapshots"
    / MODEL_REVISION
)
MLXGEN = (
    ROOT.parent
    / "tapnow-libtv-local-studio/mlx-worker/.venv-mlxgen/bin/mlxgen"
)
SEED = 202608032
WIDTH = 1080
HEIGHT = 1350
STEPS = 32
GUIDANCE = 4.0
PROMPT = """Create one finished 4:5 social campaign poster for the software product ProofLaunch.

The concept is a public self-cross-examination: the product rejects its own unsupported marketing claim before the market does. Make the conflict and verdict understandable in one feed glance.

Use this exact visible copy and no other words:
PROOFLAUNCH / CLAIM TRIAL
WE ASKED OUR OWN AI TO PROVE IT WAS 4A.
NO WITNESS
No virality evidence. Claim rejected.
Put your claim on trial before the market does.

Art direction: premium independent editorial design, tense courtroom evidence aesthetic, near-black paper texture, warm ivory type, one acid-lime evidence mark, severe asymmetric grid, deliberate negative space, crisp high-contrast typography, distinctive enough to screenshot and share. No people, no stock photography, no device mockup, no fake interface, no decorative gradients, no extra logos, no extra copy, no misspelled words, no tiny unreadable text. The verdict NO WITNESS must dominate after the headline."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(OUTPUT))
    parser.add_argument("--mlxgen", default=str(MLXGEN))
    parser.add_argument(
        "--resume-existing-artifact",
        action="store_true",
        help="Seal an already-emitted raw PNG after a post-generation receipt check failed; never regenerates or edits it.",
    )
    args = parser.parse_args()
    output = Path(args.output_dir).expanduser().resolve()
    launcher = Path(args.mlxgen).expanduser().resolve()
    output.relative_to(ROOT)
    artifact = output / "qwen-image-2512-raw-baseline.png"
    existing_names = sorted(path.name for path in output.iterdir()) if output.exists() else []
    if existing_names and not (args.resume_existing_artifact and existing_names == [artifact.name]):
        raise SystemExit("output directory must be empty, or contain only the raw artifact in explicit resume mode")
    if not launcher.is_file():
        raise SystemExit("frozen MLX-Gen launcher is missing")
    if not MODEL_SNAPSHOT.is_dir() or not (MODEL_SNAPSHOT / "transformer/model.safetensors.index.json").is_file():
        raise SystemExit("frozen Qwen-Image model snapshot is missing or drifted")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slot = next(
        row
        for row in manifest["capture_slots"]
        if row["category_id"] == "image_generation_editing" and row["reference_product"] == "Qwen-Image"
    )
    output.mkdir(parents=True, mode=0o700, exist_ok=args.resume_existing_artifact)
    command = [
        str(launcher),
        "generate",
        "--model",
        MODEL_ID,
        "--task",
        "text-to-image",
        "--prompt",
        PROMPT,
        "--width",
        str(WIDTH),
        "--height",
        str(HEIGHT),
        "--steps",
        str(STEPS),
        "--guidance",
        str(GUIDANCE),
        "--seed",
        str(SEED),
        "--output",
        str(artifact),
        "--no-progress",
        "--embed-metadata",
    ]
    environment = dict(os.environ)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    if not args.resume_existing_artifact:
        result = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                "Qwen-Image generation failed\n"
                f"stdout:\n{result.stdout[-4000:]}\n"
                f"stderr:\n{result.stderr[-4000:]}"
            )
    if not artifact.is_file():
        raise RuntimeError("Qwen-Image did not emit the expected original PNG")
    with Image.open(artifact) as image:
        actual_width, actual_height = image.size
        image_mode = image.mode
        embedded_metadata = dict(image.info)
    dimension_drift = {
        "requested": [WIDTH, HEIGHT],
        "actual": [actual_width, actual_height],
        "width_delta": actual_width - WIDTH,
        "height_delta": actual_height - HEIGHT,
        "exact_contract_size": (actual_width, actual_height) == (WIDTH, HEIGHT),
    }

    artifact_hash = sha256_file(artifact)
    prompt_hash = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
    provenance = {
        "schema": "ProofLaunchQwenImageRawBaselineProvenanceV1",
        "capture_slot_id": slot["capture_slot_id"],
        "reference_product": "Qwen-Image",
        "upstream_family": "Qwen Image 2512",
        "runtime_conversion": MODEL_ID,
        "revision": MODEL_REVISION,
        "runtime": "MLX-Gen 0.25.0",
        "accelerator": "apple_metal",
        "offline": True,
        "network_calls": 0,
        "seed": SEED,
        "width": WIDTH,
        "height": HEIGHT,
        "steps": STEPS,
        "guidance": GUIDANCE,
        "prompt": PROMPT,
        "prompt_sha256": prompt_hash,
        "post_editing_performed": False,
        "upscaling_performed": False,
        "dimension_drift": dimension_drift,
        "capture_observations": [
            "The runtime quantized the requested 1080x1350 canvas to 1072x1344.",
            "The raw image adds 'The Public self-cross-examination:' although the prompt prohibited extra copy.",
            "The closing line appears twice. No repair was applied because the frozen protocol requires the original export.",
        ],
        "artifact": {
            "name": artifact.name,
            "sha256": artifact_hash,
            "bytes": artifact.stat().st_size,
            "width": actual_width,
            "height": actual_height,
            "mode": image_mode,
            "embedded_metadata_keys": sorted(str(key) for key in embedded_metadata),
        },
        "truth_boundary": (
            "This is one original local Qwen-Image-family output through the declared 8-bit MLX conversion. "
            "It is a same-brief raw baseline capture, not a preference result, a claim about the hosted product, "
            "or evidence that every Qwen-Image deployment behaves identically."
        ),
    }
    atomic_write_text(
        output / "provenance.json",
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    capture = {
        "schema": "ProofLaunchNamedProductBaselineCaptureV1",
        "capture_slot_id": slot["capture_slot_id"],
        "category_id": slot["category_id"],
        "reference_product": slot["reference_product"],
        "reference_product_url": slot["reference_product_url"],
        "frozen_brief_sha256": slot["frozen_brief_sha256"],
        "operator_id": "codex-local-runner-20260803",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "provider_model_or_version": f"Qwen Image 2512 via {MODEL_ID}@{MODEL_REVISION} / MLX-Gen 0.25.0",
        "acquisition_method": "authorized_product_use",
        "rights_attestation": {
            "authorized_to_evaluate_and_retain": True,
            "same_frozen_brief_without_hidden_editing": True,
            "provider_and_version_recorded_truthfully": True,
        },
        "artifact": {
            "name": artifact.name,
            "mime_type": "image/png",
            "bytes": artifact.stat().st_size,
            "sha256": artifact_hash,
        },
    }
    capture["content_sha256"] = content_sha256(capture)
    atomic_write_text(
        output / "capture.json",
        json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "artifact": str(artifact),
                "capture_slot_id": slot["capture_slot_id"],
                "sha256": artifact_hash,
                "size": [actual_width, actual_height],
                "exact_contract_size": dimension_drift["exact_contract_size"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
