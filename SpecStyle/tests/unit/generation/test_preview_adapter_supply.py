from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import pickle

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.model_approval import LicenseApproval
from specstyle.generation.model_registry import ModelDescriptor
from specstyle.generation.weight_manifest import (
    ModelLoadEntrypoint,
    WeightFile,
    WeightManifest,
)

REVISION = "a" * 40
WEIGHT = b"preview-lcm-lora-safe-tensors"


def _sha(value: bytes) -> Sha256:
    return Sha256(hashlib.sha256(value).hexdigest())


def _manifest():
    from specstyle.generation.preview_adapter_supply import (
        PreviewAdapterEntrypoint,
        PreviewAdapterManifest,
    )

    return PreviewAdapterManifest(
        "org/lcm-lora-sdxl",
        "preview_adapter",
        REVISION,
        "preview/lcm-lora-sdxl",
        PreviewAdapterEntrypoint(
            "diffusers_lora", "adapter", "pytorch_lora_weights.safetensors"
        ),
        (
            WeightFile(
                "adapter/pytorch_lora_weights.safetensors",
                len(WEIGHT),
                _sha(WEIGHT),
            ),
        ),
        Sha256("0" * 64),
    ).with_computed_root()


def _descriptor(manifest=None) -> ModelDescriptor:
    value = _manifest() if manifest is None else manifest
    return ModelDescriptor(
        value.model_id,
        "preview_adapter",
        value.revision,
        value.root_sha256,
        "Apache-2.0",
        "APPROVED",
        "sdxl-production",
    )


def _approval(manifest=None) -> LicenseApproval:
    from specstyle.generation.preview_adapter_supply import (
        preview_adapter_manifest_sha256,
    )

    value = _manifest() if manifest is None else manifest
    return LicenseApproval(
        value.model_id,
        value.revision,
        preview_adapter_manifest_sha256(value),
        "Apache-2.0",
        "https://licenses.example.test/lcm-lora-sdxl",
    )


def _write_component(root: Path, manifest=None) -> Path:
    value = _manifest() if manifest is None else manifest
    component = root / value.relative_root
    target = component / value.entrypoint.subfolder / value.entrypoint.weight_name
    target.parent.mkdir(parents=True)
    target.write_bytes(WEIGHT)
    return component


def _open_root(root: Path) -> int:
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY)


def test_preview_manifest_is_distinct_from_production_manifest_contract() -> None:
    manifest = _manifest()

    assert manifest.role == "preview_adapter"
    assert manifest.entrypoint.kind == "diffusers_lora"
    with pytest.raises(DomainError, match="role"):
        WeightManifest(
            manifest.model_id,
            manifest.role,
            manifest.revision,
            manifest.relative_root,
            ModelLoadEntrypoint("diffusers_pretrained", "adapter"),
            manifest.files,
            manifest.root_sha256,
        )


def test_preview_manifest_digest_binds_lora_entrypoint() -> None:
    from specstyle.generation.preview_adapter_supply import (
        PreviewAdapterEntrypoint,
        PreviewAdapterManifest,
        preview_adapter_manifest_root_sha256,
        preview_adapter_manifest_sha256,
    )

    manifest = _manifest()
    shared_files = tuple(
        sorted(
            (
                manifest.files[0],
                WeightFile("adapter/different.safetensors", len(WEIGHT), _sha(WEIGHT)),
            ),
            key=lambda item: item.relative_path,
        )
    )
    original = PreviewAdapterManifest(
        manifest.model_id,
        manifest.role,
        manifest.revision,
        manifest.relative_root,
        manifest.entrypoint,
        shared_files,
        Sha256("0" * 64),
    ).with_computed_root()
    changed = PreviewAdapterManifest(
        manifest.model_id,
        manifest.role,
        manifest.revision,
        manifest.relative_root,
        PreviewAdapterEntrypoint("diffusers_lora", "adapter", "different.safetensors"),
        shared_files,
        Sha256("0" * 64),
    ).with_computed_root()

    assert preview_adapter_manifest_root_sha256(manifest) == manifest.root_sha256
    assert preview_adapter_manifest_sha256(original) != preview_adapter_manifest_sha256(
        changed
    )


@pytest.mark.parametrize("revision", ("main", "A" * 40, "a" * 39))
def test_preview_manifest_requires_full_lowercase_revision(revision: str) -> None:
    from specstyle.generation.preview_adapter_supply import PreviewAdapterManifest

    manifest = _manifest()
    with pytest.raises(DomainError, match="revision"):
        PreviewAdapterManifest(
            manifest.model_id,
            manifest.role,
            revision,
            manifest.relative_root,
            manifest.entrypoint,
            manifest.files,
            manifest.root_sha256,
        )


