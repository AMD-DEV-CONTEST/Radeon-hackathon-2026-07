from __future__ import annotations

import json
from pathlib import Path

from generate_gtm_audio_pk_candidates import DEFAULT_FFMPEG, DEFAULT_MODEL, generate


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-audio-v1"
SCRIPT = (
    "Your day does not need a documentary. Keep one useless detail: a sound, a color, a sentence. "
    "On day seven, the memory stays private until you choose. Keep it, edit it, export it, or delete it. "
    "Reply only keep—not the memory."
)
VOICE_DIRECTIONS = (
    {
        "candidate_id": "voice-private-documentary-a",
        "seed": 202608041,
        "speed": 1.18,
        "instruct": (
            "An intimate modern documentary narrator speaking to one person, not an audience. "
            "Quiet confidence, tactile warmth, clean consonants, a small pause after documentary, "
            "and protective emphasis on private. Never sentimental, breathy, salesy or theatrical."
        ),
    },
    {
        "candidate_id": "voice-dry-confidant-b",
        "seed": 202608042,
        "speed": 1.18,
        "instruct": (
            "A dry, intelligent confidant delivering a counter-feed idea with understated wit. "
            "Conversational pace, restrained energy, crisp list delivery, and a firm final privacy rule. "
            "No announcer tone, hype, vocal fry or identifiable-person imitation."
        ),
    },
    {
        "candidate_id": "voice-gentle-editor-c",
        "seed": 202608043,
        "speed": 1.18,
        "instruct": (
            "A calm senior magazine editor reading a private ritual aloud. Precise, human, lightly textured, "
            "with decisive verbs and no forced emotion. End on not the memory as a clear boundary, not a slogan. "
            "No celebrity resemblance, cloning, whisper performance or commercial hard sell."
        ),
    },
)


def main() -> None:
    receipt = generate(
        DEFAULT_MODEL,
        DEFAULT_FFMPEG,
        OUTPUT,
        script=SCRIPT,
        voice_directions=VOICE_DIRECTIONS,
        scenario_id="loopnote-synthetic-private-memory-launch-v1",
        schema="ProofLaunchKeepUnpostableAudioCandidatesV1",
        resume=True,
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "candidate_count": receipt["candidate_count"],
                "content_sha256": receipt["content_sha256"],
                "human_preference_observed": receipt["human_preference_observed"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
