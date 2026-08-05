#!/usr/bin/env python3
"""Generate the submission voiceover without storing credentials in the repo."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import urllib.request
from pathlib import Path

from manuscript import load_finalized_narration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=Path, default=Path("video/narration.txt"))
    parser.add_argument("--output", type=Path, default=Path("video/voiceover.mp3"))
    parser.add_argument("--voice-id", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--alignment-output",
        type=Path,
        help="Write ElevenLabs character alignment JSON and use the timestamp endpoint.",
    )
    args = parser.parse_args()

    try:
        narration, paragraphs = load_finalized_narration(args.text)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY must be supplied through the environment")

    payload = json.dumps(
        {
            "text": narration,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.55,
                "similarity_boost": 0.78,
                "style": 0.15,
                "speed": args.speed,
                "use_speaker_boost": True,
            },
        }
    ).encode()
    endpoint = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{args.voice_id}/with-timestamps"
        if args.alignment_output
        else f"https://api.elevenlabs.io/v1/text-to-speech/{args.voice_id}"
    )
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json", "xi-api-key": api_key},
        method="POST",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read()
    if args.alignment_output:
        result = json.loads(body)
        audio = base64.b64decode(result["audio_base64"])
        args.output.write_bytes(audio)
        args.alignment_output.parent.mkdir(parents=True, exist_ok=True)
        args.alignment_output.write_text(
            json.dumps(
                {
                    "alignment": result.get("alignment"),
                    "normalized_alignment": result.get("normalized_alignment"),
                    "narration_sha256": hashlib.sha256(narration.encode()).hexdigest(),
                    "audio_sha256": hashlib.sha256(audio).hexdigest(),
                    "paragraph_count": len(paragraphs),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        args.output.write_bytes(body)


if __name__ == "__main__":
    main()
