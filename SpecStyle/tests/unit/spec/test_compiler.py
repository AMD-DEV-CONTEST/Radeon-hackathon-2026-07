import pytest
from dataclasses import replace

from specstyle.domain.enums import RuleLevel, RuleScope, StaticApplicability
from specstyle.domain.identifiers import Identifier, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import (
    CompilerContext,
    EncoderCapability,
    L3PluginCapability,
    ModelCapability,
    OutputProfileCapability,
    ResourcePin,
    RuleCapability,
    RuleCatalogCapability,
    RuntimeCapability,
    StrengthMappingCapability,
    StrengthMappingEntry,
    ThresholdMetricCapability,
    ThresholdProfileCapability,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1


def _sha(character: str) -> Sha256:
    return Sha256(character * 64)


def _pin(name: str, character: str) -> ResourcePin:
    return ResourcePin(name, "r1", _sha(character))


def raw_spec() -> StyleSpecV1:
    return StyleSpecV1.model_validate(
        {
            "schema_version": "1.0",
            "schema_uri": "schemas/style-spec-1.0.schema.json",
            "metadata": {
                "spec_id": "spec",
                "name": "Spec",
                "author": "author",
                "created_at": "2026-07-30T00:00:00Z",
                "parent_spec": None,
            },
            "runtime": {
                "backend": "rocm",
                "rocm_version": "6",
                "torch_version": "2",
                "diffusers_version": "0",
                "dtype": "float16",
            },
            "models": {
                "base": {"id": "base", "revision": "r1", "sha256": "a" * 64},
                "ip_adapter": {"id": "adapter", "revision": "r1", "sha256": "b" * 64},
                "controlnet": {
                    "type": "canny",
                    "id": "control",
                    "revision": "r1",
                    "sha256": "c" * 64,
                },
            },
            "assets": {
                "style_references": (
                    {
                        "asset_sha256": "d" * 64,
                        "source_url": "https://example.com/a",
                        "license": "CC0",
                        "attribution": "author",
                        "consent": "not_applicable",
                    },
                )
            },
            "profiles": {
                "preview": {
                    "pipeline": "sdxl_turbo",
                    "resolution": (512, 512),
                    "steps": 4,
                    "guidance_scale": 0.0,
                },
                "production": {
                    "pipeline": "sdxl_base",
                    "resolution": (1024, 1024),
                    "steps": 30,
                    "guidance_scale": 5.0,
                    "scheduler": "euler",
                },
            },
            "style": {
                "preset_id": "preset",
                "user_strength": 0.7,
                "preview_ip_adapter_scale": 0.55,
                "production_ip_adapter_scale": 0.72,
            },
            "generation": {
                "img2img_strength": 0.45,
                "controlnet_scale": 0.7,
                "seed_policy": "per_asset_deterministic",
                "batch_execution": "sequential",
            },
            "domain": {
                "profile": "product_instance",
                "verifier_version": None,
                "fidelity_required": False,
            },
            "outputs": {"profiles": ("xhs_grid",)},
            "verification": {
                "ruleset_version": "1",
                "gate_defaults": {
                    "on_unverifiable": "reject",
                    "on_warning": "manual_review",
                },
                "l2": {
                    "encoder_id": "encoder",
                    "encoder_revision": "r1",
                    "preprocessing_version": "p1",
                    "threshold_profile": {
                        "id": "l2-profile",
                        "revision": "r1",
                        "sha256": "e" * 64,
                    },
                },
                "l3": None,
            },
            "repair": {
                "policy_version": "1",
                "max_rounds": 1,
                "stop_after_no_improvement": 1,
            },
            "replay_contract": {
                "mode": "semantic",
                "tolerated_metric_delta": {
                    "l2_style_fidelity": 0.0,
                    "l3_fidelity": 0.0,
                },
                "new_batch": {
                    "contract": "same_compiled_graph_and_gate_definitions",
                    "per_item_metric_equality_required": False,
                },
            },
        }
    )


def context() -> CompilerContext:
    runtime_pin = _pin("runtime", "f")
    encoder_pin = _pin("encoder", "9")
    verifier = _pin("verifier", "8")
    rules = (
        RuleCapability(
            RuleId("l1"),
            "L1_TECHNICAL",
            RuleLevel.L1,
            RuleScope.ITEM,
            "always_required",
            ("product_instance",),
            ("xhs_grid",),
            verifier,
            "none",
            None,
            1,
            (),
        ),
        RuleCapability(
            RuleId("style"),
            "L2_STYLE_FIDELITY",
            RuleLevel.L2,
            RuleScope.ITEM,
            "always_required",
            ("product_instance",),
            ("xhs_grid",),
            verifier,
            "l2",
            Identifier("style-metric"),
            2,
            (Identifier("repair-style"),),
        ),
        RuleCapability(
            RuleId("batch"),
            "L2_BATCH_CONSISTENCY",
            RuleLevel.L2,
            RuleScope.BATCH,
            "always_advisory",
            ("product_instance",),
            ("xhs_grid",),
            verifier,
            "l2",
            Identifier("batch-metric"),
            3,
            (),
        ),
    )
    return CompilerContext(
        _pin("compiler", "7"),
        (RuntimeCapability(runtime_pin, "rocm", "6", "2", "0", "float16"),),
        (
            ModelCapability(
                "base",
                _pin("base", "a"),
                None,
                ("sdxl_turbo", "sdxl_base"),
                ("float16",),
                (runtime_pin.sha256,),
            ),
            ModelCapability(
                "ip_adapter",
                _pin("adapter", "b"),
                None,
                ("sdxl_turbo", "sdxl_base"),
                ("float16",),
                (runtime_pin.sha256,),
            ),
            ModelCapability(
                "controlnet",
                _pin("control", "c"),
                "canny",
                ("sdxl_turbo", "sdxl_base"),
                ("float16",),
                (runtime_pin.sha256,),
            ),
        ),
        (
            EncoderCapability(
                encoder_pin, "p1", "layer", "cosine", (runtime_pin.sha256,)
            ),
        ),
        (
            StrengthMappingCapability(
                _pin("mapping", "6"),
                Identifier("preset"),
                (
                    StrengthMappingEntry(0.0, 0.0, 0.0),
                    StrengthMappingEntry(0.7, 0.55, 0.72),
                    StrengthMappingEntry(1.0, 1.0, 1.0),
                ),
            ),
        ),
        (
            OutputProfileCapability(
                _pin("output", "5"),
                "xhs_grid",
                ("product_instance",),
                ("preview", "production"),
            ),
        ),
        (RuleCatalogCapability("1", _pin("rules", "4"), rules),),
        (
            ThresholdProfileCapability(
                _pin("l2-profile", "e"),
                "l2",
                "l2",
                "VALIDATED",
                Identifier("preset"),
                "product_instance",
                encoder_pin,
                None,
                (
                    ThresholdMetricCapability(Identifier("style-metric"), ">=", 0.5),
                    ThresholdMetricCapability(Identifier("batch-metric"), "<=", 0.3),
                ),
                _sha("1"),
                _sha("2"),
                _sha("3"),
            ),
        ),
        (),
    )


def test_compile_resolves_two_graphs_and_a_static_plan() -> None:
    compiled = compile_style_spec(raw_spec(), context())
    assert len(compiled.preview_graphs) == len(compiled.production_graphs) == 1
    assert compiled.preview_graphs[0].scheduler is None
    assert compiled.production_graphs[0].scheduler == "euler"
    assert compiled.preview_graphs[0].ip_adapter_scale == 0.55
    assert compiled.production_graphs[0].ip_adapter_scale == 0.72
    assert (
        compiled.verification_plans[0].applicable_rule_definitions[0].applicability
        is StaticApplicability.APPLICABLE
    )
    assert compiled.verification_plans[0].l3_reason == "NO_L3_CONFIG"


def test_compile_hash_is_stable_and_changes_with_resolved_capability() -> None:
    first = compile_style_spec(raw_spec(), context())
    second = compile_style_spec(raw_spec(), context())
    changed = context()
    changed_threshold = ThresholdProfileCapability(
        changed.threshold_profiles[0].pin,
        "l2",
        "l2",
        "VALIDATED",
        Identifier("preset"),
        "product_instance",
        changed.encoder_capabilities[0].pin,
        None,
        (
            ThresholdMetricCapability(Identifier("style-metric"), ">=", 0.6),
            ThresholdMetricCapability(Identifier("batch-metric"), "<=", 0.3),
        ),
        _sha("1"),
        _sha("2"),
        _sha("3"),
    )
    changed_context = CompilerContext(
        changed.compiler_pin,
        changed.runtime_capabilities,
        changed.model_capabilities,
        changed.encoder_capabilities,
        changed.strength_mappings,
        changed.output_profile_capabilities,
        changed.rule_catalogs,
        (changed_threshold,),
        (),
    )
    assert first.compiled_spec_hash == second.compiled_spec_hash
    assert (
        first.compiled_spec_hash
        != compile_style_spec(raw_spec(), changed_context).compiled_spec_hash
    )
    # fmt: off
    rebuilt = type(first)(first.source_spec, first.compiler_pin, first.ruleset_pin, first.l2_encoder, first.preview_graphs, first.production_graphs, first.verification_plans)
    # fmt: on
    assert type(rebuilt.compiled_spec_hash) is Sha256
    assert rebuilt.compiled_spec_hash == first.compiled_spec_hash
    replaced = replace(rebuilt, compiler_pin=_pin("changed-compiler", "7"))
    assert replaced.compiled_spec_hash != first.compiled_spec_hash


def test_hash_ignores_context_reordering_and_unused_capability() -> None:
    capabilities = context()
    unused = OutputProfileCapability(
        _pin("unused", "0"),
        "background_sequence",
        ("structure_only",),
        ("preview",),
    )
    reordered = replace(
        capabilities,
        model_capabilities=tuple(reversed(capabilities.model_capabilities)),
        threshold_profiles=tuple(reversed(capabilities.threshold_profiles)),
        output_profile_capabilities=capabilities.output_profile_capabilities
        + (unused,),
    )
    assert (
        compile_style_spec(raw_spec(), capabilities).compiled_spec_hash
        == compile_style_spec(raw_spec(), reordered).compiled_spec_hash
    )


def test_l3_required_without_raw_configuration_fails_closed() -> None:
    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["domain"]["fidelity_required"] = True
    with pytest.raises(DomainError):
        compile_style_spec(StyleSpecV1.model_validate(data), context())


def _raw_with_style(strength: float, preview: float, production: float) -> StyleSpecV1:
    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["style"].update(
        user_strength=strength,
        preview_ip_adapter_scale=preview,
        production_ip_adapter_scale=production,
    )
    return StyleSpecV1.model_validate(data)


@pytest.mark.parametrize(
    ("strength", "preview", "production"),
    [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)],
)
def test_strength_mapping_uses_exact_endpoint_entries(
    strength: float, preview: float, production: float
) -> None:
    compiled = compile_style_spec(
        _raw_with_style(strength, preview, production), context()
    )
    assert (
        compiled.preview_graphs[0].ip_adapter_scale,
        compiled.production_graphs[0].ip_adapter_scale,
    ) == (preview, production)


