"""Independent field mutation tests for production verifier capabilities."""

from __future__ import annotations

import copy
import importlib
import pickle
from dataclasses import replace
from pathlib import Path

import pytest

from specstyle.domain.identifiers import Identifier, RuleId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.spec.compiled_models import CompiledStyleSpec
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from tests.unit.verification._production_fixtures import (
    _ProductionCase,
    _make_production_case,
    production_case as production_case,
)
from tests.unit.verification.test_production_static_contract import _create


_CONTRACT_ERROR = "^production verification contract violation$"


def _request_with_compiled(
    case: _ProductionCase, compiled: CompiledStyleSpec
) -> GenerationRequest:
    original = case.request
    return GenerationRequest(
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
        original.environment_hash,
        original.execution_parameters,
    )


def _replace_source(
    case: _ProductionCase, path: tuple[str, ...], value: object
) -> StyleSpecV1:
    data = case.request.compiled_spec.source_spec.model_dump(mode="python")
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return StyleSpecV1.model_validate(data)


def _issued(
    case: _ProductionCase,
) -> tuple[object, object, object, object, tuple[object, ...]]:
    production = importlib.import_module("specstyle.verification.production")
    allowlist = case.allowlist(production)
    factory = production._create_production_verifier_factory(case.loaded, allowlist)
    verifier = factory.create(
        case.request,
        case.plan,
        case.artifact_resolver,
        case.style_resolver,
    )
    return (
        production,
        allowlist,
        factory,
        verifier,
        case.plan.applicable_rule_definitions,
    )


def _mutate_l2_threshold(case: _ProductionCase) -> None:
    rule = next(
        rule for rule in case.plan.rules if rule.definition.rule_id.value == "l2_style"
    )
    object.__setattr__(rule.threshold_binding, "value", 0.75)


def _overwrite_request(target: GenerationRequest, source: GenerationRequest) -> None:
    for field in (
        "job_id",
        "attempt_id",
        "parent_attempt_id",
        "compiled_spec",
        "generation_profile",
        "output_profile",
        "source",
        "style_references",
        "prompt",
        "control_input",
        "variation_index",
        "environment_hash",
        "execution_parameters",
        "seed",
        "request_hash",
        "generation_fingerprint",
    ):
        object.__setattr__(target, field, getattr(source, field))


def test_verify_rejects_l2_threshold_drift_after_binding(
    production_case: _ProductionCase,
) -> None:
    _production, _allowlist, _factory, verifier, rules = _issued(production_case)
    _mutate_l2_threshold(production_case)

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)
    assert production_case.artifact_resolver.calls == []


@pytest.mark.parametrize("mutation", ("exchange", "replace", "reorder"))
def test_verify_rejects_l1_mapping_identity_order_or_semantic_drift(
    production_case: _ProductionCase, mutation: str
) -> None:
    production, allowlist, _factory, verifier, rules = _issued(production_case)
    mappings = allowlist.l1_rule_mappings
    if mutation == "exchange":
        mappings = (
            production._L1RuleMapping(mappings[0].rule_id, mappings[1].implementation),
            production._L1RuleMapping(mappings[1].rule_id, mappings[0].implementation),
            *mappings[2:],
        )
    elif mutation == "replace":
        mappings = (
            production._L1RuleMapping(mappings[0].rule_id, mappings[0].implementation),
            *mappings[1:],
        )
    else:
        mappings = tuple(reversed(mappings))
    object.__setattr__(allowlist, "l1_rule_mappings", mappings)

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)
    assert production_case.artifact_resolver.calls == []


@pytest.mark.parametrize(
    "field",
    ("_factory", "_request", "_plan", "_artifact_resolver", "_style_resolver"),
)
def test_verify_rejects_bound_capability_replacement(
    production_case: _ProductionCase, field: str
) -> None:
    production, _allowlist, _factory, verifier, rules = _issued(production_case)
    replacements = {
        "_factory": production._create_production_verifier_factory(
            production_case.loaded, production_case.allowlist(production)
        ),
        "_request": _request_with_compiled(
            production_case, production_case.request.compiled_spec
        ),
        "_plan": replace(production_case.plan),
        "_artifact_resolver": lambda _reference: production_case.artifact,
        "_style_resolver": lambda reference: production_case.style_resolver.values.get(
            reference
        ),
    }
    object.__setattr__(verifier, field, replacements[field])

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)


@pytest.mark.parametrize("field", ("_loaded", "_allowlist", "_evidence"))
def test_verify_rejects_factory_dependency_replacement(
    production_case: _ProductionCase, field: str
) -> None:
    production, _allowlist, factory, verifier, rules = _issued(production_case)
    replacements = {
        "_loaded": object(),
        "_allowlist": production_case.allowlist(production),
        "_evidence": production_case.loaded._borrow_image_evidence_encoder(),
    }
    object.__setattr__(factory, field, replacements[field])

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)


