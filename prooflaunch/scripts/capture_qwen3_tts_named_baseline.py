#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_named_product_baseline import content_sha256
from scripts.generate_gtm_audio_pk_candidates import DEFAULT_MODEL, MODEL_ID, MODEL_REVISION


MANIFEST = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
CHALLENGER_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/audio-candidate-receipt.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/qwen3-tts"
SEED = 202608061
INSTRUCTION = (
    "A clear, natural English product-demonstration voice. Neutral pacing and emotion, accurate pronunciation, "
    "no character imitation, no named-person style, and no added words."
)


def wav_metadata(path: Path) -> dict[str, int | float]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        return {
            "sample_rate_hz": rate,
            "channels": handle.getnchannels(),
            "sample_width_bits": handle.getsampwidth() * 8,
            "frames": frames,
            "duration_seconds": round(frames / rate, 6),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL))
    parser.add_argument("--output-dir", default=str(OUTPUT))
    args = parser.parse_args()
    model_path = Path(args.model_path).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    if not (model_path / "model.safetensors").is_file() or model_path.name != MODEL_REVISION:
        raise SystemExit("frozen Qwen3-TTS model snapshot is missing or drifted")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slot = next(
        row for row in manifest["capture_slots"]
        if row["category_id"] == "audio_voice_music" and row["reference_product"] == "Qwen3-TTS"
    )
    challenger = json.loads(CHALLENGER_RECEIPT.read_text(encoding="utf-8"))
    script = challenger["frozen_script"]
    output.mkdir(parents=True, mode=0o700)

    import mlx.core as mx  # type: ignore
    import numpy as np
    from mlx_audio.tts.generate import generate_audio  # type: ignore
    from mlx_audio.tts.utils import load_model  # type: ignore

    random.seed(SEED)
    np.random.seed(SEED)
    mx.random.seed(SEED)
    model = load_model(model_path=str(model_path))
    generate_audio(
        text=script,
        model=model,
        instruct=INSTRUCTION,
        lang_code="en",
        speed=1.0,
        temperature=0.62,
        max_tokens=2048,
        output_path=str(output),
        file_prefix="qwen3-tts-raw-baseline",
        audio_format="wav",
        join_audio=True,
        play=False,
        verbose=False,
    )
    artifact = output / "qwen3-tts-raw-baseline.wav"
    if not artifact.is_file():
        raise RuntimeError("Qwen3-TTS did not emit the expected original WAV")
    artifact_hash = sha256_file(artifact)
    provenance = {
        "schema": "ProofLaunchQwen3TTSRawBaselineProvenanceV1",
        "capture_slot_id": slot["capture_slot_id"],
        "reference_product": "Qwen3-TTS",
        "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "runtime_conversion": MODEL_ID,
        "revision": MODEL_REVISION,
        "license": "Apache-2.0",
        "accelerator": "apple_metal",
        "offline": True,
        "network_calls": 0,
        "seed": SEED,
        "generation_instruction": INSTRUCTION,
        "generation_speed": 1.0,
        "temperature": 0.62,
        "post_editing_performed": False,
        "mastering_performed": False,
        "script": script,
        "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
        "artifact": {"name": artifact.name, "sha256": artifact_hash, "bytes": artifact.stat().st_size, **wav_metadata(artifact)},
        "truth_boundary": "This is one original local Qwen3-TTS VoiceDesign output through the declared MLX conversion. It is a same-script baseline capture, not a preference result or a claim about every Qwen3-TTS deployment."
    }
    atomic_write_text(output / "provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    capture = {
        "schema": "ProofLaunchNamedProductBaselineCaptureV1",
        "capture_slot_id": slot["capture_slot_id"],
        "category_id": slot["category_id"],
        "reference_product": slot["reference_product"],
        "reference_product_url": slot["reference_product_url"],
        "frozen_brief_sha256": slot["frozen_brief_sha256"],
        "operator_id": "codex-local-runner-20260803",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "provider_model_or_version": f"Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign via {MODEL_ID}@{MODEL_REVISION}",
        "acquisition_method": "authorized_product_use",
        "rights_attestation": {
            "authorized_to_evaluate_and_retain": True,
            "same_frozen_brief_without_hidden_editing": True,
            "provider_and_version_recorded_truthfully": True
        },
        "artifact": {
            "name": artifact.name,
            "mime_type": "audio/wav",
            "bytes": artifact.stat().st_size,
            "sha256": artifact_hash
        }
    }
    capture["content_sha256"] = content_sha256(capture)
    atomic_write_text(output / "capture.json", json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": str(artifact), "capture_slot_id": slot["capture_slot_id"], "sha256": artifact_hash, "duration_seconds": provenance["artifact"]["duration_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
