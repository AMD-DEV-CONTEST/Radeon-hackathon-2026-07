#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import generate_gtm_audio_pk_candidates as base


DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1"

base.SCRIPT = (
    "We asked our own AI to prove it was four-A. It refused. No witness. No virality evidence. "
    "Claim rejected. Then it wrote the version the evidence could carry. Put your claim on trial "
    "before the market does."
)
base.VOICE_DIRECTIONS = (
    {
        "candidate_id": "voice-cross-examiner-a",
        "seed": 202608051,
        "speed": 1.19,
        "instruct": (
            "A sharp senior creative director cross-examining their own work in a premium fifteen-second "
            "technology film. Dry confidence, a clipped pause after 'refused', hard emphasis on 'No witness', "
            "then an inviting final sentence. Intelligent and human; never an announcer."
        ),
    },
    {
        "candidate_id": "voice-documentary-b",
        "seed": 202608052,
        "speed": 1.18,
        "instruct": (
            "A restrained investigative-documentary narrator reading a concise fifteen-second product story. "
            "Low-register warmth, crisp consonants, controlled tension on the verdict, and quiet conviction at "
            "the end. No hype, imitation or theatrical courtroom voice."
        ),
    },
    {
        "candidate_id": "voice-founder-c",
        "seed": 202608053,
        "speed": 1.20,
        "instruct": (
            "A candid technical founder admitting an uncomfortable product truth in a concise fifteen-second read. "
            "Conversational, self-aware and slightly amused on the opening; precise on the evidence gap; direct but "
            "welcoming on the invitation. No sales cadence."
        ),
    },
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", default=str(base.DEFAULT_MODEL))
    parser.add_argument("--ffmpeg", default=str(base.DEFAULT_FFMPEG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    receipt = base.generate(
        Path(args.model_path).expanduser().resolve(),
        Path(args.ffmpeg).expanduser().resolve(),
        Path(args.output_dir).expanduser().resolve(),
    )
    print(json.dumps({
        "campaign": "Claim Trial",
        "candidate_count": receipt["candidate_count"],
        "content_sha256": receipt["content_sha256"],
        "accelerator": receipt["runtime"]["accelerator"],
        "human_preference_observed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
