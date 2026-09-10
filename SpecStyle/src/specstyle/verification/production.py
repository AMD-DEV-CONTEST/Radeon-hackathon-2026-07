"""Private production verifier factory and bound verifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.errors import DomainError, InfrastructureError, _GpuOutOfMemoryError
from specstyle.generation.diffusers_backend import StyleAssetResolver
from specstyle.generation.diffusers_loader import (
    LoadedPipeline,
    _GPU_LEASE,
    _VerifiedImageEvidenceEncoder,
)
from specstyle.generation.image_evidence import (
    _ProcessorProvenance,
    _VerifiedImageEvidence,
)
from specstyle.generation.preprocess import PreparedImage
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import (
    CompiledRule,
    CompiledStyleSpec,
    CompiledVerificationPlan,
    CompilerContext,
)
from specstyle.verification.l1.decode import decode_png_bytes
from specstyle.verification.l1.dimensions import check_dimensions_decoded
from specstyle.verification.l1.pixels import check_pixels_decoded
from specstyle.verification.l1.production_bindings import (
    _PRODUCTION_L1_RULE_REGISTRY,
    _ProductionL1Implementation,
    _validate_production_l1_rule_registry,
)
from specstyle.verification.l3.structure_edges import _structure_edge_similarity_for_pin
from specstyle.verification.production_contracts import (
    _CanonicalProductionState,
    _FactoryIssuedState,
    _LoadedVerificationBinding,
    _ProductionContractViolation,
    _binding_digest,
    _build_canonical_state,
    _canonical_l1_mappings,
    _clone_compiler_context,
    _copy_pin,
    _descriptor_pin,
    _provenance_snapshot,
    _rebuild_request,
    _validate_production_binding,
)
from specstyle.verification.production_metrics import (
    _MetricContractViolation,
    _l1_outcome,
    _l2_similarity,
    _l3_similarity,
    _threshold_outcome,
    _unverifiable_result,
)
from specstyle.verification.rule_models import RuleDefinition, RuleResult

__all__ = ()

_ALLOWLIST_SCHEMA = "specstyle.production_verifier.v1"
_FACTORY_SEAL = object()
_VERIFIER_SEAL = object()


@runtime_checkable
class ArtifactResolver(Protocol):
    def __call__(self, reference: ArtifactRef, /) -> GeneratedArtifact | None: ...


@dataclass(frozen=True, slots=True)
class _L1RuleMapping:
    rule_id: RuleId
    implementation: str

    def __post_init__(self) -> None:
        try:
            valid = (
                type(self.rule_id) is RuleId
                and type(self.implementation) is str
                and _ProductionL1Implementation(self.implementation).value
                == self.implementation
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise DomainError("invalid production verifier dependency")


@dataclass(frozen=True, slots=True)
class _ProductionVerificationAllowlist:
    schema_version: str = _ALLOWLIST_SCHEMA
    compiler_context: CompilerContext | None = None
    processor_provenance: _ProcessorProvenance | None = None
    l1_rule_mappings: tuple[_L1RuleMapping, ...] = ()

    def __post_init__(self) -> None:
        mappings = self.l1_rule_mappings
        if (
            type(self.schema_version) is not str
            or self.schema_version != _ALLOWLIST_SCHEMA
            or type(self.compiler_context) is not CompilerContext
            or type(self.processor_provenance) is not _ProcessorProvenance
            or type(mappings) is not tuple
            or len(mappings) != len(_PRODUCTION_L1_RULE_REGISTRY)
            or any(type(mapping) is not _L1RuleMapping for mapping in mappings)
            or len({mapping.rule_id for mapping in mappings}) != len(mappings)
            or tuple(sorted(mapping.implementation for mapping in mappings))
            != tuple(
                sorted(
                    implementation.value
                    for implementation in _ProductionL1Implementation
                )
            )
        ):
            raise DomainError("invalid production verifier dependency")
        values = tuple(
            (mapping.rule_id, mapping.implementation) for mapping in mappings
        )
        try:
            _validate_production_l1_rule_registry(values)
        except DomainError:
            raise DomainError("invalid production verifier dependency") from None


@dataclass(frozen=True, slots=True, init=False)
class _ProductionVerifierFactory:
    _loaded: LoadedPipeline = field(repr=False, compare=False)
    _allowlist: _ProductionVerificationAllowlist = field(repr=False, compare=False)
    _evidence: object = field(repr=False, compare=False)
    _issued: _FactoryIssuedState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("production verifier factories are issued only")

    def create(
        self,
        request: GenerationRequest,
        plan: CompiledVerificationPlan,
        artifact_resolver: ArtifactResolver,
        style_resolver: StyleAssetResolver,
        /,
    ) -> _BoundProductionVerifier:
        _validate_create_dependencies(
            self, request, plan, artifact_resolver, style_resolver
        )
        canonical_compiled, canonical_plan = _validate_create_binding(
            self, request, plan
        )
        return _issue_bound_verifier(
            self,
            request,
            plan,
            artifact_resolver,
            style_resolver,
            canonical_compiled,
            canonical_plan,
        )

    def __copy__(self) -> _ProductionVerifierFactory:
        raise TypeError("production verifier factories cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> _ProductionVerifierFactory:
        raise TypeError("production verifier factories cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("production verifier factories cannot be serialized")


@dataclass(frozen=True, slots=True, init=False)
class _BoundProductionVerifier:
    _factory: _ProductionVerifierFactory = field(repr=False, compare=False)
    _request: GenerationRequest = field(repr=False, compare=False)
    _plan: CompiledVerificationPlan = field(repr=False, compare=False)
    _artifact_resolver: ArtifactResolver = field(repr=False, compare=False)
    _style_resolver: StyleAssetResolver = field(repr=False, compare=False)
    _canonical: _CanonicalProductionState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("production verifiers are issued only")

    def verify(
        self,
        artifacts: tuple[ArtifactRef, ...],
        rules: tuple[RuleDefinition, ...],
        /,
    ) -> tuple[RuleResult, ...]:
        with _GPU_LEASE:
            return self._verify_under_lease(artifacts, rules)

    def _verify_under_lease(
        self,
        artifacts: tuple[ArtifactRef, ...],
        rules: tuple[RuleDefinition, ...],
        /,
    ) -> tuple[RuleResult, ...]:
        reference, canonical = _validate_verifier_invocation(self, artifacts, rules)
        artifact = _resolve_artifact(self, reference)
        if artifact is None:
            results = tuple(
                RuleResult(
                    definition.rule_id,
                    RuleStatus.UNVERIFIABLE,
                    (reference.artifact_id,),
                    None,
                )
                for definition in canonical
            )
            _checkpoint(self)
            return results
        results = _evaluate_rules(self, artifact, canonical)
        _checkpoint(self)
        return results

    def __copy__(self) -> _BoundProductionVerifier:
        raise TypeError("production verifiers cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> _BoundProductionVerifier:
        raise TypeError("production verifiers cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("production verifiers cannot be serialized")


def _validate_create_dependencies(
    factory: object,
    request: object,
    plan: object,
    artifact_resolver: object,
    style_resolver: object,
) -> None:
    _validate_factory(factory)
    if (
        type(request) is not GenerationRequest
        or type(plan) is not CompiledVerificationPlan
        or not callable(artifact_resolver)
        or not callable(style_resolver)
    ):
        raise _dependency_failure()


def _loaded_binding(factory: _ProductionVerifierFactory) -> _LoadedVerificationBinding:
    loaded, evidence = factory._loaded, factory._evidence
    graph = loaded._graph
    return _LoadedVerificationBinding(
        Sha256(loaded._environment_hash.value),
        tuple(loaded._runtime),
        graph.profile,
        _descriptor_pin(graph.base),
        _descriptor_pin(graph.ip_adapter),
        _descriptor_pin(graph.controlnet),
        _copy_pin(evidence.pin),
        evidence.preprocessing_version,
        evidence.layer,
    )


def _validate_create_binding(
    factory: _ProductionVerifierFactory,
    request: GenerationRequest,
    plan: CompiledVerificationPlan,
) -> tuple[CompiledStyleSpec, CompiledVerificationPlan]:
    issued = factory._issued
    try:
        return _validate_production_binding(
            _loaded_binding(factory),
            request.compiled_spec,
            request.generation_profile,
            request.output_profile,
            request.environment_hash,
            request.graph,
            plan,
            issued.context_snapshot,
            issued.mappings,
            True,
        )
    except Exception:
        raise _dependency_failure() from None


def _issue_bound_verifier(
    factory: _ProductionVerifierFactory,
    request: GenerationRequest,
    plan: CompiledVerificationPlan,
    artifact_resolver: ArtifactResolver,
    style_resolver: StyleAssetResolver,
    canonical_compiled: CompiledStyleSpec,
    canonical_plan: CompiledVerificationPlan,
) -> _BoundProductionVerifier:
    issued = factory._issued
    try:
        state = _build_canonical_state(
            factory,
            issued,
            request,
            plan,
            artifact_resolver,
            style_resolver,
            canonical_compiled,
            canonical_plan,
        )
    except Exception:
        raise _dependency_failure() from None
    verifier = object.__new__(_BoundProductionVerifier)
    for name, value in (
        ("_factory", factory),
        ("_request", request),
        ("_plan", plan),
        ("_artifact_resolver", artifact_resolver),
        ("_style_resolver", style_resolver),
        ("_canonical", state),
        ("_seal", _VERIFIER_SEAL),
    ):
        object.__setattr__(verifier, name, value)
    return verifier


def _dependency_failure() -> DomainError:
    return DomainError("invalid production verifier dependency")


def _contract_failure() -> InfrastructureError:
    return InfrastructureError("production verification contract violation")


def _validate_verifier_invocation(
    verifier: _BoundProductionVerifier,
    artifacts: object,
    rules: object,
) -> tuple[ArtifactRef, tuple[RuleDefinition, ...]]:
    if (
        type(verifier) is not _BoundProductionVerifier
        or type(artifacts) is not tuple
        or len(artifacts) != 1
        or type(artifacts[0]) is not ArtifactRef
        or type(rules) is not tuple
    ):
        raise DomainError("invalid production verifier invocation")
    state = getattr(verifier, "_canonical", None)
    if type(state) is not _CanonicalProductionState:
        raise _contract_failure()
    if len(rules) != len(state.live_rules) or any(
        supplied is not expected for supplied, expected in zip(rules, state.live_rules)
    ):
        raise DomainError("invalid production verifier invocation")
    try:
        supplied = artifacts[0]
        reference = ArtifactRef(
            ArtifactId(supplied.artifact_id.value), Sha256(supplied.sha256.value)
        )
        if reference != supplied:
            raise ValueError
    except Exception:
        raise DomainError("invalid production verifier invocation") from None
    _checkpoint(verifier)
    return reference, state.plan.applicable_rule_definitions


def _validate_state_identities(
    verifier: _BoundProductionVerifier, state: _CanonicalProductionState
) -> None:
    pairs = (
        (verifier._factory, state.factory),
        (verifier._request, state.live_request),
        (verifier._plan, state.live_plan),
        (verifier._artifact_resolver, state.artifact_resolver),
        (verifier._style_resolver, state.style_resolver),
    )
    current = state.live_plan.applicable_rule_definitions
    if (
        verifier._seal is not _VERIFIER_SEAL
        or any(actual is not expected for actual, expected in pairs)
        or len(current) != len(state.live_rules)
        or any(
            actual is not expected
            for actual, expected in zip(current, state.live_rules)
        )
    ):
        raise _ProductionContractViolation


def _revalidate_state(state: _CanonicalProductionState) -> None:
    factory, issued, request = state.factory, state.issued, state.live_request
    _validate_factory(factory)
    if factory._issued is not issued:
        raise _ProductionContractViolation
    binding = _loaded_binding(factory)
    mappings = _canonical_l1_mappings(factory._allowlist.l1_rule_mappings)
    compiled, plan = _validate_production_binding(
        binding,
        request.compiled_spec,
        request.generation_profile,
        request.output_profile,
        request.environment_hash,
        request.graph,
        state.live_plan,
        issued.context_snapshot,
        mappings,
    )
    rebuilt = _rebuild_request(request, compiled)
    provenance = _provenance_snapshot(factory._loaded._processor_provenance)
    live_digest = _binding_digest(rebuilt, plan, mappings, binding, provenance)
    fixed_digest = _binding_digest(
        state.request,
        state.plan,
        state.mappings,
        state.loaded_binding,
        state.provenance,
    )
    if (
        rebuilt != request
        or rebuilt != state.request
        or plan != state.plan
        or mappings != state.mappings
        or binding != state.loaded_binding
        or provenance != state.provenance
        or live_digest != state.digest
        or fixed_digest != state.digest
    ):
        raise _ProductionContractViolation


def _checkpoint(verifier: _BoundProductionVerifier) -> None:
    try:
        state = verifier._canonical
        if type(state) is not _CanonicalProductionState:
            raise _ProductionContractViolation
        _validate_state_identities(verifier, state)
        _revalidate_state(state)
    except Exception:
        raise _contract_failure() from None


def _resolve_artifact(
    verifier: _BoundProductionVerifier, reference: ArtifactRef
) -> GeneratedArtifact | None:
    try:
        artifact = verifier._canonical.artifact_resolver(reference)
    except Exception:
        _checkpoint(verifier)
        raise InfrastructureError(
            "production verification artifact resolution failed"
        ) from None
    _checkpoint(verifier)
    if artifact is None:
        return None
    request = verifier._canonical.request
    if (
        type(artifact) is not GeneratedArtifact
        or artifact.ref != reference
        or type(artifact.content) is not bytes
        or hash_bytes(artifact.content) != reference.sha256
        or artifact.request_hash != request.request_hash
        or artifact.generation_fingerprint != request.generation_fingerprint
    ):
        raise _contract_failure()
    return artifact


def _resolve_styles(verifier: _BoundProductionVerifier) -> tuple[bytes, ...] | None:
    contents: list[bytes] = []
    state = verifier._canonical
    for reference in state.request.style_references:
        try:
            content = state.style_resolver(reference)
        except Exception:
            _checkpoint(verifier)
            raise InfrastructureError(
                "production verification style resolution failed"
            ) from None
        _checkpoint(verifier)
        if content is None:
            return None
        if type(content) is not bytes or hash_bytes(content) != reference.sha256:
            raise _contract_failure()
        contents.append(content)
    return tuple(contents)


def _metric_without_execution(
    rule: CompiledRule, artifact_id: ArtifactId
) -> RuleResult | None:
    binding = rule.threshold_binding
    if binding is None:
        raise _contract_failure()
    try:
        outcome = _threshold_outcome(binding.status, binding.value, None)
    except _MetricContractViolation:
        raise _contract_failure() from None
    if outcome.execute:
        return None
    if outcome.status is None:
        raise _contract_failure()
    return RuleResult(rule.definition.rule_id, outcome.status, (artifact_id,), None)


def _encode_evidence(
    verifier: _BoundProductionVerifier,
    content: bytes,
    digest: Sha256,
    cache: dict[Sha256, _VerifiedImageEvidence | None],
) -> _VerifiedImageEvidence | None:
    if digest in cache:
        _checkpoint(verifier)
        return cache[digest]
    failure: InfrastructureError | None = None
    try:
        value = verifier._canonical.issued.evidence.encode(content, digest)
    except DomainError as error:
        _checkpoint(verifier)
        if error.args != ("invalid image evidence input",):
            raise _contract_failure() from None
        value = None
    except _GpuOutOfMemoryError:
        _checkpoint(verifier)
        value = None
        failure = _GpuOutOfMemoryError("verification OOM")
    except InfrastructureError as error:
        _checkpoint(verifier)
        messages = {
            "image evidence contract violation": "production verification contract violation",
            "image evidence encoding failed": "production verification encoder failed",
        }
        value = None
        failure = InfrastructureError(
            messages.get(str(error), "production verification encoder failed")
        )
    except Exception:
        _checkpoint(verifier)
        value = None
        failure = InfrastructureError("production verification encoder failed")
    if failure is not None:
        raise failure
    _checkpoint(verifier)
    if value is not None and (
        type(value) is not _VerifiedImageEvidence or value.asset_sha256 != digest
    ):
        raise _contract_failure()
    cache[digest] = value
    return value


def _metric_result(
    rule: CompiledRule, artifact_id: ArtifactId, score: float
) -> RuleResult:
    binding = rule.threshold_binding
    if binding is None:
        raise _contract_failure()
    try:
        outcome = _threshold_outcome(binding.status, binding.value, score)
    except _MetricContractViolation:
        raise _contract_failure() from None
    if outcome.execute or outcome.status is None or outcome.score != score:
        raise _contract_failure()
    return RuleResult(rule.definition.rule_id, outcome.status, (artifact_id,), score)


def _l2_result(
    verifier: _BoundProductionVerifier,
    rule: CompiledRule,
    artifact: GeneratedArtifact,
    styles: tuple[bytes, ...],
    cache: dict[Sha256, _VerifiedImageEvidence | None],
) -> RuleResult:
    output = _encode_evidence(verifier, artifact.content, artifact.ref.sha256, cache)
    state = verifier._canonical
    references = tuple(
        _encode_evidence(verifier, content, reference.sha256, cache)
        for content, reference in zip(styles, state.request.style_references)
    )
    if output is None or any(reference is None for reference in references):
        return _unverifiable_result(rule, artifact.ref.artifact_id)
    try:
        score = _l2_similarity(
            state.issued.torch,
            output.patch_hidden_state,
            tuple(reference.patch_hidden_state for reference in references),
        )
    except Exception:
        _checkpoint(verifier)
        raise _contract_failure() from None
    _checkpoint(verifier)
    return _metric_result(rule, artifact.ref.artifact_id, score)


def _source_evidence_material(
    verifier: _BoundProductionVerifier,
) -> tuple[bytes, Sha256]:
    source = verifier._canonical.request.source
    try:
        rebuilt = PreparedImage(source.source, source.content, source.snapshot)
    except Exception:
        raise _contract_failure() from None
    if rebuilt != source or rebuilt.sha256 != source.sha256:
        raise _contract_failure()
    return rebuilt.content, rebuilt.sha256


def _l3_result(
    verifier: _BoundProductionVerifier,
    rule: CompiledRule,
    artifact: GeneratedArtifact,
    cache: dict[Sha256, _VerifiedImageEvidence | None],
) -> RuleResult:
    source_content, source_sha = _source_evidence_material(verifier)
    if (
        rule.metric_id is not None
        and rule.metric_id.value == "structure_edge_similarity"
    ):
        score = _structure_edge_similarity_for_pin(
            rule.verifier_pin, source_content, artifact.content
        )
        _checkpoint(verifier)
        return (
            _unverifiable_result(rule, artifact.ref.artifact_id)
            if score is None
            else _metric_result(rule, artifact.ref.artifact_id, score)
        )
    output = _encode_evidence(verifier, artifact.content, artifact.ref.sha256, cache)
    source = _encode_evidence(verifier, source_content, source_sha, cache)
    if output is None or source is None:
        return _unverifiable_result(rule, artifact.ref.artifact_id)
    try:
        score = _l3_similarity(
            verifier._canonical.issued.torch,
            output.projected_embedding,
            source.projected_embedding,
        )
    except Exception:
        _checkpoint(verifier)
        raise _contract_failure() from None
    _checkpoint(verifier)
    return _metric_result(rule, artifact.ref.artifact_id, score)


def _l1_results(
    verifier: _BoundProductionVerifier,
    artifact: GeneratedArtifact,
) -> dict[RuleId, RuleResult]:
    decoded = None
    try:
        decoded = decode_png_bytes(artifact.content)
    except DomainError:
        pass
    dimensions_status = pixels_status = None
    if decoded is not None:
        artifact_id = artifact.ref.artifact_id
        graph = verifier._canonical.request.graph
        expected = graph.final_output_resolution
        dimensions_status = check_dimensions_decoded(
            artifact_id, decoded, expected
        ).status
        pixels_status = check_pixels_decoded(artifact_id, decoded).status
    results: dict[RuleId, RuleResult] = {}
    for rule_id, implementation in verifier._canonical.mappings:
        try:
            outcome = _l1_outcome(
                implementation,
                decoded is not None,
                dimensions_status,
                pixels_status,
            )
        except _MetricContractViolation:
            raise _contract_failure() from None
        results[rule_id] = RuleResult(
            rule_id,
            outcome.status,
            (artifact.ref.artifact_id,),
            outcome.score,
        )
    return results


def _evaluate_rules(
    verifier: _BoundProductionVerifier,
    artifact: GeneratedArtifact,
    canonical: tuple[RuleDefinition, ...],
) -> tuple[RuleResult, ...]:
    l1_results = _l1_results(verifier, artifact)
    compiled = {
        rule.definition.rule_id: rule for rule in verifier._canonical.plan.rules
    }
    results: list[RuleResult] = []
    style_contents: tuple[bytes, ...] | None | object = object()
    evidence_cache: dict[Sha256, _VerifiedImageEvidence | None] = {}
    for definition in canonical:
        rule = compiled[definition.rule_id]
        if definition.level is RuleLevel.L1:
            results.append(l1_results[definition.rule_id])
            continue
        inactive = _metric_without_execution(rule, artifact.ref.artifact_id)
        if inactive is not None:
            results.append(inactive)
            continue
        if definition.level is RuleLevel.L2:
            if type(style_contents) is object:
                style_contents = _resolve_styles(verifier)
            if style_contents is None:
                results.append(_unverifiable_result(rule, artifact.ref.artifact_id))
                continue
            results.append(
                _l2_result(verifier, rule, artifact, style_contents, evidence_cache)
            )
            continue
        results.append(_l3_result(verifier, rule, artifact, evidence_cache))
    return tuple(results)


def _validate_factory(value: object) -> None:
    if (
        type(value) is not _ProductionVerifierFactory
        or getattr(value, "_seal", None) is not _FACTORY_SEAL
        or type(getattr(value, "_issued", None)) is not _FactoryIssuedState
    ):
        raise _dependency_failure()
    issued = value._issued
    loaded, allowlist, evidence = value._loaded, value._allowlist, value._evidence
    mappings = getattr(allowlist, "l1_rule_mappings", None)
    identities = issued.provenance_identity
    try:
        valid = (
            loaded is issued.loaded
            and allowlist is issued.allowlist
            and evidence is issued.evidence
            and type(loaded) is LoadedPipeline
            and type(allowlist) is _ProductionVerificationAllowlist
            and type(evidence) is _VerifiedImageEvidenceEncoder
            and evidence._owner is loaded
            and loaded._torch is issued.torch
            and allowlist.compiler_context is issued.context
            and allowlist.compiler_context == issued.context_snapshot
            and type(identities) is tuple
            and len(identities) == 2
            and loaded._processor_provenance is identities[0]
            and allowlist.processor_provenance is identities[1]
            and allowlist.schema_version == _ALLOWLIST_SCHEMA
            and type(mappings) is tuple
            and len(mappings) == len(issued.mapping_identities)
            and all(a is b for a, b in zip(mappings, issued.mapping_identities))
            and _canonical_l1_mappings(mappings) == issued.mappings
            and _loaded_binding(value) == issued.loaded_binding
            and _provenance_snapshot(loaded._processor_provenance) == issued.provenance
            and _provenance_snapshot(allowlist.processor_provenance)
            == issued.provenance
        )
    except Exception:
        valid = False
    if not valid:
        raise _dependency_failure()


def _create_production_verifier_factory(
    loaded: LoadedPipeline, allowlist: _ProductionVerificationAllowlist, /
) -> _ProductionVerifierFactory:
    if (
        type(loaded) is not LoadedPipeline
        or type(allowlist) is not _ProductionVerificationAllowlist
    ):
        raise _dependency_failure()
    try:
        evidence = loaded._borrow_image_evidence_encoder()
        provenance = _provenance_snapshot(evidence.processor_provenance)
        if provenance != _provenance_snapshot(allowlist.processor_provenance):
            raise _ProductionContractViolation
        factory = object.__new__(_ProductionVerifierFactory)
        for name, value in (
            ("_loaded", loaded),
            ("_allowlist", allowlist),
            ("_evidence", evidence),
            ("_seal", _FACTORY_SEAL),
        ):
            object.__setattr__(factory, name, value)
        issued = _FactoryIssuedState(
            loaded,
            allowlist,
            evidence,
            loaded._torch,
            allowlist.compiler_context,
            _clone_compiler_context(allowlist.compiler_context),
            allowlist.l1_rule_mappings,
            _canonical_l1_mappings(allowlist.l1_rule_mappings),
            _loaded_binding(factory),
            (loaded._processor_provenance, allowlist.processor_provenance),
            provenance,
        )
        object.__setattr__(factory, "_issued", issued)
        _validate_factory(factory)
        return factory
    except Exception:
        raise _dependency_failure() from None
