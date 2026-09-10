from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import InfrastructureError
from specstyle.ui.app import UiServices
from specstyle.ui.view_models import SpecEditorView
from specstyle.workflow.preview_evidence import PreviewEvidencePublication
from specstyle.workflow.preview_run_one import PreviewRunOneResult, PreviewRunStatus
from specstyle.workflow.preview_wall import (
    PreviewWallItemResult,
    PreviewWallResult,
    PreviewWallStatus,
)
from specstyle.workflow.preview_wall_evidence import PreviewWallEvidencePublication
from tests.unit.ui.test_preview_run import _Open, _install_stage, _paths, _stage


def _base() -> UiServices:
    return UiServices(lambda _text: SpecEditorView("1.0", "spec", True, (), "a" * 64))


def _publication(run_id: str, variation_index: int, content: bytes):
    digest = hashlib.sha256(content).hexdigest()
    return PreviewEvidencePublication(
        run_id,
        f"{run_id}-{digest[:16]}.png",
        ArtifactId(f"preview-{'b' * 64}"),
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


def test_preview_wall_ui_stages_once_and_projects_engineering_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_wall as module

    paths = _paths(tmp_path)
    wall_id = "preview-wall-" + "1" * 32
    items = []
    for index in range(2):
        run_id = f"{wall_id}-v{index}"
        publication = _publication(run_id, index, f"image-{index}".encode())
        display = paths.display_root / publication.display_name
        display.write_bytes(f"image-{index}".encode())
        display.chmod(0o600)
        items.append(
            PreviewWallItemResult(
                index,
                True,
                PreviewRunOneResult(
                    run_id, PreviewRunStatus.COMPLETED, "OK", publication
                ),
            )
        )
    result = PreviewWallResult(
        wall_id,
        PreviewWallStatus.COMPLETED,
        "OK",
        tuple(items),
        3.5,
        PreviewWallEvidencePublication(wall_id, Sha256("d" * 64)),
    )
    staged = _stage(paths.staging_root / "wall")
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    reservations: list[int] = []
    services = module.bind_preview_wall_services(
        _base(),
        paths,
        reserve=lambda count: reservations.append(count) or SimpleNamespace(),
        run_wall=lambda _fds, _reservation: result,
    )

    view = services.run_preview_wall("source", "style", "spec", "pos", "neg", 2)

    assert reservations == [2]
    assert view.wall_id == wall_id
    assert view.status == "COMPLETED"
    assert view.evidence_class == "ENGINEERING_ONLY"
    assert len(view.display_images) == 2
    assert "quality\tNOT_EVALUATED" in view.evidence_tsv
    assert "diversity\tNOT_EVALUATED" in view.evidence_tsv
    assert "variation_index\tattempted\tstatus" in view.evidence_tsv
    assert (view.verification, view.repair, view.export) == (
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    )
    assert not staged.directory.exists()


def _busy_result(wall_id: str) -> PreviewWallResult:
    item = PreviewWallItemResult(
        0,
        False,
        PreviewRunOneResult(f"{wall_id}-v0", PreviewRunStatus.BUSY, "GPU_BUSY", None),
    )
    return PreviewWallResult(
        wall_id,
        PreviewWallStatus.BUSY,
        "GPU_BUSY",
        (item,),
        0.1,
        PreviewWallEvidencePublication(wall_id, Sha256("e" * 64)),
    )


def test_preview_wall_ui_keeps_busy_item_without_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_wall as module

    paths = _paths(tmp_path)
    staged = _stage(paths.staging_root / "busy")
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    wall_id = "preview-wall-" + "2" * 32
    services = module.bind_preview_wall_services(
        _base(),
        paths,
        reserve=lambda _count: object(),
        run_wall=lambda *_args: _busy_result(wall_id),
    )

    view = services.run_preview_wall("source", "style", "spec", "p", "n", 1)

    assert view.status == "BUSY"
    assert view.display_images == ()
    assert view.items[0].seed is None
    assert "false\tBUSY\tGPU_BUSY" in view.evidence_tsv


@pytest.mark.parametrize(
    ("error", "status", "message"),
    (
        ("input", "FAILED", "INPUT_INVALID"),
        ("cleanup", "FAILED", "STAGING_CLEANUP_FAILED"),
        ("domain", "FAILED", "PREVIEW_WALL_REJECTED"),
        ("infra", "UNAVAILABLE", "PREVIEW_UNAVAILABLE"),
        ("unexpected", "FAILED", "INTERNAL_ERROR"),
    ),
)
def test_preview_wall_ui_maps_staging_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: str,
    status: str,
    message: str,
) -> None:
    import specstyle.ui.preview_wall as module
    from specstyle.errors import DomainError, InfrastructureError
    from specstyle.ui.preview_ui_inputs import (
        PreviewUiCleanupError,
        PreviewUiInputError,
    )

    paths = _paths(tmp_path)
    errors = {
        "input": PreviewUiInputError("bad input"),
        "cleanup": PreviewUiCleanupError("bad cleanup"),
        "domain": DomainError("bad domain"),
        "infra": InfrastructureError("bad infra"),
        "unexpected": RuntimeError("bad runtime"),
    }
    monkeypatch.setattr(
        module,
        "stage_preview_inputs",
        lambda *_args: (_ for _ in ()).throw(errors[error]),
    )
    services = module.bind_preview_wall_services(_base(), paths)

    view = services.run_preview_wall("source", "style", "spec", "p", "n", 1)

    assert view.status == status
    assert view.message == message


def test_preview_wall_ui_reports_cleanup_failure_after_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_wall as module

    paths = _paths(tmp_path)
    staged = _stage(paths.staging_root / "cleanup")
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    monkeypatch.setattr(
        module,
        "cleanup_preview_staging",
        lambda _staged: (_ for _ in ()).throw(InfrastructureError("cleanup")),
    )
    wall_id = "preview-wall-" + "3" * 32
    services = module.bind_preview_wall_services(
        _base(),
        paths,
        reserve=lambda _count: object(),
        run_wall=lambda *_args: _busy_result(wall_id),
    )

    view = services.run_preview_wall("source", "style", "spec", "p", "n", 1)

    assert view.status == "FAILED"
    assert view.message == "STAGING_CLEANUP_FAILED"


def test_unavailable_preview_wall_binding() -> None:
    from specstyle.ui.preview_wall import bind_unavailable_preview_wall_services

    services = bind_unavailable_preview_wall_services(_base(), "PREVIEW_UNAVAILABLE")
    view = services.run_preview_wall(None, None, None, "", "", 4)
    assert view.status == "UNAVAILABLE"
    assert view.message == "PREVIEW_UNAVAILABLE"


@pytest.mark.parametrize("count", (0, 5, 2.5, True))
def test_preview_wall_ui_rejects_invalid_count_without_staging(
    tmp_path: Path, count: object
) -> None:
    from specstyle.ui.preview_wall import bind_preview_wall_services

    services = bind_preview_wall_services(_base(), _paths(tmp_path))
    view = services.run_preview_wall("source", "style", "spec", "p", "n", count)
    assert view.status == "FAILED"
    assert view.message == "INVALID_WALL_COUNT"
    assert view.display_images == ()