@pytest.mark.parametrize("mutation", ("nonexact_type", "wrong_owner"))
def test_verify_requires_exact_issued_evidence_type_and_owner(
    production_case: _ProductionCase, mutation: str
) -> None:
    production, _allowlist, factory, verifier, rules = _issued(production_case)
    evidence = factory._evidence
    if mutation == "nonexact_type":
        forged_type = type("ForgedEvidence", (type(evidence),), {})
        forged = object.__new__(forged_type)
        object.__setattr__(forged, "_owner", production_case.loaded)
        object.__setattr__(forged, "_seal", evidence._seal)
        object.__setattr__(factory, "_evidence", forged)
    else:
        object.__setattr__(evidence, "_owner", object())

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)
    assert production_case.artifact_resolver.calls == []


@pytest.mark.parametrize("mutation", ("variation_and_seed", "prompt_input"))
def test_verify_rejects_synchronized_request_and_matching_artifact_forgery(
    production_case: _ProductionCase, mutation: str
) -> None:
    _production, _allowlist, _factory, verifier, rules = _issued(production_case)
    changes = (
        {"variation_index": production_case.request.variation_index + 1}
        if mutation == "variation_and_seed"
        else {"prompt": replace(production_case.request.prompt, positive="forged")}
    )
    forged = replace(production_case.request, **changes)
    _overwrite_request(production_case.request, forged)
    production_case.artifact_resolver.value = GeneratedArtifact(
        production_case.artifact.ref,
        production_case.artifact.content,
        forged.request_hash,
        forged.generation_fingerprint,
    )

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)


@pytest.mark.parametrize(
    "mutation", ("request_hash", "fingerprint", "compiled_hash", "plan_state")
)
def test_verify_rejects_request_compiled_or_plan_hash_drift(
    production_case: _ProductionCase, mutation: str
) -> None:
    _production, _allowlist, _factory, verifier, rules = _issued(production_case)
    if mutation == "request_hash":
        object.__setattr__(production_case.request, "request_hash", Sha256("a" * 64))
    elif mutation == "fingerprint":
        object.__setattr__(
            production_case.request, "generation_fingerprint", Sha256("b" * 64)
        )
    elif mutation == "compiled_hash":
        object.__setattr__(
            production_case.request.compiled_spec,
            "compiled_spec_hash",
            Sha256("c" * 64),
        )
    else:
        object.__setattr__(production_case.plan, "l3_status", "NOT_APPLICABLE")
    production_case.artifact_resolver.value = GeneratedArtifact(
        production_case.artifact.ref,
        production_case.artifact.content,
        production_case.request.request_hash,
        production_case.request.generation_fingerprint,
    )

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)


@pytest.mark.parametrize("dependency", ("torch", "context"))
def test_verify_rejects_nested_runtime_dependency_identity_replacement(
    production_case: _ProductionCase, dependency: str
) -> None:
    _production, allowlist, _factory, verifier, rules = _issued(production_case)
    if dependency == "torch":
        replacement = copy.copy(production_case.torch)
        object.__setattr__(production_case.loaded, "_torch", replacement)
        assert replacement is not production_case.torch
    else:
        object.__setattr__(
            allowlist, "compiler_context", copy.deepcopy(allowlist.compiler_context)
        )

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)


