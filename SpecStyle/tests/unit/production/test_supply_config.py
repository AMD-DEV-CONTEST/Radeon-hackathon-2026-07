from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.production.supply_config import (
    ProductionSupplyConfig,
    load_production_supply_config,
)


ROLES = ("base", "ip_adapter", "controlnet")
REVISIONS = ("a" * 40, "b" * 40, "c" * 40)


def _sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _documents() -> dict[str, dict[str, Any]]:
    models: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    for index, (role, revision) in enumerate(zip(ROLES, REVISIONS, strict=True)):
        model_id = f"org/production-{role}"
        subfolder = "adapter" if role == "ip_adapter" else "unet"
        files = [
            {
                "relative_path": f"{subfolder}/config.json",
                "size_bytes": 2,
                "sha256": hashlib.sha256(b"{}").hexdigest(),
            },
            {
                "relative_path": f"{subfolder}/model.safetensors",
                "size_bytes": index + 1,
                "sha256": hashlib.sha256(bytes([index + 1])).hexdigest(),
            },
        ]
        if role == "ip_adapter":
            files.extend(
                [
                    {
                        "relative_path": "adapter/image_encoder/config.json",
                        "size_bytes": 2,
                        "sha256": hashlib.sha256(b"{}").hexdigest(),
                    },
                    {
                        "relative_path": "adapter/image_encoder/model.safetensors",
                        "size_bytes": 3,
                        "sha256": hashlib.sha256(b"enc").hexdigest(),
                    },
                ]
            )
            files.sort(key=lambda item: item["relative_path"])
        entrypoint = {
            "kind": (
                "diffusers_ip_adapter"
                if role == "ip_adapter"
                else "diffusers_pretrained"
            ),
            "subfolder": subfolder,
            "weight_name": "model.safetensors" if role == "ip_adapter" else None,
            "image_encoder_folder": "image_encoder" if role == "ip_adapter" else None,
            "variant": None,
        }
        unsigned_manifest = {
            "schema_version": "specstyle.weight-manifest.v1",
            "model_id": model_id,
            "role": role,
            "revision": revision,
            "relative_root": f"weights/{role}",
            "entrypoint": entrypoint,
            "files": files,
        }
        root_sha256 = _sha(unsigned_manifest)
        manifest = {**unsigned_manifest, "root_sha256": root_sha256}
        models.append(
            {
                "model_id": model_id,
                "role": role,
                "revision": revision,
                "expected_sha256": root_sha256,
                "license_spdx": "Apache-2.0",
                "license_status": "APPROVED",
                "family": "sdxl-production",
            }
        )
        manifests.append(manifest)
        approvals.append(
            {
                "model_id": model_id,
                "revision": revision,
                "manifest_sha256": _sha(manifest),
                "license_spdx": "Apache-2.0",
                "evidence_url": f"https://licenses.example.test/evidence/{index}",
            }
        )
    return {
        "models.json": {
            "schema_version": "specstyle.production.models.v1",
            "models": models,
        },
        "weight_manifests.json": {
            "schema_version": "specstyle.production.weight_manifests.v1",
            "manifests": manifests,
        },
        "license_approvals.json": {
            "schema_version": "specstyle.production.license_approvals.v1",
            "approvals": approvals,
        },
    }


def _write_documents(root: Path, documents: dict[str, dict[str, Any]]) -> None:
    for filename, payload in documents.items():
        path = root / filename
        path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        path.chmod(0o600)


def _open_root(root: Path) -> int:
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY)


def _load(root: Path) -> ProductionSupplyConfig:
    root_fd = _open_root(root)
    try:
        return load_production_supply_config(root_fd)
    finally:
        os.close(root_fd)


def test_loads_ordered_joined_production_graph_without_real_cache_path(
    tmp_path: Path,
) -> None:
    documents = _documents()
    documents["license_approvals.json"]["approvals"].reverse()
    _write_documents(tmp_path, documents)

    loaded = _load(tmp_path)

    assert loaded.graph.profile == "production"
    assert loaded.graph.cache_root == "models"
    assert tuple(
        (item.model_id, item.role)
        for item in (
            loaded.graph.base,
            loaded.graph.ip_adapter,
            loaded.graph.controlnet,
        )
    ) == tuple((f"org/production-{role}", role) for role in ROLES)
    assert tuple(item.role for item in loaded.manifests) == ROLES
    assert tuple(item.model_id for item in loaded.approvals) == tuple(
        f"org/production-{role}" for role in ROLES
    )


