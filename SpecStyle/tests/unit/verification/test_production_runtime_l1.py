"""Bound production verifier resolver, invocation, and L1 contracts."""

from __future__ import annotations

import importlib
import traceback
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, PngImagePlugin

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RepairStopReason, RuleStatus
from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.actions import RETRY_SAMPLING
from specstyle.repair.loop import NextGeneration
from specstyle.verification.rule_models import VerificationReport
from tests.unit.verification._production_fixtures import (
    _ProductionCase,
    _make_production_case,
    _png,
)


@pytest.fixture
def draft_case(tmp_path: Path) -> Any:
    case = _make_production_case(tmp_path, l2_status="DRAFT", l3_status="CALIBRATED")
    try:
        yield case
    finally:
        case.close()


def _bind(case: _ProductionCase) -> tuple[object, tuple[object, ...]]:
    production = importlib.import_module("specstyle.verification.production")
    factory = production._create_production_verifier_factory(
        case.loaded, case.allowlist(production)
    )
    verifier = factory.create(
        case.request,
        case.plan,
        case.artifact_resolver,
        case.style_resolver,
    )
    return verifier, case.plan.applicable_rule_definitions


def _artifact(case: _ProductionCase, content: bytes) -> GeneratedArtifact:
    return GeneratedArtifact(
        ArtifactRef(case.artifact.ref.artifact_id, hash_bytes(content)),
        content,
        case.request.request_hash,
        case.request.generation_fingerprint,
    )


def _attempt_artifact(
    request: GenerationRequest, artifact_id: str, content: bytes
) -> GeneratedArtifact:
    return GeneratedArtifact(
        ArtifactRef(ArtifactId(artifact_id), hash_bytes(content)),
        content,
        request.request_hash,
        request.generation_fingerprint,
    )


def _statuses(results: tuple[object, ...]) -> dict[str, RuleStatus]:
    return {result.rule_id.value: result.status for result in results}


def _multiframe_gif() -> bytes:
    frames = [Image.new("RGB", (64, 64), color) for color in ((1, 2, 3), (4, 5, 6))]
    output = BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
    return output.getvalue()


def _metadata_png() -> bytes:
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("comment", "forbidden")
    return _png(metadata=metadata)


def test_verify_returns_canonical_applicable_results_without_na_or_gpu(
    draft_case: _ProductionCase,
) -> None:
    verifier, rules = _bind(draft_case)

    results = verifier.verify((draft_case.artifact.ref,), rules)

    assert tuple(result.rule_id.value for result in results) == tuple(
        sorted(rule.rule_id.value for rule in rules)
    )
    assert all(result.rule_id.value != "l2_batch" for result in results)
    assert _statuses(results) == {
        "l1_bundle": RuleStatus.PASS,
        "l1_decode": RuleStatus.PASS,
        "l1_dimensions": RuleStatus.PASS,
        "l1_pixels": RuleStatus.PASS,
        "l2_style": RuleStatus.UNVERIFIABLE,
        "l3_diagnostic": RuleStatus.UNVERIFIABLE,
    }
    assert draft_case.artifact_resolver.calls == [draft_case.artifact.ref]
    assert draft_case.style_resolver.calls == []
    assert draft_case.evidence_calls == {}


