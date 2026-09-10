"""Fail-closed production verifier static binding tests."""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.enums import RuleScope
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    Identifier,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError
from specstyle.generation.output_profile_contracts import (
    production_output_profile_capabilities,
)
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest, PreparedControlInput
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import ThresholdMetricCapability
from specstyle.spec.compiler import compile_style_spec
from tests.unit.verification._production_fixtures import (
    _ProductionCase,
    _make_production_case,
    _png,
    production_case as production_case,
)


def _request_for_context(
    case: _ProductionCase,
    context: object,
    *,
    environment_hash: Sha256 | None = None,
) -> tuple[GenerationRequest, object]:
    compiled = compile_style_spec(case.request.compiled_spec.source_spec, context)
    original = case.request
    request = GenerationRequest(
        original.job_id,
        original.attempt_id,
        original.parent_attempt_id,
        compiled,
        original.generation_profile,
        original.output_profile,
        original.source,
        original.style_references,
        original.prompt,
        original.control_input,
        original.variation_index,
        original.environment_hash if environment_hash is None else environment_hash,
        original.execution_parameters,
    )
    plans = tuple(
        plan
        for plan in compiled.verification_plans
        if plan.output_profile == request.output_profile
    )
    assert len(plans) == 1
    return request, plans[0]


def _create(
    case: _ProductionCase,
    production: object,
    *,
    context: object | None = None,
    mappings: tuple[tuple[RuleId, str], ...] | None = None,
    request: GenerationRequest | None = None,
    plan: object | None = None,
) -> object:
    selected_context = case.compiler_context if context is None else context
    allowlist = case.allowlist(
        production, compiler_context=selected_context, mappings=mappings
    )
    factory = production._create_production_verifier_factory(case.loaded, allowlist)
    return factory.create(
        case.request if request is None else request,
        case.plan if plan is None else plan,
        case.artifact_resolver,
        case.style_resolver,
    )


def _background_case(
    case: _ProductionCase, status: str
) -> tuple[object, GenerationRequest, object, GeneratedArtifact]:
    context = case.compiler_context
    catalog = context.rule_catalogs[0]
    rules = tuple(
        replace(
            rule,
            supported_output_profiles=("background_sequence",),
            metric_id=(
                Identifier("batch_style_consistency")
                if rule.scope is RuleScope.BATCH
                else rule.metric_id
            ),
        )
        if rule.level.value in {"L1", "L2"}
        else rule
        for rule in catalog.rules
    )
    l2_profile = context.threshold_profiles[0]
    batch_rule = next(rule for rule in rules if rule.scope is RuleScope.BATCH)
    batch_metric = ThresholdMetricCapability(batch_rule.metric_id, "<=", 0.25)
    context = replace(
        context,
        output_profile_capabilities=production_output_profile_capabilities(),
        rule_catalogs=(replace(catalog, rules=rules),),
        threshold_profiles=(
            replace(
                l2_profile,
                status=status,
                metrics=(*l2_profile.metrics, batch_metric),
            ),
            *context.threshold_profiles[1:],
        ),
    )
    source_type = type(case.request.compiled_spec.source_spec)
    primitive = case.request.compiled_spec.source_spec.model_dump(mode="python")
    primitive["outputs"]["profiles"] = ("background_sequence",)
    primitive["profiles"]["production"]["resolution"] = (768, 768)
    primitive["verification"]["l3"] = None
    compiled = compile_style_spec(source_type.model_validate(primitive), context)
    original = case.request
    source_bytes = original.source.content
    source_ref = AssetRef(AssetId("background-source"), hash_bytes(source_bytes))
    source = preprocess_image(
        source_bytes,
        source_ref,
        PreprocessPlan(
            (768, 768),
            "contain_pad",
            (0, 0, 0),
            original.source.snapshot.plan.processor_pin,
        ),
    )
    request = GenerationRequest(
        original.job_id,
        AttemptId("attempt-background_sequence-0"),
        None,
        compiled,
        "production",
        "background_sequence",
        source,
        original.style_references,
        original.prompt,
        PreparedControlInput("canny", source),
        original.variation_index,
        original.environment_hash,
    )
    content = _png((10, 200, 10), size=(1920, 1080))
    artifact = GeneratedArtifact(
        ArtifactRef(ArtifactId("background-artifact"), hash_bytes(content)),
        content,
        request.request_hash,
        request.generation_fingerprint,
    )
    return context, request, compiled.verification_plans[0], artifact


