"""Tests for diary/runtime.py — the server<->diary wiring seam."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from diary import runtime


class FakeClient:
    def health(self):
        return {"ok": True}


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        runtime._client = None
        runtime._agents.clear()

    def tearDown(self):
        runtime._client = None
        runtime._agents.clear()

    def test_today_iso_format(self):
        self.assertRegex(runtime.today_iso(), r"^\d{4}-\d{2}-\d{2}$")

    def test_get_client_is_singleton(self):
        runtime._client = FakeClient()
        self.assertIs(runtime.get_client(), runtime.get_client())

    def test_get_or_create_caches_by_session(self):
        runtime._client = FakeClient()
        ag1, ctx1 = runtime.get_or_create_diary_agent("s1")
        ag2, ctx2 = runtime.get_or_create_diary_agent("s1")
        self.assertIs(ag1, ag2)
        ag3, _ = runtime.get_or_create_diary_agent("s2")
        self.assertIsNot(ag1, ag3)
        self.assertIs(ctx1.client, runtime._client)

    def test_get_or_create_without_session(self):
        runtime._client = FakeClient()
        ag, ctx = runtime.get_or_create_diary_agent(None)
        self.assertIsNotNone(ag)
        self.assertIs(ctx.client, runtime._client)


if __name__ == "__main__":
    unittest.main()