def test_real_production_l1_bundle_failure_retries_and_guardrail_accepts_child(
    tmp_path: Path,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    repair = importlib.import_module("specstyle.workflow.production_repair")
    case = _make_production_case(
        tmp_path,
        l2_status="DRAFT",
        l3_status="DRAFT",
        l1_bundle_actions=(RETRY_SAMPLING,),
    )
    try:
        factory = production._create_production_verifier_factory(
            case.loaded, case.allowlist(production)
        )
        rules = case.plan.applicable_rule_definitions

        def verify(
            request: GenerationRequest, artifact: GeneratedArtifact
        ) -> VerificationReport:
            case.artifact_resolver.value = artifact
            verifier = factory.create(
                request,
                case.plan,
                case.artifact_resolver,
                case.style_resolver,
            )
            results = verifier.verify((artifact.ref,), rules)
            return VerificationReport((artifact.ref,), rules, results)

        initial = _attempt_artifact(
            case.request, "fault-injected-initial", _png((0, 0, 0))
        )
        initial_report = verify(case.request, initial)
        initial_statuses = _statuses(initial_report.results)

        assert initial_statuses == {
            "l1_bundle": RuleStatus.FAIL,
            "l1_decode": RuleStatus.PASS,
            "l1_dimensions": RuleStatus.PASS,
            "l1_pixels": RuleStatus.FAIL,
            "l2_style": RuleStatus.UNVERIFIABLE,
            "l3_diagnostic": RuleStatus.UNVERIFIABLE,
        }
        l2_rule = next(rule for rule in rules if rule.rule_id.value == "l2_style")
        assert l2_rule.required is False

        composed = repair._compose_initial_repair(case.request, initial, initial_report)

        assert type(composed.step) is NextGeneration
        assert composed.step.decision.trigger_rule_id.value == "l1_bundle"
        assert composed.step.decision.action_id == RETRY_SAMPLING
        assert (
            composed.step.decision.patch.after_parameters
            == composed.step.decision.patch.before_parameters
        )
        assert composed.step.request.parent_attempt_id == case.request.attempt_id
        assert composed.step.request.variation_index == case.request.variation_index + 1
        assert composed.step.request.seed != case.request.seed
        assert composed.step.request.request_hash != case.request.request_hash

        child = _attempt_artifact(
            composed.step.request, "artifact-child", _png((10, 200, 10))
        )
        child_report = verify(composed.step.request, child)
        terminal = repair._compose_repair_result(
            composed.history, composed.step, child, child_report
        )

        assert _statuses(child_report.results) == {
            "l1_bundle": RuleStatus.PASS,
            "l1_decode": RuleStatus.PASS,
            "l1_dimensions": RuleStatus.PASS,
            "l1_pixels": RuleStatus.PASS,
            "l2_style": RuleStatus.UNVERIFIABLE,
            "l3_diagnostic": RuleStatus.UNVERIFIABLE,
        }
        assert terminal.history.rounds == 1
        assert len(terminal.history.repair_attempts) == 1
        assert terminal.history.consecutive_no_improvement == 0
        assert (
            terminal.terminal.artifact_decision.repair_stop_reason
            is RepairStopReason.PASS_ALL_REQUIRED
        )
    finally:
        case.close()


def test_l1_uses_existing_decoded_dimension_and_pixel_primitives(
    draft_case: _ProductionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    dimensions = production.check_dimensions_decoded
    pixels = production.check_pixels_decoded
    calls: list[tuple[str, object, object]] = []

    def dimension_spy(*args: object) -> object:
        calls.append(("dimensions", args[0], args[2]))
        return dimensions(*args)

    def pixel_spy(*args: object) -> object:
        calls.append(("pixels", args[0], None))
        return pixels(*args)

    monkeypatch.setattr(production, "check_dimensions_decoded", dimension_spy)
    monkeypatch.setattr(production, "check_pixels_decoded", pixel_spy)
    verifier, rules = _bind(draft_case)

    results = verifier.verify((draft_case.artifact.ref,), rules)

    assert calls == [
        ("dimensions", draft_case.artifact.ref.artifact_id, (64, 64)),
        ("pixels", draft_case.artifact.ref.artifact_id, None),
    ]
    assert {result.rule_id.value for result in results} >= {
        "l1_dimensions",
        "l1_pixels",
    }


@pytest.mark.parametrize("artifact_count", (0, 2))
def test_verify_rejects_any_artifact_count_other_than_one_before_resolution(
    draft_case: _ProductionCase, artifact_count: int
) -> None:
    verifier, rules = _bind(draft_case)
    artifacts = (draft_case.artifact.ref,) * artifact_count

    with pytest.raises(DomainError):
        verifier.verify(artifacts, rules)
    assert draft_case.artifact_resolver.calls == []


@pytest.mark.parametrize("mutation", ("missing", "reordered", "extra", "equal_copy"))
def test_verify_requires_canonical_rule_member_identity_and_order(
    draft_case: _ProductionCase, mutation: str
) -> None:
    verifier, canonical = _bind(draft_case)
    if mutation == "missing":
        rules = canonical[:-1]
    elif mutation == "reordered":
        rules = tuple(reversed(canonical))
    elif mutation == "extra":
        rules = (*canonical, canonical[0])
    else:
        rules = (replace(canonical[0]), *canonical[1:])

    with pytest.raises(DomainError):
        verifier.verify((draft_case.artifact.ref,), rules)
    assert draft_case.artifact_resolver.calls == []


def test_missing_artifact_returns_only_unverifiable_results(
    draft_case: _ProductionCase,
) -> None:
    verifier, rules = _bind(draft_case)
    draft_case.artifact_resolver.value = None

    results = verifier.verify((draft_case.artifact.ref,), rules)

    assert all(result.status is RuleStatus.UNVERIFIABLE for result in results)
    assert all(result.score is None for result in results)


def test_artifact_resolver_exception_has_frozen_error_and_no_partial_return(
    draft_case: _ProductionCase,
) -> None:
    verifier, rules = _bind(draft_case)
    secret = "secret-artifact-resolver-detail"
    draft_case.artifact_resolver.error = RuntimeError(secret)

    with pytest.raises(
        InfrastructureError,
        match="^production verification artifact resolution failed$",
    ) as raised:
        verifier.verify((draft_case.artifact.ref,), rules)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert draft_case.style_resolver.calls == []
    assert draft_case.evidence_calls == {}


@pytest.mark.parametrize(
    "mutation",
    ("wrong_type", "ref", "content_sha", "request_hash", "fingerprint"),
)
def test_artifact_resolver_contract_mismatch_fails_closed(
    draft_case: _ProductionCase, mutation: str
) -> None:
    verifier, rules = _bind(draft_case)
    if mutation == "wrong_type":
        value: object = object()
    elif mutation == "ref":
        value = GeneratedArtifact(
            ArtifactRef(ArtifactId("other"), draft_case.artifact.ref.sha256),
            draft_case.artifact.content,
            draft_case.request.request_hash,
            draft_case.request.generation_fingerprint,
        )
    elif mutation == "request_hash":
        value = replace(draft_case.artifact, request_hash=Sha256("1" * 64))
    elif mutation == "fingerprint":
        value = replace(draft_case.artifact, generation_fingerprint=Sha256("2" * 64))
    else:
        value = replace(draft_case.artifact)
        object.__setattr__(value, "content", b"tampered")
    draft_case.artifact_resolver.value = value

    with pytest.raises(
        InfrastructureError, match="^production verification contract violation$"
    ):
        verifier.verify((draft_case.artifact.ref,), rules)
    assert draft_case.style_resolver.calls == []
    assert draft_case.evidence_calls == {}


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (
            b"not-an-image",
            ("FAIL", "FAIL", "UNVERIFIABLE", "UNVERIFIABLE"),
        ),
        (_png(size=(32, 64)), ("FAIL", "PASS", "FAIL", "PASS")),
        (_png((0, 0, 0)), ("FAIL", "PASS", "PASS", "FAIL")),
        (_png((255, 255, 255)), ("FAIL", "PASS", "PASS", "FAIL")),
        (_png(size=(4, 4)), ("FAIL", "PASS", "FAIL", "FAIL")),
    ),
)
def test_l1_mapping_rebuilds_compiled_rule_ids_and_statuses(
    draft_case: _ProductionCase,
    content: bytes,
    expected: tuple[str, str, str, str],
) -> None:
    verifier, rules = _bind(draft_case)
    artifact = _artifact(draft_case, content)
    draft_case.artifact_resolver.value = artifact

    results = verifier.verify((artifact.ref,), rules)
    statuses = _statuses(results)

    assert (
        statuses["l1_bundle"],
        statuses["l1_decode"],
        statuses["l1_dimensions"],
        statuses["l1_pixels"],
    ) == tuple(RuleStatus(value) for value in expected)


