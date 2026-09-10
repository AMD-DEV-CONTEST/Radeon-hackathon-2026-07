"""SPEC-003 immutable compiled-contract validation matrices."""

from __future__ import annotations

import dataclasses
import inspect
import math

import pytest

from specstyle.domain.identifiers import Identifier, RuleId, Sha256
from specstyle.domain.enums import RuleLevel, RuleScope, StaticApplicability
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import (
    CompiledRule,
    CompiledThresholdBinding,
    CompiledVerificationPlan,
    CompilerContext,
    EncoderCapability,
    L3PluginCapability,
    ModelCapability,
    OutputProfileCapability,
    OutputRenderContract,
    ResourcePin,
    RuleCapability,
    RuleCatalogCapability,
    RuntimeCapability,
    StrengthMappingCapability,
    StrengthMappingEntry,
    ThresholdMetricCapability,
    ThresholdProfileCapability,
)
from specstyle.verification.rule_models import GatePolicy, RuleDefinition


def _pin(name: str = "pin", character: str = "a") -> ResourcePin:
    return ResourcePin(name, "r1", Sha256(character * 64))


def _rule(**changes: object) -> RuleCapability:
    values: dict[str, object] = dict(
        rule_id=RuleId("rule"),
        kind="L2_STYLE_FIDELITY",
        level=RuleLevel.L2,
        scope=RuleScope.ITEM,
        requirement="always_advisory",
        supported_domains=("product_instance",),
        supported_output_profiles=("xhs_grid",),
        verifier_pin=_pin("verifier", "b"),
        threshold_source="l2",
        metric_id=Identifier("metric"),
        priority=0,
        affected_by_actions=(Identifier("repair"),),
    )
    values.update(changes)
    return RuleCapability(**values)  # type: ignore[arg-type]


def _threshold(**changes: object) -> ThresholdProfileCapability:
    values: dict[str, object] = dict(
        pin=_pin("threshold", "c"),
        logical_name="profile",
        source="l2",
        status="VALIDATED",
        style_pack_id=Identifier("preset"),
        domain_profile="product_instance",
        encoder_pin=_pin("encoder", "d"),
        plugin_pin=None,
        metrics=(ThresholdMetricCapability(Identifier("metric"), ">=", 0.5),),
        calibration_dataset_sha256=Sha256("e" * 64),
        validation_dataset_sha256=Sha256("f" * 64),
        annotation_protocol_sha256=Sha256("0" * 64),
    )
    values.update(changes)
    return ThresholdProfileCapability(**values)  # type: ignore[arg-type]


def _l3_rule() -> RuleCapability:
    return _rule(
        rule_id=RuleId("l3"),
        kind="L3_DOMAIN_FIDELITY",
        level=RuleLevel.L3,
        requirement="always_advisory",
        threshold_source="l3",
    )


def _plugin() -> L3PluginCapability:
    return L3PluginCapability(
        _pin("plugin", "1"),
        "product_instance",
        "v1",
        ("xhs_grid",),
        (_l3_rule(),),
    )


def _definition(
    *,
    level: RuleLevel = RuleLevel.L1,
    applicable: StaticApplicability = StaticApplicability.APPLICABLE,
) -> RuleDefinition:
    return RuleDefinition(
        RuleId("compiled-rule"),
        level,
        RuleScope.ITEM,
        False,
        applicable,
        GatePolicy("reject", "reject", "continue"),
    )


def _binding(metric_id: Identifier = Identifier("metric")) -> CompiledThresholdBinding:
    return CompiledThresholdBinding(
        _pin("profile", "2"),
        "profile",
        "VALIDATED",
        metric_id,
        ">=",
        0.5,
        Sha256("3" * 64),
        Sha256("4" * 64),
        Sha256("5" * 64),
    )


def _render_contract() -> OutputRenderContract:
    return OutputRenderContract(
        (1080, 1080),
        "contain_pad",
        "lanczos",
        (255, 255, 255),
        "disabled",
        "single_static",
    )


def _compiled_rule(
    *,
    definition: RuleDefinition | None = None,
    metric_id: Identifier | None = Identifier("metric"),
    binding: CompiledThresholdBinding | None = None,
) -> CompiledRule:
    return CompiledRule(
        definition or _definition(), _pin("verifier", "6"), metric_id, binding, 1, ()
    )


def test_resource_pin_constructs() -> None:
    assert ResourcePin("compiler", "r1", Sha256("a" * 64)).id == "compiler"