@pytest.mark.parametrize(
    "raw",
    [_raw_with_style(0.6, 0.55, 0.72), _raw_with_style(0.7, 0.54, 0.72)],
)
def test_strength_mapping_rejects_missing_exact_entry_and_raw_scale_mismatch(
    raw: StyleSpecV1,
) -> None:
    with pytest.raises(DomainError):
        compile_style_spec(raw, context())


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("runtime", lambda c: replace(c, runtime_capabilities=())),
        (
            "runtime_duplicate",
            lambda c: replace(c, runtime_capabilities=c.runtime_capabilities * 2),
        ),
        (
            "base_model",
            lambda c: replace(c, model_capabilities=c.model_capabilities[1:]),
        ),
        (
            "base_model_duplicate",
            lambda c: replace(
                c, model_capabilities=c.model_capabilities + (c.model_capabilities[0],)
            ),
        ),
        ("encoder", lambda c: replace(c, encoder_capabilities=())),
        ("output", lambda c: replace(c, output_profile_capabilities=())),
        ("ruleset", lambda c: replace(c, rule_catalogs=())),
        ("mapping", lambda c: replace(c, strength_mappings=())),
        ("l2_profile", lambda c: replace(c, threshold_profiles=())),
        (
            "mapping_duplicate",
            lambda c: replace(c, strength_mappings=c.strength_mappings * 2),
        ),
    ],
)
def test_all_core_capabilities_fail_closed_on_zero_or_multiple_resolution(
    name: str, mutate: object
) -> None:
    raw, original = raw_spec(), context()
    with pytest.raises(DomainError):
        compile_style_spec(raw, mutate(original))  # type: ignore[operator]
    assert (raw, original) == (raw_spec(), context()), name