@pytest.mark.parametrize(
    "path",
    (
        "adapter/pytorch_lora_weights.bin",
        "adapter/pytorch_lora_weights.pt",
        "adapter/README.md",
    ),
)
def test_preview_manifest_refuses_unsafe_or_nonruntime_files(path: str) -> None:
    from specstyle.generation.preview_adapter_supply import PreviewAdapterManifest

    manifest = _manifest()
    with pytest.raises(DomainError, match="file"):
        PreviewAdapterManifest(
            manifest.model_id,
            manifest.role,
            manifest.revision,
            manifest.relative_root,
            manifest.entrypoint,
            (WeightFile(path, 1, _sha(b"x")),),
            manifest.root_sha256,
        )


def test_preview_manifest_requires_sorted_unique_files_and_named_weight() -> None:
    from specstyle.generation.preview_adapter_supply import PreviewAdapterManifest

    manifest = _manifest()
    extra = WeightFile("adapter/config.json", 2, _sha(b"{}"))
    with pytest.raises(DomainError, match="sorted"):
        PreviewAdapterManifest(
            manifest.model_id,
            manifest.role,
            manifest.revision,
            manifest.relative_root,
            manifest.entrypoint,
            (manifest.files[0], extra),
            manifest.root_sha256,
        )
    with pytest.raises(DomainError, match="weight"):
        PreviewAdapterManifest(
            manifest.model_id,
            manifest.role,
            manifest.revision,
            manifest.relative_root,
            manifest.entrypoint,
            (extra,),
            manifest.root_sha256,
        )


def test_verified_preview_adapter_retains_exact_directory_and_closes(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_adapter_supply import verify_preview_adapter

    manifest = _manifest()
    component = _write_component(tmp_path, manifest)
    root_fd = _open_root(tmp_path)
    try:
        verified = verify_preview_adapter(
            root_fd, _descriptor(manifest), manifest, _approval(manifest)
        )
        loader_path = verified.borrow_loader_path()
        assert loader_path.startswith("/proc/self/fd/")
        descriptor_stat = os.fstat(int(loader_path.rsplit("/", 1)[1]))
        component_stat = component.stat()
        assert (descriptor_stat.st_dev, descriptor_stat.st_ino) == (
            component_stat.st_dev,
            component_stat.st_ino,
        )
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                operation(verified)
        verified.close()
        verified.close()
        with pytest.raises(DomainError, match="closed"):
            verified.borrow_loader_path()
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("extra_kind", ("file", "symlink"))
def test_verification_rejects_every_unlisted_or_linked_node(
    tmp_path: Path, extra_kind: str
) -> None:
    from specstyle.generation.preview_adapter_supply import verify_preview_adapter

    manifest = _manifest()
    component = _write_component(tmp_path, manifest)
    extra = component / "adapter" / "extra.json"
    if extra_kind == "file":
        extra.write_text("{}", encoding="utf-8")
    else:
        extra.symlink_to("pytorch_lora_weights.safetensors")
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError):
            verify_preview_adapter(
                root_fd, _descriptor(manifest), manifest, _approval(manifest)
            )
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("target", ("component", "file"))
def test_verification_rejects_group_writable_supply_nodes(
    tmp_path: Path, target: str
) -> None:
    from specstyle.generation.preview_adapter_supply import verify_preview_adapter

    manifest = _manifest()
    component = _write_component(tmp_path, manifest)
    path = (
        component
        if target == "component"
        else component / "adapter" / "pytorch_lora_weights.safetensors"
    )
    path.chmod(path.stat().st_mode | 0o020)
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="trusted"):
            verify_preview_adapter(
                root_fd, _descriptor(manifest), manifest, _approval(manifest)
            )
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("mismatch", ("root", "file", "revision", "approval"))
def test_verification_rejects_every_descriptor_manifest_approval_mismatch(
    tmp_path: Path, mismatch: str
) -> None:
    from dataclasses import replace

    from specstyle.generation.preview_adapter_supply import verify_preview_adapter

    manifest = _manifest()
    _write_component(tmp_path, manifest)
    descriptor = _descriptor(manifest)
    approval = _approval(manifest)
    if mismatch == "root":
        descriptor = replace(descriptor, expected_sha256=Sha256("f" * 64))
    elif mismatch == "file":
        target = tmp_path / manifest.relative_root / manifest.files[0].relative_path
        target.write_bytes(b"changed")
    elif mismatch == "revision":
        descriptor = replace(descriptor, revision="b" * 40)
    else:
        approval = replace(approval, license_spdx="MIT")
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises((DomainError, InfrastructureError)):
            verify_preview_adapter(root_fd, descriptor, manifest, approval)
    finally:
        os.close(root_fd)