def test_context_capabilities_construct_from_exact_tuples() -> None:
    pin = ResourcePin("runtime", "r1", Sha256("a" * 64))
    runtime = RuntimeCapability(pin, "rocm", "6", "2", "0", "float16")
    model = ModelCapability(
        "base", pin, None, ("sdxl_turbo", "sdxl_base"), ("float16",), (pin.sha256,)
    )
    context = CompilerContext(
        ResourcePin("compiler", "r1", Sha256("b" * 64)),
        (runtime,),
        (model,),
        (),
        (),
        (),
        (),
        (),
        (),
    )
    assert context.runtime_capabilities == (runtime,)


def test_unhashable_collection_member_is_domain_error_not_type_error() -> None:
    pin = ResourcePin("runtime", "r1", Sha256("a" * 64))
    with pytest.raises(DomainError):
        ModelCapability(
            "base",
            pin,
            None,
            ([],),
            ("float16",),
            (pin.sha256,),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("factory", "field", "bad_values"),
    [
        (lambda: ResourcePin("pin", "r1", Sha256("a" * 64)), "id", (" x", "x\n", 1)),
        (
            lambda: StrengthMappingEntry(0.5, 0.5, 0.5),
            "user_strength",
            (True, 1, math.nan, math.inf),
        ),
        (
            lambda: ThresholdMetricCapability(Identifier("metric"), ">=", 0.5),
            "value",
            (True, 1, math.nan, -math.inf),
        ),
        (_rule, "priority", (True, -1, 0.0)),
    ],
)
def test_scalar_contracts_reject_coercion_and_nonfinite_values(
    factory: object, field: str, bad_values: tuple[object, ...]
) -> None:
    """Would fail if SafeText/finite-float/exact-int guards were removed."""
    instance = factory()  # type: ignore[operator]
    for value in bad_values:
        with pytest.raises(DomainError):
            dataclasses.replace(instance, **{field: value})


@pytest.mark.parametrize(
    ("field", "bad_values"),
    (
        ("final_resolution", ([], (1080,), (1080, 0), (True, 1080))),
        ("background", ([], (255, 255), (255, 255, 256), (False, 255, 255))),
        ("native_resolution", ([], (768,), (768, 0), (True, 768))),
        ("fit", ("stretch", None)),
        ("resampling", ("bicubic", None)),
        ("overlay", ("enabled", None)),
        ("sequence_semantics", ("multi", None)),
    ),
)
def test_output_render_contract_rejects_invalid_fields(
    field: str, bad_values: tuple[object, ...]
) -> None:
    for value in bad_values:
        with pytest.raises(DomainError):
            dataclasses.replace(_render_contract(), **{field: value})


def test_output_profile_rejects_noncontract_renderer_binding() -> None:
    capability = OutputProfileCapability(
        _pin(), "xhs_grid", ("product_instance",), ("production",)
    )
    with pytest.raises(DomainError):
        dataclasses.replace(capability, render_contract=object())


