"""Preview UI binding isolated from Production workflow state and export."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import hashlib
import os
import stat

from specstyle.errors import DomainError, InfrastructureError
from specstyle.production.context_config import (
    load_production_context_config,
    require_model_pipeline_support,
)
from specstyle.production.preview_supply_config import load_preview_supply_config
from specstyle.production.supply_config import load_production_supply_config
from specstyle.ui.app import UiServices
from specstyle.ui.preview_ui_inputs import (
    OpenPreviewUiFds,
    PreviewUiCleanupError,
    PreviewUiInputError,
    PreviewUiRuntimePaths,
    StagedPreviewInputs,
    cleanup_preview_staging,
    stage_preview_inputs,
)
from specstyle.ui.view_models import PreviewReadinessUiView, PreviewRunUiView
from specstyle.workflow.preview_evidence import reconcile_preview_display
from specstyle.workflow.preview_run_one import (
    PreviewRunOneResult,
    reserve_preview_run_one,
    run_preview_one,
)

_UNAVAILABLE = "PREVIEW_UNAVAILABLE"
_MAX_DISPLAY_BYTES = 32 * 1024 * 1024


def _open_directory(path: object) -> int:
    if not isinstance(path, os.PathLike):
        raise DomainError("invalid preview runtime path")
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise InfrastructureError("preview runtime unavailable") from None


def probe_preview_readiness(paths: PreviewUiRuntimePaths) -> PreviewReadinessUiView:
    if type(paths) is not PreviewUiRuntimePaths:
        raise DomainError("invalid preview runtime paths")
    descriptors: list[int] = []
    try:
        for path in (
            paths.production_config_root,
            paths.production_context_evidence_root,
            paths.preview_config_root,
        ):
            descriptors.append(_open_directory(path))
        context = load_production_context_config(descriptors[0], descriptors[1])
        try:
            require_model_pipeline_support(
                context, "lcm", ("base", "ip_adapter", "controlnet")
            )
        except DomainError:
            return PreviewReadinessUiView(
                "UNAVAILABLE", "PREVIEW_LCM_CAPABILITY_MISSING"
            )
        load_production_supply_config(descriptors[0])
        load_preview_supply_config(descriptors[2])
        return PreviewReadinessUiView("CONFIGURED", "PREVIEW_CONFIG_READY")
    finally:
        while descriptors:
            os.close(descriptors.pop())


def reconcile_preview_ui_display(paths: PreviewUiRuntimePaths) -> tuple[str, ...]:
    private_fd = display_fd = -1
    try:
        private_fd = _open_directory(paths.evidence_root)
        display_fd = _open_directory(paths.display_root)
        return reconcile_preview_display(private_fd, display_fd)
    finally:
        if display_fd >= 0:
            os.close(display_fd)
        if private_fd >= 0:
            os.close(private_fd)


def _readiness(paths: PreviewUiRuntimePaths) -> PreviewReadinessUiView:
    try:
        return probe_preview_readiness(paths)
    except Exception:
        return PreviewReadinessUiView("UNAVAILABLE", _UNAVAILABLE)


def _display_path(paths: PreviewUiRuntimePaths, result: PreviewRunOneResult) -> str:
    publication = result.publication
    if publication is None:
        raise DomainError("preview publication unavailable")
    expected_name = f"{result.run_id}-{publication.content_sha256.value[:16]}.png"
    if publication.display_name != expected_name:
        raise DomainError("invalid preview display binding")
    path = paths.display_root / publication.display_name
    root_fd = file_fd = -1
    try:
        root_fd = _open_directory(paths.display_root)
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        file_fd = os.open(publication.display_name, flags, dir_fd=root_fd)
        info = os.fstat(file_fd)
    except OSError:
        raise InfrastructureError("preview display unavailable") from None
    try:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o022
            or not 1 <= info.st_size <= _MAX_DISPLAY_BYTES
        ):
            raise InfrastructureError("preview display unavailable")
        digest = hashlib.sha256()
        remaining = info.st_size
        while remaining:
            block = os.read(file_fd, min(remaining, 64 * 1024))
            if not block:
                raise InfrastructureError("preview display unavailable")
            digest.update(block)
            remaining -= len(block)
        if (
            os.read(file_fd, 1)
            or digest.hexdigest() != publication.content_sha256.value
        ):
            raise DomainError("invalid preview display binding")
        return str(path)
    except OSError:
        raise InfrastructureError("preview display unavailable") from None
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if root_fd >= 0:
            os.close(root_fd)


def _project(paths: PreviewUiRuntimePaths, result: object) -> PreviewRunUiView:
    if type(result) is not PreviewRunOneResult:
        raise DomainError("invalid preview run result")
    completed = result.status.value == "COMPLETED"
    if completed and result.publication.evidence_name != result.run_id:
        raise DomainError("invalid preview run publication")
    display = (_display_path(paths, result),) if completed else ()
    execution = (
        result.publication.execution_fingerprint.value
        if result.publication is not None
        else None
    )
    return PreviewRunUiView(
        result.run_id,
        result.status.value,
        result.reason_code,
        "preview",
        display,
        execution,
        result.verification,
        result.repair,
        result.export,
    )


def _failed(message: str, *, status: str = "FAILED") -> PreviewRunUiView:
    return PreviewRunUiView(
        "",
        status,
        message,
        "preview",
        (),
        None,
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    )


def _run_preview(
    paths: PreviewUiRuntimePaths,
    reserve: Callable[[], object],
    run_one: Callable[[object, object], object],
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
) -> PreviewRunUiView:
    staged: StagedPreviewInputs | None = None
    view: PreviewRunUiView | None = None
    cleanup_failed = False
    primary: BaseException | None = None
    try:
        try:
            staged = stage_preview_inputs(
                paths, source, style, spec, positive, negative
            )
            reservation = reserve()
            with OpenPreviewUiFds(paths, staged) as fds:
                view = _project(paths, run_one(fds, reservation))
        except PreviewUiCleanupError:
            view = _failed("STAGING_CLEANUP_FAILED")
        except PreviewUiInputError:
            view = _failed("INPUT_INVALID")
        except DomainError:
            view = _failed("PREVIEW_REJECTED")
        except (InfrastructureError, OSError):
            view = _failed("PREVIEW_UNAVAILABLE", status="UNAVAILABLE")
        except Exception:
            view = _failed("INTERNAL_ERROR")
    except BaseException as error:
        primary = error
        raise
    finally:
        if staged is not None:
            try:
                cleanup_preview_staging(staged)
            except InfrastructureError:
                if primary is None:
                    cleanup_failed = True
                else:
                    primary.add_note("preview staging cleanup failed")
    if cleanup_failed:
        return _failed("STAGING_CLEANUP_FAILED")
    if view is None:
        raise InfrastructureError("preview UI result unavailable")
    return view


def bind_preview_run_one_services(
    base: UiServices,
    paths: PreviewUiRuntimePaths,
    *,
    reserve: Callable[[], object] = reserve_preview_run_one,
    run_one: Callable[[object, object], object] = run_preview_one,
) -> UiServices:
    if type(base) is not UiServices or type(paths) is not PreviewUiRuntimePaths:
        raise DomainError("invalid preview UI services")

    def run(
        source: object,
        style: object,
        spec: object,
        positive: str,
        negative: str,
    ) -> PreviewRunUiView:
        return _run_preview(
            paths, reserve, run_one, source, style, spec, positive, negative
        )

    return replace(
        base,
        get_preview_readiness=lambda: _readiness(paths),
        run_preview_job=run,
    )


def bind_unavailable_preview_services(base: UiServices, reason: str) -> UiServices:
    if type(base) is not UiServices or type(reason) is not str or not reason:
        raise DomainError("invalid unavailable preview services")
    readiness = PreviewReadinessUiView("UNAVAILABLE", reason)
    return replace(
        base,
        get_preview_readiness=lambda: readiness,
        run_preview_job=lambda *_args: _failed(reason, status="UNAVAILABLE"),
    )