@pytest.mark.parametrize(
    "field",
    (
        "encoder_capabilities",
        "output_profile_capabilities",
        "rule_catalogs",
        "threshold_profiles",
    ),
)
def test_remaining_core_resolvers_reject_multiple_matches(field: str) -> None:
    base = context()
    with pytest.raises(DomainError):
        compile_style_spec(
            raw_spec(), replace(base, **{field: getattr(base, field) * 2})
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: replace(
            c,
            model_capabilities=(
                replace(c.model_capabilities[0], supported_pipelines=("lcm",)),
            )
            + c.model_capabilities[1:],
        ),
        lambda c: replace(
            c,
            model_capabilities=(
                replace(c.model_capabilities[0], supported_dtypes=("bfloat16",)),
            )
            + c.model_capabilities[1:],
        ),
        lambda c: replace(
            c,
            model_capabilities=(
                replace(c.model_capabilities[0], supported_runtime_hashes=(_sha("0"),)),
            )
            + c.model_capabilities[1:],
        ),
        lambda c: replace(
            c,
            output_profile_capabilities=(
                replace(
                    c.output_profile_capabilities[0],
                    supported_domains=("face_identity",),
                ),
            ),
        ),
    ],
)
def test_resolved_model_and_output_incompatibilities_fail_closed(
    mutate: object,
) -> None:
    with pytest.raises(DomainError):
        compile_style_spec(raw_spec(), mutate(context()))  # type: ignore[operator]


