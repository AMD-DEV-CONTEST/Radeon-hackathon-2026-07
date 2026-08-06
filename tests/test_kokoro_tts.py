"""Unit tests for the local Kokoro TTS module (offline; Kokoro/torch mocked).

The real synthesize() imports kokoro/torch/soundfile lazily, so these tests
patch ``tts.kokoro_tts.KPipeline`` (and numpy/soundfile) to verify the
orchestration (voice fallback, WAV writing, graceful failure) without a
GPU/model. No real numpy/kokoro is required to run them.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the repo root is importable when run via `python -m unittest`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts import kokoro_tts as K


class FakePipeline:
    """Mimics KPipeline(text, voice=...) yielding (graphemes, phonemes, audio)."""

    def __init__(self, good_voice="zf_xiaobei"):
        self.good_voice = good_voice
        self.calls = []

    def __call__(self, text, voice=None, speed=1.0):
        self.calls.append((text, voice, speed))
        if voice != self.good_voice:
            raise RuntimeError(f"voice {voice} not found")
        yield ("g", "p", [0.0] * 100)  # dummy audio chunk


def _run(text, lang, pipeline, np_mock=None):
    np_mock = np_mock or MagicMock()
    with patch.object(K, "_pipeline", return_value=pipeline), patch.object(
        K, "np", np_mock
    ), patch("tts.kokoro_tts.sf") as sf, patch(
        "tts.kokoro_tts.os.path.getsize", return_value=123
    ):
        out = K.synthesize(text, "/tmp/tts_test", lang=lang)
    return out, sf


class TestSynthesize(unittest.TestCase):
    def test_writes_wav_and_returns_path(self):
        pl = FakePipeline(good_voice="zf_xiaobei")
        out, sf = _run("今天天气真好。", "zh", pl)
        self.assertTrue(out.endswith(".wav"))
        sf.write.assert_called_once()
        # wrote at 24kHz
        self.assertEqual(sf.write.call_args.args[2], 24000)

    def test_unknown_lang_defaults_to_en_choices(self):
        pl = FakePipeline(good_voice="af_heart")
        out, _ = _run("hello", "xx", pl)
        self.assertIsNotNone(out)
        self.assertIn(pl.calls[0][1], K.VOICE_CHOICES["en"])

    def test_falls_back_to_next_voice_on_failure(self):
        pl = FakePipeline(good_voice=K.VOICE_CHOICES["zh"][1])
        out, _ = _run("测试", "zh", pl)
        self.assertIsNotNone(out)
        self.assertEqual(pl.calls[0][1], K.VOICE_CHOICES["zh"][0])  # tried first
        self.assertEqual(pl.calls[-1][1], K.VOICE_CHOICES["zh"][1])  # fell back

    def test_returns_none_when_all_voices_fail(self):
        pl = FakePipeline(good_voice="__none__")  # every voice raises
        out, sf = _run("测试", "zh", pl)
        self.assertIsNone(out)
        sf.write.assert_not_called()

    def test_empty_text_returns_none(self):
        self.assertIsNone(K.synthesize("", "/tmp/tts_empty", lang="zh"))
        self.assertIsNone(K.synthesize("   ", "/tmp/tts_ws", lang="zh"))


if __name__ == "__main__":
    unittest.main()
