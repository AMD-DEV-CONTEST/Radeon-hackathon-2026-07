import hashlib
import io
import json
import struct
import base64
from pathlib import Path

import pytest

import services.database_registry as registry
import services.media_generation as generation
from app.dependencies.auth import USER_API_KEY
from main import app
from services.db import close_connection, get_db, init_db
from services.media_assets import (
    MediaAssetError,
    create_media_binding,
    get_media_asset,
    import_media_asset,
    transition_media_asset,
)
from services.model_packages.manifest import load_package_manifest
from services.model_registry import (
    create_model_profile,
    create_provider,
    update_model_profile,
)
from services.model_runtime.worker_process import ADAPTERS, Kandinsky22WorkerAdapter
from tests.asgi_client import asgi_request


def png_bytes(width=8, height=9):
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    monkeypatch.setattr(
        generation,
        "get_runtime_path",
        lambda *parts: root.joinpath(*parts),
    )
    registry.init_registry()
    init_db()
    return root


def allow_native(monkeypatch):
    monkeypatch.setattr(
        generation,
        "_native_target",
        lambda package_id, operation: {
            "target_kind": "native_package",
            "package_id": package_id,
            "model_profile_id": None,
            "provider_id": None,
            "provider_model_name": "kandinsky-community/kandinsky-2-2",
        },
    )


class FakeImageExecutor:
    def __init__(self, payload=None):
        self.payload = payload or png_bytes()
        self.calls = []

    def execute(self, task, *, output_path, source, job_started):
        self.calls.append(
            {
                "task_id": task["task_id"],
                "source": source,
                "prompt": task["prompt"],
            }
        )
        assert job_started("runtime-job-test") is True
        output_path.write_bytes(self.payload)
        return {
            "effective_backend": "rocm_pytorch",
            "device_id": "amd:test",
            "runtime_job_id": "runtime-job-test",
            "output_mime_type": "image/png",
            "output_digest": hashlib.sha256(self.payload).hexdigest(),
            "elapsed_ms": 12.5,
        }


class FailingExecutor:
    def execute(self, *_args, **_kwargs):
        raise generation.MediaGenerationError(
            "TEST_GENERATION_FAILED",
            "Synthetic generation failure",
        )


def native_payload(**overrides):
    payload = {
        "database_id": "default",
        "book_id": "default",
        "operation": "image.generate",
        "prompt": "夜色中的浮空城市",
        "negative_prompt": "",
        "parameters": {
            "width": 768,
            "height": 512,
            "steps": 20,
            "guidance_scale": 4.0,
            "strength": 0.3,
        },
        "seed": 42,
        "package_id": generation.DEFAULT_IMAGE_PACKAGE_ID,
        "requested_backend": "rocm_pytorch",
    }
    payload.update(overrides)
    return payload


def test_generation_creates_temporary_asset_and_ordered_safe_events(
    tmp_path, monkeypatch
):
    setup_runtime(tmp_path, monkeypatch)
    allow_native(monkeypatch)
    db = get_db()
    db.execute(
        "INSERT INTO chapters(chapter_id,book_id,title) "
        "VALUES ('CHP_GEN','default','Generated scene')"
    )
    db.commit()
    db.close()

    task = generation.create_media_generation_task(native_payload(), start=False)
    executor = FakeImageExecutor()
    completed = generation.run_media_generation_task(
        "default",
        task["task_id"],
        executor=executor,
    )

    assert completed["status"] == "completed"
    assert completed["prompt"] == "夜色中的浮空城市"
    assert completed["runtime_job_id"] == "runtime-job-test"
    assert completed["effective_backend"] == "rocm_pytorch"
    asset = get_media_asset("default", completed["output_asset_id"])
    assert asset["source_type"] == "generated"
    assert asset["lifecycle_status"] == "temporary"
    provenance = asset["metadata"]["generation"]
    assert provenance["seed"] == 42
    assert provenance["prompt_hash"] == completed["prompt_hash"]
    assert "prompt" not in provenance

    with pytest.raises(MediaAssetError) as blocked:
        create_media_binding(
            "default",
            asset["asset_id"],
            {
                "book_id": "default",
                "target_type": "chapter",
                "target_id": "CHP_GEN",
                "binding_type": "chapter_illustration",
            },
        )
    assert blocked.value.code == "ASSET_NOT_APPROVED"
    transition_media_asset("default", asset["asset_id"], "approve")
    binding = create_media_binding(
        "default",
        asset["asset_id"],
        {
            "book_id": "default",
            "target_type": "chapter",
            "target_id": "CHP_GEN",
            "binding_type": "chapter_illustration",
        },
    )
    assert binding["asset_id"] == asset["asset_id"]

    events = generation.list_media_generation_events("default", task["task_id"])
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert events[-1]["event"] == "done"
    serialized = json.dumps(events).lower()
    assert "浮空城市" not in serialized
    assert "output_path" not in serialized
    close_connection()


