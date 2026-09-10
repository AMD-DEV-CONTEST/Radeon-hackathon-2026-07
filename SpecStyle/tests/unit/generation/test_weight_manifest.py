"""MODEL-SUPPLY-001 weight manifest contract."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

import specstyle.generation.weight_manifest as weight_manifest_module
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.weight_manifest import (
    ModelLoadEntrypoint,
    WeightFile,
    WeightManifest,
    manifest_sha256,
    verify_weight_manifest,
)


REVISION = "a" * 40


def _sha(data: bytes) -> Sha256:
    return Sha256(hashlib.sha256(data).hexdigest())


def _manifest(*, entrypoint: ModelLoadEntrypoint | None = None) -> WeightManifest:
    config = b'{"architectures": ["Test"]}'
    weights = b"safe-tensors"
    return WeightManifest(
        model_id="base-model",
        role="base",
        revision=REVISION,
        relative_root="base-model",
        entrypoint=entrypoint
        or ModelLoadEntrypoint("diffusers_pretrained", "pipeline"),
        files=(
            WeightFile("pipeline/config.json", len(config), _sha(config)),
            WeightFile("pipeline/model.safetensors", len(weights), _sha(weights)),
        ),
        root_sha256=Sha256("0" * 64),
    ).with_computed_root()


def _write_manifest_files(root: Path, manifest: WeightManifest) -> None:
    payloads = {
        "pipeline/config.json": b'{"architectures": ["Test"]}',
        "pipeline/model.safetensors": b"safe-tensors",
    }
    for relpath, payload in payloads.items():
        path = root / manifest.relative_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _open_root(root: Path) -> int:
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY)


def test_manifest_digest_is_sorted_and_binds_entrypoint() -> None:
    manifest = _manifest()
    reordered = WeightManifest(
        manifest.model_id,
        manifest.role,
        manifest.revision,
        manifest.relative_root,
        manifest.entrypoint,
        tuple(reversed(manifest.files)),
        manifest.root_sha256,
    ).with_computed_root()
    changed_entrypoint = _manifest(
        entrypoint=ModelLoadEntrypoint(
            "diffusers_pretrained", "pipeline", variant="fp16"
        )
    )

    assert manifest_sha256(manifest) == manifest_sha256(reordered)
    assert manifest.root_sha256 == reordered.root_sha256
    assert manifest_sha256(manifest) != manifest_sha256(changed_entrypoint)


@pytest.mark.parametrize(
    "revision", ["main", "A" * 40, "a" * 39, "rev-placeholder-001"]
)
def test_manifest_rejects_non_full_lowercase_commit_revision(revision: str) -> None:
    with pytest.raises(DomainError, match="revision"):
        WeightManifest(
            "base-model",
            "base",
            revision,
            "base-model",
            ModelLoadEntrypoint("diffusers_pretrained", "pipeline"),
            (WeightFile("pipeline/model.safetensors", 1, _sha(b"x")),),
            Sha256("0" * 64),
        )


def test_manifest_accepts_64_character_commit_revision() -> None:
    manifest = WeightManifest(
        "base-model",
        "base",
        "c" * 64,
        "base-model",
        ModelLoadEntrypoint("diffusers_pretrained", "pipeline"),
        (WeightFile("pipeline/model.safetensors", 1, _sha(b"x")),),
        Sha256("0" * 64),
    )

    assert manifest.revision == "c" * 64


def test_ip_adapter_entrypoint_requires_explicit_safetensors_weight() -> None:
    with pytest.raises(DomainError, match="requires weight"):
        ModelLoadEntrypoint("diffusers_ip_adapter", "adapter")


@pytest.mark.parametrize(
    ("role", "entrypoint"),
    [
        (
            "base",
            ModelLoadEntrypoint(
                "diffusers_ip_adapter", "pipeline", "pipeline/model.safetensors"
            ),
        ),
        (
            "controlnet",
            ModelLoadEntrypoint(
                "diffusers_ip_adapter", "pipeline", "pipeline/model.safetensors"
            ),
        ),
        ("ip_adapter", ModelLoadEntrypoint("diffusers_pretrained", "pipeline")),
    ],
)
def test_manifest_binds_role_to_required_diffusers_entrypoint(
    role: str, entrypoint: ModelLoadEntrypoint
) -> None:
    with pytest.raises(DomainError, match="entrypoint"):
        WeightManifest(
            "model",
            role,
            REVISION,
            "component",
            entrypoint,
            (WeightFile("pipeline/model.safetensors", 1, _sha(b"x")),),
            Sha256("0" * 64),
        )


def test_manifest_requires_role_weight_and_ip_weight_name_to_reference_safetensors() -> (
    None
):
    with pytest.raises(DomainError, match="safetensors"):
        WeightManifest(
            "ip",
            "ip_adapter",
            REVISION,
            "component",
            ModelLoadEntrypoint("diffusers_ip_adapter", "pipeline", "model.json"),
            (WeightFile("pipeline/model.json", 2, _sha(b"{}")),),
            Sha256("0" * 64),
        )


def test_pretrained_entrypoint_subtree_must_contain_safetensors() -> None:
    with pytest.raises(DomainError, match="entrypoint.*safetensors"):
        WeightManifest(
            "base-model",
            "base",
            REVISION,
            "component",
            ModelLoadEntrypoint("diffusers_pretrained", "pipeline"),
            (
                WeightFile("pipeline/config.json", 2, _sha(b"{}")),
                WeightFile("other/model.safetensors", 1, _sha(b"x")),
            ),
            Sha256("0" * 64),
        )


def test_image_encoder_subtree_must_contain_safetensors() -> None:
    with pytest.raises(DomainError, match="image encoder.*safetensors"):
        WeightManifest(
            "ip-model",
            "ip_adapter",
            REVISION,
            "component",
            ModelLoadEntrypoint(
                "diffusers_ip_adapter",
                "adapter",
                "model.safetensors",
                "image_encoder",
            ),
            (
                WeightFile("adapter/model.safetensors", 1, _sha(b"x")),
                WeightFile("image_encoder/config.json", 2, _sha(b"{}")),
            ),
            Sha256("0" * 64),
        )


def test_ip_adapter_weight_name_is_resolved_below_subfolder() -> None:
    manifest = WeightManifest(
        "ip-model",
        "ip_adapter",
        REVISION,
        "component",
        ModelLoadEntrypoint("diffusers_ip_adapter", "adapter", "model.safetensors"),
        (
            WeightFile("adapter/model.safetensors", 1, _sha(b"x")),
            WeightFile("adapter/image_encoder/config.json", 2, _sha(b"{}")),
            WeightFile("adapter/image_encoder/model.safetensors", 1, _sha(b"e")),
        ),
        Sha256("0" * 64),
    )

    assert manifest.entrypoint.weight_name == "model.safetensors"


@pytest.mark.parametrize(
    ("entrypoint", "expected"),
    [
        (
            ModelLoadEntrypoint("diffusers_ip_adapter", "adapter", "model.safetensors"),
            "adapter/image_encoder",
        ),
        (
            ModelLoadEntrypoint(
                "diffusers_ip_adapter", "adapter", "model.safetensors", "vision"
            ),
            "adapter/vision",
        ),
        (
            ModelLoadEntrypoint(
                "diffusers_ip_adapter",
                "adapter",
                "model.safetensors",
                "shared/vision",
            ),
            "shared/vision",
        ),
    ],
)
def test_effective_image_encoder_subfolder_follows_diffusers_resolution(
    entrypoint: ModelLoadEntrypoint, expected: str
) -> None:
    resolver = getattr(
        weight_manifest_module, "effective_image_encoder_subfolder", None
    )

    assert callable(resolver)
    assert resolver(entrypoint) == expected


def _ip_manifest(
    entrypoint: ModelLoadEntrypoint, relative_paths: tuple[str, ...]
) -> WeightManifest:
    return WeightManifest(
        "ip-model",
        "ip_adapter",
        REVISION,
        "component",
        entrypoint,
        tuple(
            WeightFile(path, len(path.encode()), _sha(path.encode()))
            for path in relative_paths
        ),
        Sha256("0" * 64),
    )


@pytest.mark.parametrize(
    ("entrypoint", "encoder_root"),
    [
        (
            ModelLoadEntrypoint("diffusers_ip_adapter", "adapter", "model.safetensors"),
            "adapter/image_encoder",
        ),
        (
            ModelLoadEntrypoint(
                "diffusers_ip_adapter", "adapter", "model.safetensors", "vision"
            ),
            "adapter/vision",
        ),
        (
            ModelLoadEntrypoint(
                "diffusers_ip_adapter",
                "adapter",
                "model.safetensors",
                "shared/vision",
            ),
            "shared/vision",
        ),
    ],
)
def test_ip_manifest_accepts_exact_image_encoder_files_and_listed_extras(
    entrypoint: ModelLoadEntrypoint, encoder_root: str
) -> None:
    manifest = _ip_manifest(
        entrypoint,
        (
            "adapter/model.safetensors",
            f"{encoder_root}/config.json",
            f"{encoder_root}/model.safetensors",
            f"{encoder_root}/preprocessor_config.json",
            "adapter/extra.safetensors",
        ),
    )

    assert manifest.entrypoint == entrypoint


@pytest.mark.parametrize(
    ("image_encoder_folder", "encoder_files"),
    [
        (None, ("adapter/image_encoder/model.safetensors",)),
        (None, ("adapter/image_encoder/config.json",)),
        (
            None,
            (
                "wrong/image_encoder/config.json",
                "wrong/image_encoder/model.safetensors",
            ),
        ),
        ("vision", ("adapter/vision/model.safetensors",)),
        (
            "shared/vision",
            (
                "shared/vision/config.json",
                "shared/vision/other.safetensors",
            ),
        ),
        ("shared/vision", ("shared/vision/model.safetensors",)),
    ],
)
def test_ip_manifest_requires_exact_image_encoder_config_and_weight(
    image_encoder_folder: str | None, encoder_files: tuple[str, ...]
) -> None:
    entrypoint = ModelLoadEntrypoint(
        "diffusers_ip_adapter",
        "adapter",
        "model.safetensors",
        image_encoder_folder,
    )

    with pytest.raises(DomainError, match="image encoder"):
        _ip_manifest(entrypoint, ("adapter/model.safetensors", *encoder_files))


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        "/outside",
        "base//x",
        "base/./x",
        "base/../x",
        "base/\x00x",
        "base/\x1fx",
        "base/" + "x" * 256,
        "x" * 4097,
    ],
)
def test_weight_file_rejects_escape_paths(bad_path: str) -> None:
    with pytest.raises(DomainError, match="path"):
        WeightFile(bad_path, 1, _sha(b"x"))


def test_verify_weight_manifest_checks_actual_files_and_closes_only_internal_fds(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    root_fd = _open_root(tmp_path)
    try:
        verified = verify_weight_manifest(root_fd, manifest)
        assert verified.manifest == manifest
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("mode", ["extra", "missing", "size", "hash", "pickle"])
def test_verify_weight_manifest_rejects_unmanifested_or_tampered_files(
    tmp_path: Path, mode: str
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    if mode == "extra":
        (tmp_path / "base-model" / "pipeline" / "extra.json").write_text(
            "{}", encoding="utf-8"
        )
    elif mode == "missing":
        (tmp_path / "base-model" / "pipeline" / "config.json").unlink()
    elif mode == "size":
        (tmp_path / "base-model" / "pipeline" / "model.safetensors").write_bytes(b"s")
    elif mode == "hash":
        (tmp_path / "base-model" / "pipeline" / "model.safetensors").write_bytes(
            b"wrong-bytes"
        )
    else:
        (tmp_path / "base-model" / "pipeline" / "model.safetensors").unlink()
        (tmp_path / "base-model" / "pipeline" / "model.bin").write_bytes(b"pickle")
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError):
            verify_weight_manifest(root_fd, manifest)
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("target", ["intermediate", "final"])
def test_verify_weight_manifest_rejects_symlinks(tmp_path: Path, target: str) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    if target == "intermediate":
        outside = tmp_path.parent / "outside-base-model"
        outside.mkdir(exist_ok=True)
        (tmp_path / "base-model").rename(outside / "base-model")
        (tmp_path / "base-model").symlink_to(
            outside / "base-model", target_is_directory=True
        )
    else:
        real = tmp_path / "base-model" / "pipeline" / "real.safetensors"
        (tmp_path / "base-model" / "pipeline" / "model.safetensors").rename(real)
        (tmp_path / "base-model" / "pipeline" / "model.safetensors").symlink_to(real)
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="path"):
            verify_weight_manifest(root_fd, manifest)
    finally:
        os.close(root_fd)


def test_verify_weight_manifest_rejects_non_regular_file_and_writable_root(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    (tmp_path / "base-model" / "pipeline" / "model.safetensors").unlink()
    os.mkfifo(tmp_path / "base-model" / "pipeline" / "model.safetensors")
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="regular"):
            verify_weight_manifest(root_fd, manifest)
    finally:
        os.close(root_fd)


@pytest.mark.parametrize(
    "node",
    ["base-model", "base-model/pipeline", "base-model/pipeline/model.safetensors"],
)
def test_verify_weight_manifest_rejects_writable_nested_component_nodes(
    tmp_path: Path, node: str
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    (tmp_path / node).chmod(stat.S_IRWXU | stat.S_IWGRP)
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="trusted"):
            verify_weight_manifest(root_fd, manifest)
    finally:
        os.close(root_fd)


def test_verify_weight_manifest_rejects_writable_root(tmp_path: Path) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    tmp_path.chmod(stat.S_IRWXU | stat.S_IWGRP)
    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="trusted"):
            verify_weight_manifest(root_fd, manifest)
    finally:
        os.close(root_fd)


def test_verify_weight_manifest_normalizes_dup_failure_and_keeps_root_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    root_fd = _open_root(tmp_path)

    def fail_dup(_fd: int) -> int:
        raise OSError("forced dup failure")

    monkeypatch.setattr(os, "dup", fail_dup)
    try:
        with pytest.raises(InfrastructureError, match="path"):
            verify_weight_manifest(root_fd, manifest)
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


def test_verify_weight_manifest_closes_internal_fds_after_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    root_fd = _open_root(tmp_path)
    opened: list[int] = []
    real_open = os.open
    real_dup = os.dup

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(fd)
        return fd

    def tracked_dup(fd: int) -> int:
        duplicate = real_dup(fd)
        opened.append(duplicate)
        return duplicate

    def fail_read(_fd: int, _size: int) -> bytes:
        raise OSError("forced read failure")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "dup", tracked_dup)
    monkeypatch.setattr(os, "read", fail_read)
    try:
        with pytest.raises(InfrastructureError, match="path"):
            verify_weight_manifest(root_fd, manifest)
        for fd in set(opened):
            with pytest.raises(OSError):
                os.fstat(fd)
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("operation", ["open", "list", "fstat"])
def test_verify_weight_manifest_normalizes_io_faults_and_closes_internal_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    manifest = _manifest()
    _write_manifest_files(tmp_path, manifest)
    root_fd = _open_root(tmp_path)
    opened: list[int] = []
    real_open = os.open
    real_fstat = os.fstat

    if operation == "open":

        def fail_open(*_args: object, **_kwargs: object) -> int:
            raise OSError("forced open failure")

        monkeypatch.setattr(os, "open", fail_open)
    elif operation == "list":

        def fail_list(_fd: int) -> list[str]:
            raise OSError("forced list failure")

        monkeypatch.setattr(os, "listdir", fail_list)
    else:

        def tracked_open(*args: object, **kwargs: object) -> int:
            fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
            opened.append(fd)
            return fd

        def fail_component_fstat(fd: int) -> os.stat_result:
            if fd != root_fd:
                raise OSError("forced fstat failure")
            return real_fstat(fd)

        monkeypatch.setattr(os, "open", tracked_open)
        monkeypatch.setattr(os, "fstat", fail_component_fstat)

    try:
        with pytest.raises(InfrastructureError):
            verify_weight_manifest(root_fd, manifest)
        for fd in set(opened):
            with pytest.raises(OSError):
                real_fstat(fd)
        assert real_fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)
