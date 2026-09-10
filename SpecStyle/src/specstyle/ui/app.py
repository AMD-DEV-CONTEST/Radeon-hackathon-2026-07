"""Gradio application shell — lazy import; services injected.

UI-001: Spec edit/compile feedback
UI-002: job status, preview/production labels, QA table (UNVERIFIABLE ≠ PASS)
UI-003: repair timeline, export summary, replay assessment
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from specstyle.errors import DomainError
from specstyle.ui.presenters import (
    format_qa_table,
    present_export,
    present_job_status,
    present_qa_report,
    present_repair_timeline,
    present_replay,
    present_spec_compile,
)
from specstyle.ui.view_models import (
    ExportView,
    JobStatusView,
    ProductionBatchUiView,
    ProductionRunUiView,
    PreviewReadinessUiView,
    PreviewRunUiView,
    PreviewWallUiView,
    QaRuleView,
    RepairStepView,
    ReplayView,
    SpecEditorView,
)
from specstyle.workflow.job_models import JobStatus
from specstyle.workflow.orchestrator import FakeJobResult


@dataclass(frozen=True, slots=True)
class UiServices:
    """Injected application services — UI never constructs domain backends."""

    compile_spec: Callable[[str], SpecEditorView]
    get_job_status: Callable[[], JobStatusView] | None = None
    cancel_job: Callable[[], str] | None = None
    get_qa_table: Callable[[], str] | None = None
    get_repair_timeline: Callable[[], str] | None = None
    get_export_summary: Callable[[], str] | None = None
    run_replay: (
        Callable[
            [object, object, object, str, str, str | None, str | None, str | None, str],
            str,
        ]
        | None
    ) = None
    run_production_job: (
        Callable[
            [object, object, object, str, str, str | None, str | None, str | None, str],
            ProductionRunUiView,
        ]
        | None
    ) = None
    run_production_batch: (
        Callable[
            [
                object,
                object,
                object,
                str,
                str,
                str | None,
                str | None,
                str | None,
                str,
                int,
            ],
            ProductionBatchUiView,
        ]
        | None
    ) = None
    get_preview_readiness: Callable[[], PreviewReadinessUiView] | None = None
    run_preview_job: (
        Callable[[object, object, object, str, str], PreviewRunUiView] | None
    ) = None
    run_preview_wall: (
        Callable[[object, object, object, str, str, int], PreviewWallUiView] | None
    ) = None


def build_default_services(context: object) -> UiServices:
    from specstyle.spec.compiled_models import CompilerContext

    if type(context) is not CompilerContext:
        raise DomainError("invalid compiler context")

    def _compile(text: str) -> SpecEditorView:
        return present_spec_compile(text, context)

    return UiServices(_compile)


def bind_job_result_services(
    base: UiServices,
    *,
    job_id: str,
    result: FakeJobResult | None,
    profile: str,
    on_cancel: Callable[[], None] | None,
    qa_report: object | None = None,
    replay_assessment: object | None = None,
) -> UiServices:
    """Attach UI-002/003 handlers from a finished or in-flight job snapshot."""

    def status() -> JobStatusView:
        if result is None:
            return present_job_status(
                job_id, JobStatus.GENERATING, "running", profile=profile
            )
        return present_job_status(job_id, result.final_status, "", profile=profile)

    def cancel() -> str:
        if on_cancel is None:
            return "cancel unavailable"
        on_cancel()
        return "cancel requested"

    def qa() -> str:
        if qa_report is None:
            return "no qa"
        views = present_qa_report(qa_report)  # type: ignore[arg-type]
        return format_qa_table(views)

    def repair() -> str:
        if result is None:
            return "no repair"
        steps = present_repair_timeline(result)
        return "\n".join(
            f"{s.artifact_id}\trounds={s.rounds}\tstop={s.stop_reason}" for s in steps
        )

    def export() -> str:
        if result is None:
            return "no export"
        view = present_export(result)
        return (
            f"bundle={view.bundle_name} approved={view.approved_count} "
            f"rejected={view.rejected_count} review={view.manual_review_count} "
            f"sha={view.bundle_sha256}"
        )

    def replay(*_args: object) -> str:
        if replay_assessment is None:
            return "no replay"
        view = present_replay(replay_assessment)  # type: ignore[arg-type]
        return f"{view.status}\t{view.mode}\t{','.join(view.reasons)}"

    return UiServices(
        base.compile_spec,
        get_job_status=status,
        cancel_job=cancel,
        get_qa_table=qa,
        get_repair_timeline=repair,
        get_export_summary=export,
        run_replay=replay,
        run_production_job=base.run_production_job,
        run_production_batch=base.run_production_batch,
        get_preview_readiness=base.get_preview_readiness,
        run_preview_job=base.run_preview_job,
        run_preview_wall=base.run_preview_wall,
    )


def _production_event_options(kind: str) -> dict[str, object]:
    if kind == "run":
        return {"concurrency_id": "production-run", "concurrency_limit": 2}
    if kind == "control":
        return {"concurrency_id": "production-control", "concurrency_limit": 4}
    raise DomainError("invalid production event kind")


def _enable_production_queue(app: Any) -> Any:
    return app.queue(default_concurrency_limit=1)


def create_app(services: UiServices) -> Any:
    """Create Gradio Blocks app. Requires `gradio` installed."""
    if type(services) is not UiServices:
        raise DomainError("invalid ui services")
    try:
        import gradio as gr
    except ImportError as exc:
        raise DomainError("gradio not installed") from exc

    def on_compile(spec_text: str) -> str:
        view = services.compile_spec(spec_text or "")
        if view.compile_ok:
            return f"OK {view.spec_id} hash={view.compiled_hash}"
        return "ERR " + "; ".join(view.errors)

    def on_status() -> str:
        if services.get_job_status is None:
            return "no job"
        v = services.get_job_status()
        return (
            f"{v.job_id}\t{v.status}\tprofile={v.profile_label}\t"
            f"cancelable={v.can_cancel}\t{v.message}"
        )

    def on_cancel() -> str:
        if services.cancel_job is None:
            return "cancel unavailable"
        return services.cancel_job()

    def on_qa() -> str:
        if services.get_qa_table is None:
            return "no qa"
        return services.get_qa_table()

    def on_repair() -> str:
        if services.get_repair_timeline is None:
            return "no repair"
        return services.get_repair_timeline()

    def on_export() -> str:
        if services.get_export_summary is None:
            return "no export"
        return services.get_export_summary()

    def on_replay(
        source_file: object,
        style_file: object,
        spec_file: object,
        positive_prompt: str,
        negative_prompt: str,
        source_url: str,
        license_: str,
        attribution: str,
        consent: str,
    ) -> str:
        if services.run_replay is None:
            return "no replay"
        return services.run_replay(
            source_file,
            style_file,
            spec_file,
            positive_prompt or "",
            negative_prompt or "",
            source_url or None,
            license_ or None,
            attribution or None,
            consent,
        )

    def on_run_production(
        source_file: object,
        style_file: object,
        spec_file: object,
        positive_prompt: str,
        negative_prompt: str,
        source_url: str,
        license_: str,
        attribution: str,
        consent: str,
    ) -> tuple[str, list[str], list[str], str]:
        if services.run_production_job is None:
            return "production run unavailable", [], [], "no qa"
        view = services.run_production_job(
            source_file,
            style_file,
            spec_file,
            positive_prompt or "",
            negative_prompt or "",
            source_url or None,
            license_ or None,
            attribution or None,
            consent,
        )
        status = (
            f"{view.job_id}\t{view.status}\tprofile={view.profile_label}\t"
            f"bundle={view.bundle_name}\tsha={view.bundle_sha256 or ''}\t"
            f"{view.message}"
        )
        return (
            status,
            list(view.approved_images),
            list(view.rejected_images),
            view.qa_table,
        )

    def on_run_production_batch(
        source_file: object,
        style_file: object,
        spec_file: object,
        positive_prompt: str,
        negative_prompt: str,
        source_url: str,
        license_: str,
        attribution: str,
        consent: str,
        batch_count: float,
    ) -> tuple[str, list[str], list[str], str]:
        if services.run_production_batch is None:
            return "production batch unavailable", [], [], "no evidence"
        count: object = batch_count
        if type(batch_count) is float and batch_count.is_integer():
            count = int(batch_count)
        view = services.run_production_batch(
            source_file,
            style_file,
            spec_file,
            positive_prompt or "",
            negative_prompt or "",
            source_url or None,
            license_ or None,
            attribution or None,
            consent,
            count,  # type: ignore[arg-type]
        )
        status = (
            f"{view.status}\tprofile={view.profile_label}\t"
            f"diversity_evidence={'YES' if view.diversity_evidence else 'NO'}\t"
            f"final_seed_collision={view.final_seed_collision}\t{view.message}"
        )
        return (
            status,
            list(view.approved_images),
            list(view.rejected_images),
            view.evidence_tsv,
        )

    def on_preview_readiness() -> str:
        if services.get_preview_readiness is None:
            return "UNAVAILABLE\tPREVIEW_UNAVAILABLE"
        view = services.get_preview_readiness()
        return f"{view.status}\t{view.message}"

    def on_run_preview(
        source_file: object,
        style_file: object,
        spec_file: object,
        positive_prompt: str,
        negative_prompt: str,
    ) -> tuple[str, list[str], str]:
        if services.run_preview_job is None:
            return "\tUNAVAILABLE\tprofile=preview\tPREVIEW_UNAVAILABLE", [], ""
        view = services.run_preview_job(
            source_file,
            style_file,
            spec_file,
            positive_prompt or "",
            negative_prompt or "",
        )
        status = (
            f"{view.run_id}\t{view.status}\tprofile={view.profile_label}\t"
            f"{view.message}"
        )
        evidence = (
            f"execution_fingerprint={view.execution_fingerprint or ''}\t"
            f"verification={view.verification}\trepair={view.repair}\t"
            f"export={view.export}"
        )
        return status, list(view.display_images), evidence

    def on_run_preview_wall(
        source_file: object,
        style_file: object,
        spec_file: object,
        positive_prompt: str,
        negative_prompt: str,
        wall_count: float,
    ) -> tuple[str, list[str], str]:
        if services.run_preview_wall is None:
            return "UNAVAILABLE\tprofile=preview\tENGINEERING_ONLY", [], ""
        count: object = wall_count
        if type(wall_count) is float and wall_count.is_integer():
            count = int(wall_count)
        view = services.run_preview_wall(
            source_file,
            style_file,
            spec_file,
            positive_prompt or "",
            negative_prompt or "",
            count,  # type: ignore[arg-type]
        )
        status = (
            f"{view.wall_id}\t{view.status}\tprofile={view.profile_label}\t"
            f"{view.evidence_class}\t{view.message}"
        )
        evidence = (
            f"verification={view.verification}\trepair={view.repair}\t"
            f"export={view.export}\n{view.evidence_tsv}"
        )
        return status, list(view.display_images), evidence

    with gr.Blocks(title="SpecStyle") as demo:
        gr.Markdown("# SpecStyle StyleOps")
        with gr.Tab("Spec (UI-001)"):
            spec_in = gr.Textbox(label="Style Spec YAML/JSON", lines=12)
            compile_out = gr.Textbox(label="Compile result")
            gr.Button("Compile").click(
                on_compile, inputs=[spec_in], outputs=[compile_out]
            )
        with gr.Tab("Preview"):
            preview_source = gr.File(label="Preview source image")
            preview_style = gr.File(label="Preview style reference")
            preview_spec = gr.File(label="Preview spec")
            preview_positive = gr.Textbox(label="Preview positive prompt")
            preview_negative = gr.Textbox(label="Preview negative prompt")
            preview_readiness = gr.Textbox(label="Preview readiness")
            gr.Button("Refresh preview readiness").click(
                on_preview_readiness,
                outputs=[preview_readiness],
                **_production_event_options("control"),
            )
            preview_status = gr.Textbox(label="Preview run status")
            preview_gallery = gr.Gallery(label="Preview output")
            preview_evidence = gr.Textbox(label="Preview execution evidence")
            gr.Button("Run preview").click(
                on_run_preview,
                inputs=[
                    preview_source,
                    preview_style,
                    preview_spec,
                    preview_positive,
                    preview_negative,
                ],
                outputs=[preview_status, preview_gallery, preview_evidence],
                **_production_event_options("run"),
            )
            preview_wall_count = gr.Slider(
                minimum=1,
                maximum=4,
                step=1,
                value=4,
                label="Engineering wall seeds",
            )
            preview_wall_status = gr.Textbox(label="Engineering wall status")
            preview_wall_gallery = gr.Gallery(
                label="Engineering wall output",
                columns=4,
                rows=1,
                height=360,
                object_fit="contain",
            )
            preview_wall_evidence = gr.Textbox(
                label="Engineering-only evidence", lines=10
            )
            gr.Button("Generate engineering wall").click(
                on_run_preview_wall,
                inputs=[
                    preview_source,
                    preview_style,
                    preview_spec,
                    preview_positive,
                    preview_negative,
                    preview_wall_count,
                ],
                outputs=[
                    preview_wall_status,
                    preview_wall_gallery,
                    preview_wall_evidence,
                ],
                **_production_event_options("run"),
            )
        with gr.Tab("Job / QA (UI-002)"):
            source_file = gr.File(label="Source image")
            style_file = gr.File(label="Style reference")
            production_spec = gr.File(label="Production spec")
            positive_prompt = gr.Textbox(label="Positive prompt")
            negative_prompt = gr.Textbox(label="Negative prompt")
            source_url = gr.Textbox(label="Source URL")
            license_ = gr.Textbox(label="License")
            attribution = gr.Textbox(label="Attribution")
            consent = gr.Dropdown(
                choices=["not_applicable", "obtained"],
                value="not_applicable",
                label="Consent",
            )
            run_status = gr.Textbox(label="Production run status")
            approved_gallery = gr.Gallery(label="Approved")
            rejected_gallery = gr.Gallery(label="Rejected")
            run_qa = gr.Textbox(label="Production QA table")
            gr.Button("Run production").click(
                on_run_production,
                inputs=[
                    source_file,
                    style_file,
                    production_spec,
                    positive_prompt,
                    negative_prompt,
                    source_url,
                    license_,
                    attribution,
                    consent,
                ],
                outputs=[run_status, approved_gallery, rejected_gallery, run_qa],
                **_production_event_options("run"),
            )
            batch_count = gr.Slider(
                minimum=2,
                maximum=4,
                step=1,
                value=4,
                label="Batch seeds",
            )
            batch_status = gr.Textbox(label="Batch status")
            batch_approved = gr.Gallery(label="Approved batch wall")
            batch_rejected = gr.Gallery(label="Rejected batch wall")
            batch_evidence = gr.Textbox(label="Batch evidence TSV", lines=8)
            gr.Button("Run batch").click(
                on_run_production_batch,
                inputs=[
                    source_file,
                    style_file,
                    production_spec,
                    positive_prompt,
                    negative_prompt,
                    source_url,
                    license_,
                    attribution,
                    consent,
                    batch_count,
                ],
                outputs=[
                    batch_status,
                    batch_approved,
                    batch_rejected,
                    batch_evidence,
                ],
                **_production_event_options("run"),
            )
            status_out = gr.Textbox(label="Job status (preview|production labeled)")
            gr.Button("Refresh status").click(
                on_status,
                outputs=[status_out],
                **_production_event_options("control"),
            )
            gr.Button("Cancel job").click(
                on_cancel,
                outputs=[status_out],
                **_production_event_options("control"),
            )
            qa_out = gr.Textbox(label="QA table (UNVERIFIABLE not green PASS)")
            gr.Button("Refresh QA").click(
                on_qa,
                outputs=[qa_out],
                **_production_event_options("control"),
            )
        with gr.Tab("Repair / Export / Replay (UI-003)"):
            repair_out = gr.Textbox(label="Repair timeline")
            gr.Button("Repair timeline").click(
                on_repair,
                outputs=[repair_out],
                **_production_event_options("control"),
            )
            export_out = gr.Textbox(label="Export summary")
            gr.Button("Export summary").click(
                on_export,
                outputs=[export_out],
                **_production_event_options("control"),
            )
            replay_out = gr.Textbox(label="Replay assessment")
            gr.Button("Replay").click(
                on_replay,
                inputs=[
                    source_file,
                    style_file,
                    production_spec,
                    positive_prompt,
                    negative_prompt,
                    source_url,
                    license_,
                    attribution,
                    consent,
                ],
                outputs=[replay_out],
                **_production_event_options("run"),
            )
    return _enable_production_queue(demo)


def launch_app(services: UiServices, **kwargs: object) -> Any:
    app = create_app(services)
    return app.launch(**kwargs)


# Re-export presenters helpers for tests without Gradio
__all__ = [
    "UiServices",
    "bind_job_result_services",
    "build_default_services",
    "create_app",
    "launch_app",
    "ExportView",
    "JobStatusView",
    "ProductionBatchUiView",
    "ProductionRunUiView",
    "PreviewReadinessUiView",
    "PreviewRunUiView",
    "PreviewWallUiView",
    "QaRuleView",
    "RepairStepView",
    "ReplayView",
    "SpecEditorView",
    "format_qa_table",
    "present_export",
    "present_job_status",
    "present_qa_report",
    "present_repair_timeline",
    "present_replay",
    "present_spec_compile",
]