def test_config_is_loader_issued_frozen_and_slotted(tmp_path: Path) -> None:
    _write_documents(tmp_path, _documents())
    loaded = _load(tmp_path)
    assert not hasattr(loaded, "__dict__")
    with pytest.raises(TypeError):
        ProductionSupplyConfig()  # type: ignore[call-arg]
    with pytest.raises(FrozenInstanceError):
        loaded.graph = loaded.graph  # type: ignore[misc]


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        ("models.json", lambda value: value.update(extra=True)),
        ("models.json", lambda value: value.pop("models")),
        ("models.json", lambda value: value["models"][0].update(extra=True)),
        ("models.json", lambda value: value["models"][0].pop("family")),
        (
            "weight_manifests.json",
            lambda value: value["manifests"][0]["entrypoint"].pop("variant"),
        ),
        (
            "weight_manifests.json",
            lambda value: value["manifests"][0]["files"][0].update(extra=True),
        ),
        (
            "license_approvals.json",
            lambda value: value["approvals"][0].pop("evidence_url"),
        ),
    ],
)
def test_rejects_unknown_or_missing_keys_at_every_schema_layer(
    filename: str, mutate: Any, tmp_path: Path
) -> None:
    documents = _documents()
    mutate(documents[filename])
    _write_documents(tmp_path, documents)
    with pytest.raises(DomainError):
        _load(tmp_path)


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    documents = _documents()
    _write_documents(tmp_path, documents)
    path = tmp_path / "models.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"family":', '"family":"duplicate","family":', 1))
    path.chmod(0o600)
    with pytest.raises(DomainError, match="duplicate"):
        _load(tmp_path)


def test_rejects_non_finite_json_number(tmp_path: Path) -> None:
    documents = _documents()
    _write_documents(tmp_path, documents)
    path = tmp_path / "weight_manifests.json"
    text = path.read_text(encoding="utf-8").replace(
        '"size_bytes":2', '"size_bytes":NaN', 1
    )
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(DomainError):
        _load(tmp_path)


def test_rejects_bool_where_integer_is_required(tmp_path: Path) -> None:
    documents = _documents()
    documents["weight_manifests.json"]["manifests"][0]["files"][0]["size_bytes"] = True
    _write_documents(tmp_path, documents)
    with pytest.raises(DomainError):
        _load(tmp_path)


def test_rejects_invalid_utf8(tmp_path: Path) -> None:
    _write_documents(tmp_path, _documents())
    path = tmp_path / "models.json"
    path.write_bytes(b"\xff")
    path.chmod(0o600)
    with pytest.raises(DomainError, match="UTF-8"):
        _load(tmp_path)


def test_maps_excessively_nested_json_to_domain_error(tmp_path: Path) -> None:
    _write_documents(tmp_path, _documents())
    path = tmp_path / "models.json"
    path.write_bytes(b"[" * 10_000 + b"0" + b"]" * 10_000)
    path.chmod(0o600)
    with pytest.raises(DomainError, match="JSON"):
        _load(tmp_path)


def test_maps_unpaired_json_surrogate_to_domain_error(tmp_path: Path) -> None:
    documents = _documents()
    documents["weight_manifests.json"]["manifests"][0]["relative_root"] = "\ud800"
    _write_documents(tmp_path, documents)
    with pytest.raises(DomainError):
        _load(tmp_path)


def test_rejects_total_input_over_16_mib(tmp_path: Path) -> None:
    _write_documents(tmp_path, _documents())
    target_size = 6 * 1024 * 1024
    for filename in (
        "models.json",
        "weight_manifests.json",
        "license_approvals.json",
    ):
        path = tmp_path / filename
        path.write_bytes(path.read_bytes().ljust(target_size, b" "))
        path.chmod(0o600)
    with pytest.raises(InfrastructureError, match="size"):
        _load(tmp_path)