@pytest.mark.parametrize("mapping_change", ("missing", "extra"))
def test_create_rejects_nonexact_l1_mapping_coverage(
    production_case: _ProductionCase, mapping_change: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    mappings = production_case.l1_mappings
    if mapping_change == "missing":
        mappings = mappings[:-1]
    else:
        mappings = (*mappings, (RuleId("extra"), mappings[0][1]))

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(production_case, production, mappings=mappings)


@pytest.mark.parametrize("mutation", ("metric", "operator", "value"))
def test_create_rejects_nonproduction_l2_metric_contract(
    production_case: _ProductionCase, mutation: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context = production_case.compiler_context
    catalog = context.rule_catalogs[0]
    profile = context.threshold_profiles[0]
    rules = list(catalog.rules)
    l2_index = next(
        index for index, rule in enumerate(rules) if rule.rule_id == RuleId("l2_style")
    )
    metric = profile.metrics[0]
    if mutation == "metric":
        replacement_id = Identifier("other_similarity")
        rules[l2_index] = replace(rules[l2_index], metric_id=replacement_id)
        metric = replace(metric, metric_id=replacement_id)
    elif mutation == "operator":
        metric = replace(metric, operator="<=")
    else:
        metric = replace(metric, value=1.5)
    context = replace(
        context,
        rule_catalogs=(replace(catalog, rules=tuple(rules)),),
        threshold_profiles=(
            replace(profile, metrics=(metric,)),
            *context.threshold_profiles[1:],
        ),
    )
    request, plan = _request_for_context(production_case, context)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=plan,
        )


@pytest.mark.parametrize("mutation", ("kind", "required"))
def test_create_rejects_coarse_or_required_l3_rule(
    production_case: _ProductionCase, mutation: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context = production_case.compiler_context
    plugin = context.l3_plugins[0]
    rule = plugin.rules[0]
    rule = replace(
        rule,
        kind="L3_DOMAIN_FIDELITY" if mutation == "kind" else rule.kind,
        requirement="always_required" if mutation == "required" else rule.requirement,
    )
    context = replace(context, l3_plugins=(replace(plugin, rules=(rule,)),))
    request, plan = _request_for_context(production_case, context)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=plan,
        )


@pytest.mark.parametrize("mutation", ("verifier_pin", "approval"))
def test_create_rejects_unsealed_structure_l3_contract(tmp_path, mutation: str) -> None:
    case = _make_production_case(
        tmp_path,
        l2_status="DRAFT",
        l3_status="VALIDATED",
        l3_kind="L3_DOMAIN_FIDELITY",
        l3_requirement="fidelity_required",
        fidelity_required=True,
        domain_profile="structure_only",
    )
    try:
        production = importlib.import_module("specstyle.verification.production")
        context = case.compiler_context
        if mutation == "verifier_pin":
            plugin = context.l3_plugins[0]
            rule = plugin.rules[0]
            bad_pin = replace(rule.verifier_pin, sha256=Sha256("f" * 64))
            context = replace(
                context,
                l3_plugins=(
                    replace(plugin, rules=(replace(rule, verifier_pin=bad_pin),)),
                ),
            )
        else:
            profiles = list(context.threshold_profiles)
            profiles[1] = replace(profiles[1], production_approval_sha256=None)
            context = replace(context, threshold_profiles=tuple(profiles))
        request, plan = _request_for_context(case, context)

        with pytest.raises(
            DomainError, match="^invalid production verifier dependency$"
        ):
            _create(case, production, context=context, request=request, plan=plan)
        assert case.artifact_resolver.calls == []
        assert case.style_resolver.calls == []
        assert case.evidence_calls == {}
    finally:
        case.close()


@pytest.mark.parametrize("mutation", ("coarse", "required"))
def test_create_rejects_nonadvisory_l3_semantics_when_rule_is_not_applicable(
    production_case: _ProductionCase, mutation: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context = production_case.compiler_context
    plugin = context.l3_plugins[0]
    rule = plugin.rules[0]
    rule = replace(
        rule,
        kind="L3_DOMAIN_FIDELITY" if mutation == "coarse" else rule.kind,
        requirement="always_required" if mutation == "required" else rule.requirement,
        supported_output_profiles=("background_sequence",),
    )
    context = replace(context, l3_plugins=(replace(plugin, rules=(rule,)),))
    request, plan = _request_for_context(production_case, context)
    l3_rule = next(item for item in plan.rules if item.definition.level.value == "L3")
    assert plan.l3_status == "NOT_APPLICABLE"
    assert plan.l3_reason == "NO_APPLICABLE_RULE"
    assert l3_rule.definition.applicability.value == "NOT_APPLICABLE"

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=plan,
        )
    assert production_case.artifact_resolver.calls == []
    assert production_case.style_resolver.calls == []
    assert production_case.evidence_calls == {}


def test_draft_background_batch_rule_is_unverifiable_without_metric_execution(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context, request, plan, artifact = _background_case(production_case, "DRAFT")
    production_case.artifact_resolver.value = artifact
    verifier = _create(
        production_case,
        production,
        context=context,
        request=request,
        plan=plan,
    )

    results = verifier.verify((artifact.ref,), plan.applicable_rule_definitions)

    l2_results = tuple(result for result in results if result.rule_id.value[:2] == "l2")
    assert tuple(result.rule_id.value for result in l2_results) == (
        "l2_batch",
        "l2_style",
    )
    assert all(result.status.value == "UNVERIFIABLE" for result in l2_results)
    assert all(result.score is None for result in l2_results)
    assert all(
        result.affected_artifact_ids == (artifact.ref.artifact_id,)
        for result in l2_results
    )
    assert production_case.style_resolver.calls == []
    assert production_case.evidence_calls == {}


@pytest.mark.parametrize("status", ("CALIBRATED", "VALIDATED"))
def test_create_rejects_non_draft_background_batch_rule(
    production_case: _ProductionCase, status: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context, request, plan, _ = _background_case(production_case, status)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=plan,
        )


def test_create_rejects_request_environment_not_owned_by_loaded_pipeline(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    request, _ = _request_for_context(
        production_case,
        production_case.compiler_context,
        environment_hash=Sha256("f" * 64),
    )

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(production_case, production, request=request)


def test_create_rejects_equal_but_nonmember_plan(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(production_case, production, plan=replace(production_case.plan))
