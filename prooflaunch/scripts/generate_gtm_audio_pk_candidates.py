#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_REVISION = "7d3824abff87e49756bb0f83fb5411de75d160c4"
MODEL_ID = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
DEFAULT_MODEL = Path(
    os.environ.get(
        "PROOFLAUNCH_TTS_MODEL_PATH",
        str(
            Path.home()
            / ".cache/huggingface/hub"
            / "models--mlx-community--Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
            / "snapshots"
            / MODEL_REVISION
        ),
    )
)
DEFAULT_FFMPEG = (
    ROOT.parent
    / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
)
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2"
TARGET_DURATION_SECONDS = 15.0
SCRIPT = (
    "A GTM plan should earn the next decision, not merely generate more content. "
    "ProofLaunch puts approved evidence before the promise, turns every campaign "
    "into a measurable learning loop, and keeps release in human hands. Inspect "
    "the proof. Challenge the gap. Approve manually."
)
VOICE_DIRECTIONS = (
    {
        "candidate_id": "voice-restraint-a",
        "seed": 202608031,
        "speed": 1.20,
        "instruct": (
            "A senior creative director delivering a precise 15-second launch-film read. "
            "Calm, restrained and subtly authoritative; crisp articulation, minimal pauses, "
            "brief emphasis on 'Inspect the proof'; never salesy."
        ),
    },
    {
        "candidate_id": "voice-documentary-b",
        "seed": 202608032,
        "speed": 1.20,
        "instruct": (
            "A thoughtful documentary narrator delivering a concise 15-second launch-film read. "
            "Warm confidence, natural breath, crisp consonants and quiet intensity on the "
            "last three lines; no hype, long pauses or announcer voice."
        ),
    },
    {
        "candidate_id": "voice-inquisitive-c",
        "seed": 202608033,
        "speed": 1.20,
        "instruct": (
            "A modern androgynous product strategist delivering a concise 15-second read: "
            "intelligent, inquisitive, calm and conversational. Crisp pace, restrained "
            "emotion, and an invitation to inspect rather than believe; no long pauses."
        ),
    },
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return sealed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wav_metadata(path: Path) -> dict[str, int | float]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        sample_rate = handle.getframerate()
        return {
            "sample_rate_hz": sample_rate,
            "channels": handle.getnchannels(),
            "sample_width_bits": handle.getsampwidth() * 8,
            "frames": frames,
            "duration_seconds": round(frames / sample_rate, 6),
        }


def _validate_inputs(model: Path, ffmpeg: Path, output: Path, *, resume: bool = False) -> None:
    if not model.is_dir() or not (model / "model.safetensors").is_file():
        raise SystemExit(f"cached model snapshot is missing: {model}")
    if model.name != MODEL_REVISION:
        raise SystemExit("model snapshot revision is not the frozen revision")
    if not ffmpeg.is_file() or not os.access(ffmpeg, os.X_OK):
        raise SystemExit(f"pinned ffmpeg executable is missing: {ffmpeg}")
    try:
        output.resolve().relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("output must remain inside the project") from error
    if output.exists() and any(output.iterdir()) and not resume:
        raise SystemExit("output directory must be empty")


def _master(ffmpeg: Path, raw: Path, master: Path) -> None:
    raw_duration = float(_wav_metadata(raw)["duration_seconds"])
    tempo = raw_duration / TARGET_DURATION_SECONDS
    if not 0.5 <= tempo <= 2.0:
        raise RuntimeError(f"raw delivery cannot be conformed safely: atempo={tempo:.4f}")
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(raw),
            "-af",
            f"atempo={tempo:.8f},loudnorm=I=-16:TP=-1:LRA=7",
            "-t",
            f"{TARGET_DURATION_SECONDS:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(master),
        ],
        check=True,
        cwd=ROOT,
    )


