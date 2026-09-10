"""Tests for the pinned AMD Preview adapter installer."""

from __future__ import annotations

from contextlib import nullcontext
import importlib.util
import io
import json
import os
from pathlib import Path
import stat

import pytest

from specstyle.production.preview_supply_config import load_preview_supply_config
from specstyle.generation.preview_adapter_supply import verify_preview_adapter

SCRIPT = Path(__file__).parents[3] / "deployment/amd/scripts/install_preview_adapter.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_preview_adapter", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "models").mkdir(mode=0o700)
    return runtime


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_supply_pin_matches_approved_lcm_lora_sdxl_release() -> None:
    installer = load_installer()

    assert installer.MODEL_ID == "latent-consistency/lcm-lora-sdxl"
    assert installer.REVISION == "a18548dd4956b174ec5b0d78d340c8dae0a129cd"
    assert installer.WEIGHT_SIZE == 393_855_224
    assert (
        installer.WEIGHT_SHA256
        == "a764e6859b6e04047cd761c08ff0cee96413a8e004c9f07707530cd776b19141"
    )
    assert installer.LICENSE_SPDX == "OpenRAIL++-M"
    assert installer.REVISION in installer.DOWNLOAD_URL
    assert installer.REVISION in installer.EVIDENCE_URL


def test_install_publishes_verified_weight_and_closed_loop_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    payload = b"test adapter bytes"
    monkeypatch.setattr(installer, "WEIGHT_SIZE", len(payload))
    monkeypatch.setattr(installer, "WEIGHT_SHA256", installer.sha256_bytes(payload))
    calls: list[tuple[str, int]] = []

    def opener(url: str, *, timeout: int):
        calls.append((url, timeout))
        return _Response(payload)

    runtime = _runtime(tmp_path)
    result = installer.install_preview_adapter(runtime, opener=opener)

    weight = runtime / installer.RELATIVE_ROOT / installer.WEIGHT_RELATIVE_PATH
    assert weight.read_bytes() == payload
    assert stat.S_IMODE(weight.stat().st_mode) == 0o600
    assert calls == [(installer.DOWNLOAD_URL, installer.DOWNLOAD_TIMEOUT_SECONDS)]
    assert result["status"] == "PASS"
    assert result["downloaded"] is True
    assert result["weight_sha256"] == installer.WEIGHT_SHA256

    config_fd = os.open(runtime / "preview-config", os.O_RDONLY | os.O_DIRECTORY)
    model_fd = os.open(runtime / "models", os.O_RDONLY | os.O_DIRECTORY)
    try:
        config = load_preview_supply_config(config_fd)
        verified = verify_preview_adapter(
            model_fd, config.descriptor, config.manifest, config.approval
        )
        verified.close()
    finally:
        os.close(model_fd)
        os.close(config_fd)

    for name in installer.CONFIG_FILENAMES:
        path = runtime / "preview-config" / name
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text(encoding="utf-8"))


def test_install_is_idempotent_and_does_not_redownload_valid_weight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    payload = b"already present"
    monkeypatch.setattr(installer, "WEIGHT_SIZE", len(payload))
    monkeypatch.setattr(installer, "WEIGHT_SHA256", installer.sha256_bytes(payload))
    runtime = _runtime(tmp_path)
    first_calls = 0

    def first_opener(_url: str, *, timeout: int):
        nonlocal first_calls
        first_calls += 1
        assert timeout == installer.DOWNLOAD_TIMEOUT_SECONDS
        return _Response(payload)

    installer.install_preview_adapter(runtime, opener=first_opener)

    def forbidden_opener(*_args: object, **_kwargs: object):
        raise AssertionError("valid pinned weight must not be downloaded again")

    result = installer.install_preview_adapter(runtime, opener=forbidden_opener)

    assert first_calls == 1
    assert result["status"] == "PASS"
    assert result["downloaded"] is False


