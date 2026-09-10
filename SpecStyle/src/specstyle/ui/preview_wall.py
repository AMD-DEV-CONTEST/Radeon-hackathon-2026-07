"""Preview wall UI binding with one staging and workflow invocation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from specstyle.errors import DomainError, InfrastructureError
from specstyle.ui.app import UiServices
from specstyle.ui.preview_run import _display_path
from specstyle.ui.preview_ui_inputs import (
    OpenPreviewUiFds,
    PreviewUiCleanupError,
    PreviewUiInputError,
    PreviewUiRuntimePaths,
    StagedPreviewInputs,
    cleanup_preview_staging,
    stage_preview_inputs,
)
from specstyle.ui.view_models import PreviewWallItemUiView, PreviewWallUiView
from specstyle.workflow.preview_run_one import PreviewRunStatus
from specstyle.workflow.preview_wall import (
    PreviewWallResult,
    reserve_preview_wall,
    run_preview_wall,
)


def _failed(message: str, *, status: str = "FAILED") -> PreviewWallUiView:
    return PreviewWallUiView(
        "",
        status,
        message,
        "preview",
        "ENGINEERING_ONLY",
        (),
        (),
        "quality\tNOT_EVALUATED\ndiversity\tNOT_EVALUATED",
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    )


def _item_view(
    paths: PreviewUiRuntimePaths, result: PreviewWallResult, index: int
) -> PreviewWallItemUiView:
    item = result.items[index]
    publication = item.run.publication
    display = None
    if item.run.status is PreviewRunStatus.COMPLETED:
        display = _display_path(paths, item.run)
    return PreviewWallItemUiView(
        item.variation_index,
        item.attempted,
        item.run.run_id,
        item.run.status.value,
        item.run.reason_code,
        None if publication is None else publication.seed,
        None if publication is None else publication.content_sha256.value,
        None if publication is None else publication.execution_fingerprint.value,
        display,
    )


def _evidence_tsv(items: tuple[PreviewWallItemUiView, ...]) -> str:
    rows = [
        "variation_index\tattempted\tstatus\treason\tseed\tcontent_sha256\t"
        "execution_fingerprint"
    ]
    rows.extend(
        "\t".join(
            (
                str(item.variation_index),
                str(item.attempted).lower(),
                item.status,
                item.reason_code,
                "" if item.seed is None else str(item.seed),
                item.content_sha256 or "",
                item.execution_fingerprint or "",
            )
        )
        for item in items
    )
    rows.extend(("quality\tNOT_EVALUATED", "diversity\tNOT_EVALUATED"))
    return "\n".join(rows)


def _project(paths: PreviewUiRuntimePaths, value: object) -> PreviewWallUiView:
    if type(value) is not PreviewWallResult:
        raise DomainError("invalid preview wall result")
    if value.publication is None:
        return _failed(value.reason_code, status=value.status.value)
    if value.publication.evidence_name != value.wall_id:
        raise DomainError("invalid preview wall publication")
    items = tuple(_item_view(paths, value, index) for index in range(len(value.items)))
    return PreviewWallUiView(
        value.wall_id,
        value.status.value,
        value.reason_code,
        "preview",
        "ENGINEERING_ONLY",
        items,
        tuple(item.display_image for item in items if item.display_image is not None),
        _evidence_tsv(items),
        value.verification,
        value.repair,
        value.export,
    )


def _run(
    paths: PreviewUiRuntimePaths,
    reserve: Callable[[int], object],
    run_wall: Callable[[object, object], object],
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
    count: object,
) -> PreviewWallUiView:
    if type(count) is not int or not 1 <= count <= 4:
        return _failed("INVALID_WALL_COUNT")
    staged: StagedPreviewInputs | None = None
    view: PreviewWallUiView | None = None
    cleanup_failed = False
    primary: BaseException | None = None
    try:
        try:
            staged = stage_preview_inputs(
                paths, source, style, spec, positive, negative
            )
            reservation = reserve(count)
            with OpenPreviewUiFds(paths, staged) as fds:
                view = _project(paths, run_wall(fds, reservation))
        except PreviewUiCleanupError:
            view = _failed("STAGING_CLEANUP_FAILED")
        except PreviewUiInputError:
            view = _failed("INPUT_INVALID")
        except DomainError:
            view = _failed("PREVIEW_WALL_REJECTED")
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
                    primary.add_note("preview wall staging cleanup failed")
    if cleanup_failed:
        return _failed("STAGING_CLEANUP_FAILED")
    if view is None:
        raise InfrastructureError("preview wall UI result unavailable")
    return view


def bind_preview_wall_services(
    base: UiServices,
    paths: PreviewUiRuntimePaths,
    *,
    reserve: Callable[[int], object] = reserve_preview_wall,
    run_wall: Callable[[object, object], object] = run_preview_wall,
) -> UiServices:
    if type(base) is not UiServices or type(paths) is not PreviewUiRuntimePaths:
        raise DomainError("invalid preview wall UI services")

    def run(
        source: object,
        style: object,
        spec: object,
        positive: str,
        negative: str,
        count: int,
    ) -> PreviewWallUiView:
        return _run(
            paths,
            reserve,
            run_wall,
            source,
            style,
            spec,
            positive,
            negative,
            count,
        )

    return replace(base, run_preview_wall=run)


def bind_unavailable_preview_wall_services(base: UiServices, reason: str) -> UiServices:
    if type(base) is not UiServices or type(reason) is not str or not reason:
        raise DomainError("invalid unavailable preview wall services")
    return replace(
        base,
        run_preview_wall=lambda *_args: _failed(reason, status="UNAVAILABLE"),
    )


__all__ = (
    "bind_preview_wall_services",
    "bind_unavailable_preview_wall_services",
)
