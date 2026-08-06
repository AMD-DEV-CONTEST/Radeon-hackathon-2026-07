"""Unit tests for the Bionic-Graph HTTP client (no live server needed).

We mock urllib.request.urlopen so the client's unwrapping, dedup, and error
handling can be exercised offline.
"""

import io
import json
import unittest
from unittest.mock import patch, MagicMock

import urllib.error

from database.bionic_graph_client import BionicGraphClient, BionicGraphError


def _resp(payload, status=200):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.status = status
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def _http_error(code=500, body=b'{"error":"x"}'):
    return urllib.error.HTTPError("url", code, "err", {}, io.BytesIO(body))


class TestBionicGraphClient(unittest.TestCase):
    def setUp(self):
        self.c = BionicGraphClient(graph="testgraph", timeout=5)

    def _patch(self, payload):
        return patch("urllib.request.urlopen", return_value=_resp(payload))

    def test_create_vertex_unwraps_id(self):
        with self._patch({"success": True, "data": {"id": 7}, "error": None}):
            vid = self.c.create_vertex("person:Alice", labels=["person"])
        self.assertEqual(vid, 7)

    def test_gremlin_unwraps_data(self):
        with self._patch(
            {"success": True, "data": [{"id": 1, "name": "Alice"}], "error": None}
        ):
            out = self.c.gremlin([{"step": "V", "limit": 10}])
        self.assertEqual(out, [{"id": 1, "name": "Alice"}])

    def test_search_dedups_duplicates(self):
        dup = [
            {"id": 1, "name": "Alice"},
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        with self._patch({"success": True, "data": dup, "error": None}):
            out = self.c.search("Alice")
        self.assertEqual(len(out), 2)

    def test_search_no_dedup(self):
        dup = [{"id": 1, "name": "Alice"}, {"id": 1, "name": "Alice"}]
        with self._patch({"success": True, "data": dup, "error": None}):
            out = self.c.search("Alice", dedup=False)
        self.assertEqual(len(out), 2)

    def test_error_envelope_raises(self):
        with self._patch({"success": False, "data": None, "error": "boom"}):
            with self.assertRaises(BionicGraphError):
                self.c.gremlin([{"step": "V"}])

    def test_http_error_raises(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
            with self.assertRaises(BionicGraphError):
                self.c.health()

    def test_health_returns_dict(self):
        with self._patch({"status": "ok", "version": "0.1.0"}):
            self.assertEqual(self.c.health().get("status"), "ok")

    def test_search_builds_query_string(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.method
            return _resp({"success": True, "data": [], "error": None})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.c.search("eat", mode="exact", limit=5)
        self.assertIn("text=eat", captured["url"])
        self.assertIn("mode=exact", captured["url"])
        self.assertIn("limit=5", captured["url"])


if __name__ == "__main__":
    unittest.main()
