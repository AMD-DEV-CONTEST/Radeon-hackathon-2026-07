from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import InfrastructureError
from specstyle.ui.app import UiServices
from specstyle.ui.view_models import SpecEditorView
from specstyle.workflow.preview_evidence import PreviewEvidencePublication
from specstyle.workflow.preview_run_one import PreviewRunOneResult, PreviewRunStatus


def _base() -> UiServices:
    return UiServices(lambda _text: SpecEditorView("1.0", "spec", True, (), "a" * 64))


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


def _publication(
    run_id: str, content: bytes = b"png", *, display_digest: str | None = None
) -> PreviewEvidencePublication:
    digest = hashlib.sha256(content).hexdigest()
    return PreviewEvidencePublication(
        run_id,
        f"{run_id}-{display_digest or digest[:16]}.png",
        ArtifactId(f"preview-{'b' * 64}"),
        Sha256(digest),
        Sha256("d" * 64),
        Sha256("c" * 64),
        "specstyle.preview.evidence.v3",
        0,
        "specstyle.seed.v1",
        1,
        (512, 512),
        "ENGINEERING_ONLY",
        "float16",
        "float16",
        "float32",
        "diffusers_force_upcast_roundtrip_v1",
    )


class _Open:
    def __init__(self, _paths: object, _staged: object) -> None:
        pass

    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        pass


def _stage(directory: Path) -> SimpleNamespace:
    directory.mkdir(mode=0o700)
    return SimpleNamespace(directory=directory)


def _install_stage(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
    staged: SimpleNamespace,
) -> None:
    monkeypatch.setattr(module, "stage_preview_inputs", lambda *_args: staged)
    monkeypatch.setattr(
        module,
        "cleanup_preview_staging",
        lambda candidate: shutil.rmtree(candidate.directory),
    )


def test_preview_binding_projects_only_completed_display_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)
    run_id = "preview-run-ui"
    publication = _publication(run_id)
    display = paths.display_root / publication.display_name
    display.write_bytes(b"png")
    display.chmod(0o600)
    staged = _stage(paths.staging_root / "one")
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    services = module.bind_preview_run_one_services(
        _base(),
        paths,
        reserve=lambda: SimpleNamespace(run_id=run_id),
        run_one=lambda _fds, _reservation: PreviewRunOneResult(
            run_id, PreviewRunStatus.COMPLETED, "OK", publication
        ),
    )

    view = services.run_preview_job("source", "style", "spec", "pos", "neg")

    assert view.status == "COMPLETED"
    assert view.profile_label == "preview"
    assert view.display_images == (str(display),)
    assert view.execution_fingerprint == "c" * 64
    assert (view.verification, view.repair, view.export) == (
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    )
    assert not staged.directory.exists()


@pytest.mark.parametrize(
    ("status", "reason"),
    (
        (PreviewRunStatus.BUSY, "GPU_BUSY"),
        (PreviewRunStatus.UNAVAILABLE, "PREVIEW_CONFIG_INVALID"),
        (PreviewRunStatus.FAILED, "PERSIST_FAILED"),
    ),
)
def test_preview_binding_never_exposes_noncompleted_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: PreviewRunStatus,
    reason: str,
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)
    staged = _stage(paths.staging_root / status.value)
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    services = module.bind_preview_run_one_services(
        _base(),
        paths,
        reserve=lambda: SimpleNamespace(run_id="preview-failed-ui"),
        run_one=lambda _fds, _reservation: PreviewRunOneResult(
            "preview-failed-ui", status, reason, None
        ),
    )

    view = services.run_preview_job("source", "style", "spec", "pos", "neg")

    assert view.status == status.value
    assert view.message == reason
    assert view.display_images == ()
    assert view.execution_fingerprint is None
    assert "APPROVED" not in repr(view)
    assert not staged.directory.exists()


def test_preview_binding_rejects_cross_run_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)
    publication = _publication("preview-other-run")
    display = paths.display_root / publication.display_name
    display.write_bytes(b"png")
    display.chmod(0o600)
    staged = _stage(paths.staging_root / "cross-run")
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    services = module.bind_preview_run_one_services(
        _base(),
        paths,
        reserve=lambda: SimpleNamespace(run_id="preview-requested-run"),
        run_one=lambda _fds, _reservation: PreviewRunOneResult(
            "preview-requested-run",
            PreviewRunStatus.COMPLETED,
            "OK",
            publication,
        ),
    )

    view = services.run_preview_job("source", "style", "spec", "pos", "neg")

    assert view.status == "FAILED"
    assert view.message == "PREVIEW_REJECTED"
    assert view.display_images == ()


