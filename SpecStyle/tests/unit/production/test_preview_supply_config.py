from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from specstyle.errors import DomainError, InfrastructureError

REVISION = "a" * 40
WEIGHT = b"preview-lcm-lora-safe-tensors"


def _sha(value: object) -> str:
    encoded = (
        value
        if type(value) is bytes
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    return hashlib.sha256(encoded).hexdigest()


def _documents() -> dict[str, dict[str, Any]]:
    entrypoint = {
        "kind": "diffusers_lora",
        "subfolder": "adapter",
        "weight_name": "pytorch_lora_weights.safetensors",
    }
    files = [
        {
            "relative_path": "adapter/pytorch_lora_weights.safetensors",
            "size_bytes": len(WEIGHT),
            "sha256": _sha(WEIGHT),
        }
    ]
    unsigned = {
        "schema_version": "specstyle.preview-adapter-manifest.v1",
        "model_id": "org/lcm-lora-sdxl",
        "role": "preview_adapter",
        "revision": REVISION,
        "relative_root": "preview/lcm-lora-sdxl",
        "entrypoint": entrypoint,
        "files": files,
    }
    root_sha = _sha(unsigned)
    manifest = {**unsigned, "root_sha256": root_sha}
    return {
        "models.json": {
            "schema_version": "specstyle.preview.models.v1",
            "models": [
                {
                    "model_id": "org/lcm-lora-sdxl",
                    "role": "preview_adapter",
                    "revision": REVISION,
                    "expected_sha256": root_sha,
                    "license_spdx": "Apache-2.0",
                    "license_status": "APPROVED",
                    "family": "sdxl-production",
                }
            ],
        },
        "weight_manifests.json": {
            "schema_version": "specstyle.preview.weight_manifests.v1",
            "manifests": [manifest],
        },
        "license_approvals.json": {
            "schema_version": "specstyle.preview.license_approvals.v1",
            "approvals": [
                {
                    "model_id": "org/lcm-lora-sdxl",
                    "revision": REVISION,
                    "manifest_sha256": _sha(manifest),
                    "license_spdx": "Apache-2.0",
                    "evidence_url": "https://licenses.example.test/lcm-lora-sdxl",
                }
            ],
        },
    }


def _write(root: Path, documents: dict[str, dict[str, Any]]) -> None:
    for name, value in documents.items():
        path = root / name
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        path.chmod(0o600)


def _load(root: Path):
    from specstyle.production.preview_supply_config import load_preview_supply_config

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return load_preview_supply_config(descriptor)
    finally:
        os.close(descriptor)


def test_loads_one_closed_loop_preview_adapter_without_production_graph(
    tmp_path: Path,
) -> None:
    _write(tmp_path, _documents())

    config = _load(tmp_path)

    assert config.descriptor.role == "preview_adapter"
    assert config.descriptor.model_id == "org/lcm-lora-sdxl"
    assert config.manifest.role == "preview_adapter"
    assert config.approval.model_id == config.descriptor.model_id
    assert not hasattr(config, "graph")


@pytest.mark.parametrize(
    ("filename", "mutation"),
    (
        ("models.json", lambda value: value.update(extra=True)),
        ("models.json", lambda value: value["models"].append(value["models"][0])),
        ("models.json", lambda value: value["models"][0].update(extra=True)),
        (
            "weight_manifests.json",
            lambda value: value["manifests"][0]["entrypoint"].update(extra=True),
        ),
        (
            "license_approvals.json",
            lambda value: value["approvals"][0].pop("evidence_url"),
        ),
    ),
)
def test_rejects_unknown_keys_or_non_singleton_collections(
    tmp_path: Path, filename: str, mutation
) -> None:
    documents = _documents()
    mutation(documents[filename])
    _write(tmp_path, documents)
    with pytest.raises(DomainError):
        _load(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda docs: docs["models.json"]["models"][0].update(role="ip_adapter"),
        lambda docs: docs["models.json"]["models"][0].update(model_id="lcm-lora-sdxl"),
        lambda docs: docs["models.json"]["models"][0].update(expected_sha256="f" * 64),
        lambda docs: docs["weight_manifests.json"]["manifests"][0].update(
            revision="b" * 40
        ),
        lambda docs: docs["license_approvals.json"]["approvals"][0].update(
            license_spdx="MIT"
        ),
    ),
)
def test_rejects_role_placeholder_or_closed_loop_mismatch(
    tmp_path: Path, mutation
) -> None:
    documents = _documents()
    mutation(documents)
    _write(tmp_path, documents)
    with pytest.raises(DomainError):
        _load(tmp_path)


def test_preview_config_inherits_strict_file_mode_boundary(tmp_path: Path) -> None:
    _write(tmp_path, _documents())
    (tmp_path / "models.json").chmod(0o640)

    with pytest.raises(InfrastructureError, match="mode"):
        _load(tmp_path)