@pytest.mark.parametrize(
    "catalog_rules",
    [
        lambda rules: tuple(rule for rule in rules if rule.kind != "L1_TECHNICAL"),
        lambda rules: tuple(rule for rule in rules if rule.kind != "L2_STYLE_FIDELITY"),
        lambda rules: rules + (replace(rules[1], rule_id=RuleId("style-two")),),
        lambda rules: (
            rules
            + (
                replace(
                    rules[0],
                    rule_id=RuleId("l3"),
                    kind="L3_DIAGNOSTIC",
                    level=RuleLevel.L3,
                    threshold_source="none",
                    metric_id=None,
                ),
            )
        ),
    ],
)
def test_catalog_structure_and_l1_threshold_rules_are_fail_closed(
    catalog_rules: object,
) -> None:
    base = context()
    catalog = replace(
        base.rule_catalogs[0], rules=catalog_rules(base.rule_catalogs[0].rules)
    )  # type: ignore[operator]
    with pytest.raises(DomainError):
        compile_style_spec(raw_spec(), replace(base, rule_catalogs=(catalog,)))


# fmt: off
def test_catalog_na_rule_retains_audit_fields_and_sorted_actions() -> None:
    base = context()
    extra = replace(base.rule_catalogs[0].rules[1], supported_output_profiles=("talking_head_cover",), affected_by_actions=(Identifier("z"), Identifier("a")))
    catalog = replace(base.rule_catalogs[0], rules=(base.rule_catalogs[0].rules[0], extra, base.rule_catalogs[0].rules[2]))
    profile = replace(base.threshold_profiles[0], metrics=(base.threshold_profiles[0].metrics[1],))
    rule = next(rule for rule in compile_style_spec(raw_spec(), replace(base, rule_catalogs=(catalog,), threshold_profiles=(profile,))).verification_plans[0].rules if rule.definition.rule_id == extra.rule_id)
    assert rule.definition.applicability is StaticApplicability.NOT_APPLICABLE
    assert (rule.verifier_pin, rule.metric_id, rule.priority, rule.affected_by_actions, rule.threshold_binding) == (extra.verifier_pin, extra.metric_id, extra.priority, (Identifier("a"), Identifier("z")), None)
