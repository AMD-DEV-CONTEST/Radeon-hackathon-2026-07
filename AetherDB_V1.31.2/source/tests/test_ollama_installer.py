import zipfile
from pathlib import Path
from types import SimpleNamespace

import services.database_registry as registry
import services.ollama_installer as installer
import services.ollama_management as management
from services.db import close_connection, init_db
from services.ollama_installation import OllamaInstallPlan, TrustedOllamaArtifact


def artifact(
    artifact_id,
    filename,
    *,
    role="primary",
    install_type="user_archive",
    accelerator=None,
):
    return TrustedOllamaArtifact(
        id=artifact_id,
        platform="windows",
        architectures=("arm64",),
        role=role,
        install_type=install_type,
        filename=filename,
        url=f"https://github.com/ollama/ollama/releases/download/v0.32.0/{filename}",
        size=1,
        sha256="0" * 64,
        verification=("sha256", "archive_layout"),
        requires_user_confirmation=True,
        accelerator=accelerator,
    )


def test_managed_archive_install_is_user_scoped_and_applies_addon(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    primary = artifact("primary", "ollama-windows-arm64.zip")
    addon = artifact(
        "addon",
        "ollama-windows-amd64-rocm.zip",
        role="accelerator_addon",
        install_type="runtime_addon",
        accelerator="rocm",
    )
    with zipfile.ZipFile(cache / primary.filename, "w") as archive:
        archive.writestr("ollama.exe", b"runtime")
    with zipfile.ZipFile(cache / addon.filename, "w") as archive:
        archive.writestr("lib/ollama/rocm/runtime.dll", b"addon")
    plan = OllamaInstallPlan(
        version="0.32.0",
        platform="windows",
        architecture="arm64",
        accelerator="rocm",
        cache_root=str(cache),
        artifacts=(primary, addon),
    )
    monkeypatch.setattr(
        installer,
        "get_runtime_path",
        lambda *parts: tmp_path.joinpath("runtime", *parts),
    )

    result = installer.install_verified_plan(plan)
    root = Path(result.managed_root)

    assert result.method == "managed_user_archive"
    assert (root / "ollama.exe").read_bytes() == b"runtime"
    assert (root / "lib/ollama/rocm/runtime.dll").read_bytes() == b"addon"


def test_zip_install_rejects_parent_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    destination = tmp_path / "destination"
    destination.mkdir()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", b"blocked")

    try:
        installer._extract_zip(archive_path, destination)
    except installer.OllamaInstallerError as exc:
        assert exc.code == "ARCHIVE_LAYOUT_INVALID"
    else:
        raise AssertionError("Unsafe install archive was accepted")
    assert not (tmp_path / "outside.txt").exists()


def test_archive_paths_reject_windows_ads_and_device_names():
    assert installer._safe_member("lib/runtime.dll") is True
    assert installer._safe_member("runtime.dll:payload") is False
    assert installer._safe_member("NUL.txt") is False


def test_provider_initialization_is_idempotent_and_has_no_credential(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()

    first = management.ensure_default_ollama_provider()
    second = management.ensure_default_ollama_provider()

    assert first["id"] == second["id"] == "ollama-local-default"
    assert second["provider_type"] == "local_ollama"
    assert second["credential_ref"] is None
    assert second["health_status"] == "healthy"
    assert len([item for item in management.list_providers() if item["id"] == first["id"]]) == 1
    close_connection()


def test_tar_install_rejects_links_before_extraction(tmp_path, monkeypatch):
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="bin/ollama\n"),
            SimpleNamespace(
                returncode=0,
                stdout="lrwxrwxrwx user/group 0 date bin/ollama -> ../../outside\n",
            ),
        ]
    )
    monkeypatch.setattr(installer.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    try:
        installer._list_tar_zstd(tmp_path / "release.tar.zst")
    except installer.OllamaInstallerError as exc:
        assert exc.code == "ARCHIVE_LAYOUT_INVALID"
    else:
        raise AssertionError("Linked archive member was accepted")