@pytest.mark.parametrize("target", ("loaded", "allowlist", "shared"))
def test_verify_rejects_processor_provenance_drift_after_binding(
    production_case: _ProductionCase, target: str
) -> None:
    _production, allowlist, _factory, verifier, rules = _issued(production_case)
    original = production_case.loaded._processor_provenance
    changed = replace(original, transformers_version="99.0.0")
    if target in {"loaded", "shared"}:
        object.__setattr__(production_case.loaded, "_processor_provenance", changed)
    if target == "allowlist":
        object.__setattr__(allowlist, "processor_provenance", changed)
    elif target == "shared":
        object.__setattr__(original, "transformers_version", "99.0.0")

    with pytest.raises(InfrastructureError, match=_CONTRACT_ERROR):
        verifier.verify((production_case.artifact.ref,), rules)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "specstyle.production_verifier.v2"),
        ("compiler_context", object()),
        ("processor_provenance", object()),
        ("l1_rule_mappings", []),
        ("l1_rule_mappings", ()),
        ("l1_rule_mappings", (object(),)),
    ),
)
def test_allowlist_rejects_each_nonexact_field(
    production_case: _ProductionCase, field: str, value: object
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    capability = production_case.loaded._borrow_image_evidence_encoder()
    values = {
        "schema_version": "specstyle.production_verifier.v1",
        "compiler_context": production_case.compiler_context,
        "processor_provenance": capability.processor_provenance,
        "l1_rule_mappings": tuple(
            production._L1RuleMapping(*entry) for entry in production_case.l1_mappings
        ),
    }
    values[field] = value

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        production._ProductionVerificationAllowlist(**values)


@pytest.mark.parametrize("implementation", ("", "fake", object()))
def test_l1_mapping_rejects_nonallowlisted_implementation(
    implementation: object,
) -> None:
    production = importlib.import_module("specstyle.verification.production")

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        production._L1RuleMapping(RuleId("rule"), implementation)


@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_allowlist_requires_each_l1_implementation_exactly_once(
    production_case: _ProductionCase, mutation: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    mappings = production_case.l1_mappings
    if mutation == "missing":
        mappings = mappings[:-1]
    else:
        mappings = (
            mappings[0],
            (mappings[1][0], mappings[0][1]),
            *mappings[2:],
        )

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        production_case.allowlist(production, mappings=mappings)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "CALIBRATED"),
        ("operator", "<="),
        ("value", 0.25),
        ("metric_id", Identifier("other_similarity")),
        ("calibration_dataset_sha256", Sha256("1" * 64)),
        ("validation_dataset_sha256", Sha256("2" * 64)),
        ("annotation_protocol_sha256", Sha256("3" * 64)),
    ),
)
def test_create_rejects_each_forged_threshold_binding_field(
    production_case: _ProductionCase, field: str, value: object
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    original_plan = production_case.plan
    rules = list(original_plan.rules)
    index = next(
        index
        for index, rule in enumerate(rules)
        if rule.definition.rule_id.value == "l2_style"
    )
    rule = rules[index]
    binding = replace(rule.threshold_binding, **{field: value})
    rule_changes = {"threshold_binding": binding}
    if field == "metric_id":
        rule_changes["metric_id"] = value
    rules[index] = replace(rule, **rule_changes)
    forged_plan = replace(original_plan, rules=tuple(rules))
    compiled = replace(
        production_case.request.compiled_spec,
        verification_plans=(forged_plan,),
    )
    request = _request_with_compiled(production_case, compiled)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(production_case, production, request=request, plan=forged_plan)


@pytest.mark.parametrize("field", ("layer", "distance_function"))
def test_create_rejects_nonproduction_encoder_semantics(
    production_case: _ProductionCase, field: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context = production_case.compiler_context
    encoder = replace(context.encoder_capabilities[0], **{field: f"other-{field}"})
    context = replace(context, encoder_capabilities=(encoder,))
    compiled = compile_style_spec(
        production_case.request.compiled_spec.source_spec, context
    )
    request = _request_with_compiled(production_case, compiled)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=compiled.verification_plans[0],
        )


def test_create_rejects_preprocessing_not_owned_by_evidence_encoder(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context = production_case.compiler_context
    encoder = replace(
        context.encoder_capabilities[0], preprocessing_version="other-preprocessing"
    )
    context = replace(context, encoder_capabilities=(encoder,))
    source = _replace_source(
        production_case,
        ("verification", "l2", "preprocessing_version"),
        encoder.preprocessing_version,
    )
    compiled = compile_style_spec(source, context)
    request = _request_with_compiled(production_case, compiled)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=compiled.verification_plans[0],
        )


def test_factory_is_noncopyable_nonserializable_and_owns_loaded_evidence(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    allowlist = production_case.allowlist(production)
    factory = production._create_production_verifier_factory(
        production_case.loaded, allowlist
    )

    assert factory._evidence._owner is production_case.loaded
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(factory)


@pytest.mark.parametrize(
    ("operation", "message"),
    (
        (copy.copy, "production verifiers cannot be copied"),
        (copy.deepcopy, "production verifiers cannot be copied"),
        (pickle.dumps, "production verifiers cannot be serialized"),
    ),
)
def test_bound_verifier_is_noncopyable_and_nonserializable(
    production_case: _ProductionCase, operation: object, message: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    verifier = _create(production_case, production)

    with pytest.raises(TypeError, match=f"^{message}$"):
        operation(verifier)


def test_create_rejects_actual_evidence_layer_mismatch_without_io(
    production_case: _ProductionCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    loader = importlib.import_module("specstyle.generation.diffusers_loader")
    monkeypatch.setattr(loader, "_EVIDENCE_LAYER", "hidden_states[-1]")

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(production_case, production)
    assert production_case.artifact_resolver.calls == []
    assert production_case.style_resolver.calls == []
    assert production_case.evidence_calls == {}


def test_closed_loaded_owner_invalidates_factory_create(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    allowlist = production_case.allowlist(production)
    factory = production._create_production_verifier_factory(
        production_case.loaded, allowlist
    )
    production_case.loaded.close()

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        factory.create(
            production_case.request,
            production_case.plan,
            production_case.artifact_resolver,
            production_case.style_resolver,
        )


@pytest.mark.parametrize("role", ("base", "ip_adapter", "controlnet"))
def test_create_rejects_each_model_pin_not_owned_by_loaded_pipeline(
    production_case: _ProductionCase, role: str
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    context = production_case.compiler_context
    capabilities = list(context.model_capabilities)
    index = next(
        index
        for index, capability in enumerate(capabilities)
        if capability.role == role
    )
    old_pin = capabilities[index].pin
    new_pin = replace(
        old_pin,
        id=f"other-{role}",
        revision="other-revision",
        sha256=Sha256(str(index + 4) * 64),
    )
    capabilities[index] = replace(capabilities[index], pin=new_pin)
    changes: dict[str, object] = {"model_capabilities": tuple(capabilities)}
    source = _replace_source(production_case, ("models", role, "id"), new_pin.id)
    data = source.model_dump(mode="python")
    data["models"][role]["revision"] = new_pin.revision
    data["models"][role]["sha256"] = new_pin.sha256.value
    if role == "ip_adapter":
        encoder = replace(context.encoder_capabilities[0], pin=new_pin)
        l2_profile = replace(context.threshold_profiles[0], encoder_pin=new_pin)
        changes["encoder_capabilities"] = (encoder,)
        changes["threshold_profiles"] = (
            l2_profile,
            *context.threshold_profiles[1:],
        )
        data["verification"]["l2"]["encoder_id"] = new_pin.id
        data["verification"]["l2"]["encoder_revision"] = new_pin.revision
    context = replace(context, **changes)
    source = StyleSpecV1.model_validate(data)
    compiled = compile_style_spec(source, context)
    request = _request_with_compiled(production_case, compiled)

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(
            production_case,
            production,
            context=context,
            request=request,
            plan=compiled.verification_plans[0],
        )


def test_create_rejects_evidence_pin_not_owned_by_request_graph(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    loaded = production_case.loaded
    original_pin = loaded._image_encoder_pin
    object.__setattr__(
        loaded,
        "_image_encoder_pin",
        replace(original_pin, sha256=Sha256("9" * 64)),
    )
    try:
        with pytest.raises(
            DomainError, match="^invalid production verifier dependency$"
        ):
            _create(production_case, production)
    finally:
        object.__setattr__(loaded, "_image_encoder_pin", original_pin)


def test_create_rejects_runtime_not_owned_by_loaded_pipeline(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    loaded = production_case.loaded
    original_runtime = loaded._runtime
    object.__setattr__(loaded, "_runtime", ("0", "0", "0", "float16"))
    try:
        with pytest.raises(
            DomainError, match="^invalid production verifier dependency$"
        ):
            _create(production_case, production)
    finally:
        object.__setattr__(loaded, "_runtime", original_runtime)


def test_create_rejects_source_that_requires_coarse_domain_fidelity(
    tmp_path: Path,
) -> None:
    case = _make_production_case(
        tmp_path,
        fidelity_required=True,
        l3_kind="L3_DOMAIN_FIDELITY",
        l3_requirement="fidelity_required",
    )
    try:
        production = importlib.import_module("specstyle.verification.production")
        with pytest.raises(
            DomainError, match="^invalid production verifier dependency$"
        ):
            _create(case, production)
    finally:
        case.close()


@pytest.mark.parametrize("profile_index", (0, 1))
def test_selected_revoked_profile_is_rejected_at_create_without_runtime_calls(
    production_case: _ProductionCase, profile_index: int
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    profiles = list(production_case.compiler_context.threshold_profiles)
    profiles[profile_index] = replace(profiles[profile_index], status="REVOKED")
    context = replace(
        production_case.compiler_context, threshold_profiles=tuple(profiles)
    )

    with pytest.raises(DomainError, match="^invalid production verifier dependency$"):
        _create(production_case, production, context=context)
    assert production_case.artifact_resolver.calls == []
    assert production_case.style_resolver.calls == []
    assert production_case.evidence_calls == {}


@pytest.mark.parametrize("profile_index", (0, 1))
def test_unselected_revoked_profile_does_not_invalidate_current_request(
    production_case: _ProductionCase, profile_index: int
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    selected = production_case.compiler_context.threshold_profiles[profile_index]
    extra = replace(
        selected,
        pin=replace(
            selected.pin,
            id=f"unused-{selected.pin.id}",
            sha256=Sha256(str(profile_index + 7) * 64),
        ),
        logical_name=f"unused-{selected.logical_name}",
        status="REVOKED",
    )
    context = replace(
        production_case.compiler_context,
        threshold_profiles=(
            *production_case.compiler_context.threshold_profiles,
            extra,
        ),
    )

    verifier = _create(production_case, production, context=context)

    assert callable(verifier.verify)
    assert production_case.artifact_resolver.calls == []
    assert production_case.style_resolver.calls == []
    assert production_case.evidence_calls == {}