@pytest.mark.parametrize(
    ("factory", "field", "invalid_values"),
    [
        (
            lambda: ModelCapability(
                "base", _pin(), None, ("sdxl_base",), ("float16",), (Sha256("a" * 64),)
            ),
            "supported_pipelines",
            (
                (["sdxl_base"],),
                ({"pipeline": "sdxl_base"},),
                ("wrong",),
                ("lcm", "lcm"),
            ),
        ),
        (
            lambda: EncoderCapability(
                _pin(), "p1", "layer", "cosine", (Sha256("a" * 64),)
            ),
            "supported_runtime_hashes",
            (
                ([Sha256("a" * 64)],),
                ({"hash": "a"},),
                ("wrong",),
                (Sha256("a" * 64), Sha256("a" * 64)),
            ),
        ),
        (
            lambda: OutputProfileCapability(
                _pin(), "xhs_grid", ("product_instance",), ("preview",)
            ),
            "supported_domains",
            (
                (["product_instance"],),
                ({"domain": "product_instance"},),
                ("wrong",),
                ("product_instance", "product_instance"),
            ),
        ),
        (
            _threshold,
            "metrics",
            (
                ([ThresholdMetricCapability(Identifier("metric"), ">=", 0.5)],),
                ({"metric": 1},),
                (Identifier("wrong"),),
                (),
            ),
        ),
        (
            _rule,
            "affected_by_actions",
            (
                ([Identifier("repair")],),
                ({"action": 1},),
                ("wrong",),
                (Identifier("repair"), Identifier("repair")),
            ),
        ),
        (
            lambda: ModelCapability(
                "base",
                _pin(),
                None,
                ("sdxl_base",),
                ("float16",),
                (Sha256("a" * 64),),
            ),
            "supported_dtypes",
            (
                (["float16"],),
                ({"dtype": "float16"},),
                ("wrong",),
                ("float16", "float16"),
            ),
        ),
        (
            lambda: OutputProfileCapability(
                _pin(), "xhs_grid", ("product_instance",), ("preview",)
            ),
            "supported_generation_profiles",
            (
                (["preview"],),
                ({"profile": "preview"},),
                ("wrong",),
                ("preview", "preview"),
            ),
        ),
        (
            _rule,
            "supported_output_profiles",
            (
                (["xhs_grid"],),
                ({"profile": "xhs_grid"},),
                ("wrong",),
                ("xhs_grid", "xhs_grid"),
            ),
        ),
        (
            lambda: RuleCatalogCapability("v1", _pin(), (_rule(),)),
            "rules",
            (
                ([_rule()],),
                ({"rule": 1},),
                (RuleId("wrong"),),
                (_rule(), _rule()),
            ),
        ),
        (
            _plugin,
            "supported_output_profiles",
            (
                (["xhs_grid"],),
                ({"profile": "xhs_grid"},),
                ("wrong",),
                ("xhs_grid", "xhs_grid"),
            ),
        ),
        (
            _plugin,
            "rules",
            (
                ([_l3_rule()],),
                ({"rule": 1},),
                (RuleId("wrong"),),
                (_l3_rule(), _l3_rule()),
            ),
        ),
    ],
)
def test_collections_reject_unhashable_wrong_type_and_duplicates(
    factory: object, field: str, invalid_values: tuple[object, ...]
) -> None:
    """Would fail if tuple, item-type, or uniqueness checks became permissive."""
    instance = factory()  # type: ignore[operator]
    for value in invalid_values:
        with pytest.raises(DomainError):
            dataclasses.replace(instance, **{field: value})


@pytest.mark.parametrize(
    "entries",
    [
        (StrengthMappingEntry(0.1, 0.1, 0.1), StrengthMappingEntry(1.0, 1.0, 1.0)),
        (
            StrengthMappingEntry(0.0, 0.7, 0.7),
            StrengthMappingEntry(0.5, 0.6, 0.8),
            StrengthMappingEntry(1.0, 1.0, 1.0),
        ),
        (
            StrengthMappingEntry(0.0, 0.0, 0.0),
            StrengthMappingEntry(0.5, 0.6, 0.7),
            StrengthMappingEntry(1.0, 0.5, 1.0),
        ),
        (
            StrengthMappingEntry(0.0, 0.0, 0.0),
            StrengthMappingEntry(0.5, 0.5, 0.5),
            StrengthMappingEntry(0.5, 0.6, 0.6),
            StrengthMappingEntry(1.0, 1.0, 1.0),
        ),
        (
            StrengthMappingEntry(0.0, 0.0, 0.0),
            StrengthMappingEntry(0.7, 0.7, 0.7),
            StrengthMappingEntry(0.6, 0.8, 0.8),
            StrengthMappingEntry(1.0, 1.0, 1.0),
        ),
    ],
)
def test_strength_mapping_requires_endpoints_increasing_strength_and_monotonic_scales(
    entries: tuple[StrengthMappingEntry, ...],
) -> None:
    with pytest.raises(DomainError):
        StrengthMappingCapability(_pin(), Identifier("preset"), entries)


def test_capability_relationship_invariants_are_fail_closed() -> None:
    """Would fail if role/source/level and L2-vs-L3 bindings drifted apart."""
    with pytest.raises(DomainError):
        ModelCapability(
            "controlnet", _pin(), None, ("lcm",), ("float16",), (Sha256("a" * 64),)
        )
    with pytest.raises(DomainError):
        _threshold(source="l3", encoder_pin=_pin(), plugin_pin=None)
    with pytest.raises(DomainError):
        _rule(
            kind="L1_TECHNICAL", threshold_source="l2", metric_id=Identifier("metric")
        )
    with pytest.raises(DomainError):
        _threshold(
            metrics=(
                ThresholdMetricCapability(Identifier("metric"), ">=", 0.5),
                ThresholdMetricCapability(Identifier("metric"), "<=", 0.6),
            )
        )