def test_generation_publish_approves_and_binds_output_to_content_group(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    allow_native(monkeypatch)
    status, chapter = asgi_request(
        app,
        "POST",
        "/api/books/default/chapters",
        headers={"X-API-Key": USER_API_KEY},
        json_body={"title": "Generated scene", "language_code": "zh-CN"},
    )
    assert status == 200
    task = generation.create_media_generation_task(native_payload(), start=False)
    completed = generation.run_media_generation_task(
        "default",
        task["task_id"],
        executor=FakeImageExecutor(),
    )
    assert completed["status"] == "completed"

    status, body = asgi_request(
        app,
        "POST",
        f"/api/media-generation/tasks/{task['task_id']}/publish",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={
            "book_id": "default",
            "target_type": "content_group",
            "target_id": chapter["content_group_id"],
            "binding_type": "chapter_illustration",
        },
    )

    assert status == 200
    assert body["asset"]["lifecycle_status"] == "approved"
    assert body["binding"]["target_type"] == "content_group"
    assert body["binding"]["target_id"] == chapter["content_group_id"]
    close_connection()


def test_img2img_uses_server_resolved_media_reference(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    allow_native(monkeypatch)
    source = import_media_asset(
        "default",
        "default",
        io.BytesIO(png_bytes(32, 32)),
        filename="source.png",
        declared_mime="image/png",
    )
    payload = native_payload(
        operation="image.img2img",
        source_asset_id=source["asset_id"],
    )
    task = generation.create_media_generation_task(payload, start=False)
    executor = FakeImageExecutor(png_bytes(64, 64))

    completed = generation.run_media_generation_task(
        "default",
        task["task_id"],
        executor=executor,
    )

    assert completed["status"] == "completed"
    source_ref = executor.calls[0]["source"]
    assert source_ref["sha256"] == source["content_hash"]
    assert Path(source_ref["path"]).is_file()
    assert "path" not in json.dumps(
        generation.list_media_generation_events("default", task["task_id"])
    )
    close_connection()


def test_cancel_retry_and_failure_recovery_are_durable(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    allow_native(monkeypatch)
    queued = generation.create_media_generation_task(native_payload(), start=False)
    cancelled = generation.cancel_media_generation_task("default", queued["task_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["output_asset_id"] is None

    retry = generation.retry_media_generation_task(
        "default",
        queued["task_id"],
        start=False,
    )
    assert retry["retry_of"] == queued["task_id"]
    assert retry["seed"] == queued["seed"]

    failed_source = generation.create_media_generation_task(
        native_payload(seed=99),
        start=False,
    )
    failed = generation.run_media_generation_task(
        "default",
        failed_source["task_id"],
        executor=FailingExecutor(),
    )
    assert failed["status"] == "failed"
    assert failed["error_code"] == "TEST_GENERATION_FAILED"

    db = get_db()
    db.execute(
        "UPDATE media_generation_tasks SET status='running' WHERE task_id=?",
        (retry["task_id"],),
    )
    db.commit()
    db.close()
    submitted = []
    monkeypatch.setattr(
        generation,
        "_submit_task",
        lambda database_id, task_id: submitted.append((database_id, task_id)),
    )
    recovered = generation.recover_interrupted_media_generation_tasks()
    assert recovered["interrupted"] == 1
    assert generation.get_media_generation_task(
        "default", retry["task_id"]
    )["error_code"] == "PROCESS_INTERRUPTED"
    close_connection()


def test_user_owned_external_model_is_not_subject_to_native_catalog(
    tmp_path, monkeypatch
):
    setup_runtime(tmp_path, monkeypatch)
    create_provider(
        {
            "id": "ollama-user",
            "display_name": "User Ollama",
            "provider_type": "local_ollama",
            "base_url": "http://127.0.0.1:11434",
            "api_format": "ollama_chat",
            "enabled": True,
        }
    )
    profile = create_model_profile(
        {
            "id": "ollama-user:custom-image",
            "provider_id": "ollama-user",
            "provider_model_name": "my-studio-model:latest",
            "display_name": "My Studio Model",
            "model_type": "image_generation",
            "enabled": True,
            "privacy_level": "local_only",
        }
    )

    task = generation.create_media_generation_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "image.generate",
            "prompt": "a city",
            "model_profile_id": profile["id"],
        },
        start=False,
    )

    assert task["target_kind"] == "external_provider"
    assert task["model_profile_id"] == profile["id"]
    assert task["provider_model_name"] == "my-studio-model:latest"
    assert task["package_id"] is None

    update_model_profile(profile["id"], {"enabled": False})
    with pytest.raises(generation.MediaGenerationError) as disabled:
        generation.create_media_generation_task(
            {
                "database_id": "default",
                "book_id": "default",
                "operation": "image.generate",
                "prompt": "a second city",
                "model_profile_id": profile["id"],
            },
            start=False,
        )
    assert disabled.value.code == "MODEL_NOT_ENABLED"
    close_connection()


def test_cloud_external_model_requires_explicit_upload_confirmation(
    tmp_path, monkeypatch
):
    setup_runtime(tmp_path, monkeypatch)
    create_provider(
        {
            "id": "cloud-image",
            "display_name": "Cloud Image",
            "provider_type": "openai_compatible",
            "base_url": "https://api.example.com/v1",
            "api_format": "openai_images",
            "enabled": True,
        }
    )
    profile = create_model_profile(
        {
            "id": "cloud-image:custom",
            "provider_id": "cloud-image",
            "provider_model_name": "future-image-model",
            "display_name": "Future Image Model",
            "model_type": "image_generation",
            "enabled": True,
            "privacy_level": "cloud_upload",
        }
    )
    request = {
        "database_id": "default",
        "book_id": "default",
        "operation": "image.generate",
        "prompt": "a city",
        "model_profile_id": profile["id"],
    }
    with pytest.raises(generation.MediaGenerationError) as blocked:
        generation.create_media_generation_task(request, start=False)
    assert blocked.value.code == "CLOUD_UPLOAD_CONFIRMATION_REQUIRED"

    task = generation.create_media_generation_task(
        {**request, "allow_cloud_upload": True},
        start=False,
    )
    assert task["allow_cloud_upload"] is True
    close_connection()


def test_external_provider_uses_exact_user_model_and_bounded_base64_contract(
    tmp_path, monkeypatch
):
    setup_runtime(tmp_path, monkeypatch)
    create_provider(
        {
            "id": "local-image-api",
            "display_name": "Local Image API",
            "provider_type": "local",
            "base_url": "http://127.0.0.1:9081/v1",
            "api_format": "openai_images",
            "enabled": True,
        }
    )
    profile = create_model_profile(
        {
            "id": "local-image-api:owned",
            "provider_id": "local-image-api",
            "provider_model_name": "author-trained-image:4",
            "display_name": "Author Image",
            "model_type": "image_generation",
            "enabled": True,
            "privacy_level": "local_only",
        }
    )
    task = generation.create_media_generation_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "image.generate",
            "prompt": "a silver tower",
            "model_profile_id": profile["id"],
        },
        start=False,
    )
    captured = {}
    payload = json.dumps(
        {
            "data": [
                {
                    "b64_json": base64.b64encode(png_bytes()).decode("ascii"),
                }
            ]
        }
    ).encode("utf-8")

    class Response:
        status_code = 200
        headers = {"content-length": str(len(payload))}

        @staticmethod
        def iter_content(_chunk_size):
            yield payload

        @staticmethod
        def close():
            captured["closed"] = True

    def fake_post(url, **kwargs):
        captured.update(url=url, request=kwargs["json"])
        return Response()

    monkeypatch.setattr(generation, "_validate_runtime_target", lambda _provider: None)
    monkeypatch.setattr(generation, "_credential_headers", lambda _provider: {})
    monkeypatch.setattr(generation.requests, "post", fake_post)
    output = tmp_path / "external-output.png"

    result = generation.ExternalImageGenerationExecutor().execute(
        task,
        output_path=output,
        source=None,
        job_started=lambda _job_id: True,
    )

    assert output.read_bytes() == png_bytes()
    assert result["output_mime_type"] == "image/png"
    assert captured["request"]["model"] == "author-trained-image:4"
    assert captured["url"].endswith("/v1/images/generations")
    assert captured["closed"] is True
    close_connection()


def test_generation_api_auth_and_queue_contract(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    allow_native(monkeypatch)
    monkeypatch.setattr(generation, "_submit_task", lambda *_args: None)
    body = native_payload()

    assert asgi_request(
        app,
        "POST",
        "/api/media-generation/tasks",
        json_body=body,
    )[0] == 401
    status, created = asgi_request(
        app,
        "POST",
        "/api/media-generation/tasks",
        headers={"X-API-Key": USER_API_KEY},
        json_body=body,
    )
    assert status == 202
    assert created["task"]["status"] == "queued"
    task_id = created["task"]["task_id"]

    status, listed = asgi_request(
        app,
        "GET",
        "/api/media-generation/tasks",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default", "book_id": "default"},
    )
    assert status == 200
    assert listed["total"] == 1
    assert "prompt" not in listed["tasks"][0]

    status, cancelled = asgi_request(
        app,
        "POST",
        f"/api/media-generation/tasks/{task_id}/cancel",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
    )
    assert status == 200
    assert cancelled["task"]["status"] == "cancelled"
    close_connection()


def test_kandinsky_manifest_and_adapter_keep_trusted_offline_boundary():
    manifest = load_package_manifest(
        Path("resources/model_packages/aetherdb-kandinsky-2-2.json")
    )
    assert manifest.package_kind == "image_generation"
    assert manifest.source.kind == "offline_only"
    assert manifest.license.license_id == "Apache-2.0"
    assert manifest.runtime_policy.default_lease_mode == "EXCLUSIVE"
    assert set(manifest.supported_backends) == {"rocm_pytorch", "cuda"}
    assert all(item.path.endswith(".safetensors") for item in manifest.files if item.role == "weights")
    assert "aetherdb_diffusers_kandinsky" in ADAPTERS
    assert ADAPTERS["aetherdb_diffusers_kandinsky"] is Kandinsky22WorkerAdapter
    source = Path("services/model_runtime/worker_process.py").read_text(encoding="utf-8")
    assert "trust_remote_code" not in source
    assert Kandinsky22WorkerAdapter(Path(".")).capabilities()["remote_code"] is False
