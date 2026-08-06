"""Text-to-speech using Qwen Omni multimodal API via raw SSE streaming.

DEPRECATED: the app now uses local Kokoro TTS (see ``tts/kokoro_tts.py``) so it
can run fully offline. This module is kept only as an optional cloud fallback and
is no longer imported by ``main.py`` / ``server.py`` / ``audio/stream_handler.py``.
"""

import base64
import json
import logging
from pathlib import Path

import requests

from config.settings import QWEN_API_KEY, QWEN_BASE_URL
from utils.timing import timing

logger = logging.getLogger(__name__)

OMNI_MODEL = "qwen3.5-omni-flash"
VOICES = {"zh": "Ethan", "en": "Ethan"}


@timing(name="tts_synthesize")
def synthesize(text: str, filepath: str, lang: str = "zh") -> str:
    """Convert text to speech using Qwen Omni model.

    Uses raw SSE streaming (OpenAI SDK doesn't support 'audio' delta field yet).
    Falls back to macOS say if TTS fails.
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    wav_path = filepath.rsplit(".", 1)[0] + ".wav"

    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return _macos_say(text, filepath, lang)

    voice = VOICES.get(lang, "Ethan")

    try:
        resp = requests.post(
            f"{QWEN_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {QWEN_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OMNI_MODEL,
                "messages": [{"role": "user", "content": text}],
                "modalities": ["text", "audio"],
                "audio": {"voice": voice, "format": "wav"},
                "stream": True,
            },
            stream=True,
            timeout=30,
        )

        audio_chunks = []
        for line in resp.iter_lines():
            if not line or not line.startswith(b"data:"):
                continue
            try:
                data = json.loads(line[5:])
            except json.JSONDecodeError:
                continue
            if choices := data.get("choices"):
                delta = choices[0].get("delta", {})
                if audio := delta.get("audio"):
                    audio_chunks.append(base64.b64decode(audio["data"]))

        if audio_chunks:
            audio_bytes = b"".join(audio_chunks)
            with open(wav_path, "wb") as f:
                f.write(audio_bytes)
            logger.info("Omni TTS: %.1fKB → %s", len(audio_bytes) / 1024, wav_path)
            return wav_path

        logger.warning("No audio in Omni response")
        return _macos_say(text, filepath, lang)

    except Exception as e:
        logger.warning("Omni TTS failed: %s, fallback to macOS say", e)
        return _macos_say(text, filepath, lang)


def _macos_say(text: str, filepath: str, lang: str) -> str:
    import subprocess

    voices = {"zh": ["Tingting", "Shelley", "default"], "en": ["Samantha", "Moira", "default"]}
    aiff_path = filepath.rsplit(".", 1)[0] + ".aiff"
    for voice in voices.get(lang, voices["en"]):
        try:
            subprocess.run(
                ["say", "-v", voice, "-o", aiff_path, text],
                capture_output=True,
                check=True,
            )
            logger.info("macOS say: %s (%s)", voice, lang)
            return aiff_path
        except subprocess.CalledProcessError:
            continue
    return filepath
