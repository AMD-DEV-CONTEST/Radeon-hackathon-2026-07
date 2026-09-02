import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import services.database_registry as database_registry
import services.model_packages.installer as installer
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from services.model_packages.manifest import (
    ModelPackageManifest,
    load_package_manifest,
)
from services.model_packages.registry import (
    accept_license,
    check_distribution_eligibility,
    get_installation,
    get_operation,
    sync_catalog,
)
from services.model_packages.verifier import package_target, verification_record_is_current
from services.embedding_runtime import load_bge_m3_manifest
from tests.asgi_client import asgi_request


ADMIN = {"X-API-Key": ADMIN_API_KEY}


def request(method, path, *, json_body=None, headers=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers)


def manifest_payload(
    payload: bytes,
    *,
    package_id: str = "test.vision",
    package_version: str = "1.0.0",
    core_required: bool = False,
    source_kind: str = "offline_only",
):
    source = {
        "kind": "offline_only",
        "base_url": None,
        "trusted_redirect_hosts": [],
        "revision": "test-revision",
    }
    if source_kind == "trusted_https":
        source = {
            "kind": "trusted_https",
            "base_url": "https://models.example.test/releases/",
            "trusted_redirect_hosts": ["models.example.test"],
            "revision": "test-revision",
        }
    return {
        "schema_version": 1,
        "package_id": package_id,
        "package_version": package_version,
        "display_name": "Test vision package",
        "package_kind": "vision_embedding",
        "core_required": core_required,
        "model_profile_id": None,
        "model_family": "test/vision",
        "modalities": ["image"],
        "capabilities": ["vision_embedding"],
        "runtime_adapter": "test_vision_worker",
        "supported_platforms": ["windows", "linux", "macos"],
        "supported_architectures": ["x86_64", "arm64"],
        "supported_backends": ["rocm", "cuda", "cpu"],
        "install_subdir": package_id,
        "install_size_bytes": len(payload),
        "model_size_bytes": len(payload),
        "resource_profile": {
            "minimum_ram_mb": 1,
            "recommended_ram_mb": 2,
            "minimum_vram_mb": 0,
            "recommended_vram_mb": 1,
            "evidence_level": "estimated",
        },
        "embedding": None,
        "residency_policy_default": "idle_unload",
        "runtime_policy": None,
        "offload_capabilities": ["cpu_fallback"],
        "license": {
            "license_id": "TEST-1.0",
            "display_name": "Test License",
            "url": "https://licenses.example.test/test",
            "redistribution_allowed": False,
            "requires_acceptance": True,
            "notice_path": None,
        },
        "source": source,
        "files": [
            {
                "path": "weights/model.bin",
                "download_path": "weights/model.bin",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "role": "model",
            }
        ],
    }


def setup_package_runtime(tmp_path, monkeypatch, payload=b"trusted-model", **manifest_kwargs):
    runtime = tmp_path / "runtime"
    catalog = tmp_path / "catalog"
    models = tmp_path / "models"
    inbox = runtime / "inbox"
    cache = runtime / "cache"
    catalog.mkdir()
    inbox.mkdir(parents=True)
    raw = manifest_payload(payload, **manifest_kwargs)
    manifest_path = catalog / "package.json"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    monkeypatch.setattr(database_registry, "REGISTRY_PATH", str(runtime / "registry.db"))
    monkeypatch.setattr(database_registry, "DATABASES_ROOT", str(runtime / "databases"))
    monkeypatch.setattr(database_registry, "OLD_DB_PATH", str(runtime / "missing.db"))
    monkeypatch.setenv("AETHERDB_MODEL_PACKAGE_CATALOG", str(catalog))
    monkeypatch.setenv("AETHERDB_MODEL_PACKAGE_ROOT", str(models))
    monkeypatch.delenv("AETHERDB_MODEL_ROOT", raising=False)
    monkeypatch.setattr(installer, "model_package_inbox", lambda: inbox.resolve())
    monkeypatch.setattr(installer, "model_package_cache_root", lambda: cache.resolve())
    monkeypatch.setattr(
        installer,
        "_start_thread",
        lambda operation_id: installer._run_operation_safely(operation_id),
    )
    database_registry.init_registry()
    init_db()
    sync_catalog()
    return {
        "manifest": load_package_manifest(manifest_path),
        "models": models,
        "inbox": inbox,
        "cache": cache,
        "payload": payload,
    }