def test_rejects_wrong_mode_owner_symlink_and_fifo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.production.config_io as config_io

    _write_documents(tmp_path, _documents())
    models = tmp_path / "models.json"
    models.chmod(0o640)
    with pytest.raises(InfrastructureError, match="mode"):
        _load(tmp_path)

    models.chmod(0o600)
    real_fstat = os.fstat
    target_inode = models.stat().st_ino

    def wrong_file_owner(fd: int) -> Any:
        value = real_fstat(fd)
        if value.st_ino != target_inode:
            return value
        return type(
            "FileStat",
            (),
            {
                "st_mode": value.st_mode,
                "st_uid": value.st_uid + 1,
                "st_gid": value.st_gid,
                "st_dev": value.st_dev,
                "st_ino": value.st_ino,
                "st_size": value.st_size,
                "st_mtime_ns": value.st_mtime_ns,
                "st_ctime_ns": value.st_ctime_ns,
            },
        )()

    monkeypatch.setattr(config_io.os, "fstat", wrong_file_owner)
    with pytest.raises(InfrastructureError, match="owner"):
        _load(tmp_path)
    monkeypatch.undo()

    target = tmp_path / "target.json"
    models.rename(target)
    models.symlink_to(target.name)
    with pytest.raises(InfrastructureError):
        _load(tmp_path)
    models.unlink()
    os.mkfifo(models, 0o600)
    with pytest.raises(InfrastructureError, match="regular"):
        _load(tmp_path)


def test_detects_file_size_change_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.production.config_io as config_io

    _write_documents(tmp_path, _documents())
    models_path = tmp_path / "models.json"
    target_inode = models_path.stat().st_ino
    real_read = os.read
    changed = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal changed
        chunk = real_read(fd, size)
        if not changed and os.fstat(fd).st_ino == target_inode:
            changed = True
            with models_path.open("ab") as stream:
                stream.write(b" ")
        return chunk

    monkeypatch.setattr(config_io.os, "read", changing_read)
    with pytest.raises(InfrastructureError, match="changed"):
        _load(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "model_order",
        "manifest_order",
        "duplicate_role",
        "revision_join",
        "root_sha_join",
        "approval_sha_join",
        "license_join",
        "floating_revision",
        "blocked_license",
        "placeholder_digest",
        "unsorted_files",
    ],
)
def test_rejects_invalid_production_order_and_closed_loop(
    mutation: str, tmp_path: Path
) -> None:
    documents = _documents()
    models = documents["models.json"]["models"]
    manifests = documents["weight_manifests.json"]["manifests"]
    approvals = documents["license_approvals.json"]["approvals"]
    if mutation == "model_order":
        models[0], models[1] = models[1], models[0]
    elif mutation == "manifest_order":
        manifests[0], manifests[1] = manifests[1], manifests[0]
    elif mutation == "duplicate_role":
        models[1]["role"] = "base"
    elif mutation == "revision_join":
        approvals[0]["revision"] = "d" * 40
    elif mutation == "root_sha_join":
        models[0]["expected_sha256"] = "f" * 64
    elif mutation == "approval_sha_join":
        approvals[0]["manifest_sha256"] = "f" * 64
    elif mutation == "license_join":
        approvals[0]["license_spdx"] = "MIT"
    elif mutation == "floating_revision":
        models[0]["revision"] = "main"
    elif mutation == "blocked_license":
        models[0]["license_status"] = "BLOCKED"
    elif mutation == "placeholder_digest":
        placeholder_id = "sdxl-base-1.0"
        models[0]["model_id"] = placeholder_id
        manifests[0]["model_id"] = placeholder_id
        unsigned = {
            key: value for key, value in manifests[0].items() if key != "root_sha256"
        }
        manifests[0]["root_sha256"] = _sha(unsigned)
        models[0]["expected_sha256"] = manifests[0]["root_sha256"]
        approvals[0]["model_id"] = placeholder_id
        approvals[0]["manifest_sha256"] = _sha(manifests[0])
    elif mutation == "unsorted_files":
        manifests[0]["files"].reverse()
    _write_documents(tmp_path, documents)
    with pytest.raises(DomainError):
        _load(tmp_path)


def test_borrows_caller_fd_and_does_not_leak_internal_fds(tmp_path: Path) -> None:
    _write_documents(tmp_path, _documents())
    root_fd = _open_root(tmp_path)
    before = len(os.listdir("/dev/fd"))
    try:
        load_production_supply_config(root_fd)
        os.fstat(root_fd)
        assert len(os.listdir("/dev/fd")) == before

        (tmp_path / "models.json").chmod(0o640)
        with pytest.raises(InfrastructureError):
            load_production_supply_config(root_fd)
        os.fstat(root_fd)
        assert len(os.listdir("/dev/fd")) == before
    finally:
        os.close(root_fd)
