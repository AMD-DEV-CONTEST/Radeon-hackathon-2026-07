"""Tests for the diary-wired utterance processing in audio/stream_handler.py."""

import base64
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import audio.stream_handler as sh
from diary import runtime as diary_runtime


class ProcessTurnTextTest(unittest.TestCase):
    def test_empty_text_returns_empty(self):
        res = sh.process_turn_text("")
        self.assertEqual(res["text"], "")
        self.assertEqual(res["answer"], "")

    def test_runs_agent_and_tts(self):
        fake_agent = mock.Mock()
        fake_agent.process_turn.return_value = "今天天气不错"
        fake_ctx = mock.Mock()
        fake_client = mock.Mock()
        fake_client.health.return_value = {}

        with mock.patch.object(
            diary_runtime, "get_or_create_diary_agent", return_value=(fake_agent, fake_ctx)
        ), mock.patch.object(diary_runtime, "get_client", return_value=fake_client), mock.patch(
            "tts.kokoro_tts.synthesize", return_value="/tmp/x.wav"
        ), mock.patch("os.path.exists", return_value=True), mock.patch(
            "builtins.open", mock.mock_open(read_data=b"RIFF")
        ), mock.patch("base64.b64encode", return_value=b"QUJD"):
            res = sh.process_turn_text(
                "今天去跑步了", date="2026-08-05", session_id="s9", lang="zh"
            )

        self.assertEqual(res["answer"], "今天天气不错")
        self.assertEqual(res["audio_b64"], "QUJD")
        args, kwargs = fake_agent.process_turn.call_args
        self.assertEqual(args[1], "2026-08-05")  # date
        self.assertEqual(args[2], "今天去跑步了")  # text
        self.assertEqual(kwargs.get("lang"), "zh")

    def test_empty_reply_no_audio(self):
        fake_agent = mock.Mock()
        fake_agent.process_turn.return_value = ""
        with mock.patch.object(
            diary_runtime, "get_or_create_diary_agent", return_value=(fake_agent, mock.Mock())
        ), mock.patch.object(diary_runtime, "get_client", return_value=mock.Mock()), mock.patch(
            "tts.kokoro_tts.synthesize"
        ) as synth:
            res = sh.process_turn_text("记一下", date="2026-08-05")
        self.assertEqual(res["answer"], "")
        self.assertIsNone(res["audio_b64"])
        synth.assert_not_called()

    def test_process_utterance_stt_failure(self):
        with mock.patch(
            "audio.stt_client.transcribe", return_value="[未配置 API key]"
        ), mock.patch("base64.b64decode", return_value=b"RIFF"):
            res = sh.process_utterance("AAAA")
        self.assertEqual(res["text"], "")
        self.assertTrue(res["answer"].startswith("["))


if __name__ == "__main__":
    unittest.main()
