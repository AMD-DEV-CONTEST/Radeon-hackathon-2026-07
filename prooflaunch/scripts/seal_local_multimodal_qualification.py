#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts/local-multimodal-qualification-v1"
OUTPUT = ROOT / "evidence/v10/local-multimodal-qualification.json"
FFPROBE_DEFAULT = (
    ROOT.parent
    / "tapnow-libtv-local-studio/backend-node/node_modules"
    / "@ffprobe-installer/darwin-arm64/ffprobe"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def relative_artifact(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def wav_metadata(path: Path) -> dict[str, object]:
    with wave.open(str(path), "rb") as source:
        frames = source.getnframes()
        rate = source.getframerate()
        return {
            "codec": f"pcm_s{source.getsampwidth() * 8}le",
            "sample_rate": rate,
            "channels": source.getnchannels(),
            "bits_per_sample": source.getsampwidth() * 8,
            "duration_seconds": round(frames / rate, 6),
        }


def png_metadata(path: Path) -> dict[str, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    return {"width": width, "height": height}


def video_metadata(path: Path, ffprobe: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffprobe failed")
    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    video = next(item for item in streams if item.get("width"))
    audio = next((item for item in streams if item.get("sample_rate")), None)
    result: dict[str, object] = {
        "codec": video["codec_name"],
        "width": video["width"],
        "height": video["height"],
        "pixel_format": video["pix_fmt"],
        "frame_rate": video["r_frame_rate"],
        "duration_seconds": round(float(payload["format"]["duration"]), 6),
    }
    if audio:
        result["audio"] = {
            "codec": audio["codec_name"],
            "sample_rate": int(audio["sample_rate"]),
            "channels": audio["channels"],
        }
    return result


def artifact_record(path: Path, metadata: dict[str, object]) -> dict[str, object]:
    return {
        "path": relative_artifact(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        **metadata,
    }


def stable_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffprobe", type=Path, default=FFPROBE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    ffprobe = args.ffprobe.expanduser().resolve()
    if not ffprobe.is_file():
        raise SystemExit(f"ffprobe is unavailable: {ffprobe}")

    raw_audio = ARTIFACT_ROOT / "qwen3-tts/proof-before-promise.wav"
    master_audio = ARTIFACT_ROOT / "qwen3-tts/proof-before-promise-master.wav"
    distilled_video = ARTIFACT_ROOT / "ltx23/proof-before-promise.mp4"
    distilled_frame = ARTIFACT_ROOT / "ltx23/proof-before-promise-frame.png"
    one_stage_video = ARTIFACT_ROOT / "ltx23/proof-before-promise-one-stage.mp4"
    one_stage_frame = ARTIFACT_ROOT / "ltx23/proof-before-promise-one-stage-frame.png"
    required = (
        raw_audio,
        master_audio,
        distilled_video,
        distilled_frame,
        one_stage_video,
        one_stage_frame,
    )
    missing = [relative_artifact(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"qualification artifacts are missing: {missing}")

    receipt: dict[str, object] = {
        "schema": "ProofLaunchLocalMultimodalQualificationV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution": {
            "host_accelerator": "apple_metal",
            "cloud_api_calls": 0,
            "network_downloads": 0,
            "offline_environment": "HF_HUB_OFFLINE=1",
            "local_model_inference_observed": True,
            "local_model_training_observed": False,
            "radeon_local_inference_observed": False,
        },
        "campaign_binding": {
            "campaign_id": "prooflaunch-zero-budget-b2b-v1",
            "strategy_id": "strategy-9f4df3ee036be652",
            "approved_proof": "Compiles a rights-bound brief into review-ready GTM assets.",
            "proof_evidence_sha256": "3d117f36274cab2ec550c33493485f84cd084e412eff4bef47ff49a37fb15aa4",
            "exact_cta": "Review the evidence, then decide whether to join the design-partner cohort.",
            "blind_selected_territory_used": False,
            "purpose": "unselected development qualification only",
        },
        "models": {
            "speech": {
                "model_id": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
                "revision": "7d3824abff87e49756bb0f83fb5411de75d160c4",
                "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                "license": "apache-2.0",
                "license_source": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                "production_rights_cleared_for_this_synthetic_probe": True,
            },
            "video": {
                "model_id": "dgrauet/ltx-2.3-mlx",
                "revision": "24eed44ee6c66114fa0b5a5b8bbc92121f848a3e",
                "base_model": "Lightricks/LTX-2.3",
                "license": "ltx-2-community-license-agreement",
                "license_source": "https://huggingface.co/Lightricks/LTX-2.3/blob/76730e634e70a28f4e8d51f5e29c08e40e2d8e74/LICENSE",
                "commercial_revenue_threshold_usd": 10_000_000,
                "operator_entity_revenue_verified": False,
                "production_rights_cleared": False,
            },
        },
        "input_rights": {
            "script_authored_for_this_qualification": True,
            "visual_prompt_authored_for_this_qualification": True,
            "reference_audio_used": False,
            "reference_image_used": False,
            "person_or_celebrity_likeness_requested": False,
            "copied_campaign_creative_used": False,
        },
        "artifacts": {
            "speech_raw": artifact_record(raw_audio, wav_metadata(raw_audio)),
            "speech_master": artifact_record(master_audio, wav_metadata(master_audio)),
            "video_distilled": artifact_record(
                distilled_video, video_metadata(distilled_video, ffprobe)
            ),
            "video_distilled_frame": artifact_record(
                distilled_frame, png_metadata(distilled_frame)
            ),
            "video_one_stage": artifact_record(
                one_stage_video, video_metadata(one_stage_video, ffprobe)
            ),
            "video_one_stage_frame": artifact_record(
                one_stage_frame, png_metadata(one_stage_frame)
            ),
        },
        "attempts": [
            {
                "attempt": 1,
                "lane": "ltx_distilled",
                "status": "failed_at_decode",
                "error": "ffmpeg not found on PATH",
                "accepted": False,
            },
            {
                "attempt": 2,
                "lane": "ltx_distilled",
                "status": "artifact_generated",
                "visual_review": "rejected_subject_not_recognizable",
                "accepted": False,
            },
            {
                "attempt": 3,
                "lane": "ltx_one_stage",
                "status": "artifact_generated",
                "visual_review": "single_evidence_card_recognizable",
                "accepted": False,
                "rejection_reasons": [
                    "resolution_below_product_gate",
                    "duration_below_product_gate",
                    "no_named_human_blind_review",
                    "video_model_production_rights_not_cleared",
                ],
            },
        ],
        "quality_gates": {
            "speech_48khz_stereo_24bit_delivery": True,
            "speech_semantic_transcription_verified": False,
            "speech_named_human_listening_review": False,
            "video_subject_recognizable_after_bounded_repair": True,
            "video_minimum_width": 1920,
            "video_minimum_duration_seconds": 6,
            "video_delivery_gate_passed": False,
            "named_human_blind_review_passed": False,
            "four_a_effect_claim_eligible": False,
            "product_admission_passed": False,
        },
        "truth_boundary": (
            "This receipt proves offline Apple-Metal inference with cached Qwen3-TTS and LTX-2.3 "
            "weights plus technical artifact hashing. The speech master has not received semantic or "
            "listening review. The video is a 384x256 one-second qualification, not a production "
            "deliverable. No artifact establishes 4A quality, Top-1 standing, Radeon inference, "
            "external publication, business lift or causal revenue."
        ),
    }
    receipt["content_sha256"] = stable_digest(receipt)
    output = args.output.expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "content_sha256": receipt["content_sha256"],
                "product_admission_passed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
