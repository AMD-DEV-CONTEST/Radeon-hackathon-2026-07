"""UI presenters — require happy-path compile_ok; QA fidelity; no Gradio."""

from __future__ import annotations

import json

from specstyle.domain.enums import (
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.domain.artifacts import ArtifactRef
from specstyle.spec.replay import ReplayAssessment
from specstyle.ui.presenters import (
    format_qa_table,
    present_job_status,
    present_qa_report,
    present_replay,
    present_spec_compile,
)
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)
from specstyle.workflow.job_models import JobStatus
from tests.unit.spec.test_compiler import context, raw_spec


def test_present_spec_compile_ok_requires_success() -> None:
    ctx = context()
    data = raw_spec().model_dump(mode="json")
    text = json.dumps(data)
    view = present_spec_compile(text, ctx)
    assert view.compile_ok is True
    assert view.errors == ()
    assert view.compiled_hash is not None
    assert len(view.compiled_hash) == 64
    assert view.spec_id == raw_spec().metadata.spec_id


def test_present_spec_compile_error_path() -> None:
    bad = present_spec_compile("not-yaml: [", context())
    assert bad.compile_ok is False
    assert bad.errors
    assert bad.compiled_hash is None


def test_present_qa_unverifiable_not_pass_class() -> None:
    aid = ArtifactId("a1")
    policy = GatePolicy("reject", "reject", "reject")
    rule = RuleDefinition(
        RuleId("R1"),
        RuleLevel.L2,
        RuleScope.ITEM,
        True,
        StaticApplicability.APPLICABLE,
        policy,
    )
    report = VerificationReport(
        (ArtifactRef(aid, Sha256("a" * 64)),),
        (rule,),
        (RuleResult(RuleId("R1"), RuleStatus.UNVERIFIABLE, (aid,), None),),
    )
    views = present_qa_report(report)
    assert len(views) == 1
    assert views[0].status == "UNVERIFIABLE"
    assert views[0].display_class == "unverifiable"
    assert views[0].display_class != "pass"
    table = format_qa_table(views)
    assert "UNVERIFIABLE" in table
    assert "\tpass" not in table.split("\n")[1]


def test_present_job_status_profile_and_cancel() -> None:
    running = present_job_status("j1", JobStatus.GENERATING, profile="preview")
    assert running.profile_label == "preview"
    assert running.can_cancel is True
    done = present_job_status("j1", "COMPLETED", profile="production")
    assert done.can_cancel is False
    assert done.profile_label == "production"


def test_present_replay() -> None:
    view = present_replay(
        ReplayAssessment("REJECTED", "same_input", ("seed_mismatch",))
    )
    assert view.status == "REJECTED"
    assert "seed_mismatch" in view.reasons
