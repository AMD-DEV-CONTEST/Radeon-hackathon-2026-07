from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.services.embeddings import LocalEmbeddingEngine


class AgentFlowBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/system/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("ollama_running", payload)
        self.assertTrue(payload["ok"])

    def test_chat_fallback_path(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={"message": "Plan a launch checklist for an offline AI demo."},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Planner Agent", " ".join(item["agent"] for item in payload["timeline"]))
        self.assertTrue(payload["conversation_id"])
        self.assertTrue(payload["response"])

    def test_embedding_dimension(self) -> None:
        vector = LocalEmbeddingEngine(dimensions=256).embed("agent memory research tool reviewer")
        self.assertEqual(len(vector), 256)
        self.assertTrue(any(value != 0 for value in vector))


if __name__ == "__main__":
    unittest.main()
