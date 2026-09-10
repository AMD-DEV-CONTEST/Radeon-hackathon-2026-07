from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow.preview_evidence import PreviewEvidencePublication


def _publication(run_id: str, variation_index: int, digest: str):
    return PreviewEvidencePublication(
        run_id,
        f"{run_id}-{digest[:16]}.png",
        ArtifactId(f"preview-{'a' * 64}"),
        Sha256(digest),
        Sha256("f" * 64),
        Sha256(f"{variation_index + 1:064x}"),
        "specstyle.preview.evidence.v3",
        variation_index,
        "specstyle.seed.v1",
        100 + variation_index,
        (512, 512),
        "ENGINEERING_ONLY",
        "float16",
        "float16",
        "float32",
        "diffusers_force_upcast_roundtrip_v1",
    )


def _items(wall_id: str, digests: tuple[str, ...]):
    from specstyle.workflow.preview_wall_evidence import PreviewWallEvidenceItem

    return tuple(
        PreviewWallEvidenceItem(
            index,
            True,
            f"{wall_id}-v{index}",
            "COMPLETED",
            "OK",
            _publication(f"{wall_id}-v{index}", index, digest),
        )
        for index, digest in enumerate(digests)
    )


def _root(tmp_path: Path) -> tuple[int, Path]:
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY), root


def test_wall_manifest_allows_duplicate_hash_as_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall_evidence as module

    monkeypatch.setattr(module, "_verify_stored_publication", lambda *_args: None)

    wall_id = "preview-wall-" + "1" * 32
    root_fd, root = _root(tmp_path)
    try:
        publication = module.publish_preview_wall_evidence(
            root_fd,
            wall_id,
            _items(wall_id, ("a" * 64, "a" * 64)),
            1.25,
            "COMPLETED",
        )
    finally:
        os.close(root_fd)
    manifest = json.loads(
        (root / publication.evidence_name / "manifest.json").read_text()
    )
    assert manifest["status"] == "COMPLETED"
    assert manifest["metrics"]["unique_content_hash_count"] == 1
    assert manifest["metrics"]["duplicate_count"] == 1
    assert manifest["diversity"] == "NOT_EVALUATED"


def test_wall_manifest_is_no_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall_evidence as module

    monkeypatch.setattr(module, "_verify_stored_publication", lambda *_args: None)

    wall_id = "preview-wall-" + "2" * 32
    root_fd, _root_path = _root(tmp_path)
    try:
        items = _items(wall_id, ("b" * 64,))
        module.publish_preview_wall_evidence(root_fd, wall_id, items, 1.0, "COMPLETED")
        with pytest.raises(DomainError, match="already exists"):
            module.publish_preview_wall_evidence(
                root_fd, wall_id, items, 1.0, "COMPLETED"
            )
    finally:
        os.close(root_fd)


def test_wall_manifest_rename_failure_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall_evidence as module
    from specstyle.workflow._job_store_fs import StoreIO

    wall_id = "preview-wall-" + "3" * 32
    root_fd, root = _root(tmp_path)
    monkeypatch.setattr(
        module,
        "rename_noreplace",
        lambda *_args: (_ for _ in ()).throw(StoreIO()),
    )
    monkeypatch.setattr(module, "_verify_stored_publication", lambda *_args: None)
    try:
        with pytest.raises(InfrastructureError, match="unavailable"):
            module.publish_preview_wall_evidence(
                root_fd,
                wall_id,
                _items(wall_id, ("c" * 64,)),
                1.0,
                "COMPLETED",
            )
    finally:
        os.close(root_fd)
    assert list(root.iterdir()) == []


def test_wall_rejects_publication_for_different_variation() -> None:
    from specstyle.workflow.preview_wall_evidence import PreviewWallEvidenceItem

    wall_id = "preview-wall-" + "4" * 32
    with pytest.raises(DomainError, match="variation"):
        PreviewWallEvidenceItem(
            1,
            True,
            f"{wall_id}-v1",
            "COMPLETED",
            "OK",
            _publication(f"{wall_id}-v1", 0, "d" * 64),
        )


def test_wall_rejects_publication_without_private_v3_evidence(tmp_path: Path) -> None:
    from specstyle.workflow.preview_wall_evidence import publish_preview_wall_evidence

    wall_id = "preview-wall-" + "5" * 32
    root_fd, _root_path = _root(tmp_path)
    try:
        with pytest.raises((DomainError, InfrastructureError)):
            publish_preview_wall_evidence(
                root_fd,
                wall_id,
                _items(wall_id, ("e" * 64,)),
                1.0,
                "COMPLETED",
            )
    finally:
        os.close(root_fd)


def test_wall_accepts_publication_backed_by_private_v3_evidence(tmp_path: Path) -> None:
    from specstyle.workflow.preview_evidence import publish_preview_evidence
    from specstyle.workflow.preview_wall_evidence import (
        PreviewWallEvidenceItem,
        publish_preview_wall_evidence,
    )
    from tests.unit.workflow.test_preview_evidence import _artifact

    wall_id = "preview-wall-" + "6" * 32
    run_id = f"{wall_id}-v0"
    root_fd, _root_path = _root(tmp_path)
    display = tmp_path / "display"
    display.mkdir(mode=0o700)
    display_fd = os.open(display, os.O_RDONLY | os.O_DIRECTORY)
    try:
        item_publication = publish_preview_evidence(
            root_fd, display_fd, run_id, _artifact(tmp_path / "item", run_id)
        )
        publication = publish_preview_wall_evidence(
            root_fd,
            wall_id,
            (
                PreviewWallEvidenceItem(
                    0, True, run_id, "COMPLETED", "OK", item_publication
                ),
            ),
            1.0,
            "COMPLETED",
        )
    finally:
        os.close(display_fd)
        os.close(root_fd)
    assert publication.evidence_name == wall_id
    manifest = json.loads(
        (_root_path / publication.evidence_name / "manifest.json").read_text()
    )
    assert manifest["schema_version"] == "specstyle.preview.wall-evidence.v2"
    assert manifest["items"][0]["artifact"]["evidence_schema_version"] == (
        "specstyle.preview.evidence.v3"
    )
    assert manifest["items"][0]["artifact"]["runtime_dtype"] == "float16"
    assert manifest["items"][0]["artifact"]["vae_at_rest_dtype"] == "float16"
    assert manifest["items"][0]["artifact"]["vae_compute_dtype"] == "float32"
    assert manifest["items"][0]["artifact"]["vae_precision_policy"] == (
        "diffusers_force_upcast_roundtrip_v1"
    )
