from __future__ import annotations

import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from src.web import AgentHandler


class FakeAgent:
    def run(self, image: str, request: str, **kwargs) -> dict:
        overlay_path = kwargs["overlay_path"]
        with open(overlay_path, "wb") as output:
            output.write(b"\x89PNG\r\n\x1a\noverlay")
        return {
            "schema_version": "3.0",
            "image": {"filename": "temporary.jpg"},
            "intent": {"task_type": "shooting"},
            "analysis": {"scene": "test"},
            "shooting_plan": {"mode": "shooting"},
            "critic": {"status": "pass", "issues": []},
            "agent_trace": [],
            "tool_calls": [
                {
                    "tool": "vision_analyzer",
                    "device": "AMD Radeon GPU / ROCm HIP",
                    "status": "completed",
                    "seconds": 1.0,
                }
            ],
            "permission_audit": [
                {
                    "tool": "vision_analyzer",
                    "permission": "gpu_inference",
                    "decision": "allow",
                }
            ],
            "privacy": {
                "core_inference": "local_amd_rocm",
                "external_ai_api": False,
                "external_network_allowed": False,
                "persistent_memory": False,
            },
            "metrics": {"gpu": "AMD Radeon Graphics"},
            "pose_json": {
                "body_pose": {"body_rotation": "Turn 15 degrees to the side"},
                "hands": {"position": "Hold the phone naturally"},
                "gaze": {"direction": "Look toward the camera"},
                "photographer": {
                    "position": "To the subject's front-left",
                    "distance": "1.5 to 2 meters",
                },
            },
            "pose_card": {
                "status": "generated",
                "render_mode": "ai_photography_execution_card",
                "path": str(overlay_path),
                "source_preserved": True,
                "source_pixels_in_output": True,
                "image_generation_model_used": False,
            },
            "preview": {"status": "disabled"},
            "visual_review": {"status": "not_applicable", "issues": []},
        }


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.health_patch = patch(
            "src.web._health",
            return_value={"status": "ready", "gpu": "AMD Radeon Graphics"},
        )
        cls.agent_patch = patch("src.web._get_agent", return_value=FakeAgent())
        cls.health_patch.start()
        cls.agent_patch.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.agent_patch.stop()
        cls.health_patch.stop()

    def request(self, path: str, value: object | None = None):
        data = None if value is None else json.dumps(value).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        return urllib.request.urlopen(request, timeout=3)

    def test_index_and_health(self) -> None:
        with self.request("/") as response:
            page = response.read().decode()
            self.assertIn("AI Photography Guidance Card", page)
            self.assertIn("Tool Invocation", page)
            self.assertIn("Permission Audit", page)
            self.assertNotIn("generateConcept", page)
            self.assertIn("Content-Security-Policy", response.headers)
        with self.request("/api/health") as response:
            self.assertEqual(json.load(response)["status"], "ready")

    def test_analyze_contract_and_original_filename(self) -> None:
        image = base64.b64encode(b"\xff\xd8\xfftest").decode()
        body = {
            "filename": "../../portrait.jpg",
            "image": "data:image/jpeg;base64," + image,
        }
        with self.request("/api/analyze", body) as response:
            result = json.load(response)
        self.assertEqual(result["schema_version"], "3.0")
        self.assertEqual(result["image"]["filename"], "portrait.jpg")
        self.assertTrue(
            result["pose_card"]["data_url"].startswith("data:image/png")
        )
        self.assertEqual(
            result["pose_card"]["render_mode"],
            "ai_photography_execution_card",
        )
        self.assertFalse(result["pose_card"]["image_generation_model_used"])
        self.assertTrue(
            result["pose_card"]["filename"].endswith(
                "-ai-photography-guidance-card.png"
            )
        )
        self.assertEqual(result["preview"]["status"], "disabled")

    def test_rejects_concept_generation_request(self) -> None:
        image = base64.b64encode(b"\xff\xd8\xfftest").decode()
        body = {
            "filename": "portrait.jpg",
            "request": "Create a shooting plan.",
            "image": "data:image/jpeg;base64," + image,
            "generate_concept": True,
        }
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/analyze", body)
        self.assertEqual(caught.exception.code, 400)

    def test_accepts_image_without_text_request(self) -> None:
        image = base64.b64encode(b"\xff\xd8\xfftest").decode()
        body = {
            "filename": "portrait.jpg",
            "image": "data:image/jpeg;base64," + image,
        }
        with self.request("/api/analyze", body) as response:
            self.assertEqual(json.load(response)["schema_version"], "3.0")

    def test_rejects_non_object_and_invalid_image(self) -> None:
        for body in ([], {"image": "bad"}):
            with self.subTest(body=body):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request("/api/analyze", body)
                self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