def accept_test_license(manifest):
    return accept_license(
        manifest.package_id,
        manifest.package_version,
        manifest_digest=manifest.digest(),
        license_id=manifest.license.license_id,
        accepted_by="test-admin",
    )


def write_offline_package(path: Path, manifest: ModelPackageManifest, payload: bytes):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "package-manifest.json",
            json.dumps(manifest.model_dump(mode="json")),
        )
        archive.writestr(manifest.files[0].path, payload)


def test_catalog_is_admin_only_and_does_not_duplicate_model_profiles(tmp_path, monkeypatch):
    setup = setup_package_runtime(tmp_path, monkeypatch)

    assert request("GET", "/api/model-packages")[0] == 401
    status, body = request("GET", "/api/model-packages", headers=ADMIN)
    assert status == 200
    package = body["packages"][0]
    assert package["package_id"] == "test.vision"
    assert package["installation"]["status"] == "install_available"
    assert package["profile_registered"] is False
    assert str(tmp_path) not in json.dumps(body)
    with sqlite3.connect(database_registry.REGISTRY_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_profiles").fetchone()[0] == 0
    close_connection()


def test_core_package_matches_the_pinned_bge_m3_runtime_manifest():
    package = load_package_manifest(
        Path("resources/model_packages/aetherdb-bge-m3.json")
    )
    runtime = load_bge_m3_manifest()

    assert package.package_id == "aetherdb.bge-m3"
    assert package.core_required is True
    assert package.model_family == runtime.model_id
    assert package.source.revision == runtime.revision
    assert package.embedding.dimension == runtime.dimensions == 1024
    assert package.embedding.normalization == runtime.normalization == "l2"
    assert package.embedding.vector_space_id == "text.bge-m3.dense.v1"
    assert package.residency_policy_default == "always"
    assert [item.path for item in package.files] == [
        item.path for item in runtime.artifacts
    ]
    assert [item.sha256 for item in package.files] == [
        item.sha256 for item in runtime.artifacts
    ]
    assert package.runtime_policy.residency_mode == "PREFERRED"
    assert package.runtime_policy.default_lease_mode == "SHARED"
    assert package.runtime_policy.shared_gpu_eligible is True


def test_kokoro_baseline_is_pinned_and_tts_selection_is_not_model_locked():
    package = load_package_manifest(
        Path("resources/model_packages/aetherdb-kokoro-82m.json")
    )
    candidates = json.loads(
        Path("resources/tts_model_candidates.json").read_text(encoding="utf-8")
    )

    assert package.package_id == "aetherdb.kokoro-82m"
    assert package.model_family == "hexgrad/Kokoro-82M"
    assert package.source.revision == "f3ff3571791e39611d31c381e3a41a3af07b4987"
    assert package.runtime_adapter == "aetherdb_torch_kokoro"
    assert set(package.supported_backends) == {"rocm_pytorch", "cuda", "cpu"}
    assert {"audio.tts.chapter", "audio.tts.segment"} <= set(package.capabilities)
    assert package.license.license_id == "Apache-2.0"
    assert package.install_size_bytes == sum(item.size for item in package.files)
    assert package.files[1].sha256 == (
        "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
    )
    assert candidates["selection_policy"]["model_switching"] == "per_task"
    assert candidates["selection_policy"]["default_package_id"] is None
    assert candidates["selection_policy"]["automatic_model_substitution"] is False
    assert {
        item["candidate_id"] for item in candidates["candidates"]
    } == {
        "kokoro-82m-v1",
        "qwen3-tts-12hz-1.7b-customvoice",
    }
    competition = candidates["candidates"][1]
    assert {"zh", "en"} <= set(competition["languages"])
    assert competition["rocm_evidence"] == "pending_amd_server_probe"


def test_bge_override_is_writable_only_when_it_matches_the_managed_package_root(
    tmp_path, monkeypatch
):
    package = load_package_manifest(
        Path("resources/model_packages/aetherdb-bge-m3.json")
    )
    managed_root = tmp_path / "managed-models"
    monkeypatch.setenv("AETHERDB_MODEL_PACKAGE_ROOT", str(managed_root))
    monkeypatch.setenv("AETHERDB_MODEL_ROOT", str(managed_root / "bge-m3"))
    target, scope = package_target(package)
    assert target == (managed_root / "bge-m3").resolve()
    assert scope == "managed"

    monkeypatch.setenv("AETHERDB_MODEL_ROOT", str(tmp_path / "packaged-read-only"))
    _, scope = package_target(package)
    assert scope == "external_override"


def test_license_acceptance_is_bound_to_exact_manifest(tmp_path, monkeypatch):
    setup = setup_package_runtime(tmp_path, monkeypatch)
    manifest = setup["manifest"]

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "offline_cache",
            "source_ref": "missing.zip",
        },
    )
    assert status == 409
    assert body["detail"]["code"] == "LICENSE_ACCEPTANCE_REQUIRED"

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/license-acceptance",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "manifest_digest": "0" * 64,
            "license_id": manifest.license.license_id,
            "accepted": True,
        },
    )
    assert status == 409
    assert body["detail"]["code"] == "LICENSE_CONFIRMATION_MISMATCH"

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/license-acceptance",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "manifest_digest": manifest.digest(),
            "license_id": manifest.license.license_id,
            "accepted": True,
        },
    )
    assert status == 200
    assert body["accepted"] is True
    close_connection()


