import hashlib
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
import services.database_registry as registry
import services.ollama_install_tasks as install_tasks
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from services.ollama_installation import OllamaInstallPlan, TrustedOllamaArtifact
from services.ollama_installer import InstallActionResult
from tests.asgi_client import asgi_request


class DownloadResponse:
    def __init__(self, payload=b"", *, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.payload), max(1, chunk_size)):
            yield self.payload[offset : offset + chunk_size]

    def close(self):
        self.closed = True


def request(method, path, *, json_body=None, headers=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers)


def setup_registry(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()
    return {"X-API-Key": ADMIN_API_KEY}


def make_plan(tmp_path, payload=b"trusted-release", sha256=None):
    artifact = TrustedOllamaArtifact(
        id="linux-x64-primary",
        platform="linux",
        architectures=("x86_64",),
        role="primary",
        install_type="system_archive",
        filename="ollama-linux-amd64.tar.zst",
        url="https://github.com/ollama/ollama/releases/download/v0.32.0/ollama-linux-amd64.tar.zst",
        size=len(payload),
        sha256=sha256 or hashlib.sha256(payload).hexdigest(),
        verification=("sha256", "archive_layout"),
        requires_user_confirmation=True,
    )
    return OllamaInstallPlan(
        version="0.32.0",
        platform="linux",
        architecture="x86_64",
        accelerator=None,
        cache_root=str(tmp_path / "install-cache"),
        artifacts=(artifact,),
    )


def configure_plan(tmp_path, monkeypatch, payload=b"trusted-release", sha256=None):
    plan = make_plan(tmp_path, payload, sha256)
    monkeypatch.setattr(install_tasks, "resolve_install_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(
        install_tasks,
        "_start_background_thread",
        lambda target, args, _name: target(*args),
    )
    monkeypatch.setattr(install_tasks, "_verify_platform_artifact", lambda *_args: None)
    return plan


def test_install_download_requires_admin_confirmation_and_is_idempotent(
    tmp_path, monkeypatch
):
    admin = setup_registry(tmp_path, monkeypatch)
    payload = b"trusted-release"
    plan = configure_plan(tmp_path, monkeypatch, payload)
    monkeypatch.setattr(
        install_tasks.requests,
        "get",
        lambda *_args, **_kwargs: DownloadResponse(
            payload, headers={"Content-Length": str(len(payload))}
        ),
    )

    assert request("POST", "/api/ollama/install/operations", json_body={})[0] == 401
    status, body = request(
        "POST", "/api/ollama/install/operations", headers=admin, json_body={}
    )
    assert status == 201
    operation = body["operation"]
    assert operation["status"] == "awaiting_confirmation"
    assert not (tmp_path / "install-cache" / plan.artifacts[0].filename).exists()

    repeated_status, repeated = request(
        "POST", "/api/ollama/install/operations", headers=admin, json_body={}
    )
    assert repeated_status == 201
    assert repeated["operation"]["id"] == operation["id"]

    status, body = request(
        "POST",
        f"/api/ollama/install/operations/{operation['id']}/confirm-download",
        headers=admin,
        json_body={},
    )
    assert status == 202
    assert body["operation"]["status"] == "ready_to_launch"
    assert body["operation"]["artifacts"][0]["verified"] is True
    assert body["operation"]["completed_bytes"] == len(payload)
    assert (tmp_path / "install-cache" / plan.artifacts[0].filename).read_bytes() == payload
    close_connection()


def test_untrusted_redirect_fails_without_creating_package(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    plan = configure_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(
        install_tasks.requests,
        "get",
        lambda *_args, **_kwargs: DownloadResponse(
            status_code=302, headers={"Location": "https://example.test/payload"}
        ),
    )

    _, created = request(
        "POST", "/api/ollama/install/operations", headers=admin, json_body={}
    )
    operation_id = created["operation"]["id"]
    _, body = request(
        "POST",
        f"/api/ollama/install/operations/{operation_id}/confirm-download",
        headers=admin,
        json_body={},
    )
    assert body["operation"]["status"] == "failed"
    assert body["operation"]["error_code"] == "REDIRECT_BLOCKED"
    assert not (Path(plan.cache_root) / plan.artifacts[0].filename).exists()
    close_connection()


def test_checksum_mismatch_removes_partial_download(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    payload = b"wrong-release"
    plan = configure_plan(tmp_path, monkeypatch, payload, sha256="0" * 64)
    monkeypatch.setattr(
        install_tasks.requests,
        "get",
        lambda *_args, **_kwargs: DownloadResponse(
            payload, headers={"Content-Length": str(len(payload))}
        ),
    )

    _, created = request(
        "POST", "/api/ollama/install/operations", headers=admin, json_body={}
    )
    operation_id = created["operation"]["id"]
    _, body = request(
        "POST",
        f"/api/ollama/install/operations/{operation_id}/confirm-download",
        headers=admin,
        json_body={},
    )
    assert body["operation"]["status"] == "failed"
    assert body["operation"]["error_code"] == "SHA256_MISMATCH"
    assert not (Path(plan.cache_root) / plan.artifacts[0].filename).exists()
    assert not list(Path(plan.cache_root).glob("*.part"))
    close_connection()


def test_cancel_before_confirmation_and_restart_recovery(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    configure_plan(tmp_path, monkeypatch)
    first = install_tasks.create_install_operation()
    cancelled = install_tasks.cancel_install_operation(first["id"])
    assert cancelled["status"] == "cancelled"

    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        conn.execute(
            "INSERT INTO ollama_install_operations "
            "(id,version,platform,architecture,status,artifacts_json,cache_root) "
            "VALUES ('interrupted','0.32.0','linux','x86_64','downloading','[]','cache')"
        )
        conn.execute(
            "INSERT INTO ollama_install_operations "
            "(id,version,platform,architecture,status,artifacts_json,cache_root) "
            "VALUES ('verified','0.32.0','linux','x86_64','ready_to_launch','[]','cache')"
        )
        conn.commit()
    install_tasks.recover_interrupted_install_operations()
    assert install_tasks.get_install_operation("interrupted")["error_code"] == "INTERRUPTED"
    assert install_tasks.get_install_operation("verified")["status"] == "ready_to_launch"
    close_connection()


def test_zip_layout_rejects_parent_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../ollama.exe", b"not-an-executable")

    try:
        install_tasks._verify_zip_archive(
            archive_path, require_ollama_executable=True, verify_pe=False
        )
    except install_tasks.OllamaInstallTaskError as exc:
        assert exc.code == "ARCHIVE_LAYOUT_INVALID"
    else:
        raise AssertionError("Unsafe archive path was accepted")


def test_accelerator_addon_archive_does_not_require_main_executable(tmp_path):
    archive_path = tmp_path / "rocm-addon.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("lib/ollama/rocm/runtime.dll", b"runtime")

    install_tasks._verify_zip_archive(
        archive_path, require_ollama_executable=False, verify_pe=False
    )


def test_launch_rechecks_packages_and_initializes_provider_without_model(
    tmp_path, monkeypatch
):
    admin = setup_registry(tmp_path, monkeypatch)
    payload = b"trusted-release"
    plan = configure_plan(tmp_path, monkeypatch, payload)
    cache_path = Path(plan.cache_root) / plan.artifacts[0].filename
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(payload)
    operation = install_tasks.create_install_operation()
    install_tasks._update(operation["id"], status="ready_to_launch", progress=1.0)
    executable = tmp_path / "managed" / "bin" / "ollama"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"runtime")
    calls = []
    monkeypatch.setattr(
        install_tasks,
        "install_verified_plan",
        lambda _plan: InstallActionResult("managed_user_archive", str(executable.parent.parent)),
    )
    monkeypatch.setattr(
        install_tasks,
        "wait_for_ollama_executable",
        lambda _operation_id: executable,
    )
    monkeypatch.setattr(
        install_tasks,
        "apply_post_discovery_addons",
        lambda _plan, found, _action: calls.append(found),
    )
    monkeypatch.setattr(
        install_tasks,
        "start_existing_runtime",
        lambda: {"running": True, "api_compatible": True, "models": []},
    )
    monkeypatch.setattr(
        install_tasks,
        "get_runtime_status",
        lambda: {"running": True, "api_compatible": True, "models": []},
    )
    monkeypatch.setattr(
        install_tasks,
        "ensure_default_ollama_provider",
        lambda: {"id": "ollama-local-default"},
    )

    assert request(
        "POST",
        f"/api/ollama/install/operations/{operation['id']}/launch",
        json_body={"confirm_version": "0.32.0"},
    )[0] == 401
    mismatch_status, mismatch = request(
        "POST",
        f"/api/ollama/install/operations/{operation['id']}/launch",
        headers=admin,
        json_body={"confirm_version": "0.31.0"},
    )
    assert mismatch_status == 409
    assert mismatch["detail"]["code"] == "CONFIRMATION_MISMATCH"

    status, body = request(
        "POST",
        f"/api/ollama/install/operations/{operation['id']}/launch",
        headers=admin,
        json_body={"confirm_version": "0.32.0"},
    )
    assert status == 202
    assert body["operation"]["status"] == "ready"
    assert body["operation"]["provider_id"] == "ollama-local-default"
    assert body["operation"]["launch_method"] == "managed_user_archive"
    assert calls == [executable]
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM model_profiles").fetchone()[0] == 0
    close_connection()


def test_launch_refuses_package_changed_after_download(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    configure_plan(tmp_path, monkeypatch, b"expected")
    operation = install_tasks.create_install_operation()
    install_tasks._update(operation["id"], status="ready_to_launch", progress=1.0)
    launched = []
    monkeypatch.setattr(
        install_tasks,
        "install_verified_plan",
        lambda _plan: launched.append(True),
    )

    result = install_tasks.launch_install_operation(operation["id"], "0.32.0")

    assert result["status"] == "failed"
    assert result["error_code"] == "VERIFICATION_FAILED"
    assert launched == []
    close_connection()


@pytest.mark.skipif(os.name != "nt", reason="Windows Authenticode verifier")
def test_windows_authenticode_verifier_accepts_system_signature_and_rejects_unsigned(
    tmp_path,
):
    install_tasks._verify_windows_authenticode(
        Path(os.environ["SystemRoot"]) / "System32" / "notepad.exe"
    )
    unsigned = tmp_path / "unsigned.exe"
    unsigned.write_bytes(b"not a signed executable")

    with pytest.raises(install_tasks.OllamaInstallTaskError) as captured:
        install_tasks._verify_windows_authenticode(unsigned)
    assert captured.value.code == "SIGNATURE_INVALID"
