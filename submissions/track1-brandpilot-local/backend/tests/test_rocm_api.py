from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.prompts import build_commercial_prompt, sanitize_prompt_field
from app.services.rocm_jobs import RocmJobService
from app.services.store import ProjectStore


def wait_for(service: RocmJobService, job_id: str, status: str, timeout: float = 3) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get(job_id)
        if job["status"] == status:
            return job
        if job["status"] == "failed" and status != "failed":
            pytest.fail(job["failure"])
        time.sleep(0.01)
    pytest.fail(f"Job did not reach {status}")


class FakePipeline:
    def __init__(
        self,
        output_dir: Path,
        *,
        blocker: threading.Event | None = None,
        fail: bool = False,
        counters: dict[str, int] | None = None,
    ):
        self.output_dir = output_dir
        self.blocker = blocker
        self.fail = fail
        self.counters = counters if counters is not None else {"loads": 0, "generations": 0}

    def load_model(self) -> None:
        self.counters["loads"] += 1

    def generate_ad_image(
        self,
        image_path,
        concept,
        output_format,
        *,
        output_path,
        progress_callback,
        seed,
    ):
        self.counters["generations"] += 1
        progress_callback(1, 15)
        if self.blocker:
            self.blocker.wait(timeout=2)
        if self.fail:
            raise RuntimeError("synthetic GPU failure")
        Image.new("RGB", (768, 768), "red").save(output_path)
        progress_callback(15, 15)
        return {
            "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
            "model_revision": "462165984030d82259a11f4367a4eed129e94a7b",
            "pipeline_class": "StableDiffusionXLImg2ImgPipeline",
            "width": 768,
            "height": 768,
            "steps": 15,
            "strength": 0.35,
            "guidance_scale": 6.5,
            "seed": seed,
            "generation_seconds": 1.25,
            "peak_allocated_gpu_memory_bytes": 123,
            "peak_reserved_gpu_memory_bytes": 456,
            "gpu_device_name": "AMD Radeon Test Device",
            "pytorch_version": "2.9.1-test",
            "hip_rocm_version": "7.2-test",
        }


def positive_status() -> dict:
    return {
        "gpu_connected": True,
        "rocm_available": True,
        "device": "AMD Radeon Test Device",
        "pytorch_version": "2.9.1-test",
        "hip_version": "7.2-test",
        "message": "AMD Radeon HIP device verified.",
    }


