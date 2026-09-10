#!/usr/bin/env python3
"""Install the pinned LCM-LoRA SDXL Preview supply without touching PyTorch."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, BinaryIO, Callable, Iterator, Sequence
from urllib.request import urlopen

MODEL_ID = "latent-consistency/lcm-lora-sdxl"
REVISION = "a18548dd4956b174ec5b0d78d340c8dae0a129cd"
WEIGHT_NAME = "pytorch_lora_weights.safetensors"
WEIGHT_RELATIVE_PATH = f"adapter/{WEIGHT_NAME}"
WEIGHT_SIZE = 393_855_224
WEIGHT_SHA256 = "a764e6859b6e04047cd761c08ff0cee96413a8e004c9f07707530cd776b19141"
LICENSE_SPDX = "OpenRAIL++-M"
MANIFEST_RELATIVE_ROOT = "preview/lcm-lora-sdxl"
RELATIVE_ROOT = Path("models") / MANIFEST_RELATIVE_ROOT
DOWNLOAD_URL = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{WEIGHT_NAME}"
EVIDENCE_URL = f"https://huggingface.co/{MODEL_ID}/blob/{REVISION}/README.md"
DOWNLOAD_TIMEOUT_SECONDS = 300
CONFIG_FILENAMES = (
    "models.json",
    "weight_manifests.json",
    "license_approvals.json",
)
_CHUNK_BYTES = 1024 * 1024
_OPEN_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
if hasattr(os, "O_CLOEXEC"):
    _OPEN_DIRECTORY_FLAGS |= os.O_CLOEXEC


class InstallPreviewAdapterError(RuntimeError):
    """A fail-closed, user-safe Preview supply installation error."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_directory(fd: int, label: str, *, private: bool = False) -> None:
    try:
        info = os.fstat(fd)
    except OSError as exc:
        raise InstallPreviewAdapterError(f"{label} directory unavailable") from exc
    allowed_owners = {os.geteuid(), 0}
    mode = stat.S_IMODE(info.st_mode)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid not in allowed_owners
        or mode & 0o022
        or (private and (info.st_uid != os.geteuid() or mode != 0o700))
    ):
        raise InstallPreviewAdapterError(f"{label} directory untrusted")


