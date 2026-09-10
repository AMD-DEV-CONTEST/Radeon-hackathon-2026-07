"""UI presenters: map domain objects to view models; redact errors."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.errors import DomainError, SpecStyleError
from specstyle.exporting.bundle import ExportBundle
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.compiled_models import CompilerContext
from specstyle.spec.loader import load_style_spec_text
from specstyle.spec.replay import ReplayAssessment
from specstyle.ui.view_models import (
    ExportView,
    JobStatusView,
    QaRuleView,
    RepairStepView,
    ReplayView,
    SpecEditorView,
)
from specstyle.verification.rule_models import RuleResult, VerificationReport
from specstyle.workflow.job_models import JobStatus
from specstyle.workflow.orchestrator import FakeJobResult

_STATUS_CLASS = {
    "PASS": "pass",
    "FAIL": "fail",
    "WARNING": "warning",
    "UNVERIFIABLE": "unverifiable",
}


def _redact(exc: BaseException) -> str:
    if isinstance(exc, SpecStyleError):
        return str(exc)
    return "internal error"


def present_spec_compile(spec_text: str, context: CompilerContext, /) -> SpecEditorView:
    try:
        raw = load_style_spec_text(spec_text)
        compiled = compile_style_spec(raw, context)
        return SpecEditorView(
            raw.schema_version,
            raw.metadata.spec_id,
            True,
            (),
            compiled.compiled_spec_hash.value,
        )
    except Exception as exc:
        return SpecEditorView("?", "?", False, (_redact(exc),), None)


def present_job_status(
    job_id: str,
    status: JobStatus | str,
    message: str = "",
    *,
    profile: str = "production",
) -> JobStatusView:
    value = status.value if isinstance(status, JobStatus) else str(status)
    if profile not in ("preview", "production", ""):
        raise DomainError("invalid profile label")
    terminal = value in ("COMPLETED", "JOB_FAILED", "CANCELLED")
    return JobStatusView(
        job_id, value, message, can_cancel=not terminal, profile_label=profile
    )


def present_qa_report(report: VerificationReport) -> tuple[QaRuleView, ...]:
    if type(report) is not VerificationReport:
        raise DomainError("invalid report")
    views: list[QaRuleView] = []
    for result in report.results:
        if type(result) is not RuleResult:
            continue
        status = result.status.value
        # Never present UNVERIFIABLE as PASS/green.
        if result.status is RuleStatus.UNVERIFIABLE and status == "PASS":
            raise DomainError("unverifiable presented as pass")
        views.append(
            QaRuleView(
                result.rule_id.value,
                status,
                result.score,
                _STATUS_CLASS.get(status, "fail"),
            )
        )
    return tuple(views)


def present_export(result: FakeJobResult) -> ExportView:
    if type(result) is not FakeJobResult:
        raise DomainError("invalid job result")
    approved = rejected = review = 0
    for cohort in result.cohorts:
        for item in cohort.items:
            st = item.terminal.artifact_decision.artifact_status.value
            if st == "APPROVED":
                approved += 1
            elif st == "REJECTED":
                rejected += 1
            else:
                review += 1
    bundle_hash = None
    name = ""
    if isinstance(result.bundle, ExportBundle):
        bundle_hash = result.bundle.bundle_sha256.value
        name = result.bundle.bundle_name
    return ExportView(name, approved, rejected, review, bundle_hash)


def present_repair_timeline(result: FakeJobResult) -> tuple[RepairStepView, ...]:
    if type(result) is not FakeJobResult:
        raise DomainError("invalid job result")
    steps: list[RepairStepView] = []
    for history, terminal in zip(result.histories, result.terminals, strict=False):
        stop = None
        if terminal.artifact_decision.repair_stop_reason is not None:
            stop = terminal.artifact_decision.repair_stop_reason.value
        steps.append(
            RepairStepView(
                history.current_target_artifact_id.value,
                history.rounds,
                stop,
            )
        )
    # histories without paired terminal
    if len(result.histories) > len(result.terminals):
        for history in result.histories[len(result.terminals) :]:
            steps.append(
                RepairStepView(
                    history.current_target_artifact_id.value, history.rounds, None
                )
            )
    return tuple(steps)


def present_replay(assessment: ReplayAssessment) -> ReplayView:
    if type(assessment) is not ReplayAssessment:
        raise DomainError("invalid replay assessment")
    return ReplayView(assessment.status, assessment.mode, assessment.reasons)


def format_qa_table(views: tuple[QaRuleView, ...]) -> str:
    """Human-readable QA table; UNVERIFIABLE never shown as PASS."""
    lines = ["rule_id\tstatus\tscore\tclass"]
    for v in views:
        if v.status == "UNVERIFIABLE" and v.display_class == "pass":
            raise DomainError("unverifiable presented as pass")
        score = "" if v.score is None else f"{v.score:.4f}"
        lines.append(f"{v.rule_id}\t{v.status}\t{score}\t{v.display_class}")
    return "\n".join(lines)