# fmt: on


def _advisory_catalog(capabilities: CompilerContext) -> CompilerContext:
    rules = tuple(
        rule
        if rule.kind == "L1_TECHNICAL"
        else replace(rule, requirement="always_advisory")
        for rule in capabilities.rule_catalogs[0].rules
    )
    return replace(
        capabilities,
        rule_catalogs=(replace(capabilities.rule_catalogs[0], rules=rules),),
    )


@pytest.mark.parametrize(
    ("status", "advisory", "valid"),
    [
        ("VALIDATED", False, True),
        ("DRAFT", False, False),
        ("CALIBRATED", False, False),
        ("REVOKED", False, False),
        ("DRAFT", True, True),
        ("CALIBRATED", True, True),
        ("REVOKED", True, False),
    ],
)
def test_l2_threshold_status_matrix_respects_requiredness(
    status: str, advisory: bool, valid: bool
) -> None:
    base = _advisory_catalog(context()) if advisory else context()
    profile = replace(base.threshold_profiles[0], status=status)
    candidate = replace(base, threshold_profiles=(profile,))
    if valid:
        assert compile_style_spec(raw_spec(), candidate).verification_plans[0].rules
    else:
        with pytest.raises(DomainError):
            compile_style_spec(raw_spec(), candidate)


@pytest.mark.parametrize(
    "profile",
    [
        lambda p: replace(p, style_pack_id=Identifier("other")),
        lambda p: replace(p, domain_profile="face_identity"),
        lambda p: replace(p, encoder_pin=_pin("other", "0")),
        lambda p: replace(
            p,
            metrics=(ThresholdMetricCapability(Identifier("style-metric"), ">=", 0.5),),
        ),
        lambda p: replace(
            p,
            metrics=p.metrics
            + (ThresholdMetricCapability(Identifier("extra"), ">=", 0.1),),
        ),
    ],
)
def test_l2_binding_and_metric_set_must_match_exactly(profile: object) -> None:
    base = context()
    with pytest.raises(DomainError):
        compile_style_spec(
            raw_spec(),
            replace(base, threshold_profiles=(profile(base.threshold_profiles[0]),)),
        )  # type: ignore[operator]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["verification"]["l2"]["threshold_profile"].update(id="other"),
        lambda d: d["verification"]["l2"]["threshold_profile"].update(revision="r2"),
        lambda d: d["verification"]["l2"]["threshold_profile"].update(sha256="0" * 64),
        lambda d: d["verification"]["gate_defaults"].update(on_warning="continue"),
    ],
)
def test_raw_l2_pin_and_required_continue_must_fail_closed(change: object) -> None:
    data = raw_spec().model_dump(mode="python", round_trip=True)
    change(data)  # type: ignore[operator]
    with pytest.raises(DomainError):
        compile_style_spec(StyleSpecV1.model_validate(data), context())


