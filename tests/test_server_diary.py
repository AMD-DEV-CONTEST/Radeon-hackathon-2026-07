"""Tests for server.py after the diary swap (agent + date threading)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import server


class ServerDiaryTest(unittest.TestCase):
    def setUp(self):
        self.app = server.app.test_client()

    def test_health_ok(self):
        fake_client = mock.Mock()
        fake_client.health.return_value = {"status": "ok"}
        with mock.patch.object(server.runtime, "get_client", return_value=fake_client):
            r = self.app.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["database"])

    def test_health_degraded(self):
        fake_client = mock.Mock()
        fake_client.health.side_effect = RuntimeError("down")
        with mock.patch.object(server.runtime, "get_client", return_value=fake_client):
            r = self.app.get("/api/health")
        self.assertFalse(r.get_json()["database"])

    def test_ask_uses_date_and_agent(self):
        with mock.patch.object(
            server, "process_turn_text", return_value={"text": "hi", "answer": "ok", "audio_b64": None}
        ) as m, mock.patch.object(server.runtime, "today_iso", return_value="2026-08-05"):
            r = self.app.post("/api/ask", json={"query": "今天吃了什么", "date": "2026-08-04"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["answer"], "ok")
        self.assertEqual(body["date"], "2026-08-04")
        _, kwargs = m.call_args
        self.assertEqual(kwargs["date"], "2026-08-04")

    def test_ask_defaults_to_today(self):
        with mock.patch.object(
            server, "process_turn_text", return_value={"text": "x", "answer": "y", "audio_b64": None}
        ) as m, mock.patch.object(server.runtime, "today_iso", return_value="2026-08-05"):
            r = self.app.post("/api/ask", json={"query": "hi"})
        self.assertEqual(r.get_json()["date"], "2026-08-05")
        self.assertEqual(m.call_args.kwargs["date"], "2026-08-05")


class WSControlTest(unittest.TestCase):
    def setUp(self):
        server._session_dates.clear()

    def tearDown(self):
        server._session_dates.clear()

    def _ws(self):
        return mock.Mock()

    def test_hello_sets_date_and_sends_ready(self):
        ws = self._ws()
        handler = mock.Mock()
        out = server._handle_control(ws, handler, "s1", '{"type":"hello","vad":"client","date":"2026-08-04"}')
        self.assertIsNone(out)
        self.assertEqual(server._session_dates["s1"], "2026-08-04")
        ws.send.assert_called_once()
        self.assertIn("ready", ws.send.call_args.args[0])

    def test_date_control_updates_session_and_acks(self):
        ws = self._ws()
        server._session_dates["s1"] = "2026-08-05"
        out = server._handle_control(ws, mock.Mock(), "s1", '{"type":"date","date":"2026-08-06"}')
        self.assertIsNone(out)
        self.assertEqual(server._session_dates["s1"], "2026-08-06")
        self.assertIn("date_ack", ws.send.call_args.args[0])

    def test_text_control_returns_text_turn(self):
        ws = self._ws()
        out = server._handle_control(ws, mock.Mock(), "s1", '{"type":"text","text":"今天吃了啥"}')
        self.assertEqual(out, {"text": "今天吃了啥"})

    def test_eou_returns_utterance_from_handler(self):
        ws = self._ws()
        handler = mock.Mock()
        handler.end_of_utterance.return_value = "WAVB64"
        out = server._handle_control(ws, handler, "s1", '{"type":"eou"}')
        self.assertEqual(out, "WAVB64")


if __name__ == "__main__":
    unittest.main()