def generate(
    model_path: Path,
    ffmpeg: Path,
    output: Path,
    *,
    script: str = SCRIPT,
    voice_directions: tuple[dict[str, object], ...] = VOICE_DIRECTIONS,
    scenario_id: str = "prooflaunch-b2b-ai-launch-zero-budget-v1",
    schema: str = "ProofLaunchGTMAudioPKCandidatesV1",
    resume: bool = False,
) -> dict[str, Any]:
    _validate_inputs(model_path, ffmpeg, output, resume=resume)
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    raw_root = output / "raw"
    master_root = output / "master"
    raw_root.mkdir(mode=0o700, exist_ok=True)
    master_root.mkdir(mode=0o700, exist_ok=True)

    # Imports stay lazy so unit tests and non-Apple environments can validate the
    # receipt logic without importing MLX or touching an accelerator.
    import mlx.core as mx  # type: ignore
    import numpy as np
    from mlx_audio.tts.generate import generate_audio  # type: ignore
    from mlx_audio.tts.utils import load_model  # type: ignore

    model = load_model(model_path=str(model_path))
    rows: list[dict[str, Any]] = []
    for spec in voice_directions:
        seed = int(spec["seed"])
        random.seed(seed)
        np.random.seed(seed)
        mx.random.seed(seed)
        candidate_id = str(spec["candidate_id"])
        raw = raw_root / f"{candidate_id}.wav"
        master = master_root / f"{candidate_id}-48k-stereo-24bit.wav"
        if not (resume and raw.is_file() and master.is_file()):
            generate_audio(
                text=script,
                model=model,
                instruct=str(spec["instruct"]),
                lang_code="en",
                speed=float(spec["speed"]),
                temperature=0.62,
                max_tokens=2048,
                output_path=str(raw_root),
                file_prefix=candidate_id,
                audio_format="wav",
                join_audio=True,
                play=False,
                verbose=False,
            )
            if not raw.is_file():
                raise RuntimeError(f"VoiceDesign did not emit the expected file: {raw}")
            _master(ffmpeg, raw, master)
        raw_meta = _wav_metadata(raw)
        master_meta = _wav_metadata(master)
        if master_meta["sample_rate_hz"] != 48000:
            raise RuntimeError("master sample rate gate failed")
        if master_meta["channels"] != 2 or master_meta["sample_width_bits"] != 24:
            raise RuntimeError("master stereo/bit-depth gate failed")
        if abs(float(master_meta["duration_seconds"]) - TARGET_DURATION_SECONDS) > 0.10:
            raise RuntimeError("15-second same-Brief duration gate failed")
        rows.append(
            {
                "candidate_id": candidate_id,
                "seed": seed,
                "generation_speed": spec["speed"],
                "voice_direction": spec["instruct"],
                "reference_audio_used": False,
                "identifiable_person_imitation_requested": False,
                "raw": {
                    "project_relative_path": str(raw.relative_to(ROOT)),
                    "sha256": _sha256(raw),
                    "bytes": raw.stat().st_size,
                    **raw_meta,
                },
                "master": {
                    "project_relative_path": str(master.relative_to(ROOT)),
                    "sha256": _sha256(master),
                    "bytes": master.stat().st_size,
                    **master_meta,
                },
                "semantic_round_trip_status": "not_run_no_cached_asr_model",
                "human_listening_review_status": "pending",
            }
        )

    hashes = {row["master"]["sha256"] for row in rows}
    if len(hashes) != len(rows):
        raise RuntimeError("audio candidate diversity gate failed: duplicate masters")
    payload = {
        "schema": schema,
        "scenario_id": scenario_id,
        "frozen_script": script,
        "frozen_script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "model": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "local_snapshot": str(model_path),
            "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "license": "Apache-2.0",
            "reference_audio_used": False,
        },
        "runtime": {
            "accelerator": "apple_metal",
            "offline_environment_required": True,
            "cloud_api_calls": 0,
            "network_downloads": 0,
            "ffmpeg_path": str(ffmpeg),
            "mastering_target": (
                "15.0 seconds; 48 kHz stereo 24-bit PCM; loudnorm target -16 LUFS, "
                "-1 dBTP, LRA 7"
            ),
        },
        "candidate_count": len(rows),
        "resumed_from_existing_candidates": resume,
        "candidates": rows,
        "mechanical_gate_passed": True,
        "human_preference_observed": False,
        "four_a_quality_proven": False,
        "top_product_parity_proven": False,
        "truth_boundary": (
            "These are locally generated, content-addressed same-script VoiceDesign candidates. "
            "The receipt proves generation provenance and container mechanics only. It does not "
            "prove semantic fidelity, human preference, 4A quality, Top-product parity, commercial "
            "effect, Radeon execution, publication, or revenue lift."
        ),
    }
    receipt = _seal(payload)
    receipt_path = output / "audio-candidate-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL))
    parser.add_argument("--ffmpeg", default=str(DEFAULT_FFMPEG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    receipt = generate(
        Path(args.model_path).expanduser().resolve(),
        Path(args.ffmpeg).expanduser().resolve(),
        Path(args.output_dir).expanduser().resolve(),
    )
    print(
        json.dumps(
            {
                "candidate_count": receipt["candidate_count"],
                "content_sha256": receipt["content_sha256"],
                "human_preference_observed": receipt["human_preference_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