# fmt: off
def _l3_case(*, required: bool = True, requirement: str = "fidelity_required", output: str = "xhs_grid") -> tuple[StyleSpecV1, CompilerContext]:
    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["domain"] = {"profile": "product_instance", "verifier_version": "v1", "fidelity_required": required}
    data["verification"]["l3"] = {"plugin_id": "plugin", "plugin_revision": "r1", "threshold_profile": "l3"}
    raw, base, plugin_pin = StyleSpecV1.model_validate(data), context(), _pin("plugin", "b")
    rule = RuleCapability(RuleId("l3"), "L3_DOMAIN_FIDELITY", RuleLevel.L3, RuleScope.ITEM, requirement, ("product_instance",), (output,), _pin("l3-verifier", "a"), "l3", Identifier("l3-metric"), 0, ())
    plugin = L3PluginCapability(plugin_pin, "product_instance", "v1", ("xhs_grid",), (rule,))
    profile = ThresholdProfileCapability(_pin("l3-profile", "c"), "l3", "l3", "VALIDATED", Identifier("preset"), "product_instance", None, plugin_pin, (ThresholdMetricCapability(Identifier("l3-metric"), ">=", 0.8),), _sha("1"), _sha("2"), _sha("3"))
    return raw, replace(base, threshold_profiles=base.threshold_profiles + (profile,), l3_plugins=(plugin,))
# fmt: on


def test_required_l3_resolves_an_applicable_domain_gate() -> None:
    raw, capabilities = _l3_case()
    plan = compile_style_spec(raw, capabilities).verification_plans[0]
    assert plan.l3_status == "APPLICABLE"
    assert RuleId("l3") in {rule.rule_id for rule in plan.applicable_rule_definitions}


# fmt: off
def test_actual_l3_na_ignores_metric_and_required_status_checks() -> None:
    raw, base = _l3_case(required=False, requirement="always_required")
    plugin = replace(base.l3_plugins[0], supported_output_profiles=("talking_head_cover",))
    profile = replace(base.threshold_profiles[-1], status="CALIBRATED", metrics=(ThresholdMetricCapability(Identifier("other-metric"), ">=", 0.8),))
    plan = compile_style_spec(raw, replace(base, l3_plugins=(plugin,), threshold_profiles=base.threshold_profiles[:-1] + (profile,))).verification_plans[0]
    l3_rules = tuple(rule for rule in plan.rules if rule.definition.level is RuleLevel.L3)
    assert (plan.l3_status, plan.l3_reason, plan.l3_plugin_pin, plan.l3_threshold_profile_pin) == ("NOT_APPLICABLE", "NO_APPLICABLE_RULE", plugin.pin, profile.pin)
    assert l3_rules and all(rule.threshold_binding is None for rule in l3_rules)
# fmt: on


@pytest.mark.parametrize(
    ("change", "required"),
    [
        (lambda c: replace(c, l3_plugins=()), True),
        (lambda c: replace(c, l3_plugins=c.l3_plugins * 2), True),
        (lambda c: replace(c, threshold_profiles=c.threshold_profiles[:-1]), True),
        (
            lambda c: replace(
                c, threshold_profiles=c.threshold_profiles + (c.threshold_profiles[-1],)
            ),
            True,
        ),
        (
            lambda c: replace(
                c,
                threshold_profiles=c.threshold_profiles[:-1]
                + (replace(c.threshold_profiles[-1], status="REVOKED"),),
            ),
            False,
        ),
        (
            lambda c: replace(
                c,
                threshold_profiles=c.threshold_profiles[:-1]
                + (replace(c.threshold_profiles[-1], status="DRAFT"),),
            ),
            True,
        ),
    ],
)
def test_l3_plugin_and_threshold_resolution_status_matrix_is_fail_closed(
    change: object, required: bool
) -> None:
    raw, base = _l3_case(required=required)
    with pytest.raises(DomainError):
        compile_style_spec(raw, change(base))  # type: ignore[operator]