def test_distribution_check_fails_closed_on_license_and_verified_install(
    tmp_path, monkeypatch
):
    setup = setup_package_runtime(tmp_path, monkeypatch)
    manifest = setup["manifest"]

    result = check_distribution_eligibility(
        [(manifest.package_id, manifest.package_version)]
    )
    assert result["eligible"] is False
    assert result["packages"][0]["blockers"] == [
        "REDISTRIBUTION_NOT_ALLOWED",
        "LICENSE_ACCEPTANCE_REQUIRED",
        "PACKAGE_NOT_VERIFIED",
    ]

    accept_test_license(manifest)
    result = check_distribution_eligibility(
        [(manifest.package_id, manifest.package_version)]
    )
    assert result["packages"][0]["blockers"] == [
        "REDISTRIBUTION_NOT_ALLOWED",
        "PACKAGE_NOT_VERIFIED",
    ]
    assert str(tmp_path) not in json.dumps(result)
    close_connection()


def test_offline_install_is_verified_atomic_and_repairable(tmp_path, monkeypatch):
    setup = setup_package_runtime(tmp_path, monkeypatch)
    manifest = setup["manifest"]
    accept_test_license(manifest)
    archive = setup["inbox"] / "vision.zip"
    write_offline_package(archive, manifest, setup["payload"])

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "offline_cache",
            "source_ref": archive.name,
        },
    )
    assert status == 202
    assert body["operation"]["status"] == "installed"
    target = setup["models"] / manifest.install_subdir
    assert (target / manifest.files[0].path).read_bytes() == setup["payload"]
    assert verification_record_is_current(manifest, target)
    installation = get_installation(manifest.package_id)
    assert installation["install_ref"] == manifest.install_subdir
    assert str(tmp_path) not in json.dumps(body)

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/verify",
        headers=ADMIN,
        json_body={"package_version": manifest.package_version},
    )
    assert status == 202
    assert body["operation"]["status"] == "verified"

    (target / manifest.files[0].path).write_bytes(b"x" * len(setup["payload"]))
    assert verification_record_is_current(manifest, target) is False

    _, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/verify",
        headers=ADMIN,
        json_body={"package_version": manifest.package_version},
    )
    assert body["operation"]["status"] == "failed"
    assert body["operation"]["error_code"] == "PACKAGE_INTEGRITY_FAILED"
    assert get_installation(manifest.package_id)["status"] == "repair_required"
    close_connection()


def test_bad_offline_hash_leaves_no_target_or_staging_directory(tmp_path, monkeypatch):
    setup = setup_package_runtime(tmp_path, monkeypatch)
    manifest = setup["manifest"]
    accept_test_license(manifest)
    archive = setup["inbox"] / "wrong.zip"
    write_offline_package(archive, manifest, b"x" * len(setup["payload"]))

    _, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "offline_cache",
            "source_ref": archive.name,
        },
    )
    assert body["operation"]["status"] == "failed"
    assert body["operation"]["error_code"] == "SHA256_MISMATCH"
    assert not (setup["models"] / manifest.install_subdir).exists()
    assert not list(setup["models"].glob(".aetherdb-stage-*"))
    close_connection()


def test_optional_package_can_disable_enable_and_uninstall_safely(tmp_path, monkeypatch):
    setup = setup_package_runtime(tmp_path, monkeypatch)
    manifest = setup["manifest"]
    accept_test_license(manifest)
    archive = setup["inbox"] / "optional.zip"
    write_offline_package(archive, manifest, setup["payload"])
    request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "offline_cache",
            "source_ref": archive.name,
        },
    )

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/disable",
        headers=ADMIN,
        json_body={},
    )
    assert status == 200
    assert body["installation"]["status"] == "disabled"
    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/enable",
        headers=ADMIN,
        json_body={},
    )
    assert status == 200
    assert body["installation"]["status"] == "installed"

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/uninstall",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "confirm_package_id": manifest.package_id,
        },
    )
    assert status == 200
    assert body["installation"]["status"] == "install_available"
    assert not (setup["models"] / manifest.install_subdir).exists()
    close_connection()


