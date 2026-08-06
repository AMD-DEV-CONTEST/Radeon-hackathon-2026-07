"""Local text-to-speech using Kokoro (kokoro + misaki + torch, CPU-friendly).

This replaces the cloud Qwen-Omni TTS client so the diary / voice app can speak
fully offline on this box. Kokoro is a small (~80M param) generative TTS model
that runs comfortably on CPU; audio is written as 24 kHz WAV via soundfile.

Design notes
------------
* Kokoro (and torch) are imported lazily *inside* :func:`synthesize` so that
  merely importing this module (e.g. from ``main.py`` / ``server.py``) does not
  require torch to be installed in every environment. When Kokoro is missing or
  fails at runtime we return ``None`` and let the caller degrade gracefully
  (the previous Qwen client fell back to macOS ``say``, which does not exist on
  Linux — so here we explicitly avoid that and just skip audio).
* The public signature mirrors the old client: ``synthesize(text, filepath, lang)``
  where ``filepath`` is a stem and we return the concrete ``.wav`` path.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
import soundfile as sf

from utils.timing import timing

logger = logging.getLogger(__name__)

# Kokoro voice names are per-language packs (not a single global list). These are
# the Mandarin and English voices shipped in hexgrad/Kokoro-82M. The first entry of
# each list is the default; remaining entries are fallbacks if a voice file is
# missing from the model repo / mirror.
VOICE_CHOICES: dict[str, list[str]] = {
    "zh": ["zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
           "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang"],
    "en": ["af_heart", "af_bella", "af_nova", "am_adam", "am_michael"],
}

# Kokoro language codes -> which KPipeline lang_code to use.
LANG_CODES: dict[str, str] = {
    "zh": "z",
    "en": "a",
}

_PIPELINES: dict[str, object] = {}  # cached KPipeline per lang_code


def _out_wav(filepath: str) -> str:
    return filepath.rsplit(".", 1)[0] + ".wav"


def _pipeline(lang_code: str):
    if lang_code not in _PIPELINES:
        from kokoro import KPipeline

        _PIPELINES[lang_code] = KPipeline(lang_code=lang_code)
    return _PIPELINES[lang_code]


@timing(name="tts_synthesize")
def synthesize(text: str, filepath: str, lang: str = "zh") -> str | None:
    """Synthesize ``text`` to a local WAV and return its path, or ``None`` on failure.

    ``filepath`` is treated as a stem; the produced file is ``<stem>.wav``.
    """
    if not text or not text.strip():
        return None

    wav_path = _out_wav(filepath)
    Path(wav_path).parent.mkdir(parents=True, exist_ok=True)

    lang_code = LANG_CODES.get(lang, LANG_CODES["en"])
    choices = VOICE_CHOICES.get(lang, VOICE_CHOICES["en"])

    try:
        pipeline = _pipeline(lang_code)

        audio_np = None
        last_err: Exception | None = None
        for voice in choices:
            try:
                chunks = [a for _gs, _ps, a in pipeline(text, voice=voice, speed=1.0)]
            except Exception as e:  # missing voice file, etc.
                last_err = e
                logger.warning("Kokoro voice %s unavailable: %s", voice, e)
                continue
            if chunks:
                audio_np = np.concatenate(chunks, axis=0)
                break
        if audio_np is None:
            logger.warning("Kokoro produced no audio for lang=%s (%s)", lang, last_err)
            return None
        sf.write(wav_path, audio_np, 24000)
        logger.info("Kokoro TTS (%s/%s): %.1fKB -> %s", lang, voice, os.path.getsize(wav_path) / 1024, wav_path)
        return wav_path
    except Exception as e:
        logger.warning("Kokoro TTS failed for lang=%s: %s", lang, e)
        return None
