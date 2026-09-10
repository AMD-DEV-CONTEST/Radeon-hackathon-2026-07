from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from specstyle.errors import InfrastructureError


def _paths(tmp_path: Path):
    from specstyle.ui.preview_ui_inputs import PreviewUiRuntimePaths

    roots = []
    for name in (
        "production-config",
        "production-evidence",
        "preview-config",
        "models",
        "preview-evidence",
        "display",
        "styles",
        "staging",
    ):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        roots.append(path)
    return PreviewUiRuntimePaths(*roots)


def _upload(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _spec() -> bytes:
    from tests.unit.spec.test_compiler import raw_spec

    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["profiles"]["preview"].update(pipeline="lcm", steps=4, guidance_scale=0.0)
    return json.dumps(data, separators=(",", ":")).encode()


def test_preview_staging_emits_independent_private_metadata_and_descriptors(
    tmp_path: Path,
) -> None:
    from specstyle.ui.preview_ui_inputs import (
        OpenPreviewUiFds,
        cleanup_preview_staging,
        stage_preview_inputs,
    )

    paths = _paths(tmp_path)
    source = _upload(tmp_path / "source.png", b"source")
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())
    staged = stage_preview_inputs(paths, source, style, spec, "positive", "negative")
    try:
        metadata = json.loads(staged.metadata.read_text(encoding="utf-8"))
        assert metadata["schema_version"] == "specstyle.preview.job_input.v1"
        assert set(metadata) == {"schema_version", "source", "style", "prompt"}
        assert "credit" not in repr(metadata)
        assert metadata["prompt"]["preset_id"] == "preset"
        for path in (staged.source, staged.style, staged.spec, staged.metadata):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with OpenPreviewUiFds(paths, staged) as fds:
            values = tuple(getattr(fds, field) for field in fds.__slots__)
            assert len(values) == 11
            assert all(os.fstat(fd).st_ino > 0 for fd in values)
    finally:
        directory = staged.directory
        cleanup_preview_staging(staged)
    assert not directory.exists()


def test_preview_staging_rejects_symlink_uploads(tmp_path: Path) -> None:
    from specstyle.ui.preview_ui_inputs import PreviewUiInputError, stage_preview_inputs

    paths = _paths(tmp_path)
    target = _upload(tmp_path / "target.png", b"source")
    source = tmp_path / "source-link.png"
    source.symlink_to(target)
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())

    with pytest.raises(PreviewUiInputError, match="source upload required"):
        stage_preview_inputs(paths, source, style, spec, "positive", "negative")
    assert list(paths.staging_root.iterdir()) == []


def test_preview_runtime_paths_reject_directory_symlink(tmp_path: Path) -> None:
    from specstyle.errors import DomainError
    from specstyle.ui.preview_ui_inputs import PreviewUiRuntimePaths

    paths = _paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    values = [
        paths.production_config_root,
        paths.production_context_evidence_root,
        paths.preview_config_root,
        paths.model_root,
        paths.evidence_root,
        paths.display_root,
        paths.style_asset_root,
        paths.staging_root,
    ]
    values[2] = linked

    with pytest.raises(DomainError, match="preview_config_root unavailable"):
        PreviewUiRuntimePaths(*values)


def test_open_preview_fds_rejects_root_replaced_by_symlink(tmp_path: Path) -> None:
    from specstyle.ui.preview_ui_inputs import OpenPreviewUiFds, stage_preview_inputs

    paths = _paths(tmp_path)
    source = _upload(tmp_path / "source.png", b"source")
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())
    staged = stage_preview_inputs(paths, source, style, spec, "positive", "negative")
    original = paths.preview_config_root
    moved = tmp_path / "preview-config-moved"
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=True)
    try:
        with pytest.raises(OSError):
            with OpenPreviewUiFds(paths, staged):
                pytest.fail("replaced root must not open")
    finally:
        original.unlink()
        from specstyle.ui.preview_ui_inputs import cleanup_preview_staging

        cleanup_preview_staging(staged)


def test_open_preview_fds_rejects_root_replaced_by_directory(tmp_path: Path) -> None:
    from specstyle.ui.preview_ui_inputs import (
        OpenPreviewUiFds,
        cleanup_preview_staging,
        stage_preview_inputs,
    )

    paths = _paths(tmp_path)
    source = _upload(tmp_path / "source.png", b"source")
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())
    staged = stage_preview_inputs(paths, source, style, spec, "positive", "negative")
    original = paths.preview_config_root
    moved = tmp_path / "preview-config-original"
    original.rename(moved)
    original.mkdir(mode=0o700)
    try:
        with pytest.raises(InfrastructureError, match="identity"):
            with OpenPreviewUiFds(paths, staged):
                pytest.fail("replaced root must not open")
    finally:
        cleanup_preview_staging(staged)


def test_preview_staging_cleanup_reports_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_ui_inputs as module

    paths = _paths(tmp_path)
    source = _upload(tmp_path / "source.png", b"source")
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())
    staged = module.stage_preview_inputs(
        paths, source, style, spec, "positive", "negative"
    )
    monkeypatch.setattr(
        module.os,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected")),
    )

    with pytest.raises(InfrastructureError, match="cleanup failed"):
        module.cleanup_preview_staging(staged)


@pytest.mark.parametrize("replacement", ("symlink", "directory"))
def test_stage_rejects_replaced_staging_root(tmp_path: Path, replacement: str) -> None:
    from specstyle.ui.preview_ui_inputs import stage_preview_inputs

    paths = _paths(tmp_path)
    source = _upload(tmp_path / "source.png", b"source")
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())
    original = paths.staging_root
    moved = tmp_path / "staging-original"
    original.rename(moved)
    if replacement == "symlink":
        original.symlink_to(moved, target_is_directory=True)
        expected = OSError
    else:
        original.mkdir(mode=0o700)
        expected = InfrastructureError

    with pytest.raises(expected):
        stage_preview_inputs(paths, source, style, spec, "positive", "negative")
    assert list(moved.iterdir()) == []


def test_staged_capability_cleans_original_root_after_path_replacement(
    tmp_path: Path,
) -> None:
    from specstyle.ui.preview_ui_inputs import (
        cleanup_preview_staging,
        stage_preview_inputs,
    )

    paths = _paths(tmp_path)
    source = _upload(tmp_path / "source.png", b"source")
    style = _upload(tmp_path / "style.png", b"style")
    spec = _upload(tmp_path / "spec.json", _spec())
    staged = stage_preview_inputs(paths, source, style, spec, "positive", "negative")
    original = paths.staging_root
    moved = tmp_path / "staging-held-by-fd"
    original.rename(moved)
    original.mkdir(mode=0o700)

    cleanup_preview_staging(staged)

    assert list(moved.iterdir()) == []
    assert list(original.iterdir()) == []
