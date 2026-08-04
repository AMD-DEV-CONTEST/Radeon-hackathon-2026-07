from __future__ import annotations

import io
import json
import ssl
from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from PIL import Image

from scripts.download_remote_evidence import (
    EvidenceClient,
    EvidenceDownloadError,
    TOKEN_ENV,
    download_evidence,
    safe_filename,
)


class FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self._body = io.BytesIO(body)
        self.headers = {"Content-Type": content_type}

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, routes: dict[str, tuple[bytes, str]], expected_token: str):
        self.routes = routes
        self.expected_token = expected_token
        self.requests = []

    def open(self, request, timeout=0):
        self.requests.append(request)
        assert timeout == 30
        assert request.get_header("Authorization") == f"Bearer {self.expected_token}"
        path = request.full_url.split("example.test", 1)[1]
        if path not in self.routes:
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        body, content_type = self.routes[path]
        return FakeResponse(body, content_type)


def json_route(payload: dict) -> tuple[bytes, str]:
    return json.dumps(payload).encode(), "application/json"


def valid_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(output, format="PNG")
    return output.getvalue()


def completed_routes(job_id: str, project_id: str, result_id: str):
    image = valid_png()
    import hashlib

    result = {
        "result_id": result_id,
        "job_id": job_id,
        "project_id": project_id,
        "mode": "rocm",
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "model_revision": "462165984030d82259a11f4367a4eed129e94a7b",
        "output_sha256": hashlib.sha256(image).hexdigest(),
        "human_review_status": "approved",
        "review_note": "verified",
        "image_url": f"/experimental/rocm/jobs/{job_id}/output",
        "model_load_seconds": 2.5,
        "generation_seconds": 12.5,
        "total_seconds": 15.5,
        "peak_allocated_vram_bytes": 123,
        "peak_reserved_vram_bytes": 456,
        "gpu_device_name": "AMD Radeon Graphics",
        "pytorch_version": "2.9.1+gitff65f5b",
        "hip_rocm_version": "7.2.53211-e1a6bc5663",
        "width": 768,
        "height": 768,
        "steps": 15,
        "strength": 0.35,
        "guidance_scale": 6.5,
        "seed": 20260725,
    }
    return {
        "/experimental/rocm/status": json_route(
            {
                "enabled": True,
                "gpu_connected": True,
                "rocm_available": True,
                "model_id": result["model_id"],
                "model_revision": result["model_revision"],
                "internal_path": "/private",
            }
        ),
        f"/experimental/rocm/jobs/{job_id}": json_route(
            {
                "job_id": job_id,
                "project_id": project_id,
                "status": "completed",
                "stage": "completed",
                "output_available": True,
                "gpu_confirmation": True,
                "secret": "must-not-save",
            }
        ),
        f"/projects/{project_id}": json_route(
            {
                "project_id": project_id,
                "configuration": {"product_name": "do not save"},
                "results": [result],
            }
        ),
        f"/experimental/rocm/jobs/{job_id}/output": (
            image,
            "image/png",
        ),
    }


def test_missing_token_is_refused(tmp_path):
    with pytest.raises(EvidenceDownloadError, match=TOKEN_ENV):
        download_evidence(
            "https://example.test",
            str(uuid4()),
            tmp_path,
            environ={},
            opener=FakeOpener({}, ""),
        )


def test_invalid_token_error_is_safe(monkeypatch):
    token = "do-not-print-this-token"

    class Unauthorized:
        def open(self, request, timeout=0):
            raise HTTPError(request.full_url, 401, token, {}, None)

    client = EvidenceClient("https://example.test", token, opener=Unauthorized())
    with pytest.raises(EvidenceDownloadError) as caught:
        client.json("/experimental/rocm/status")
    assert token not in str(caught.value)
    assert "Authentication failed" in str(caught.value)


def test_certificate_verification_is_enabled(monkeypatch):
    contexts = []
    original = ssl.create_default_context

    def capture():
        context = original()
        contexts.append(context)
        return context

    monkeypatch.setattr(ssl, "create_default_context", capture)
    EvidenceClient("https://example.test", "x" * 32, opener=FakeOpener({}, "x" * 32))
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname is True