def test_required_l3_rejects_advisory_domain_gate() -> None:
    raw, capabilities = _l3_case(requirement="always_advisory")
    with pytest.raises(DomainError):
        compile_style_spec(raw, capabilities)


def _two_output_case(reverse: bool = False) -> tuple[StyleSpecV1, CompilerContext]:
    data = raw_spec().model_dump(mode="python", round_trip=True)
    outputs = ("xhs_grid", "talking_head_cover")
    data["outputs"]["profiles"] = tuple(reversed(outputs)) if reverse else outputs
    raw, base = StyleSpecV1.model_validate(data), context()
    rules = tuple(
        replace(rule, supported_output_profiles=outputs)
        for rule in base.rule_catalogs[0].rules
    )
    output = OutputProfileCapability(
        _pin("talking", "0"),
        "talking_head_cover",
        ("product_instance",),
        ("preview", "production"),
    )
    return raw, replace(
        base,
        output_profile_capabilities=base.output_profile_capabilities + (output,),
        rule_catalogs=(replace(base.rule_catalogs[0], rules=rules),),
    )


def test_multi_output_graphs_preserve_raw_order_and_hash_is_sequence_sensitive() -> (
    None
):
    raw, capabilities = _two_output_case()
    reversed_raw, reversed_capabilities = _two_output_case(reverse=True)
    compiled = compile_style_spec(raw, capabilities)
    reversed_compiled = compile_style_spec(reversed_raw, reversed_capabilities)
    assert (
        tuple(graph.output_profile for graph in compiled.preview_graphs)
        == raw.outputs.profiles
    )
    assert (
        tuple(graph.output_profile for graph in compiled.production_graphs)
        == raw.outputs.profiles
    )
    assert (
        tuple(plan.output_profile for plan in compiled.verification_plans)
        == raw.outputs.profiles
    )
    assert compiled.compiled_spec_hash != reversed_compiled.compiled_spec_hash


def test_hash_normalizes_negative_zero_and_style_reference_order_is_sensitive() -> None:
    zero = raw_spec().model_dump(mode="python", round_trip=True)
    zero["profiles"]["preview"]["guidance_scale"] = -0.0
    references = raw_spec().model_dump(mode="python", round_trip=True)
    second = dict(references["assets"]["style_references"][0], asset_sha256="0" * 64)
    references["assets"]["style_references"] = tuple(
        references["assets"]["style_references"]
    ) + (second,)
    reversed_references = dict(references)
    reversed_references["assets"] = dict(
        references["assets"],
        style_references=tuple(reversed(references["assets"]["style_references"])),
    )
    baseline = compile_style_spec(raw_spec(), context())
    assert (
        baseline.compiled_spec_hash
        == compile_style_spec(
            StyleSpecV1.model_validate(zero), context()
        ).compiled_spec_hash
    )
    assert (
        compile_style_spec(
            StyleSpecV1.model_validate(references), context()
        ).compiled_spec_hash
        != compile_style_spec(
            StyleSpecV1.model_validate(reversed_references), context()
        ).compiled_spec_hash
    )


def test_synthetic_fixture_has_a_fixed_canonical_hash_golden_vector() -> None:
    assert compile_style_spec(raw_spec(), context()).compiled_spec_hash.value == (
        "c21f061f246a258eb1ffc9043343f4bcc886ea775fdc2302c7d2cfe03538141a"
    )


def test_production_approval_digest_changes_compiled_hash() -> None:
    baseline_context = context()
    profile = baseline_context.threshold_profiles[0]
    approved_profile = replace(profile, production_approval_sha256=_sha("a"))
    approved_context = replace(
        baseline_context,
        threshold_profiles=(approved_profile, *baseline_context.threshold_profiles[1:]),
    )

    assert (
        compile_style_spec(raw_spec(), approved_context).compiled_spec_hash
        != compile_style_spec(raw_spec(), baseline_context).compiled_spec_hash
    )