@pytest.fixture
def experimental(
    tmp_path, monkeypatch, payload, image_bytes
) -> tuple[object, RocmJobService, dict]:
    monkeypatch.setenv("ENABLE_EXPERIMENTAL_ROCM", "true")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEMO_AUTH_TOKEN", "a" * 64)
    project_store = ProjectStore(tmp_path / "storage")
    service = RocmJobService(
        project_store=project_store,
        output_root=tmp_path / "outputs",
        pipeline_factory=lambda output: FakePipeline(output),
        status_provider=positive_status,
    )
    import app.api.routes as normal_routes
    import app.api.rocm as rocm_routes

    monkeypatch.setattr(normal_routes, "store", project_store)
    monkeypatch.setattr(normal_routes, "STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setattr(rocm_routes, "store", project_store)
    monkeypatch.setattr(rocm_routes, "rocm_jobs", service)
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {'a' * 64}"}
    project = client.post("/projects", json=payload, headers=headers).json()
    upload = client.post(
        f"/projects/{project['project_id']}/assets",
        files={"file": ("safe.png", image_bytes, "image/png")},
        headers=headers,
    )
    assert upload.status_code == 201
    yield client, service, {"project": project, "headers": headers}
    service.shutdown()


def test_experimental_endpoint_disabled_by_default(client, payload, image_bytes):
    project = client.post("/projects", json=payload).json()
    client.post(
        f"/projects/{project['project_id']}/assets",
        files={"file": ("safe.png", image_bytes, "image/png")},
    )
    response = client.post(
        f"/experimental/rocm/projects/{project['project_id']}/generate",
        json={"creative_style": "Luxury", "output_format": "Instagram Square"},
    )
    assert response.status_code == 503


def test_demo_auth_missing_invalid_and_valid(experimental):
    client, _, context = experimental
    assert client.get("/experimental/rocm/status").status_code == 401
    assert client.get(f"/projects/{context['project']['project_id']}").status_code == 401
    assert (
        client.get(
            "/experimental/rocm/status",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    response = client.get("/experimental/rocm/status", headers=context["headers"])
    assert response.status_code == 200
    assert response.json()["gpu_connected"] is True


def test_authenticated_demo_refuses_wildcard_cors(monkeypatch):
    from app.core.config import validate_experimental_configuration

    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEMO_AUTH_TOKEN", "a" * 64)
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="explicit CORS origins"):
        validate_experimental_configuration()


def test_invalid_project_and_missing_asset(experimental, payload):
    client, _, context = experimental
    headers = context["headers"]
    assert (
        client.post(
            "/experimental/rocm/projects/not-a-uuid/generate",
            json={"creative_style": "Luxury", "output_format": "Instagram Square"},
            headers=headers,
        ).status_code
        == 404
    )
    empty = client.post("/projects", json=payload, headers=headers).json()
    assert (
        client.post(
            f"/experimental/rocm/projects/{empty['project_id']}/generate",
            json={"creative_style": "Luxury", "output_format": "Instagram Square"},
            headers=headers,
        ).status_code
        == 409
    )


def test_job_completes_returns_output_and_metadata(experimental):
    client, service, context = experimental
    project_id = context["project"]["project_id"]
    submitted = client.post(
        f"/experimental/rocm/projects/{project_id}/generate",
        json={
            "creative_style": "Luxury",
            "output_format": "Instagram Square",
            "seed": 20260725,
        },
        headers=context["headers"],
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    job = wait_for(service, job_id, "completed")
    assert job["stage"] == "completed"
    assert job["current_step"] == job["total_steps"] == 15
    assert job["gpu_confirmation"] is True
    result = job["result"]
    required = {
        "result_id",
        "job_id",
        "project_id",
        "mode",
        "experimental",
        "model_id",
        "model_revision",
        "pipeline_class",
        "prompt",
        "negative_prompt",
        "model_load_seconds",
        "generation_seconds",
        "total_seconds",
        "peak_allocated_vram_bytes",
        "peak_reserved_vram_bytes",
        "gpu_device_name",
        "pytorch_version",
        "hip_rocm_version",
        "input_sha256",
        "output_sha256",
        "disclosure",
    }
    assert required <= result.keys()
    assert result["mode"] == "rocm" and result["experimental"] is True
    output = client.get(
        f"/experimental/rocm/jobs/{job_id}/output", headers=context["headers"]
    )
    assert output.status_code == 200
    assert output.headers["content-type"] == "image/png"
    persisted = client.get(f"/projects/{project_id}", headers=context["headers"]).json()
    assert persisted["results"][0]["result_id"] == result["result_id"]


def test_protected_output_supports_authenticated_browser_fetch(experimental):
    client, service, context = experimental
    project_id = context["project"]["project_id"]
    submitted = client.post(
        f"/experimental/rocm/projects/{project_id}/generate",
        json={"creative_style": "Luxury", "output_format": "Instagram Square"},
        headers=context["headers"],
    )
    job_id = submitted.json()["job_id"]
    wait_for(service, job_id, "completed")
    response = client.get(
        f"/experimental/rocm/jobs/{job_id}/output",
        headers={**context["headers"], "Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_queued_loading_and_generating_states(
    tmp_path, payload, image_bytes
):
    project_store = ProjectStore(tmp_path / "storage")
    from app.schemas.project import ProjectCreate

    project = project_store.create(ProjectCreate(**payload))
    assets = project_store.projects / project["project_id"] / "assets"
    assets.mkdir(parents=True)
    (assets / "asset.png").write_bytes(image_bytes)
    project["asset"] = {"storage_name": "asset.png", "content_type": "image/png"}
    project_store.save(project)
    load_blocker = threading.Event()
    generation_blocker = threading.Event()

    class StagePipeline(FakePipeline):
        def load_model(self):
            self.counters["loads"] += 1
            load_blocker.wait(timeout=2)

    service = RocmJobService(
        project_store=project_store,
        output_root=tmp_path / "outputs",
        pipeline_factory=lambda output: StagePipeline(
            output, blocker=generation_blocker
        ),
        status_provider=positive_status,
    )
    submitted = service.submit(project, "Luxury", "Instagram Square", 1)
    assert submitted["status"] == "queued"
    wait_for(service, submitted["job_id"], "loading_model")
    load_blocker.set()
    wait_for(service, submitted["job_id"], "generating")
    generation_blocker.set()
    wait_for(service, submitted["job_id"], "completed")
    service.shutdown()


def test_second_endpoint_submission_returns_conflict(experimental):
    client, service, context = experimental
    blocker = threading.Event()
    service.pipeline_factory = lambda output: FakePipeline(output, blocker=blocker)
    project_id = context["project"]["project_id"]
    body = {"creative_style": "Luxury", "output_format": "Instagram Square"}
    first = client.post(
        f"/experimental/rocm/projects/{project_id}/generate",
        json=body,
        headers=context["headers"],
    )
    assert first.status_code == 202
    wait_for(service, first.json()["job_id"], "generating")
    second = client.post(
        f"/experimental/rocm/projects/{project_id}/generate",
        json=body,
        headers=context["headers"],
    )
    assert second.status_code == 409
    blocker.set()
    wait_for(service, first.json()["job_id"], "completed")


def test_second_concurrent_job_rejected_and_pipeline_reused(
    tmp_path, payload, image_bytes
):
    project_store = ProjectStore(tmp_path / "storage")
    from app.schemas.project import ProjectCreate

    project = project_store.create(ProjectCreate(**payload))
    assets = project_store.projects / project["project_id"] / "assets"
    assets.mkdir(parents=True)
    asset_path = assets / "asset.png"
    asset_path.write_bytes(image_bytes)
    project["asset"] = {
        "storage_name": "asset.png",
        "content_type": "image/png",
    }
    project_store.save(project)
    blocker = threading.Event()
    counters = {"loads": 0, "generations": 0}
    service = RocmJobService(
        project_store=project_store,
        output_root=tmp_path / "outputs",
        pipeline_factory=lambda output: FakePipeline(
            output, blocker=blocker, counters=counters
        ),
        status_provider=positive_status,
    )
    first = service.submit(project, "Luxury", "Instagram Square", 1)
    wait_for(service, first["job_id"], "generating")
    with pytest.raises(RuntimeError, match="Only one"):
        service.submit(project, "Luxury", "Instagram Square", 2)
    blocker.set()
    wait_for(service, first["job_id"], "completed")
    second = service.submit(project_store.get(project["project_id"]), "Lifestyle", "Instagram Square", 2)
    wait_for(service, second["job_id"], "completed")
    assert counters == {"loads": 1, "generations": 2}
    service.shutdown()


def test_failed_model_load_is_discarded_then_healthy_pipeline_is_reused(
    tmp_path, payload, image_bytes, monkeypatch
):
    project_store = ProjectStore(tmp_path / "storage")
    from app.schemas.project import ProjectCreate

    project = project_store.create(ProjectCreate(**payload))
    assets = project_store.projects / project["project_id"] / "assets"
    assets.mkdir(parents=True)
    (assets / "asset.png").write_bytes(image_bytes)
    project["asset"] = {"storage_name": "asset.png", "content_type": "image/png"}
    project_store.save(project)
    counters = {"loads": 0, "generations": 0, "empty_cache": 0}

    class LoadOncePipeline(FakePipeline):
        def load_model(self) -> None:
            self.counters["loads"] += 1
            if self.counters["loads"] == 1:
                raise RuntimeError(
                    "synthetic model load failure token=private-value-123 "
                    "https://example.test/failure /example/cache"
                )

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def empty_cache():
            counters["empty_cache"] += 1

    monkeypatch.setitem(
        __import__("sys").modules,
        "torch",
        SimpleNamespace(cuda=FakeCuda()),
    )

    service = RocmJobService(
        project_store=project_store,
        output_root=tmp_path / "outputs",
        pipeline_factory=lambda output: LoadOncePipeline(output, counters=counters),
        status_provider=positive_status,
    )
    first = service.submit(project, "Luxury", "Instagram Square", 1)
    failed = wait_for(service, first["job_id"], "failed")
    assert service._pipeline is None
    assert "[credential]" in failed["failure"]
    assert "[url]" in failed["failure"]
    assert "[path]" in failed["failure"]
    assert "private-value-123" not in failed["failure"]
    assert counters["empty_cache"] == 1
    second = service.submit(project_store.get(project["project_id"]), "Luxury", "Instagram Square", 2)
    wait_for(service, second["job_id"], "completed")
    healthy_pipeline = service._pipeline
    assert healthy_pipeline is not None
    third = service.submit(
        project_store.get(project["project_id"]),
        "Lifestyle",
        "Instagram Square",
        3,
    )
    wait_for(service, third["job_id"], "completed")
    assert service._pipeline is healthy_pipeline
    assert counters == {"loads": 2, "generations": 2, "empty_cache": 1}
    service.shutdown()


def test_failed_state_has_safe_error_and_no_mock_fallback(
    tmp_path, payload, image_bytes
):
    project_store = ProjectStore(tmp_path / "storage")
    from app.schemas.project import ProjectCreate

    project = project_store.create(ProjectCreate(**payload))
    asset_dir = project_store.projects / project["project_id"] / "assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / "asset.png").write_bytes(image_bytes)
    project["asset"] = {"storage_name": "asset.png", "content_type": "image/png"}
    project_store.save(project)
    service = RocmJobService(
        project_store=project_store,
        output_root=tmp_path / "outputs",
        pipeline_factory=lambda output: FakePipeline(output, fail=True),
        status_provider=positive_status,
    )
    job = service.submit(project, "Luxury", "Instagram Square", 1)
    failed = wait_for(service, job["job_id"], "failed")
    assert "synthetic GPU failure" in failed["failure"]
    assert failed["result"] is None and failed["output_available"] is False
    assert project_store.get(project["project_id"])["results"] == []
    service.shutdown()


def test_output_path_traversal_is_refused(experimental, tmp_path):
    _, service, context = experimental
    project = service.store.get(context["project"]["project_id"])
    submitted = service.submit(project, "Luxury", "Instagram Square", 1)
    wait_for(service, submitted["job_id"], "completed")
    outside = tmp_path / "outside.png"
    Image.new("RGB", (8, 8), "blue").save(outside)
    with service._state_lock:
        service._jobs[submitted["job_id"]]["_output_path"] = str(outside)
    with pytest.raises(ValueError, match="Unsafe"):
        service.output_path(submitted["job_id"])


def test_prompt_sanitization_and_no_readable_copy(payload):
    payload["product_name"] = "Product\x00\nName"
    payload["negative_instructions"] = "avoid clutter " * 100
    prompt, negative = build_commercial_prompt(
        payload, "Minimal Studio", "Instagram Square"
    )
    assert "\x00" not in prompt and "\n" not in prompt
    assert "no added typography" in prompt.lower()
    assert "no added packaging copy" in prompt.lower()
    assert "unreadable text" in negative
    assert len(negative) <= 900
    assert len(sanitize_prompt_field("x" * 500, 20)) == 20


def test_seed_and_style_validation(experimental):
    client, _, context = experimental
    project_id = context["project"]["project_id"]
    for body in (
        {
            "creative_style": "Unknown",
            "output_format": "Instagram Square",
        },
        {
            "creative_style": "Luxury",
            "output_format": "Instagram Square",
            "seed": -1,
        },
    ):
        assert (
            client.post(
                f"/experimental/rocm/projects/{project_id}/generate",
                json=body,
                headers=context["headers"],
            ).status_code
            == 422
        )


def test_status_provider_refuses_missing_gpu_or_hip(monkeypatch):
    class FakeCuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def device_count():
            return 0

    fake = SimpleNamespace(
        __version__="test",
        version=SimpleNamespace(hip=None),
        cuda=FakeCuda(),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake)
    status = RocmJobService._default_status_provider()
    assert status["gpu_connected"] is False
    assert status["rocm_available"] is False
