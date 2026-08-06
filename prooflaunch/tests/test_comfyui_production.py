from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from prooflaunch_remix.comfyui_production import (
    ComfyGenerationRequest,
    ComfyProductionError,
    ComfyUIProductionClient,
    ComfyWorkflowContract,
    MediaKind,
    ModelRuntimeRef,
    WorkflowBinding,
)


class _FakeComfyHandler(BaseHTTPRequestHandler):
    submitted = None
    unsafe_output = False
    interrupted = False
    image_bytes = b""

    def log_message(self, *_args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/prompt":
            type(self).submitted = json.loads(body)
            self._json({"prompt_id": "prompt-123", "node_errors": {}})
        elif self.path == "/interrupt":
            type(self).interrupted = True
            self._json({})
        else:
            self.send_error(404)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/history/prompt-123":
            filename = "../escape.png" if type(self).unsafe_output else "result.png"
            self._json(
                {
                    "prompt-123": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": filename, "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                    }
                }
            )
        elif parsed.path == "/view":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(type(self).image_bytes)))
            self.end_headers()
            self.wfile.write(type(self).image_bytes)
        else:
            self.send_error(404)

    def _json(self, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ComfyUIProductionClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        workflow = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "output"}},
        }
        self.workflow_path = self.root / "workflow-api.json"
        self.workflow_path.write_text(json.dumps(workflow, sort_keys=True))
        image = Image.new("RGB", (32, 32), "purple")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        _FakeComfyHandler.image_bytes = buffer.getvalue()
        _FakeComfyHandler.submitted = None
        _FakeComfyHandler.unsafe_output = False
        _FakeComfyHandler.interrupted = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeComfyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = ComfyUIProductionClient(
            f"http://127.0.0.1:{self.server.server_port}",
            timeout_seconds=5,
            poll_interval_seconds=0.01,
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def contract(self, **changes) -> ComfyWorkflowContract:
        values = {
            "workflow_id": "qwen-image-production-v1",
            "media_kind": MediaKind.IMAGE,
            "workflow_source_url": "https://github.com/Comfy-Org/workflow_templates",
            "workflow_revision": "1" * 40,
            "workflow_api_sha256": hashlib.sha256(self.workflow_path.read_bytes()).hexdigest(),
            "bindings": (
                WorkflowBinding("prompt", "1", "text"),
                WorkflowBinding("seed", "3", "seed"),
            ),
            "output_node_ids": ("9",),
            "models": (
                ModelRuntimeRef(
                    project="Qwen-Image",
                    repository_url="https://github.com/QwenLM/Qwen-Image",
                    source_revision="2" * 40,
                    model_id="Qwen/Qwen-Image-2.0",
                    model_revision="3" * 40,
                    source_license="Apache-2.0",
                    model_license="Apache-2.0",
                    license_locator="https://huggingface.co/Qwen/Qwen-Image-2.0/blob/main/LICENSE",
                    commercial_use_allowed=True,
                    weight_sha256="4" * 64,
                ),
            ),
            "executable_admission": True,
        }
        values.update(changes)
        return ComfyWorkflowContract(**values)

    def request(self, **changes) -> ComfyGenerationRequest:
        values = {
            "request_id": "case-001",
            "values": {"prompt": "cinematic product proof", "seed": 42},
            "upload_paths": {},
            "output_dir": str(self.root / "output"),
            "rights_locator": "project-owned://case-001",
        }
        values.update(changes)
        return ComfyGenerationRequest(**values)

    def test_executes_frozen_workflow_and_seals_generated_output(self) -> None:
        receipt = self.client.execute(self.contract(), self.workflow_path, self.request())
        self.assertEqual(receipt.prompt_id, "prompt-123")
        self.assertEqual(len(receipt.artifacts), 1)
        artifact = receipt.artifacts[0]
        target = Path(receipt.output_root) / artifact.relative_path
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), artifact.content_sha256)
        self.assertFalse(receipt.external_publish_executed)
        self.assertFalse(receipt.human_release_completed)
        self.assertFalse(receipt.four_a_effect_proven)
        submitted = _FakeComfyHandler.submitted["prompt"]
        self.assertEqual(submitted["1"]["inputs"]["text"], "cinematic product proof")
        self.assertEqual(submitted["3"]["inputs"]["seed"], 42)

    def test_non_admitted_workflow_never_calls_backend(self) -> None:
        with self.assertRaisesRegex(ComfyProductionError, "not passed executable"):
            self.client.execute(
                self.contract(executable_admission=False), self.workflow_path, self.request()
            )
        self.assertIsNone(_FakeComfyHandler.submitted)

    def test_unpinned_or_noncommercial_model_cannot_be_executable(self) -> None:
        model = replace(
            self.contract().models[0],
            model_revision=None,
            commercial_use_allowed=False,
            weight_sha256=None,
        )
        with self.assertRaisesRegex(ComfyProductionError, "pinned, hashed weights"):
            replace(self.contract(), models=(model,)).validate()

    def test_workflow_hash_drift_fails_before_submission(self) -> None:
        contract = self.contract()
        self.workflow_path.write_text("{}")
        with self.assertRaisesRegex(ComfyProductionError, "hash does not match"):
            self.client.execute(contract, self.workflow_path, self.request())
        self.assertIsNone(_FakeComfyHandler.submitted)

    def test_undeclared_override_fails_before_submission(self) -> None:
        request = self.request(values={"prompt": "x", "seed": 1, "steps": 100})
        with self.assertRaisesRegex(ComfyProductionError, "undeclared"):
            self.client.execute(self.contract(), self.workflow_path, request)

    def test_path_traversal_output_interrupts_and_fails_closed(self) -> None:
        _FakeComfyHandler.unsafe_output = True
        with self.assertRaisesRegex(ComfyProductionError, "unsafe output filename"):
            self.client.execute(self.contract(), self.workflow_path, self.request())
        self.assertTrue(_FakeComfyHandler.interrupted)

    def test_large_output_limit_fails_before_buffering_and_cleans_partial_file(self) -> None:
        client = ComfyUIProductionClient(
            f"http://127.0.0.1:{self.server.server_port}",
            timeout_seconds=5,
            poll_interval_seconds=0.01,
            max_output_bytes=len(_FakeComfyHandler.image_bytes) - 1,
        )
        request = self.request(output_dir=str(self.root / "limited-output"))
        with self.assertRaisesRegex(ComfyProductionError, "exceeds size limit"):
            client.execute(self.contract(), self.workflow_path, request)
        self.assertTrue(_FakeComfyHandler.interrupted)
        self.assertEqual(list((self.root / "limited-output").iterdir()), [])

    def test_remote_endpoint_is_blocked_by_default(self) -> None:
        with self.assertRaisesRegex(ComfyProductionError, "not allowlisted"):
            ComfyUIProductionClient("https://example.com")


if __name__ == "__main__":
    unittest.main()