@contextmanager
def _open_path_directory(path: Path, label: str) -> Iterator[int]:
    try:
        fd = os.open(path, _OPEN_DIRECTORY_FLAGS)
    except OSError as exc:
        raise InstallPreviewAdapterError(f"{label} directory unavailable") from exc
    try:
        _validate_directory(fd, label)
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _open_child_directory(parent_fd: int, name: str, label: str) -> Iterator[int]:
    try:
        fd = os.open(name, _OPEN_DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise InstallPreviewAdapterError(f"{label} directory unavailable") from exc
    try:
        _validate_directory(fd, label)
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _ensure_private_directory(parent_fd: int, name: str, label: str) -> Iterator[int]:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise InstallPreviewAdapterError(f"{label} directory unavailable") from exc
    try:
        fd = os.open(name, _OPEN_DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise InstallPreviewAdapterError(f"{label} directory unavailable") from exc
    try:
        _validate_directory(fd, label, private=True)
        yield fd
    finally:
        os.close(fd)


def _hash_open_file(fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        while chunk := os.read(fd, _CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
    except OSError as exc:
        raise InstallPreviewAdapterError("adapter weight unreadable") from exc
    return size, digest.hexdigest()


def _existing_weight_valid(adapter_fd: int) -> bool:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(WEIGHT_NAME, flags, dir_fd=adapter_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise InstallPreviewAdapterError("adapter weight path refused") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise InstallPreviewAdapterError("adapter weight path refused")
        size, digest = _hash_open_file(fd)
        return size == WEIGHT_SIZE and digest == WEIGHT_SHA256
    finally:
        os.close(fd)


def _write_all(fd: int, value: bytes) -> None:
    offset = 0
    try:
        while offset < len(value):
            offset += os.write(fd, value[offset:])
    except OSError as exc:
        raise InstallPreviewAdapterError("adapter write failed") from exc


def _copy_response(response: BinaryIO, fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = response.read(min(_CHUNK_BYTES, WEIGHT_SIZE - size + 1))
        if not chunk:
            break
        if type(chunk) is not bytes:
            raise InstallPreviewAdapterError("adapter response invalid")
        size += len(chunk)
        if size > WEIGHT_SIZE:
            raise InstallPreviewAdapterError("adapter size mismatch")
        digest.update(chunk)
        _write_all(fd, chunk)
    return size, digest.hexdigest()


def _download_weight(
    adapter_fd: int,
    opener: Callable[..., Any],
) -> None:
    temporary = f".{WEIGHT_NAME}.tmp-{secrets.token_hex(12)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = -1
    try:
        fd = os.open(temporary, flags, 0o600, dir_fd=adapter_fd)
        with opener(DOWNLOAD_URL, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            size, digest = _copy_response(response, fd)
        if size != WEIGHT_SIZE or digest != WEIGHT_SHA256:
            raise InstallPreviewAdapterError("adapter digest mismatch")
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(
            temporary,
            WEIGHT_NAME,
            src_dir_fd=adapter_fd,
            dst_dir_fd=adapter_fd,
        )
        os.fsync(adapter_fd)
    except InstallPreviewAdapterError:
        raise
    except Exception as exc:
        raise InstallPreviewAdapterError("adapter download failed") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=adapter_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _manifest_documents() -> tuple[
    dict[str, object], dict[str, object], dict[str, object]
]:
    entrypoint = {
        "kind": "diffusers_lora",
        "subfolder": "adapter",
        "weight_name": WEIGHT_NAME,
    }
    files = [
        {
            "relative_path": WEIGHT_RELATIVE_PATH,
            "size_bytes": WEIGHT_SIZE,
            "sha256": WEIGHT_SHA256,
        }
    ]
    unsigned = {
        "schema_version": "specstyle.preview-adapter-manifest.v1",
        "model_id": MODEL_ID,
        "role": "preview_adapter",
        "revision": REVISION,
        "relative_root": MANIFEST_RELATIVE_ROOT,
        "entrypoint": entrypoint,
        "files": files,
    }
    root_sha = sha256_bytes(canonical_json(unsigned))
    manifest = {**unsigned, "root_sha256": root_sha}
    descriptor = {
        "model_id": MODEL_ID,
        "role": "preview_adapter",
        "revision": REVISION,
        "expected_sha256": root_sha,
        "license_spdx": LICENSE_SPDX,
        "license_status": "APPROVED",
        "family": "sdxl-production",
    }
    approval = {
        "model_id": MODEL_ID,
        "revision": REVISION,
        "manifest_sha256": sha256_bytes(canonical_json(manifest)),
        "license_spdx": LICENSE_SPDX,
        "evidence_url": EVIDENCE_URL,
    }
    return descriptor, manifest, approval


def preview_config_documents() -> dict[str, dict[str, object]]:
    descriptor, manifest, approval = _manifest_documents()
    return {
        "models.json": {
            "schema_version": "specstyle.preview.models.v1",
            "models": [descriptor],
        },
        "weight_manifests.json": {
            "schema_version": "specstyle.preview.weight_manifests.v1",
            "manifests": [manifest],
        },
        "license_approvals.json": {
            "schema_version": "specstyle.preview.license_approvals.v1",
            "approvals": [approval],
        },
    }


def _atomic_write_config(config_fd: int, filename: str, value: object) -> None:
    temporary = f".{filename}.tmp-{secrets.token_hex(12)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = -1
    try:
        fd = os.open(temporary, flags, 0o600, dir_fd=config_fd)
        _write_all(fd, canonical_json(value))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(
            temporary,
            filename,
            src_dir_fd=config_fd,
            dst_dir_fd=config_fd,
        )
        os.fsync(config_fd)
    except InstallPreviewAdapterError:
        raise
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config publish failed") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=config_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _verify_config_snapshot(
    config_fd: int, documents: dict[str, dict[str, object]]
) -> None:
    from specstyle.production.preview_supply_config import load_preview_supply_config

    try:
        names = set(os.listdir(config_fd))
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config unreadable") from exc
    if names != set(CONFIG_FILENAMES):
        raise InstallPreviewAdapterError("preview config snapshot mismatch")
    for filename in CONFIG_FILENAMES:
        if _read_config_file(config_fd, filename) != canonical_json(
            documents[filename]
        ):
            raise InstallPreviewAdapterError("preview config snapshot mismatch")
    try:
        load_preview_supply_config(config_fd)
    except Exception as exc:
        raise InstallPreviewAdapterError("preview config closed loop invalid") from exc


def _read_config_file(config_fd: int, filename: str) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(filename, flags, dir_fd=config_fd)
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config file refused") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise InstallPreviewAdapterError("preview config file refused")
        chunks: list[bytes] = []
        while chunk := os.read(fd, _CHUNK_BYTES):
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config file unreadable") from exc
    finally:
        os.close(fd)


def _existing_config_is_current(
    runtime_fd: int, documents: dict[str, dict[str, object]]
) -> bool:
    try:
        config_fd = os.open("preview-config", _OPEN_DIRECTORY_FLAGS, dir_fd=runtime_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config directory refused") from exc
    try:
        _validate_directory(config_fd, "preview config", private=True)
        _verify_config_snapshot(config_fd, documents)
        return True
    finally:
        os.close(config_fd)


def _cleanup_staged_config(runtime_fd: int, staging: str) -> None:
    try:
        stage_fd = os.open(staging, _OPEN_DIRECTORY_FLAGS, dir_fd=runtime_fd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config cleanup failed") from exc
    try:
        for filename in os.listdir(stage_fd):
            os.unlink(filename, dir_fd=stage_fd)
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config cleanup failed") from exc
    finally:
        os.close(stage_fd)
    try:
        os.rmdir(staging, dir_fd=runtime_fd)
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config cleanup failed") from exc


def _publish_config_snapshot(
    runtime_fd: int, documents: dict[str, dict[str, object]]
) -> None:
    staging = f".preview-config.tmp-{secrets.token_hex(12)}"
    published = False
    try:
        with _ensure_private_directory(
            runtime_fd, staging, "staged preview config"
        ) as config_fd:
            for filename in CONFIG_FILENAMES:
                _atomic_write_config(config_fd, filename, documents[filename])
            _verify_config_snapshot(config_fd, documents)
            os.fsync(config_fd)
        os.replace(
            staging,
            "preview-config",
            src_dir_fd=runtime_fd,
            dst_dir_fd=runtime_fd,
        )
        published = True
        os.fsync(runtime_fd)
    except InstallPreviewAdapterError:
        raise
    except OSError as exc:
        raise InstallPreviewAdapterError("preview config publish failed") from exc
    finally:
        if not published:
            _cleanup_staged_config(runtime_fd, staging)


def _config_hashes(
    documents: dict[str, dict[str, object]],
) -> tuple[str, str]:
    manifest = documents["weight_manifests.json"]["manifests"][0]
    assert type(manifest) is dict
    return manifest["root_sha256"], sha256_bytes(canonical_json(manifest))


def _install_weight(runtime_fd: int, opener: Callable[..., Any]) -> bool:
    with _open_child_directory(runtime_fd, "models", "models") as models_fd:
        with _ensure_private_directory(
            models_fd, "preview", "preview models"
        ) as preview:
            with _ensure_private_directory(
                preview, "lcm-lora-sdxl", "preview adapter"
            ) as component:
                with _ensure_private_directory(
                    component, "adapter", "preview adapter weights"
                ) as adapter:
                    if _existing_weight_valid(adapter):
                        return False
                    _download_weight(adapter, opener)
                    return True


def install_preview_adapter(
    runtime_root: Path,
    /,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, object]:
    """Install and publish the single approved Preview adapter supply."""
    documents = preview_config_documents()
    with _open_path_directory(Path(runtime_root), "runtime") as runtime_fd:
        config_current = _existing_config_is_current(runtime_fd, documents)
        downloaded = _install_weight(runtime_fd, opener)
        if not config_current:
            _publish_config_snapshot(runtime_fd, documents)
        root_sha, manifest_sha = _config_hashes(documents)
    return {
        "schema_version": 1,
        "status": "PASS",
        "reason_code": "OK",
        "model_id": MODEL_ID,
        "revision": REVISION,
        "downloaded": downloaded,
        "weight_size": WEIGHT_SIZE,
        "weight_sha256": WEIGHT_SHA256,
        "manifest_root_sha256": root_sha,
        "manifest_sha256": manifest_sha,
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the pinned LCM Preview adapter"
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("/workspace/persistence/lookfile-runtime"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    try:
        result = install_preview_adapter(arguments.runtime_root)
    except InstallPreviewAdapterError:
        result = {
            "schema_version": 1,
            "status": "FAIL",
            "reason_code": "INSTALL_FAILED",
        }
        code = 2
    else:
        code = 0
    sys.stdout.write(canonical_json(result).decode("utf-8") + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