def test_compiled_rule_constructor_matrix_is_fail_closed() -> None:
    na = _definition(level=RuleLevel.L3, applicable=StaticApplicability.NOT_APPLICABLE)
    assert _compiled_rule(definition=na).threshold_binding is None
    invalid = (
        lambda: _compiled_rule(definition=na, binding=_binding()),
        lambda: _compiled_rule(binding=None),
        lambda: _compiled_rule(binding=_binding(Identifier("other"))),
    )
    for construct in invalid:
        with pytest.raises(DomainError):
            construct()


def test_compiled_verification_plan_constructor_matrix_is_fail_closed() -> None:
    l1 = _compiled_rule(metric_id=None)
    l3 = _compiled_rule(definition=_definition(level=RuleLevel.L3), binding=_binding())
    na_l3 = _compiled_rule(
        definition=_definition(
            level=RuleLevel.L3, applicable=StaticApplicability.NOT_APPLICABLE
        )
    )
    pin = _pin("output", "7")
    assert CompiledVerificationPlan(
        "xhs_grid", pin, (l1,), "NOT_APPLICABLE", "NO_L3_CONFIG", None, None
    )
    assert CompiledVerificationPlan(
        "xhs_grid",
        pin,
        (l3,),
        "APPLICABLE",
        None,
        _pin("plugin", "8"),
        _pin("profile", "9"),
    )
    assert CompiledVerificationPlan(
        "xhs_grid",
        pin,
        (na_l3,),
        "NOT_APPLICABLE",
        "NO_APPLICABLE_RULE",
        _pin("plugin", "8"),
        _pin("profile", "9"),
    )
    invalid = (
        lambda: CompiledVerificationPlan(
            "xhs_grid", pin, (l3,), "APPLICABLE", None, None, None
        ),
        lambda: CompiledVerificationPlan(
            "xhs_grid", pin, (na_l3,), "NOT_APPLICABLE", "NO_L3_CONFIG", None, None
        ),
        lambda: CompiledVerificationPlan(
            "xhs_grid",
            pin,
            (na_l3,),
            "NOT_APPLICABLE",
            "NO_APPLICABLE_RULE",
            None,
            None,
        ),
    )
    for construct in invalid:
        with pytest.raises(DomainError):
            construct()


def test_all_input_dataclasses_are_frozen_slotted_and_reject_unknown_keywords() -> None:
    """Would fail if a public capability ceased to be an immutable slotted contract."""
    classes = (
        ResourcePin,
        RuntimeCapability,
        ModelCapability,
        EncoderCapability,
        StrengthMappingEntry,
        StrengthMappingCapability,
        OutputRenderContract,
        OutputProfileCapability,
        ThresholdMetricCapability,
        ThresholdProfileCapability,
        RuleCapability,
        RuleCatalogCapability,
        L3PluginCapability,
        CompilerContext,
    )
    for cls in classes:
        assert dataclasses.is_dataclass(cls) and "__slots__" in cls.__dict__
        assert getattr(cls, "__dataclass_params__").frozen
        with pytest.raises(TypeError):
            cls(unexpected=True)  # type: ignore[call-arg]
        assert "unexpected" not in inspect.signature(cls).parameters


def test_public_contract_declares_exactly_twenty_two_frozen_slotted_dataclasses() -> (
    None
):
    """Would fail if SPEC-003 added a mutable public model outside the frozen contract."""
    import specstyle.spec.compiled_models as models

    names = {
        "ResourcePin",
        "RuntimeCapability",
        "ModelCapability",
        "EncoderCapability",
        "StrengthMappingEntry",
        "StrengthMappingCapability",
        "OutputRenderContract",
        "OutputProfileCapability",
        "ThresholdMetricCapability",
        "ThresholdProfileCapability",
        "RuleCapability",
        "RuleCatalogCapability",
        "L3PluginCapability",
        "CompilerContext",
        "ResolvedRuntime",
        "ResolvedModel",
        "ResolvedEncoder",
        "CompiledThresholdBinding",
        "CompiledRule",
        "CompiledExecutionGraph",
        "CompiledVerificationPlan",
        "CompiledStyleSpec",
    }
    declared = {
        name
        for name, value in vars(models).items()
        if isinstance(value, type)
        and value.__module__ == models.__name__
        and dataclasses.is_dataclass(value)
    }
    assert declared == names
    assert all(
        getattr(getattr(models, name), "__dataclass_params__").frozen for name in names
    )
    assert all("__slots__" in getattr(models, name).__dict__ for name in names)