def test_successful_metadata_and_image_retrieval(tmp_path):
    job_id, project_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
    token = "temporary-secret-value"
    routes = completed_routes(job_id, project_id, result_id)
    environ = {TOKEN_ENV: token}
    files = download_evidence(
        "https://example.test",
        job_id,
        tmp_path,
        environ=environ,
        opener=FakeOpener(routes, token),
    )
    assert TOKEN_ENV not in environ
    assert {path.name for path in files} == {
        "system-status.json",
        "job-metadata.json",
        "result-metadata.json",
        "review-state.json",
        "generated-output.png",
        "hashes.json",
    }
    assert (tmp_path / "generated-output.png").read_bytes().startswith(b"\x89PNG")
    status = json.loads((tmp_path / "system-status.json").read_text())
    assert status["gpu_connected"] is True
    assert "internal_path" not in status
    result = json.loads((tmp_path / "result-metadata.json").read_text())
    assert result["human_review_status"] == "approved"
    assert result["generation_seconds"] == 12.5
    assert "configuration" not in result
    hashes = json.loads((tmp_path / "hashes.json").read_text())
    assert hashes["generated-output.png"] == result["output_sha256"]


@pytest.mark.parametrize("filename", ["../escape.json", "safe/escape.json", "x.json"])
def test_unsafe_filename_rejected(filename):
    with pytest.raises(EvidenceDownloadError, match="Unsafe"):
        safe_filename(filename)


def test_remote_path_traversal_rejected():
    client = EvidenceClient(
        "https://example.test", "x" * 32, opener=FakeOpener({}, "x" * 32)
    )
    with pytest.raises(EvidenceDownloadError, match="Unsafe remote"):
        client.json("/experimental/../private")


def test_token_not_written_to_files_or_exception(tmp_path):
    job_id, project_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
    token = "token-that-must-never-be-written"
    routes = completed_routes(job_id, project_id, result_id)
    environ = {TOKEN_ENV: token}
    download_evidence(
        "https://example.test",
        job_id,
        tmp_path,
        environ=environ,
        opener=FakeOpener(routes, token),
    )
    for path in tmp_path.iterdir():
        assert token.encode() not in path.read_bytes()


def test_hash_mismatch_rejected_without_partial_files(tmp_path):
    job_id, project_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
    token = "temporary-secret-value"
    routes = completed_routes(job_id, project_id, result_id)
    project_path = f"/projects/{project_id}"
    project = json.loads(routes[project_path][0])
    project["results"][0]["output_sha256"] = "0" * 64
    routes[project_path] = json_route(project)

    with pytest.raises(EvidenceDownloadError, match="hash did not match"):
        download_evidence(
            "https://example.test",
            job_id,
            tmp_path,
            environ={TOKEN_ENV: token},
            opener=FakeOpener(routes, token),
        )
    assert list(tmp_path.iterdir()) == []


def test_invalid_image_rejected_without_partial_files(tmp_path):
    job_id, project_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
    token = "temporary-secret-value"
    routes = completed_routes(job_id, project_id, result_id)
    routes[f"/experimental/rocm/jobs/{job_id}/output"] = (
        b"\x89PNG\r\n\x1a\nnot-a-real-image",
        "image/png",
    )

    with pytest.raises(EvidenceDownloadError, match="image was invalid"):
        download_evidence(
            "https://example.test",
            job_id,
            tmp_path,
            environ={TOKEN_ENV: token},
            opener=FakeOpener(routes, token),
        )
    assert list(tmp_path.iterdir()) == []


def test_incomplete_json_schema_is_rejected(tmp_path):
    job_id, project_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
    token = "temporary-secret-value"
    routes = completed_routes(job_id, project_id, result_id)
    routes["/experimental/rocm/status"] = json_route({"enabled": True})

    with pytest.raises(EvidenceDownloadError, match="schema was incomplete"):
        download_evidence(
            "https://example.test",
            job_id,
            tmp_path,
            environ={TOKEN_ENV: token},
            opener=FakeOpener(routes, token),
        )
    assert list(tmp_path.iterdir()) == []
