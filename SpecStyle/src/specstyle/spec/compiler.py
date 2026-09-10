"""Pure fail-closed compiler from StyleSpec (1.0|1.1) to immutable execution plans."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from specstyle.domain.enums import RuleLevel, StaticApplicability
from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import (
    CompiledExecutionGraph,
    CompiledRule,
    CompiledStyleSpec,
    CompiledThresholdBinding,
    CompiledVerificationPlan,
    CompilerContext,
    L3PluginCapability,
    ModelCapability,
    OutputProfileCapability,
    ResolvedEncoder,
    ResolvedModel,
    ResolvedRuntime,
    RuleCapability,
    RuleCatalogCapability,
    StrengthMappingCapability,
    StrengthMappingEntry,
    ThresholdProfileCapability,
)
from specstyle.spec.models import StyleSpec, StyleSpecV1, StyleSpecV11
from specstyle.verification.rule_models import GatePolicy, RuleDefinition

_T = TypeVar("_T")


def compile_style_spec(
    raw: StyleSpec, context: CompilerContext, /
) -> CompiledStyleSpec:
    """Resolve one fully pinned spec without I/O, fallback selection, or mutation."""
    if (
        type(raw) not in (StyleSpecV1, StyleSpecV11)
        or type(context) is not CompilerContext
    ):
        raise DomainError("raw and context must have exact contract types")
    runtime = _runtime(raw, context)
    models = _models(raw, context, runtime)
    encoder = _encoder(raw, context, runtime)
    mapping = _mapping(raw, context)
    outputs = _outputs(raw, context)
    catalog = _catalog(raw, context)
    _validate_catalog(catalog, raw)
    l2_profile = _l2_profile(raw, context, encoder, catalog)
    plugin, l3_profile = _l3_resolution(raw, context)
    _validate_l3(raw, plugin, l3_profile)
    plans = tuple(
        _plan(raw, output, catalog, l2_profile, plugin, l3_profile)
        for output in outputs
    )
    _validate_l1_coverage(plans, raw)
    graphs = _graphs(raw, outputs, runtime, models, mapping)
    return CompiledStyleSpec(
        raw, context.compiler_pin, catalog.pin, encoder, graphs[0], graphs[1], plans
    )


def _one(values: tuple[_T, ...], matches: Callable[[_T], bool], name: str) -> _T:
    selected = tuple(value for value in values if matches(value))
    if len(selected) != 1:
        raise DomainError(f"{name} must resolve exactly once")
    return selected[0]


def _pin_matches(pin: object, identifier: str, revision: str, sha256: str) -> bool:
    return (
        getattr(pin, "id", None) == identifier
        and getattr(pin, "revision", None) == revision
        and getattr(getattr(pin, "sha256", None), "value", None) == sha256
    )


def _runtime(raw: StyleSpec, context: CompilerContext) -> ResolvedRuntime:
    capability = _one(
        context.runtime_capabilities,
        lambda item: (
            (
                item.backend,
                item.rocm_version,
                item.torch_version,
                item.diffusers_version,
                item.dtype,
            )
            == (
                raw.runtime.backend,
                raw.runtime.rocm_version,
                raw.runtime.torch_version,
                raw.runtime.diffusers_version,
                raw.runtime.dtype,
            )
        ),
        "runtime",
    )
    return ResolvedRuntime(
        capability.pin,
        capability.backend,
        capability.rocm_version,
        capability.torch_version,
        capability.diffusers_version,
        capability.dtype,
    )


def _models(
    raw: StyleSpec, context: CompilerContext, runtime: ResolvedRuntime
) -> tuple[ResolvedModel, ResolvedModel, ResolvedModel]:
    specs = (
        ("base", raw.models.base, None),
        ("ip_adapter", raw.models.ip_adapter, None),
        ("controlnet", raw.models.controlnet, raw.models.controlnet.type),
    )
    resolved: list[ResolvedModel] = []
    for role, spec, controlnet_type in specs:
        capability = _one(
            context.model_capabilities,
            lambda item: _model_matches(
                item, role, spec.id, spec.revision, spec.sha256, controlnet_type
            ),
            f"{role} model",
        )
        if (
            runtime.pin.sha256 not in capability.supported_runtime_hashes
            or runtime.dtype not in capability.supported_dtypes
            or raw.profiles.preview.pipeline not in capability.supported_pipelines
            or raw.profiles.production.pipeline not in capability.supported_pipelines
        ):
            raise DomainError(f"{role} model does not support resolved graph")
        resolved.append(ResolvedModel(role, capability.pin, controlnet_type))
    return tuple(resolved)  # type: ignore[return-value]


def _model_matches(
    capability: ModelCapability,
    role: str,
    identifier: str,
    revision: str,
    sha256: str,
    controlnet_type: object,
) -> bool:
    return (
        capability.role == role
        and _pin_matches(capability.pin, identifier, revision, sha256)
        and capability.controlnet_type == controlnet_type
    )


def _encoder(
    raw: StyleSpec, context: CompilerContext, runtime: ResolvedRuntime
) -> ResolvedEncoder:
    capability = _one(
        context.encoder_capabilities,
        lambda item: (
            _pin_matches(
                item.pin,
                raw.verification.l2.encoder_id,
                raw.verification.l2.encoder_revision,
                item.pin.sha256.value,
            )
            and item.preprocessing_version == raw.verification.l2.preprocessing_version
        ),
        "L2 encoder",
    )
    if runtime.pin.sha256 not in capability.supported_runtime_hashes:
        raise DomainError("encoder does not support resolved runtime")
    return ResolvedEncoder(
        capability.pin,
        capability.preprocessing_version,
        capability.layer,
        capability.distance_function,
    )


def _mapping(raw: StyleSpec, context: CompilerContext) -> StrengthMappingCapability:
    preset = Identifier(raw.style.preset_id)
    capability = _one(
        context.strength_mappings,
        lambda item: item.preset_id == preset,
        "strength mapping",
    )
    entry = _one(
        capability.entries,
        lambda item: item.user_strength == raw.style.user_strength,
        "strength mapping entry",
    )
    if (entry.preview_ip_adapter_scale, entry.production_ip_adapter_scale) != (
        raw.style.preview_ip_adapter_scale,
        raw.style.production_ip_adapter_scale,
    ):
        raise DomainError("raw scales do not match strength mapping")
    return capability


def _outputs(
    raw: StyleSpec, context: CompilerContext
) -> tuple[OutputProfileCapability, ...]:
    return tuple(
        _output(raw.domain.profile, output, context) for output in raw.outputs.profiles
    )


def _output(
    domain: str, output: str, context: CompilerContext
) -> OutputProfileCapability:
    capability = _one(
        context.output_profile_capabilities,
        lambda item: item.profile == output,
        f"output profile {output}",
    )
    if domain not in capability.supported_domains or {"preview", "production"} - set(
        capability.supported_generation_profiles
    ):
        raise DomainError("output profile is incompatible")
    return capability


def _catalog(raw: StyleSpec, context: CompilerContext) -> RuleCatalogCapability:
    return _one(
        context.rule_catalogs,
        lambda item: item.ruleset_version == raw.verification.ruleset_version,
        "ruleset",
    )


def _validate_catalog(catalog: RuleCatalogCapability, raw: StyleSpec) -> None:
    rules = catalog.rules
    fidelity = tuple(rule for rule in rules if rule.kind == "L2_STYLE_FIDELITY")
    batch = tuple(rule for rule in rules if rule.kind == "L2_BATCH_CONSISTENCY")
    if (
        len(fidelity) != 1
        or len(batch) != 1
        or not any(rule.kind == "L1_TECHNICAL" for rule in rules)
    ):
        raise DomainError("catalog must contain L1 and exactly both L2 rules")
    if any(
        rule.kind == "L1_TECHNICAL" and rule.threshold_source != "none"
        for rule in rules
    ):
        raise DomainError("L1 rules cannot use thresholds")
    if any(rule.kind.startswith("L3_") for rule in rules):
        raise DomainError("catalog cannot contain L3 rules")
    _unique_rule_ids(rules)


def _l2_profile(
    raw: StyleSpec,
    context: CompilerContext,
    encoder: ResolvedEncoder,
    catalog: RuleCatalogCapability,
) -> ThresholdProfileCapability:
    reference = raw.verification.l2.threshold_profile
    profile = _one(
        context.threshold_profiles,
        lambda item: (
            item.source == "l2"
            and _pin_matches(
                item.pin, reference.id, reference.revision, reference.sha256
            )
        ),
        "L2 threshold profile",
    )
    if (
        profile.style_pack_id != Identifier(raw.style.preset_id)
        or profile.domain_profile != raw.domain.profile
        or profile.encoder_pin != encoder.pin
    ):
        raise DomainError("L2 threshold profile binding mismatch")
    expected = _expected_metrics(catalog.rules, "l2", raw)
    if {metric.metric_id for metric in profile.metrics} != expected:
        raise DomainError("L2 threshold metrics mismatch")
    _validate_threshold_status(profile, catalog.rules, raw)
    return profile


def _expected_metrics(
    rules: tuple[RuleCapability, ...],
    source: str,
    raw: StyleSpec,
    plugin: L3PluginCapability | None = None,
) -> set[Identifier]:
    return {
        rule.metric_id
        for rule in rules
        if rule.threshold_source == source
        and any(
            _applicable(rule, raw.domain.profile, output, plugin)
            for output in raw.outputs.profiles
        )
        and rule.metric_id is not None
    }


def _validate_threshold_status(
    profile: ThresholdProfileCapability,
    rules: tuple[RuleCapability, ...],
    raw: StyleSpec,
    plugin: L3PluginCapability | None = None,
) -> None:
    if profile.status == "REVOKED":
        raise DomainError("revoked threshold profile")
    relevant = tuple(
        rule
        for rule in rules
        if rule.threshold_source == profile.source
        and any(
            _applicable(rule, raw.domain.profile, output, plugin)
            for output in raw.outputs.profiles
        )
    )
    if any(_required(rule, raw) for rule in relevant) and profile.status != "VALIDATED":
        raise DomainError("required threshold profile must be validated")


def _l3_resolution(
    raw: StyleSpec, context: CompilerContext
) -> tuple[L3PluginCapability | None, ThresholdProfileCapability | None]:
    if raw.verification.l3 is None:
        if raw.domain.fidelity_required:
            raise DomainError("fidelity required needs L3 configuration")
        return None, None
    if raw.domain.verifier_version is None:
        raise DomainError("L3 config needs domain verifier version")
    config = raw.verification.l3
    plugin = _one(
        context.l3_plugins,
        lambda item: (
            _pin_matches(
                item.pin,
                config.plugin_id,
                config.plugin_revision,
                item.pin.sha256.value,
            )
            and item.domain_profile == raw.domain.profile
            and item.domain_verifier_version == raw.domain.verifier_version
        ),
        "L3 plugin",
    )
    profile = _one(
        context.threshold_profiles,
        lambda item: (
            item.source == "l3"
            and item.logical_name == config.threshold_profile
            and item.style_pack_id == Identifier(raw.style.preset_id)
            and item.domain_profile == raw.domain.profile
            and item.plugin_pin == plugin.pin
        ),
        "L3 threshold profile",
    )
    expected = _expected_metrics(plugin.rules, "l3", raw, plugin)
    if expected and {metric.metric_id for metric in profile.metrics} != expected:
        raise DomainError("L3 threshold metrics mismatch")
    _validate_threshold_status(profile, plugin.rules, raw, plugin)
    return plugin, profile


def _validate_l3(
    raw: StyleSpec,
    plugin: L3PluginCapability | None,
    profile: ThresholdProfileCapability | None,
) -> None:
    if not raw.domain.fidelity_required:
        return
    if plugin is None or profile is None or profile.status != "VALIDATED":
        raise DomainError("fidelity required needs validated L3")
    for output in raw.outputs.profiles:
        if not any(
            rule.kind == "L3_DOMAIN_FIDELITY"
            and _applicable(rule, raw.domain.profile, output, plugin)
            and _required(rule, raw)
            for rule in plugin.rules
        ):
            raise DomainError("each output needs applicable L3 fidelity gate")


def _plan(
    raw: StyleSpec,
    output: OutputProfileCapability,
    catalog: RuleCatalogCapability,
    l2_profile: ThresholdProfileCapability,
    plugin: L3PluginCapability | None,
    l3_profile: ThresholdProfileCapability | None,
) -> CompiledVerificationPlan:
    source_rules = catalog.rules + (() if plugin is None else plugin.rules)
    _unique_rule_ids(source_rules)
    rules = tuple(
        sorted(
            (
                _compiled_rule(
                    rule, raw, output.profile, l2_profile, plugin, l3_profile
                )
                for rule in source_rules
            ),
            key=lambda item: item.definition.rule_id.value,
        )
    )
    l3_rules = tuple(
        rule
        for rule in rules
        if rule.definition.level is RuleLevel.L3
        and rule.definition.applicability is StaticApplicability.APPLICABLE
    )
    if plugin is None:
        return CompiledVerificationPlan(
            output.profile,
            output.pin,
            rules,
            "NOT_APPLICABLE",
            "NO_L3_CONFIG",
            None,
            None,
        )
    if not l3_rules:
        return CompiledVerificationPlan(
            output.profile,
            output.pin,
            rules,
            "NOT_APPLICABLE",
            "NO_APPLICABLE_RULE",
            plugin.pin,
            l3_profile.pin if l3_profile else None,
        )
    return CompiledVerificationPlan(
        output.profile,
        output.pin,
        rules,
        "APPLICABLE",
        None,
        plugin.pin,
        l3_profile.pin if l3_profile else None,
    )


def _compiled_rule(
    rule: RuleCapability,
    raw: StyleSpec,
    output: str,
    l2_profile: ThresholdProfileCapability,
    plugin: L3PluginCapability | None,
    l3_profile: ThresholdProfileCapability | None,
) -> CompiledRule:
    active = _applicable(rule, raw.domain.profile, output, plugin)
    definition = RuleDefinition(
        rule.rule_id,
        rule.level,
        rule.scope,
        _required(rule, raw),
        StaticApplicability.APPLICABLE
        if active
        else StaticApplicability.NOT_APPLICABLE,
        GatePolicy(
            "reject",
            raw.verification.gate_defaults.on_unverifiable,
            raw.verification.gate_defaults.on_warning,
        ),
    )
    binding = _binding(rule, active, l2_profile, l3_profile)
    return CompiledRule(
        definition,
        rule.verifier_pin,
        rule.metric_id,
        binding,
        rule.priority,
        tuple(sorted(rule.affected_by_actions, key=lambda item: item.value)),
    )


def _required(rule: RuleCapability, raw: StyleSpec) -> bool:
    return rule.requirement == "always_required" or (
        rule.requirement == "fidelity_required" and raw.domain.fidelity_required
    )


def _applicable(
    rule: RuleCapability, domain: str, output: str, plugin: L3PluginCapability | None
) -> bool:
    return (
        domain in rule.supported_domains
        and output in rule.supported_output_profiles
        and (
            rule.level is not RuleLevel.L3
            or plugin is not None
            and output in plugin.supported_output_profiles
        )
    )


def _binding(
    rule: RuleCapability,
    active: bool,
    l2_profile: ThresholdProfileCapability,
    l3_profile: ThresholdProfileCapability | None,
) -> CompiledThresholdBinding | None:
    if not active or rule.metric_id is None:
        return None
    profile = (
        l2_profile
        if rule.threshold_source == "l2"
        else l3_profile
        if rule.threshold_source == "l3"
        else None
    )
    if profile is None:
        raise DomainError("applicable threshold rule lacks profile")
    metric = _one(
        profile.metrics,
        lambda item: item.metric_id == rule.metric_id,
        "threshold metric",
    )
    return CompiledThresholdBinding(
        profile.pin,
        profile.logical_name,
        profile.status,
        metric.metric_id,
        metric.operator,
        metric.value,
        profile.calibration_dataset_sha256,
        profile.validation_dataset_sha256,
        profile.annotation_protocol_sha256,
        profile.production_approval_sha256,
    )


def _validate_l1_coverage(
    plans: tuple[CompiledVerificationPlan, ...], raw: StyleSpec
) -> None:
    for plan, output in zip(plans, raw.outputs.profiles):
        if not any(
            rule.definition.level is RuleLevel.L1
            and rule.definition.required
            and rule.definition.applicability is StaticApplicability.APPLICABLE
            for rule in plan.rules
        ):
            raise DomainError(f"output {output} has no applicable required L1")


def _graphs(
    raw: StyleSpec,
    outputs: tuple[OutputProfileCapability, ...],
    runtime: ResolvedRuntime,
    models: tuple[ResolvedModel, ResolvedModel, ResolvedModel],
    mapping: StrengthMappingCapability,
) -> tuple[tuple[CompiledExecutionGraph, ...], tuple[CompiledExecutionGraph, ...]]:
    mapping_entry = _one(
        mapping.entries,
        lambda item: item.user_strength == raw.style.user_strength,
        "strength mapping entry",
    )
    common = (runtime, models, mapping, mapping_entry)
    return (
        tuple(_graph(raw, output, "preview", *common) for output in outputs),
        tuple(_graph(raw, output, "production", *common) for output in outputs),
    )


def _graph(
    raw: StyleSpec,
    output: OutputProfileCapability,
    profile: str,
    runtime: ResolvedRuntime,
    models: tuple[ResolvedModel, ResolvedModel, ResolvedModel],
    mapping: StrengthMappingCapability,
    entry: StrengthMappingEntry,
) -> CompiledExecutionGraph:
    source = raw.profiles.preview if profile == "preview" else raw.profiles.production
    scale = (
        entry.preview_ip_adapter_scale
        if profile == "preview"
        else entry.production_ip_adapter_scale
    )
    return CompiledExecutionGraph(
        profile,
        output.profile,
        output.pin,
        source.pipeline,
        source.resolution,
        source.steps,
        source.guidance_scale,
        None if profile == "preview" else raw.profiles.production.scheduler,
        runtime,
        models[0],
        models[1],
        models[2],
        tuple(
            Sha256(reference.asset_sha256) for reference in raw.assets.style_references
        ),
        Identifier(raw.style.preset_id),
        raw.style.user_strength,
        mapping.pin,
        scale,
        raw.generation.img2img_strength,
        raw.generation.controlnet_scale,
        raw.generation.seed_policy,
        raw.generation.batch_execution,
        output.render_contract,
    )


def _unique_rule_ids(rules: tuple[RuleCapability, ...]) -> None:
    if len({rule.rule_id for rule in rules}) != len(rules):
        raise DomainError("compiled rules must have unique rule ids")
