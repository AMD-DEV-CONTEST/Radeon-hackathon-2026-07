"""REL-001 fault injection against real shipped fail-closed entry points.

OOM/cancel drive ``run_production_job``. Fixtures live in
``specstyle.reliability.fixtures`` (no ``tests.*`` imports).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleScope, StaticApplicability
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.bundle import ExportBundle, export_bundle
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.model_registry import ModelRegistry
from specstyle.reliability.fixtures import (
    CannyBuilder,
    ScriptedVerifier,
    sample_approved_export_request,
    sample_compiled,
    sample_context_with_style_low,
    sample_environment,
    sample_materials,
    sample_plan,
    sample_prompt,
    sample_root_request,
    sample_source,
    sample_spec_text,
)
from specstyle.verification.l1.decode import rule_decode
from specstyle.verification.protocols import run_verifier
from specstyle.verification.rule_models import GatePolicy, RuleDefinition
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.orchestrator import FakeJobResult
from specstyle.workflow.real_pipeline import (
    CancelToken,
    PipelineServices,
    _CancellableBackend,
    _FaultyBackend,
    assert_export_isolation,
    run_production_job,
)

FaultKind = Literal[
    "corrupt_image",
    "model_missing",
    "oom",
    "verifier_unavailable",
    "hash_mismatch",
    "disk_failure",
    "cancel",
]


@dataclass(frozen=True, slots=True)
class FaultScenario:
    kind: FaultKind
    expect_fail_closed: bool = True


@dataclass(frozen=True, slots=True)
class FaultResult:
    kind: FaultKind
    failed_closed: bool
    detail: str


DEFAULT_SCENARIOS: tuple[FaultScenario, ...] = tuple(
    FaultScenario(k)
    for k in (
        "corrupt_image",
        "model_missing",
        "oom",
        "verifier_unavailable",
        "hash_mismatch",
        "disk_failure",
        "cancel",
    )
)


def _sha(c: str = "a") -> Sha256:
    return Sha256(c * 64)


def exercise_fault(kind: FaultKind) -> FaultResult:
    """Drive real shipped code paths; return whether fail-closed held."""
    if kind == "corrupt_image":
        result = rule_decode(ArtifactId("bad"), b"not-a-png")
        return FaultResult(
            kind, result.status.value == "FAIL", f"l1_decode={result.status.value}"
        )

    if kind == "model_missing":
        try:
            ModelRegistry(()).require_production("missing-model")
            return FaultResult(kind, False, "unexpected_pass")
        except DomainError as exc:
            return FaultResult(kind, True, str(exc))

    if kind == "oom":
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "store").mkdir()
            (root / "out").mkdir()
            store = JobStore(root / "store")
            fd = os.open(os.fspath(root / "out"), os.O_RDONLY | os.O_DIRECTORY)
            try:
                result = run_production_job(
                    spec_text=sample_spec_text(),
                    context=sample_context_with_style_low(),
                    source=sample_source(),
                    prompt=sample_prompt(sample_compiled()),
                    control_builder=CannyBuilder(),
                    environment=sample_environment(),
                    plan=sample_plan(),
                    job_store=store,
                    root_fd=fd,
                    bundle_name="oom-fault",
                    services=PipelineServices(
                        _FaultyBackend(FakeBackend(), 0, "generation OOM"),
                        ScriptedVerifier(),
                    ),
                )
            finally:
                os.close(fd)
            closed = (
                result.final_status == "JOB_FAILED"
                and result.bundle is None
                and not (root / "out" / "oom-fault").exists()
            )
            try:
                assert_export_isolation(result)
            except DomainError:
                closed = False
            return FaultResult(kind, closed, f"status={result.final_status}")

    if kind == "verifier_unavailable":

        class Boom:
            def verify(self, artifacts: Any, rules: Any, /) -> Any:
                raise RuntimeError("detector down")

        policy = GatePolicy("reject", "reject", "reject")
        rules = (
            RuleDefinition(
                RuleId("R1"),
                RuleLevel.L1,
                RuleScope.ITEM,
                True,
                StaticApplicability.APPLICABLE,
                policy,
            ),
        )
        try:
            run_verifier(
                Boom(),
                (ArtifactRef(ArtifactId("a1"), _sha("b")),),
                rules,
            )
            return FaultResult(kind, False, "verifier_passed")
        except InfrastructureError as exc:
            return FaultResult(kind, True, str(exc))

    if kind == "hash_mismatch":
        bogus = FakeJobResult(
            ExportBundle("x", 1, 1, _sha("1"), _sha("2"), _sha("3"), ()),
            (),
            (),
            (),
            "JOB_FAILED",
        )
        try:
            assert_export_isolation(bogus)
            return FaultResult(kind, False, "accepted_bundle_on_failed")
        except DomainError:
            return FaultResult(kind, True, "rejected_bundle_on_failed")

    if kind == "disk_failure":
        # Real ExportRequest + invalid root fd → export target fail-closed.
        request = sample_approved_export_request()
        try:
            export_bundle(request, -1, "diskfail")
            return FaultResult(kind, False, "export_accepted_bad_fd")
        except DomainError as exc:
            return FaultResult(kind, True, str(exc))

    if kind == "cancel":
        token = CancelToken()
        token.cancel()
        closed = True
        detail = "ok"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "store").mkdir()
            (root / "out").mkdir()
            store = JobStore(root / "store")
            fd = os.open(os.fspath(root / "out"), os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    run_production_job(
                        spec_text=sample_spec_text(),
                        context=sample_context_with_style_low(),
                        source=sample_source(),
                        prompt=sample_prompt(sample_compiled()),
                        control_builder=CannyBuilder(),
                        environment=sample_environment(),
                        plan=sample_plan(),
                        job_store=store,
                        root_fd=fd,
                        bundle_name="cancel-fault",
                        services=PipelineServices(FakeBackend(), ScriptedVerifier()),
                        cancel=token,
                    )
                    closed = False
                    detail = "cancel_did_not_raise"
                except DomainError as exc:
                    detail = str(exc)
                    closed = (
                        "cancel" in str(exc)
                        and not (root / "out" / "cancel-fault").exists()
                    )
            finally:
                os.close(fd)
        proxy = _CancellableBackend(FakeBackend(), token)
        try:
            compiled, source, prompt, env, env_hash = sample_materials()
            proxy.generate(sample_root_request(compiled, source, prompt, env_hash))
            closed = False
            detail = f"{detail};proxy_did_not_refuse"
        except DomainError as exc:
            if "cancel" not in str(exc):
                closed = False
            detail = f"{detail};proxy={exc}"
        return FaultResult(kind, closed, detail)

    raise DomainError(f"unknown fault kind: {kind}")


def run_fault_suite(
    scenarios: tuple[FaultScenario, ...],
    injector: Callable[[FaultKind], FaultResult] | None = None,
) -> tuple[FaultResult, ...]:
    if type(scenarios) is not tuple or not scenarios:
        raise DomainError("empty fault suite")
    runner = injector if injector is not None else exercise_fault
    if not callable(runner):
        raise DomainError("invalid injector")
    results: list[FaultResult] = []
    for scenario in scenarios:
        if type(scenario) is not FaultScenario:
            raise DomainError("invalid scenario")
        result = runner(scenario.kind)
        if type(result) is not FaultResult:
            raise DomainError("invalid fault result")
        if scenario.expect_fail_closed and not result.failed_closed:
            raise DomainError(f"fault not fail-closed: {scenario.kind}")
        results.append(result)
    return tuple(results)