@pytest.mark.parametrize("corruption", ("name", "content"))
def test_preview_binding_rejects_display_not_bound_to_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)
    run_id = "preview-display-binding"
    publication = _publication(
        run_id, display_digest="d" * 16 if corruption == "name" else None
    )
    display = paths.display_root / publication.display_name
    display.write_bytes(b"changed" if corruption == "content" else b"png")
    display.chmod(0o600)
    staged = _stage(paths.staging_root / corruption)
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    services = module.bind_preview_run_one_services(
        _base(),
        paths,
        reserve=lambda: SimpleNamespace(run_id=run_id),
        run_one=lambda _fds, _reservation: PreviewRunOneResult(
            run_id, PreviewRunStatus.COMPLETED, "OK", publication
        ),
    )

    view = services.run_preview_job("source", "style", "spec", "pos", "neg")

    assert view.status == "FAILED"
    assert view.message == "PREVIEW_REJECTED"
    assert view.display_images == ()


def test_preview_readiness_is_local_and_does_not_replace_production_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)

    def production(*_args: object) -> object:
        return object()

    base = _base()
    object.__setattr__(base, "run_production_job", production)
    monkeypatch.setattr(
        module,
        "probe_preview_readiness",
        lambda _paths: (_ for _ in ()).throw(RuntimeError("broken preview")),
    )
    services = module.bind_preview_run_one_services(base, paths)

    readiness = services.get_preview_readiness()
    assert readiness.status == "UNAVAILABLE"
    assert readiness.message == "PREVIEW_UNAVAILABLE"
    assert services.run_production_job is production


def test_preview_readiness_borrows_and_closes_all_config_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)
    borrowed: list[int] = []

    context = object()

    def capture(*descriptors: int) -> object:
        borrowed.extend(descriptors)
        assert all(os.fstat(fd).st_ino > 0 for fd in descriptors)
        return context

    monkeypatch.setattr(module, "load_production_context_config", capture)
    monkeypatch.setattr(module, "load_production_supply_config", capture)
    monkeypatch.setattr(module, "load_preview_supply_config", capture)
    support_queries: list[tuple[object, str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        module,
        "require_model_pipeline_support",
        lambda *query: support_queries.append(query),
    )

    view = module.probe_preview_readiness(paths)

    assert view.status == "CONFIGURED"
    assert support_queries == [(context, "lcm", ("base", "ip_adapter", "controlnet"))]
    assert len(borrowed) == 4
    for descriptor in set(borrowed):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_preview_readiness_reports_missing_lcm_capability_without_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_run as module
    from specstyle.errors import DomainError

    paths = _paths(tmp_path)
    monkeypatch.setattr(module, "load_production_context_config", lambda *_: object())
    monkeypatch.setattr(module, "load_production_supply_config", lambda *_: object())
    monkeypatch.setattr(module, "load_preview_supply_config", lambda *_: object())
    monkeypatch.setattr(
        module,
        "require_model_pipeline_support",
        lambda *_: (_ for _ in ()).throw(DomainError("missing lcm")),
    )

    view = module.probe_preview_readiness(paths)

    assert view.status == "UNAVAILABLE"
    assert view.message == "PREVIEW_LCM_CAPABILITY_MISSING"


def test_unavailable_preview_binding_preserves_production_service() -> None:
    from specstyle.ui.preview_run import bind_unavailable_preview_services

    base = _base()

    def production(*_args: object) -> object:
        return object()

    object.__setattr__(base, "run_production_job", production)
    services = bind_unavailable_preview_services(base, "PREVIEW_CONFIG_UNAVAILABLE")

    assert services.get_preview_readiness().status == "UNAVAILABLE"
    assert services.run_preview_job(None, None, None, "", "").status == "UNAVAILABLE"
    assert services.run_production_job is production


def test_preview_binding_reports_staging_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.ui.preview_run as module

    paths = _paths(tmp_path)
    run_id = "preview-cleanup-failure"
    publication = _publication(run_id)
    display = paths.display_root / publication.display_name
    display.write_bytes(b"png")
    display.chmod(0o600)
    staged = _stage(paths.staging_root / "cleanup-failure")
    _install_stage(module, monkeypatch, staged)
    monkeypatch.setattr(module, "OpenPreviewUiFds", _Open)
    monkeypatch.setattr(
        module,
        "cleanup_preview_staging",
        lambda _path: (_ for _ in ()).throw(
            InfrastructureError("preview staging cleanup failed")
        ),
    )
    services = module.bind_preview_run_one_services(
        _base(),
        paths,
        reserve=lambda: SimpleNamespace(run_id=run_id),
        run_one=lambda _fds, _reservation: PreviewRunOneResult(
            run_id, PreviewRunStatus.COMPLETED, "OK", publication
        ),
    )

    view = services.run_preview_job("source", "style", "spec", "pos", "neg")

    assert view.status == "FAILED"
    assert view.message == "STAGING_CLEANUP_FAILED"
    assert view.display_images == ()