@pytest.mark.parametrize(
    "content",
    (
        _multiframe_gif(),
        _png(mode="L"),
        _metadata_png(),
    ),
)
def test_l1_decode_classifies_multiframe_non_rgb_and_metadata_as_hard_fail(
    draft_case: _ProductionCase, content: bytes
) -> None:
    verifier, rules = _bind(draft_case)
    artifact = _artifact(draft_case, content)
    draft_case.artifact_resolver.value = artifact

    statuses = _statuses(verifier.verify((artifact.ref,), rules))

    assert statuses["l1_bundle"] is RuleStatus.FAIL
    assert statuses["l1_decode"] is RuleStatus.FAIL
    assert statuses["l1_dimensions"] is RuleStatus.UNVERIFIABLE
    assert statuses["l1_pixels"] is RuleStatus.UNVERIFIABLE


@pytest.fixture
def style_contract_case(tmp_path: Path) -> Any:
    case = _make_production_case(tmp_path, l2_status="VALIDATED", l3_status="DRAFT")
    try:
        yield case
    finally:
        case.close()


def test_missing_style_evidence_makes_l2_unverifiable_without_encoding(
    style_contract_case: _ProductionCase,
) -> None:
    verifier, rules = _bind(style_contract_case)
    style_contract_case.style_resolver.values.clear()

    results = verifier.verify((style_contract_case.artifact.ref,), rules)

    l2 = next(result for result in results if result.rule_id.value == "l2_style")
    assert l2.status is RuleStatus.UNVERIFIABLE
    assert l2.score is None
    assert style_contract_case.evidence_calls == {}


def test_style_resolver_exception_has_frozen_error_and_no_partial_return(
    style_contract_case: _ProductionCase,
) -> None:
    verifier, rules = _bind(style_contract_case)
    secret = "secret-style-resolver-detail"
    style_contract_case.style_resolver.error = RuntimeError(secret)

    with pytest.raises(
        InfrastructureError,
        match="^production verification style resolution failed$",
    ) as raised:
        verifier.verify((style_contract_case.artifact.ref,), rules)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert secret not in "".join(traceback.format_exception(raised.value))
    assert style_contract_case.evidence_calls == {}


@pytest.mark.parametrize("value", (object(), b"wrong-style-content"))
def test_style_resolver_wrong_type_or_hash_is_contract_violation(
    style_contract_case: _ProductionCase, value: object
) -> None:
    verifier, rules = _bind(style_contract_case)
    reference = style_contract_case.request.style_references[0]
    style_contract_case.style_resolver.values[reference] = value

    with pytest.raises(
        InfrastructureError, match="^production verification contract violation$"
    ):
        verifier.verify((style_contract_case.artifact.ref,), rules)
    assert style_contract_case.evidence_calls == {}
