"""Lightweight Production UI projections built from completed domain results."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from specstyle.errors import InfrastructureError
from specstyle.ui.presenters import format_qa_table, present_qa_report
from specstyle.ui.production_ui_state import ProductionTerminalProjection
from specstyle.ui.view_models import (
    JobStatusView,
    ProductionBatchItemUiView,
    ProductionBatchUiView,
    ProductionRunUiView,
)


def terminal_projection(
    export_root: Path, result: object, job_id: str
) -> ProductionTerminalProjection:
    view = _view(export_root, result, job_id)
    job_result = getattr(result, "job_result", None)
    return ProductionTerminalProjection(
        view,
        JobStatusView(
            view.job_id, view.status, view.message, False, view.profile_label
        ),
        _bounded_qa(view.qa_table),
        _repair_timeline(job_result),
        _export_summary(getattr(result, "export_result", None)),
    )


def failure_projection(view: ProductionRunUiView) -> ProductionTerminalProjection:
    return ProductionTerminalProjection(
        view,
        JobStatusView(
            view.job_id, view.status, view.message, False, view.profile_label
        ),
        view.qa_table,
        "no repair",
        "no export",
    )


def status_projection(
    job_id: str, status: str, message: str
) -> ProductionTerminalProjection:
    view = ProductionRunUiView(
        job_id,
        status,
        message,
        "production",
        "",
        None,
        (),
        (),
        "no qa",
    )
    return ProductionTerminalProjection(
        view,
        JobStatusView(job_id, status, message, False, "production"),
        "no qa",
        "no repair",
        "no export",
    )


def projection_with_message(
    projection: ProductionTerminalProjection, message: str
) -> ProductionTerminalProjection:
    return replace(
        projection,
        run_view=replace(projection.run_view, message=message),
        status=replace(projection.status, message=message),
    )


def batch_projection(
    view: ProductionBatchUiView,
    items: tuple[ProductionTerminalProjection, ...],
) -> ProductionTerminalProjection:
    job_id = view.items[-1].run.job_id if view.items else ""
    qa = tuple(f"item={i}\n{item.qa_table}" for i, item in enumerate(items))
    repairs = tuple(f"item={i}\n{item.repair_timeline}" for i, item in enumerate(items))
    exports = tuple(f"item={i} {item.export_summary}" for i, item in enumerate(items))
    run_view = ProductionRunUiView(
        job_id,
        view.status,
        view.message,
        view.profile_label,
        "",
        None,
        view.approved_images,
        view.rejected_images,
        "\n\n".join(qa) if qa else "no qa",
    )
    return ProductionTerminalProjection(
        run_view,
        JobStatusView(job_id, view.status, view.message, False, view.profile_label),
        run_view.qa_table,
        "\n\n".join(repairs) if repairs else "no repair",
        "\n".join(exports) if exports else "no export",
    )


def successful_batch_item(
    export_root: Path,
    result: object,
    item_index: int,
    requested_variation: int,
    max_rounds: int,
    job_id: str,
    cleanup_error: str | None,
) -> ProductionBatchItemUiView:
    job_result = getattr(result, "job_result", None)
    history = getattr(job_result, "history", None)
    initial = getattr(history, "initial_attempt", None)
    initial_variation, initial_seed = _seed_evidence(getattr(initial, "request", None))
    final_variation, final_seed = _seed_evidence(getattr(job_result, "request", None))
    if (
        initial_variation != requested_variation
        or not requested_variation
        <= final_variation
        <= requested_variation + max_rounds
    ):
        raise InfrastructureError("production batch evidence unavailable")
    return ProductionBatchItemUiView(
        item_index,
        requested_variation,
        initial_seed,
        final_variation,
        final_seed,
        _view(export_root, result, job_id),
        cleanup_error,
    )


def failed_batch_item(
    item_index: int,
    requested_variation: int,
    job_id: str,
    message: str,
    cleanup_error: str | None = None,
) -> ProductionBatchItemUiView:
    return ProductionBatchItemUiView(
        item_index,
        requested_variation,
        None,
        None,
        None,
        failure(job_id, message),
        cleanup_error,
    )


def cancelled_batch_item(
    item_index: int,
    requested_variation: int,
    job_id: str,
    cleanup_error: str | None = None,
) -> ProductionBatchItemUiView:
    return ProductionBatchItemUiView(
        item_index,
        requested_variation,
        None,
        None,
        None,
        cancelled(job_id),
        cleanup_error,
    )


def batch_view(items: tuple[ProductionBatchItemUiView, ...]) -> ProductionBatchUiView:
    completed = sum(item.run.status == "COMPLETED" for item in items)
    cancelled_run = any(item.run.status == "CANCELLED" for item in items)
    cleanup_failed = any(item.cleanup_error is not None for item in items)
    if cancelled_run and completed == 0:
        status = "CANCELLED"
    elif completed == 0:
        status = "JOB_FAILED"
    elif completed == len(items) and not cleanup_failed:
        status = "COMPLETED"
    else:
        status = "PARTIAL"
    seeds = tuple(
        item.final_seed
        for item in items
        if item.run.status == "COMPLETED" and item.final_seed is not None
    )
    collision = len(seeds) != len(set(seeds))
    diversity = status == "COMPLETED" and not collision
    message = f"{completed}/{len(items)} exports completed"
    if cancelled_run:
        message += "; batch cancelled"
    return ProductionBatchUiView(
        status,
        message,
        "production",
        items,
        collision,
        diversity,
        tuple(path for item in items for path in item.run.approved_images),
        tuple(path for item in items for path in item.run.rejected_images),
        _batch_tsv(items, status, collision, diversity),
    )


def failure(job_id: str, message: str) -> ProductionRunUiView:
    return ProductionRunUiView(
        job_id,
        "JOB_FAILED",
        message,
        "production",
        "",
        None,
        (),
        (),
        "no qa",
    )


def cancelled(job_id: str) -> ProductionRunUiView:
    return ProductionRunUiView(
        job_id,
        "CANCELLED",
        "production run cancelled",
        "production",
        "",
        None,
        (),
        (),
        "no qa",
    )


def busy() -> ProductionRunUiView:
    return ProductionRunUiView(
        "",
        "BUSY",
        "production run busy",
        "production",
        "",
        None,
        (),
        (),
        "no qa",
    )


def batch_failure(message: str) -> ProductionBatchUiView:
    return ProductionBatchUiView(
        "JOB_FAILED",
        message,
        "production",
        (),
        False,
        False,
        (),
        (),
        _batch_tsv((), "JOB_FAILED", False, False),
    )


def batch_busy() -> ProductionBatchUiView:
    return ProductionBatchUiView(
        "BUSY",
        "production run busy",
        "production",
        (),
        False,
        False,
        (),
        (),
        _batch_tsv((), "BUSY", False, False),
    )


def _view(export_root: Path, result: object, job_id: str) -> ProductionRunUiView:
    export = getattr(result, "export_result")
    bundle = getattr(export, "bundle")
    qa = _qa_table(getattr(getattr(result, "job_result", None), "report", None))
    return ProductionRunUiView(
        _job_id(export) or job_id,
        _status(export),
        "production run completed",
        "production",
        bundle.bundle_name,
        getattr(getattr(bundle, "bundle_sha256", None), "value", None),
        _image_paths(export_root, bundle, "approved/"),
        _image_paths(export_root, bundle, "rejected/"),
        qa,
    )


def _repair_timeline(job_result: object) -> str:
    history = getattr(job_result, "history", None)
    initial = getattr(history, "initial_attempt", None)
    initial_id = _artifact_id(getattr(initial, "artifact", None))
    if not initial_id:
        return "no repair"
    attempts = tuple(getattr(history, "repair_attempts", ()))
    stop = getattr(
        getattr(getattr(job_result, "terminal", None), "artifact_decision", None),
        "repair_stop_reason",
        None,
    )
    stop_reason = getattr(stop, "value", "")
    rows = ["attempt_index\tartifact_id\taction_id\ttrigger_rule_id\tstop_reason"]
    rows.append(
        "\t".join(
            _tsv_value(value)
            for value in (0, initial_id, "", "", stop_reason if not attempts else "")
        )
    )
    for index, attempt in enumerate(attempts, start=1):
        decision = getattr(attempt, "decision", None)
        values = (
            index,
            _artifact_id(getattr(attempt, "artifact", None)),
            getattr(getattr(decision, "action_id", None), "value", ""),
            getattr(getattr(decision, "trigger_rule_id", None), "value", ""),
            stop_reason if index == len(attempts) else "",
        )
        rows.append("\t".join(_tsv_value(value) for value in values))
    return "\n".join(rows)


def _export_summary(export: object) -> str:
    bundle = getattr(export, "bundle", None)
    name = getattr(bundle, "bundle_name", "")
    if not name:
        return "no export"
    paths = tuple(getattr(item, "relative_path", "") for item in bundle.files)
    approved = _route_count(paths, "approved/")
    rejected = _route_count(paths, "rejected/")
    review = _route_count(paths, "manual_review/")
    digest = getattr(getattr(bundle, "bundle_sha256", None), "value", "")
    return (
        f"bundle={name} approved={approved} rejected={rejected} "
        f"review={review} sha={digest}"
    )


def _batch_tsv(
    items: tuple[ProductionBatchItemUiView, ...],
    status: str,
    collision: bool,
    diversity: bool,
) -> str:
    if collision:
        evidence = "NOT_DIVERSITY_EVIDENCE_FINAL_SEED_COLLISION"
    elif diversity:
        evidence = "VALID_DIVERSITY_EVIDENCE"
    else:
        evidence = "NOT_DIVERSITY_EVIDENCE_INCOMPLETE_BATCH"
    rows = [
        "item_index\trequested_variation\tinitial_seed\tfinal_variation\t"
        "final_seed\tjob_id\tjob_status\tmessage\tbundle\tbundle_sha256\t"
        "cleanup_error\tqa\tbatch_status\tevidence"
    ]
    for item in items:
        values = (
            item.item_index,
            item.requested_variation_index,
            item.initial_seed,
            item.final_variation_index,
            item.final_seed,
            item.run.job_id,
            item.run.status,
            item.run.message,
            item.run.bundle_name,
            item.run.bundle_sha256,
            item.cleanup_error,
            item.run.qa_table,
            status,
            evidence,
        )
        rows.append("\t".join(_tsv_value(value) for value in values))
    return "\n".join(rows)


def _seed_evidence(request: object) -> tuple[int, int]:
    variation = getattr(request, "variation_index", None)
    snapshot = getattr(request, "seed", None)
    snapshot_variation = getattr(snapshot, "variation_index", None)
    seed = getattr(snapshot, "seed", None)
    if (
        type(variation) is not int
        or not 0 <= variation < 2**31
        or type(snapshot_variation) is not int
        or snapshot_variation != variation
        or type(seed) is not int
        or not 0 <= seed < 2**63
    ):
        raise InfrastructureError("production batch evidence unavailable")
    return variation, seed


def _qa_table(report: object | None) -> str:
    if report is None:
        return "no qa"
    return format_qa_table(present_qa_report(report))  # type: ignore[arg-type]


def _image_paths(export_root: Path, bundle: object, prefix: str) -> tuple[str, ...]:
    paths = (
        str(export_root / bundle.bundle_name / relative)
        for file in getattr(bundle, "files", ())
        if (relative := getattr(file, "relative_path", "")).startswith(prefix)
        and relative.endswith(".png")
    )
    return tuple(sorted(paths))


def _bounded_qa(value: str) -> str:
    lines = value.splitlines()
    if len(lines) <= 257:
        return value
    return "\n".join((*lines[:257], "TRUNCATED\tTRUNCATED\t\twarning"))


def _status(export: object) -> str:
    job = getattr(getattr(export, "job_state", None), "job", None)
    status = getattr(job, "status", None)
    return getattr(status, "value", str(status or "COMPLETED"))


def _job_id(export: object) -> str:
    job = getattr(getattr(export, "job_state", None), "job", None)
    return getattr(getattr(job, "job_id", None), "value", "")


def _artifact_id(artifact: object) -> str:
    ref = getattr(artifact, "ref", None)
    return getattr(getattr(ref, "artifact_id", None), "value", "")


def _route_count(paths: tuple[str, ...], prefix: str) -> int:
    return sum(path.startswith(prefix) and path.endswith(".png") for path in paths)


def _tsv_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")
