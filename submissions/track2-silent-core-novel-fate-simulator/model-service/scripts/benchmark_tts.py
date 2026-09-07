#!/usr/bin/env python3
"""Validate OpenAI and MiniMax-compatible TTS contracts and report latency."""

from __future__ import annotations

import argparse
import io
import json
import time

import requests
import soundfile as sf


TEXT = (
    "Far below the city, the dragon opened one ancient eye. "
    "Above it, the bells of Silent Core began to ring."
)


def duration_seconds(audio: bytes) -> float:
    with sf.SoundFile(io.BytesIO(audio)) as handle:
        return len(handle) / handle.samplerate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8003/v1")
    args = parser.parse_args()
    endpoint = f"{args.base_url.rstrip('/')}/audio/speech"

    started = time.perf_counter()
    binary = requests.post(
        endpoint,
        json={
            "model": "silent-core/tts",
            "input": TEXT,
            "voice": "heart",
            "response_format": "mp3",
            "speed": 1.0,
        },
        timeout=120,
    )
    binary.raise_for_status()
    binary_latency = time.perf_counter() - started
    binary_duration = duration_seconds(binary.content)

    stream_started = time.perf_counter()
    first_chunk = None
    statuses = []
    chunk_bytes = 0
    with requests.post(
        endpoint,
        json={
            "model": "silent-core/tts",
            "text": TEXT,
            "stream": True,
            "voice_setting": {"voice_id": "male-qn-qingse", "speed": 1.0, "pitch": 0},
            "audio_setting": {"format": "mp3", "sample_rate": 24000, "channel": 1},
            "output_format": "hex",
        },
        stream=True,
        timeout=(10, 120),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            if first_chunk is None:
                first_chunk = time.perf_counter()
            event = json.loads(line)
            if event.get("base_resp", {}).get("status_code") != 0:
                raise RuntimeError(event)
            data = event["data"]
            statuses.append(data["status"])
            chunk_bytes += len(bytes.fromhex(data["audio"]))
    stream_finished = time.perf_counter()

    result = {
        "openai": {
            "latency_seconds": round(binary_latency, 3),
            "audio_seconds": round(binary_duration, 3),
            "rtf": round(binary_latency / binary_duration, 3),
            "bytes": len(binary.content),
        },
        "minimax_stream": {
            "first_chunk_seconds": round((first_chunk or stream_finished) - stream_started, 3),
            "total_seconds": round(stream_finished - stream_started, 3),
            "statuses": statuses,
            "bytes": chunk_bytes,
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