class DownloadResponse:
    def __init__(self, payload, *, status_code=206, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.payload), chunk_size):
            yield self.payload[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class DownloadSession:
    def __init__(self, payload, expected_offset):
        self.payload = payload
        self.expected_offset = expected_offset
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert kwargs["headers"]["Range"] == f"bytes={self.expected_offset}-"
        return DownloadResponse(
            self.payload[self.expected_offset :],
            headers={
                "Content-Range": (
                    f"bytes {self.expected_offset}-{len(self.payload) - 1}/"
                    f"{len(self.payload)}"
                )
            },
        )


class RedirectSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, *_args, **_kwargs):
        return DownloadResponse(
            b"",
            status_code=302,
            headers={"Location": "https://untrusted.example.test/model.bin"},
        )


def test_catalog_download_resumes_partial_file_and_uses_only_trusted_url(
    tmp_path, monkeypatch
):
    setup = setup_package_runtime(
        tmp_path,
        monkeypatch,
        source_kind="trusted_https",
    )
    manifest = setup["manifest"]
    accept_test_license(manifest)
    cache_file = setup["cache"] / manifest.package_id / manifest.package_version / manifest.files[0].path
    cache_file.parent.mkdir(parents=True)
    offset = 4
    cache_file.with_name(cache_file.name + ".part").write_bytes(setup["payload"][:offset])
    session = DownloadSession(setup["payload"], offset)
    monkeypatch.setattr(installer.requests, "Session", lambda: session)

    _, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "catalog",
        },
    )
    assert body["operation"]["status"] == "installed"
    assert session.calls[0][0].startswith("https://models.example.test/releases/")
    assert session.calls[0][1]["allow_redirects"] is False
    close_connection()


def test_catalog_download_rejects_untrusted_redirect(tmp_path, monkeypatch):
    setup = setup_package_runtime(
        tmp_path,
        monkeypatch,
        source_kind="trusted_https",
    )
    manifest = setup["manifest"]
    accept_test_license(manifest)
    monkeypatch.setattr(installer.requests, "Session", RedirectSession)

    _, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "catalog",
        },
    )
    assert body["operation"]["status"] == "failed"
    assert body["operation"]["error_code"] == "DOWNLOAD_TARGET_BLOCKED"
    assert not (setup["models"] / manifest.install_subdir).exists()
    close_connection()


def test_archive_parent_traversal_and_core_removal_are_blocked(tmp_path, monkeypatch):
    setup = setup_package_runtime(
        tmp_path,
        monkeypatch,
        package_id="test.core",
        core_required=True,
    )
    manifest = setup["manifest"]
    accept_test_license(manifest)
    archive = setup["inbox"] / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "package-manifest.json",
            json.dumps(manifest.model_dump(mode="json")),
        )
        package.writestr("../model.bin", setup["payload"])
    _, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/install",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "source_kind": "offline_cache",
            "source_ref": archive.name,
        },
    )
    assert body["operation"]["error_code"] == "ARCHIVE_LAYOUT_INVALID"

    status, body = request(
        "POST",
        f"/api/model-packages/{manifest.package_id}/uninstall",
        headers=ADMIN,
        json_body={
            "package_version": manifest.package_version,
            "confirm_package_id": manifest.package_id,
        },
    )
    assert status == 409
    assert body["detail"]["code"] == "CORE_PACKAGE_REQUIRED"
    close_connection()


def test_interrupted_download_recovery_reuses_the_same_operation(tmp_path, monkeypatch):
    setup = setup_package_runtime(
        tmp_path,
        monkeypatch,
        source_kind="trusted_https",
    )
    manifest = setup["manifest"]
    accept_test_license(manifest)
    operation = installer.create_operation(
        manifest,
        operation="install",
        source_kind="catalog",
        source_ref="catalog",
    )
    installer.update_operation(operation["id"], status="downloading")
    started = []
    monkeypatch.setattr(installer, "_start_thread", lambda value: started.append(value))

    installer.recover_interrupted_operations()
    assert started == [operation["id"]]
    assert get_operation(operation["id"])["status"] == "downloading"
    close_connection()