@pytest.mark.parametrize("payload", (b"short", b"wrong-size-and-content"))
def test_invalid_download_does_not_publish_weight_or_config(
    tmp_path: Path, payload: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    expected = b"expected adapter"
    monkeypatch.setattr(installer, "WEIGHT_SIZE", len(expected))
    monkeypatch.setattr(installer, "WEIGHT_SHA256", installer.sha256_bytes(expected))
    runtime = _runtime(tmp_path)

    with pytest.raises(installer.InstallPreviewAdapterError):
        installer.install_preview_adapter(
            runtime, opener=lambda *_a, **_k: _Response(payload)
        )

    assert (
        not (runtime / installer.RELATIVE_ROOT)
        .joinpath(installer.WEIGHT_RELATIVE_PATH)
        .exists()
    )
    config = runtime / "preview-config"
    assert not config.exists() or list(config.iterdir()) == []


def test_install_refuses_symlinked_model_root(tmp_path: Path) -> None:
    installer = load_installer()
    runtime = tmp_path / "runtime"
    outside = tmp_path / "outside"
    runtime.mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    (runtime / "models").symlink_to(outside, target_is_directory=True)

    with pytest.raises(installer.InstallPreviewAdapterError, match="models"):
        installer.install_preview_adapter(
            runtime, opener=lambda *_a, **_k: nullcontext(_Response(b""))
        )

    assert list(outside.iterdir()) == []


def test_config_write_failure_leaves_no_public_partial_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    payload = b"adapter"
    monkeypatch.setattr(installer, "WEIGHT_SIZE", len(payload))
    monkeypatch.setattr(installer, "WEIGHT_SHA256", installer.sha256_bytes(payload))
    real_write = installer._atomic_write_config
    calls = 0

    def fail_second(config_fd: int, filename: str, value: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise installer.InstallPreviewAdapterError("injected config failure")
        real_write(config_fd, filename, value)

    monkeypatch.setattr(installer, "_atomic_write_config", fail_second)
    runtime = _runtime(tmp_path)

    with pytest.raises(installer.InstallPreviewAdapterError):
        installer.install_preview_adapter(
            runtime, opener=lambda *_a, **_k: _Response(payload)
        )

    assert not (runtime / "preview-config").exists()
    assert not list(runtime.glob(".preview-config.tmp-*"))


def test_config_namespace_publish_failure_is_invisible_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    payload = b"adapter"
    monkeypatch.setattr(installer, "WEIGHT_SIZE", len(payload))
    monkeypatch.setattr(installer, "WEIGHT_SHA256", installer.sha256_bytes(payload))
    real_replace = installer.os.replace

    def fail_namespace(source, destination, **kwargs):
        if destination == "preview-config":
            raise OSError("injected namespace publish failure")
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(installer.os, "replace", fail_namespace)
    runtime = _runtime(tmp_path)

    with pytest.raises(installer.InstallPreviewAdapterError):
        installer.install_preview_adapter(
            runtime, opener=lambda *_a, **_k: _Response(payload)
        )

    assert not (runtime / "preview-config").exists()
    assert not list(runtime.glob(".preview-config.tmp-*"))


def test_existing_complete_config_is_never_rewritten_or_mixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    payload = b"adapter"
    monkeypatch.setattr(installer, "WEIGHT_SIZE", len(payload))
    monkeypatch.setattr(installer, "WEIGHT_SHA256", installer.sha256_bytes(payload))
    runtime = _runtime(tmp_path)
    installer.install_preview_adapter(
        runtime, opener=lambda *_a, **_k: _Response(payload)
    )
    config = runtime / "preview-config"
    before = {name: (config / name).read_bytes() for name in installer.CONFIG_FILENAMES}
    monkeypatch.setattr(
        installer,
        "EVIDENCE_URL",
        f"https://example.invalid/{installer.REVISION}/changed-license",
    )

    with pytest.raises(installer.InstallPreviewAdapterError, match="config"):
        installer.install_preview_adapter(
            runtime,
            opener=lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("weight must be reused")
            ),
        )

    assert {name: (config / name).read_bytes() for name in before} == before


def test_cli_failure_is_structured_and_does_not_echo_exception(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()

    def fail(*_args: object, **_kwargs: object):
        raise installer.InstallPreviewAdapterError("secret network detail")

    monkeypatch.setattr(installer, "install_preview_adapter", fail)
    code = installer.main(["--runtime-root", "/does/not/matter"])
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output == {
        "reason_code": "INSTALL_FAILED",
        "schema_version": 1,
        "status": "FAIL",
    }
