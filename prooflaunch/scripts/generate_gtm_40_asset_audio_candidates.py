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


DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v3-40-asset-interview"


base.SCRIPT = (
    "Forty polished assets are not the test. The test is which thirty-nine should never ship. "
    "Label every claim fact, inference, hypothesis, or blocked. If the evidence object or release "
    "owner is blank, stop. Let one source-bound card earn human review."
)
base.VOICE_DIRECTIONS = (
    {
        "candidate_id": "voice-interrogator-a",
        "seed": 202608041,
        "speed": 1.18,
        "instruct": (
            "A senior B2B creative director delivering a precise fifteen-second hiring test. "
            "Restrained authority, clipped first sentence, deliberate emphasis on 'thirty-nine' "
            "and 'stop', then a calm final invitation; never salesy or theatrical."
        ),
    },
    {
        "candidate_id": "voice-documentary-b",
        "seed": 202608042,
        "speed": 1.18,
        "instruct": (
            "A premium technology documentary narrator delivering a concise fifteen-second read. "
            "Warm low-register confidence, crisp consonants, one controlled pause before the four "
            "claim states, and quiet conviction on the final line; no announcer voice."
        ),
    },
    {
        "candidate_id": "voice-contrarian-c",
        "seed": 202608043,
        "speed": 1.18,
        "instruct": (
            "A modern androgynous product strategist challenging a popular assumption in a concise "
            "fifteen-second read. Intelligent, conversational and slightly provocative on the opening, "
            "then precise and calm; invite inspection rather than belief."
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
        "campaign": "The 40-Asset Interview",
        "candidate_count": receipt["candidate_count"],
        "content_sha256": receipt["content_sha256"],
        "human_preference_observed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
