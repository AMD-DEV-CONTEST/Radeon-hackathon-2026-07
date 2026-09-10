"""APP-COMPOSE-001A production generation composition contracts."""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import threading
from dataclasses import fields
from dataclasses import FrozenInstanceError, replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.enums import (
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    Identifier,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.preprocess import (
    PreprocessPlan,
    PreparedImage,
    preprocess_image,
)
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import RenderedPrompt
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import ResourcePin
from specstyle.workflow.job_store import JobStore
from specstyle.verification.rule_models import GatePolicy, RuleDefinition, RuleResult


class _HostileStr(str):
    def __eq__(self, _other: object) -> bool:
        return True

    __hash__ = str.__hash__


class _HostileInt(int):
    pass


class _HostileTuple(tuple):
    pass


class _HostileJobId(JobId):
    pass


class _HostileRuleId(RuleId):
    pass


class _HostileAssetRef(AssetRef):
    pass


class _HostilePreparedImage(PreparedImage):
    pass


class _HostilePrompt(RenderedPrompt):
    pass


def _png(size: tuple[int, int] = (64, 64), color: str = "red") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


def _source() -> PreparedImage:
    content = _png()
    return preprocess_image(
        content,
        AssetRef(AssetId("source"), hash_bytes(content)),
        PreprocessPlan(
            (64, 64),
            "contain_pad",
            (0, 0, 0),
            ResourcePin("processor", "r1", hash_bytes(b"processor")),
        ),
    )


def _prompt() -> RenderedPrompt:
    return RenderedPrompt(
        ResourcePin("template", "r1", hash_bytes(b"template")),
        Identifier("preset"),
        "positive",
        "",
    )


def _style_references() -> tuple[AssetRef, ...]:
    return (
        AssetRef(AssetId("style-0"), hash_bytes(b"style-0")),
        AssetRef(AssetId("style-1"), hash_bytes(b"style-1")),
    )


def _request_type():
    try:
        module = importlib.import_module("specstyle.workflow.production_service")
    except ModuleNotFoundError:
        pytest.fail("production service module is missing")
    return module, module.ProductionJobRequest


def _request_kwargs() -> dict[str, object]:
    return {
        "job_id": JobId("job-1"),
        "spec_text": "spec",
        "source": _source(),
        "style_references": _style_references(),
        "prompt": _prompt(),
        "output_profile": "xhs_grid",
        "variation_index": 0,
        "bundle_name": "bundle-1",
    }


def test_production_service_exposes_one_public_runtime_surface() -> None:
    module, request_type = _request_type()

    request = request_type(**_request_kwargs())

    assert module.__all__ == (
        "ProductionJobRequest",
        "ProductionJobResult",
        "ProductionL1RuleBinding",
        "production_l1_rule_bindings",
        "ProductionRuntime",
        "ProductionRuntimeReadiness",
        "ProductionRuntimeFailureKind",
        "load_production_compiler_context",
        "open_production_runtime",
    )
    assert module._ProductionGenerationRuntime is module.ProductionRuntime
    assert module._RuntimeReadiness is module.ProductionRuntimeReadiness
    assert module._RuntimeFailureKind is module.ProductionRuntimeFailureKind
    assert module._open_production_generation_runtime is module.open_production_runtime
    assert callable(module.open_production_runtime)
    assert tuple(field.name for field in fields(module.ProductionJobResult)) == (
        "compiled",
        "graph",
        "verification_plan",
        "request",
        "artifact",
        "report",
        "history",
        "terminal",
        "job_state",
    )
    assert not hasattr(request, "__dict__")
    assert request.style_references == _style_references()
    with pytest.raises(FrozenInstanceError):
        request.bundle_name = "other"


def test_production_runtime_exposes_only_named_export_entrypoints() -> None:
    module = _request_type()[0]

    assert not hasattr(module.ProductionRuntime, "export")
    assert callable(module.ProductionRuntime.publish_export)
    assert callable(module.ProductionRuntime.recover_exports)
    assert tuple(
        inspect.signature(module.ProductionRuntime.publish_export).parameters
    ) == (
        "self",
        "command",
        "target_root_fd",
    )
    assert tuple(
        inspect.signature(module.ProductionRuntime.recover_exports).parameters
    ) == (
        "self",
        "commands",
        "target_root_fd",
    )


def test_single_item_runtime_rejects_required_batch_plan() -> None:
    module = importlib.import_module("specstyle.workflow.production_service")
    definition = RuleDefinition(
        RuleId("batch_required"),
        RuleLevel.L2,
        RuleScope.BATCH,
        True,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", "reject", "manual_review"),
    )
    plan = SimpleNamespace(rules=(SimpleNamespace(definition=definition),))

    with pytest.raises(DomainError, match="^BATCH_CONTEXT_REQUIRED$"):
        module._reject_required_batch_plan(plan)


def test_public_l1_bindings_are_frozen_slotted_and_exact() -> None:
    module = _request_type()[0]
    binding = module.ProductionL1RuleBinding(
        RuleId("l1_bundle"), "technical_rgb_png_bundle_v1"
    )

    assert tuple(field.name for field in fields(binding)) == (
        "rule_id",
        "implementation",
    )
    assert not hasattr(binding, "__dict__")
    with pytest.raises(FrozenInstanceError):
        binding.implementation = "decode_png_rgb_no_metadata_v1"
    with pytest.raises(DomainError):
        module.ProductionL1RuleBinding(
            _HostileRuleId("l1_bundle"), "technical_rgb_png_bundle_v1"
        )
    with pytest.raises(DomainError):
        module.ProductionL1RuleBinding(
            RuleId("l1_bundle"), _HostileStr("technical_rgb_png_bundle_v1")
        )

    first = module.production_l1_rule_bindings()
    second = module.production_l1_rule_bindings()
    assert tuple((item.rule_id.value, item.implementation) for item in first) == (
        ("l1_bundle", "technical_rgb_png_bundle_v1"),
        ("l1_decode", "decode_png_rgb_no_metadata_v1"),
        ("l1_dimensions", "dimensions_exact_v1"),
        ("l1_pixels", "pixels_nonblank_v1"),
    )
    assert first is not second
    assert all(left is not right for left, right in zip(first, second, strict=True))
    object.__setattr__(first[0], "implementation", "tampered")
    assert module.production_l1_rule_bindings()[0].implementation == (
        "technical_rgb_png_bundle_v1"
    )


def test_prepare_export_builds_one_approved_xhs_item_without_expanding_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    from specstyle.reliability.fixtures import sample_approved_export_request
    from specstyle.workflow.job_models import Job, JobBudget, JobState, JobStatus

    prepared = sample_approved_export_request()
    item = prepared.cohorts[0].items[0]
    generation_request = item.history.current_request
    job_request = request_type(
        generation_request.job_id,
        generation_request.compiled_spec.source_spec.model_dump_json(),
        generation_request.source,
        generation_request.style_references,
        generation_request.prompt,
        generation_request.output_profile,
        generation_request.variation_index,
        "bundle",
    )
    job = Job(
        generation_request.job_id,
        generation_request.compiled_spec.compiled_spec_hash,
        (generation_request.output_profile,),
        JobBudget(2),
        JobStatus.APPROVED,
        "2026-08-02T00:00:00.000Z",
        "2026-08-02T00:00:01.000Z",
    )
    result = module.ProductionJobResult(
        generation_request.compiled_spec,
        generation_request.compiled_spec.production_graphs[0],
        generation_request.compiled_spec.verification_plans[0],
        generation_request,
        item.history.current_artifact,
        item.history.current_report,
        item.history,
        item.terminal,
        JobState(job, 5, (generation_request.attempt_id,), ()),
    )
    runtime = object.__new__(module._ProductionGenerationRuntime)
    runtime._environment = prepared.environment
    from specstyle.reliability.fixtures import sample_compiler_context

    runtime._compiler_context = sample_compiler_context()
    monkeypatch.setattr(
        module,
        "_select_initial_contract",
        lambda *_args: (
            result.compiled,
            result.graph,
            result.verification_plan,
        ),
    )

    command = runtime.prepare_export(job_request, result, prepared.asset_credits)

    assert module.__all__ == (
        "ProductionJobRequest",
        "ProductionJobResult",
        "ProductionL1RuleBinding",
        "production_l1_rule_bindings",
        "ProductionRuntime",
        "ProductionRuntimeReadiness",
        "ProductionRuntimeFailureKind",
        "load_production_compiler_context",
        "open_production_runtime",
    )
    assert command.job_id == generation_request.job_id
    assert command.bundle_name == "bundle"
    assert len(command.export_request.cohorts) == 1
    cohort = command.export_request.cohorts[0]
    assert cohort.output_profile == "xhs_grid"
    assert len(cohort.items) == 1
    assert cohort.items[0].sequence_index is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_id", object()),
        ("job_id", _HostileJobId("job-1")),
        ("spec_text", object()),
        ("spec_text", _HostileStr("spec")),
        ("source", object()),
        (
            "source",
            lambda: _HostilePreparedImage(
                _source().source, _source().content, _source().snapshot
            ),
        ),
        ("style_references", []),
        ("style_references", ()),
        ("style_references", _HostileTuple(_style_references())),
        (
            "style_references",
            lambda: (
                _HostileAssetRef(
                    _style_references()[0].asset_id,
                    _style_references()[0].sha256,
                ),
            ),
        ),
        ("prompt", object()),
        (
            "prompt",
            lambda: _HostilePrompt(
                _prompt().template_pin,
                _prompt().preset_id,
                _prompt().positive,
                _prompt().negative,
            ),
        ),
        ("output_profile", "unknown"),
        ("output_profile", _HostileStr("xhs_grid")),
        ("variation_index", True),
        ("variation_index", -1),
        ("variation_index", 2**31),
        ("variation_index", _HostileInt(0)),
        ("bundle_name", "bad/name"),
        ("bundle_name", _HostileStr("bundle-1")),
    ],
)
def test_request_rejects_noncanonical_fields(field: str, value: object) -> None:
    _module, request_type = _request_type()
    kwargs = _request_kwargs()
    kwargs[field] = value() if callable(value) else value

    with pytest.raises(DomainError):
        request_type(**kwargs)


@pytest.mark.parametrize(
    ("output_profile", "maximum_job_id_length"),
    [
        ("xhs_grid", 114),
        ("talking_head_cover", 104),
        ("background_sequence", 103),
    ],
)
def test_request_accepts_only_job_ids_that_fit_the_exact_attempt_id(
    output_profile: str, maximum_job_id_length: int
) -> None:
    _module, request_type = _request_type()
    kwargs = _request_kwargs()
    kwargs["output_profile"] = output_profile
    kwargs["job_id"] = JobId("j" * maximum_job_id_length)

    request = request_type(**kwargs)
    expected_attempt_id = f"{'j' * maximum_job_id_length}-a0-{output_profile}-0"

    assert request.job_id.value == "j" * maximum_job_id_length
    assert len(expected_attempt_id) == 128
    assert AttemptId(expected_attempt_id).value == expected_attempt_id

    kwargs["job_id"] = JobId("j" * (maximum_job_id_length + 1))
    with pytest.raises(DomainError):
        request_type(**kwargs)


@pytest.mark.parametrize(
    ("profiles", "policy_version", "max_rounds", "stop_after"),
    [
        (("xhs_grid", "talking_head_cover"), "1.0", 1, 1),
        (("xhs_grid",), "1.1", 1, 1),
        (("xhs_grid",), "1.0", 2, 1),
        (("xhs_grid",), "1.0", 2, 2),
    ],
)
def test_selection_rejects_non_frozen_single_item_repair_contract_pre_genesis(
    monkeypatch: pytest.MonkeyPatch,
    profiles: tuple[str, ...],
    policy_version: str,
    max_rounds: int,
    stop_after: int,
) -> None:
    module, request_type = _request_type()
    graph = SimpleNamespace(output_profile="xhs_grid")
    plan = SimpleNamespace(output_profile="xhs_grid", rules=())
    compiled = SimpleNamespace(
        production_graphs=(graph,),
        verification_plans=(plan,),
        source_spec=SimpleNamespace(
            outputs=SimpleNamespace(profiles=profiles),
            repair=SimpleNamespace(
                policy_version=policy_version,
                max_rounds=max_rounds,
                stop_after_no_improvement=stop_after,
            ),
        ),
    )
    monkeypatch.setattr(module, "load_style_spec_text", lambda _text: object())
    monkeypatch.setattr(module, "compile_style_spec", lambda *_args: compiled)

    with pytest.raises(DomainError, match="production repair contract is unsupported"):
        module._select_initial_contract(request_type(**_request_kwargs()), object())


def test_module_has_no_forbidden_production_dependencies() -> None:
    module = _request_type()[0]
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    forbidden = (
        "specstyle.generation.fake_backend",
        "specstyle.workflow.real_pipeline",
        "specstyle.workflow.orchestrator",
        "specstyle.workflow.batch_runner",
        "specstyle.exporting",
        "gradio",
        "tests",
    )
    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden
    )
    assert {
        "specstyle.workflow.production_artifacts",
        "specstyle.workflow.production_reports",
        "specstyle.workflow.production_repair",
        "specstyle.repair.history",
        "specstyle.repair.loop",
        "specstyle.verification.production",
        "specstyle.verification.protocols",
        "specstyle.verification.rule_models",
    }.issubset(imports)
    repair_core_calls = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module in {"specstyle.repair.history", "specstyle.repair.loop"}
        for alias in node.names
    }
    assert not {
        "start_repair_history",
        "next_repair_step",
        "consume_repair_result",
    }.intersection(repair_core_calls)


class _UnusedControlBuilder:
    def build(self, _source: object, _graph: object) -> object:
        raise AssertionError("control input must not be built while opening")


def test_private_factory_loads_and_owns_only_the_loaded_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _request_type()[0]
    factory = getattr(module, "_open_production_generation_runtime", None)
    assert callable(factory)

    from tests.unit.generation.test_diffusers_loader import (
        _Diffusers,
        _Torch,
        _environment,
        _supply,
    )
    from tests.unit.spec.test_compiler import context

    supply, graph = _supply(tmp_path / "weights")
    store_root = tmp_path / "store"
    store_root.mkdir()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    artifact_root_fd = os.open(artifact_root, os.O_RDONLY | os.O_DIRECTORY)
    diffusers = _Diffusers()
    l1_rule_bindings = tuple(
        module.ProductionL1RuleBinding(RuleId(rule_id), implementation)
        for rule_id, implementation in (
            ("l1_bundle", "technical_rgb_png_bundle_v1"),
            ("l1_decode", "decode_png_rgb_no_metadata_v1"),
            ("l1_dimensions", "dimensions_exact_v1"),
            ("l1_pixels", "pixels_nonblank_v1"),
        )
    )
    issued_factories: list[object] = []
    create_factory = module._create_production_verifier_factory

    def tracked_create_factory(*args: object) -> object:
        issued = create_factory(*args)
        issued_factories.append(issued)
        return issued

    monkeypatch.setattr(
        module, "_create_production_verifier_factory", tracked_create_factory
    )
    callback_versions: list[str] = []
    base_context = context()

    def compiler_context_factory(preprocessing_version: str):
        callback_versions.append(preprocessing_version)
        encoder = base_context.encoder_capabilities[0]
        return replace(
            base_context,
            encoder_capabilities=(
                replace(
                    encoder,
                    pin=ResourcePin(
                        graph.ip_adapter.model_id,
                        graph.ip_adapter.revision,
                        graph.ip_adapter.expected_sha256,
                    ),
                    preprocessing_version=preprocessing_version,
                    layer="hidden_states[-2]",
                ),
            ),
        )

    runtime = factory(
        supply,
        graph,
        _environment(),
        compiler_context_factory,
        lambda _reference: b"",
        _UnusedControlBuilder(),
        l1_rule_bindings,
        JobStore(store_root),
        artifact_root_fd,
        torch_module=_Torch(),
        diffusers_module=diffusers,
    )
    os.close(artifact_root_fd)
    initial_loaded = runtime._loaded
    initial_allowlist = runtime._allowlist
    pipeline = initial_loaded.borrow_pipeline()
    owned_factory = runtime._verifier_factory
    assert callable(runtime._load_pipeline)
    assert callback_versions == [
        runtime._loaded._borrow_image_evidence_encoder().preprocessing_version
    ]
    assert runtime.compiler_context == runtime._compiler_context
    assert runtime.compiler_context is not runtime._compiler_context
    external_context = runtime.compiler_context
    object.__setattr__(external_context, "encoder_capabilities", ())
    assert runtime.compiler_context.encoder_capabilities
    assert (
        runtime._allowlist.processor_provenance is runtime._loaded._processor_provenance
    )
    assert tuple(
        (mapping.rule_id.value, mapping.implementation)
        for mapping in runtime._allowlist.l1_rule_mappings
    ) == tuple(
        (binding.rule_id.value, binding.implementation) for binding in l1_rule_bindings
    )

    runtime._loaded.close()
    runtime._verifier_factory = None
    runtime._readiness_value = module._RuntimeReadiness.QUARANTINED
    runtime._failure_kind_value = module._RuntimeFailureKind.GPU_OOM
    runtime.reopen()
    reopened_loaded = runtime._loaded
    reopened_allowlist = runtime._allowlist
    reopened_pipeline = reopened_loaded.borrow_pipeline()
    reopened_factory = runtime._verifier_factory
    assert reopened_allowlist is not initial_allowlist
    assert (
        reopened_allowlist.processor_provenance is reopened_loaded._processor_provenance
    )
    assert reopened_factory._allowlist is reopened_allowlist
    with pytest.raises(DomainError, match="closed"):
        initial_loaded.borrow_pipeline()

    reopened_loaded.close()
    runtime._verifier_factory = None
    runtime._readiness_value = module._RuntimeReadiness.QUARANTINED
    runtime._failure_kind_value = module._RuntimeFailureKind.GPU_OOM
    failed_loaded: list[object] = []
    retained_load = runtime._load_pipeline

    def tracked_load():
        loaded = retained_load()
        failed_loaded.append(loaded)
        return loaded

    primary = InfrastructureError("reopen factory failed")
    runtime._load_pipeline = tracked_load
    failed_bindings: list[tuple[object, object]] = []

    def fail_factory(loaded, allowlist):
        failed_bindings.append((loaded, allowlist))
        raise primary

    monkeypatch.setattr(
        module,
        "_create_production_verifier_factory",
        fail_factory,
    )
    with pytest.raises(InfrastructureError) as raised:
        runtime.reopen()
    assert raised.value is primary
    assert runtime._loaded is reopened_loaded
    assert runtime._allowlist is reopened_allowlist
    assert runtime._verifier_factory is None
    assert runtime.readiness is module._RuntimeReadiness.QUARANTINED
    assert runtime.failure_kind is module._RuntimeFailureKind.GPU_OOM
    assert failed_bindings[0][0] is failed_loaded[0]
    assert (
        failed_bindings[0][1].processor_provenance
        is failed_loaded[0]._processor_provenance
    )
    with pytest.raises(DomainError, match="closed"):
        failed_loaded[0].borrow_pipeline()

    runtime.close()
    runtime.close()

    assert issued_factories == [owned_factory, reopened_factory]
    assert runtime._verifier_factory is None
    assert pipeline.hooks == 1
    assert reopened_pipeline is not pipeline
    assert reopened_pipeline.hooks == 1
    assert failed_loaded[0]._closed is True
    assert len(callback_versions) == 1
    assert supply.borrow_component("base").model_id == "base"
    supply.close()


@pytest.mark.parametrize(
    "failure_kind",
    (
        "raises",
        "wrong_type",
        "missing_encoder",
        "wrong_version",
        "wrong_layer",
        "duplicate_encoder",
        "mutated_sequence",
    ),
)
def test_context_factory_runs_once_outside_gpu_lease_and_failure_closes_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    module = _request_type()[0]
    from tests.unit.spec.test_compiler import context

    class Evidence:
        pin = context().encoder_capabilities[0].pin
        preprocessing_version = "processor-v1"
        layer = "layer"

    class Loaded:
        closed = False

        def _borrow_image_evidence_encoder(self):
            return Evidence()

        def close(self) -> None:
            self.closed = True

    loaded = Loaded()
    loads: list[str] = []
    monkeypatch.setattr(
        module,
        "_bind_pipeline_loader",
        lambda *_args: lambda: (loads.append("load"), loaded)[1],
    )
    lease_depth = 0

    class Lease:
        def __enter__(self):
            nonlocal lease_depth
            lease_depth += 1

        def __exit__(self, *_args):
            nonlocal lease_depth
            lease_depth -= 1

    monkeypatch.setattr(module, "_GPU_LEASE", Lease())
    calls: list[str] = []
    primary = InfrastructureError("context callback failed")

    def compiler_context_factory(version: str):
        calls.append(version)
        assert lease_depth == 0
        if failure_kind == "raises":
            raise primary
        if failure_kind == "wrong_type":
            return object()
        base = context()
        if failure_kind == "missing_encoder":
            return replace(base, encoder_capabilities=())
        encoder = base.encoder_capabilities[0]
        if failure_kind == "wrong_version":
            return base
        bound = replace(
            encoder,
            preprocessing_version=version,
            layer="wrong" if failure_kind == "wrong_layer" else "layer",
        )
        candidate = replace(
            base,
            encoder_capabilities=(
                (bound, bound) if failure_kind == "duplicate_encoder" else (bound,)
            ),
        )
        if failure_kind == "mutated_sequence":
            object.__setattr__(candidate, "encoder_capabilities", [bound])
        return candidate

    store_root = tmp_path / "store"
    artifact_root = tmp_path / "artifacts"
    store_root.mkdir()
    artifact_root.mkdir()
    root_fd = os.open(artifact_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected = InfrastructureError if failure_kind == "raises" else DomainError
        with pytest.raises(expected) as raised:
            module.open_production_runtime(
                object(),
                object(),
                object(),
                compiler_context_factory,
                lambda _reference: b"",
                _UnusedControlBuilder(),
                module.production_l1_rule_bindings(),
                JobStore(store_root),
                root_fd,
            )
    finally:
        os.close(root_fd)

    if failure_kind == "raises":
        assert raised.value is primary
    assert loads == ["load"]
    assert calls == ["processor-v1"]
    assert loaded.closed is True


def test_factory_rejects_noncanonical_l1_bindings_before_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _request_type()[0]
    good = module.production_l1_rule_bindings()
    swapped = (
        module.ProductionL1RuleBinding(
            RuleId("l1_bundle"), "decode_png_rgb_no_metadata_v1"
        ),
        module.ProductionL1RuleBinding(
            RuleId("l1_decode"), "technical_rgb_png_bundle_v1"
        ),
        *good[2:],
    )
    hostile = module.production_l1_rule_bindings()
    object.__setattr__(hostile[0], "rule_id", _HostileRuleId("l1_bundle"))
    candidates = (
        good[:-1],
        (*good, good[-1]),
        tuple(reversed(good)),
        swapped,
        list(good),
        hostile,
    )
    loads: list[str] = []
    monkeypatch.setattr(
        module,
        "_bind_pipeline_loader",
        lambda *_args: lambda: loads.append("load"),
    )
    store_root = tmp_path / "store"
    artifact_root = tmp_path / "artifacts"
    store_root.mkdir()
    artifact_root.mkdir()
    root_fd = os.open(artifact_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for bindings in candidates:
            with pytest.raises(DomainError):
                module.open_production_runtime(
                    object(),
                    object(),
                    object(),
                    lambda _version: object(),
                    lambda _reference: b"",
                    _UnusedControlBuilder(),
                    bindings,
                    JobStore(store_root),
                    root_fd,
                )
    finally:
        os.close(root_fd)

    assert loads == []


def test_context_factory_reentry_fails_before_a_second_load_and_closes_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _request_type()[0]
    from tests.unit.spec.test_compiler import context

    class Evidence:
        pin = context().encoder_capabilities[0].pin
        preprocessing_version = "processor-v1"
        layer = "layer"

    class Loaded:
        closed = False

        def _borrow_image_evidence_encoder(self):
            return Evidence()

        def close(self) -> None:
            self.closed = True

    loaded = Loaded()
    loads: list[str] = []
    monkeypatch.setattr(
        module,
        "_bind_pipeline_loader",
        lambda *_args: lambda: (loads.append("load"), loaded)[1],
    )
    store_root = tmp_path / "store"
    artifact_root = tmp_path / "artifacts"
    store_root.mkdir()
    artifact_root.mkdir()
    store = JobStore(store_root)
    root_fd = os.open(artifact_root, os.O_RDONLY | os.O_DIRECTORY)
    primary = InfrastructureError("stop outer callback")

    def compiler_context_factory(_version: str):
        with pytest.raises(DomainError, match="invalid production runtime dependency"):
            module.open_production_runtime(
                object(),
                object(),
                object(),
                compiler_context_factory,
                lambda _reference: b"",
                _UnusedControlBuilder(),
                module.production_l1_rule_bindings(),
                store,
                root_fd,
            )
        raise primary

    try:
        with pytest.raises(InfrastructureError) as raised:
            module.open_production_runtime(
                object(),
                object(),
                object(),
                compiler_context_factory,
                lambda _reference: b"",
                _UnusedControlBuilder(),
                module.production_l1_rule_bindings(),
                store,
                root_fd,
            )
    finally:
        os.close(root_fd)

    assert raised.value is primary
    assert loads == ["load"]
    assert loaded.closed is True


def test_source_consumers_do_not_import_private_runtime_surfaces() -> None:
    source_root = Path(__file__).parents[3] / "src" / "specstyle"
    private = {
        "_ProductionGenerationRuntime",
        "_RuntimeReadiness",
        "_RuntimeFailureKind",
        "_open_production_generation_runtime",
    }
    violations: list[tuple[str, str]] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "specstyle.workflow.production_service":
                continue
            violations.extend(
                (str(path.relative_to(source_root)), alias.name)
                for alias in node.names
                if alias.name in private
            )

    assert violations == []


def test_public_factory_and_runtime_shapes_are_frozen() -> None:
    module = _request_type()[0]
    signature = inspect.signature(module.open_production_runtime)
    parameters = tuple(signature.parameters.values())

    assert tuple(parameter.name for parameter in parameters) == (
        "supply",
        "pipeline_graph",
        "environment",
        "compiler_context_factory",
        "style_assets",
        "control_builder",
        "l1_rule_bindings",
        "job_store",
        "artifact_root_fd",
        "torch_module",
        "diffusers_module",
        "clock",
    )
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        for parameter in parameters[:9]
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[9:]
    )
    assert parameters[-1].default is module._utc_now
    assert tuple(field.name for field in fields(module.ProductionJobResult)) == (
        "compiled",
        "graph",
        "verification_plan",
        "request",
        "artifact",
        "report",
        "history",
        "terminal",
        "job_state",
    )
    assert module._ProductionGenerationRuntime.__slots__ == (
        "_loaded",
        "_load_pipeline",
        "_allowlist",
        "_verifier_factory",
        "_report_store",
        "_artifact_store",
        "_environment",
        "_compiler_context",
        "_style_assets",
        "_control_builder",
        "_job_store",
        "_clock",
        "_state_lock",
        "_run_lock",
        "_active_job_id",
        "_active_cancel",
        "_active_cancel_reason",
        "_readiness_value",
        "_failure_kind_value",
        "_closed",
    )


def _runtime_with_close_probes(module, events: list[str], first_error: Exception):
    runtime = object.__new__(module._ProductionGenerationRuntime)

    class Factory:
        def close(self) -> None:
            events.append("factory")

    class Loaded:
        def close(self) -> None:
            assert runtime._verifier_factory is None
            events.append("loaded")
            raise first_error

    class ArtifactStore:
        def close(self) -> None:
            events.append("artifact")
            raise InfrastructureError("later artifact close failure")

    class ReportStore:
        def close(self) -> None:
            events.append("report")
            raise InfrastructureError("later report close failure")

    values = {
        "_loaded": Loaded(),
        "_load_pipeline": lambda: None,
        "_allowlist": object(),
        "_verifier_factory": Factory(),
        "_report_store": ReportStore(),
        "_artifact_store": ArtifactStore(),
        "_environment": object(),
        "_compiler_context": object(),
        "_style_assets": object(),
        "_control_builder": object(),
        "_job_store": object(),
        "_clock": lambda: "2026-08-01T00:00:00.000Z",
        "_state_lock": threading.RLock(),
        "_run_lock": threading.Lock(),
        "_active_job_id": None,
        "_active_cancel": None,
        "_active_cancel_reason": None,
        "_readiness_value": module._RuntimeReadiness.READY,
        "_failure_kind_value": None,
        "_closed": False,
    }
    for name, value in values.items():
        setattr(runtime, name, value)
    return runtime


def test_close_detaches_factory_attempts_all_cleanup_and_preserves_first_error() -> (
    None
):
    module = _request_type()[0]
    events: list[str] = []
    first_error = InfrastructureError("first loaded close failure")
    runtime = _runtime_with_close_probes(module, events, first_error)

    with pytest.raises(InfrastructureError) as raised:
        runtime.close()
    runtime.close()

    assert raised.value is first_error
    assert events == ["factory", "loaded", "report", "artifact"]
    assert runtime._closed is True


def test_failed_runtime_open_cleanup_uses_runtime_ownership_order() -> None:
    module = _request_type()[0]
    events: list[str] = []

    class Resource:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            events.append(self.name)
            raise InfrastructureError(f"{self.name} close failure")

    module._cleanup_failed_open(
        Resource("loaded"),
        Resource("factory"),
        Resource("report"),
        Resource("artifact"),
    )

    assert events == ["report", "artifact", "factory", "loaded"]


def test_execute_after_close_fails_before_validating_the_request() -> None:
    module = _request_type()[0]
    runtime = _runtime_with_close_probes(
        module, [], InfrastructureError("unused close failure")
    )
    runtime._closed = True
    runtime._readiness_value = module._RuntimeReadiness.CLOSED

    with pytest.raises(InfrastructureError, match="^production runtime closed$"):
        runtime._execute_initial_attempt(object())


class _FlowRepository:
    def __init__(
        self,
        events: list[str],
        put_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.put_error = put_error
        self.close_error = close_error
        self.stored: GeneratedArtifact | None = None

    def put(self, artifact: GeneratedArtifact, /) -> None:
        self.events.append("artifact.put")
        if self.put_error is not None:
            raise self.put_error
        self.stored = artifact

    def __call__(self, _reference: ArtifactRef, /) -> GeneratedArtifact | None:
        self.events.append("artifact.read")
        return self.stored

    def close(self) -> None:
        self.events.append("artifact.close")
        if self.close_error is not None:
            raise self.close_error


class _FlowArtifactStore:
    def __init__(self, events: list[str], repository: _FlowRepository) -> None:
        self.events = events
        self.repository = repository

    def for_job(self, _job_id: JobId, /) -> _FlowRepository:
        self.events.append("artifact.for_job")
        return self.repository


class _FlowReportRepository:
    def __init__(
        self,
        events: list[str],
        put_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.put_error = put_error
        self.close_error = close_error
        self.stored: object | None = None

    def put(self, _request: object, report: object, /) -> None:
        self.events.append("report.put")
        if self.put_error is not None:
            raise self.put_error
        self.stored = report

    def __call__(self) -> object | None:
        self.events.append("report.read")
        return self.stored

    def close(self) -> None:
        self.events.append("report.close")
        if self.close_error is not None:
            raise self.close_error


class _FlowReportStore:
    def __init__(self, events: list[str], repository: _FlowReportRepository) -> None:
        self.events = events
        self.repository = repository

    def for_attempt(
        self, _job_id: JobId, _attempt_id: AttemptId, /
    ) -> _FlowReportRepository:
        self.events.append("report.for_attempt")
        return self.repository


class _FlowFactory:
    def __init__(
        self, events: list[str], create_error: Exception | None = None
    ) -> None:
        self.events = events
        self.create_error = create_error

    def create(self, *_args: object) -> object:
        self.events.append("verifier.create")
        if self.create_error is not None:
            raise self.create_error
        return object()


class _FlowJobStore:
    def __init__(self, events: list[str], state: object) -> None:
        self.events = events
        self.state = state
        self.appended: list[object] = []

    def get_snapshot(self, _job_id: JobId) -> None:
        self.events.append("duplicate.read")
        return None

    def load(self, _job_id: JobId) -> object:
        self.events.append("job.load")
        return self.state

    def append_event(self, _job_id: JobId, event: object) -> None:
        self.appended.append(event)
        self.events.append(f"event.{event.event_type.value}")


def _flow_artifact() -> GeneratedArtifact:
    content = _png()
    return GeneratedArtifact(
        ArtifactRef(ArtifactId("artifact-1"), hash_bytes(content)),
        content,
        Sha256("1" * 64),
        Sha256("2" * 64),
    )


def _install_flow_mocks(module, monkeypatch, events: list[str]) -> tuple[object, ...]:
    compiled, graph, plan = (object() for _ in range(3))
    generation_request = SimpleNamespace(
        job_id=JobId("job-1"), attempt_id=AttemptId("job-1-a0-xhs_grid-0")
    )
    artifact, report = _flow_artifact(), object()
    history = SimpleNamespace(
        current_request=generation_request,
        current_artifact=artifact,
        current_report=report,
    )
    terminal = SimpleNamespace(no_action=None)
    composition = SimpleNamespace(
        history=history, step=terminal, selecting_decision=None
    )

    def marked(name: str, value: object = None) -> object:
        events.append(name)
        return value

    monkeypatch.setattr(
        module,
        "_select_initial_contract",
        lambda *_args: marked("compile/select", (compiled, graph, plan)),
    )
    monkeypatch.setattr(
        module, "_preflight_bindings", lambda *_args: marked("preflight")
    )
    monkeypatch.setattr(
        module,
        "_initial_generation_request",
        lambda *_args: marked("request.build", generation_request),
    )
    monkeypatch.setattr(
        module, "_create_initial_job", lambda *_args: marked("genesis", object())
    )
    monkeypatch.setattr(
        module, "_record_attempt_start", lambda *_args: marked("events.1-3")
    )
    monkeypatch.setattr(
        module,
        "_run_initial_generation",
        lambda *_args: marked("generation", artifact),
    )
    monkeypatch.setattr(
        module, "_record_attempt_finish", lambda *_args: marked("event.4")
    )
    monkeypatch.setattr(
        module,
        "_run_initial_verification",
        lambda *_args: marked("verification", report),
    )
    monkeypatch.setattr(
        module,
        "_compose_initial_repair",
        lambda *_args: marked("repair.compose", composition),
    )
    monkeypatch.setattr(
        module._ProductionGenerationRuntime,
        "_record_terminal",
        lambda *_args: marked("event.final"),
    )
    return (
        compiled,
        graph,
        plan,
        generation_request,
        artifact,
        report,
        history,
        terminal,
    )


def _flow_runtime(
    module,
    events: list[str],
    repository: _FlowRepository,
    factory: _FlowFactory,
    report_repository: _FlowReportRepository | None = None,
):
    runtime = object.__new__(module._ProductionGenerationRuntime)
    state = object()
    if report_repository is None:
        report_repository = _FlowReportRepository(events)
    values = {
        "_loaded": object(),
        "_load_pipeline": lambda: None,
        "_allowlist": object(),
        "_verifier_factory": factory,
        "_artifact_store": _FlowArtifactStore(events, repository),
        "_report_store": _FlowReportStore(events, report_repository),
        "_environment": object(),
        "_compiler_context": object(),
        "_style_assets": object(),
        "_control_builder": object(),
        "_job_store": _FlowJobStore(events, state),
        "_clock": lambda: "2026-08-01T00:00:00.000Z",
        "_state_lock": threading.RLock(),
        "_run_lock": threading.Lock(),
        "_active_job_id": None,
        "_active_cancel": None,
        "_active_cancel_reason": None,
        "_readiness_value": module._RuntimeReadiness.READY,
        "_failure_kind_value": None,
        "_closed": False,
    }
    for name, value in values.items():
        setattr(runtime, name, value)
    return runtime, state


def test_initial_attempt_order_binds_verifier_before_genesis_and_persists_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    repository = _FlowRepository(events)
    runtime, state = _flow_runtime(module, events, repository, _FlowFactory(events))
    expected = _install_flow_mocks(module, monkeypatch, events)

    result = runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert events == [
        "compile/select",
        "preflight",
        "duplicate.read",
        "request.build",
        "artifact.for_job",
        "report.for_attempt",
        "verifier.create",
        "genesis",
        "events.1-3",
        "generation",
        "artifact.put",
        "artifact.read",
        "event.4",
        "verification",
        "report.put",
        "report.read",
        "repair.compose",
        "event.final",
        "job.load",
        "report.close",
        "artifact.close",
    ]
    assert tuple(getattr(result, name) for name in result.__dataclass_fields__) == (
        *expected,
        state,
    )


def test_invalid_contract_stops_before_any_job_or_repository_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    runtime, _state = _flow_runtime(
        module, events, _FlowRepository(events), _FlowFactory(events)
    )

    def reject(*_args: object) -> None:
        events.append("compile/select")
        raise DomainError("production repair contract is unsupported")

    monkeypatch.setattr(module, "_select_initial_contract", reject)

    with pytest.raises(
        DomainError, match="^production repair contract is unsupported$"
    ):
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert events == ["compile/select"]


def test_verifier_bind_failure_is_pre_genesis_and_closes_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    error = DomainError("invalid production verifier dependency")
    repository = _FlowRepository(events)
    runtime, _state = _flow_runtime(
        module, events, repository, _FlowFactory(events, error)
    )
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(DomainError) as raised:
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert raised.value is error
    assert events == [
        "compile/select",
        "preflight",
        "duplicate.read",
        "request.build",
        "artifact.for_job",
        "report.for_attempt",
        "verifier.create",
        "report.close",
        "artifact.close",
    ]


def test_report_repository_open_failure_closes_artifact_before_genesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    repository = _FlowRepository(events)
    runtime, _state = _flow_runtime(module, events, repository, _FlowFactory(events))
    error = InfrastructureError("production report store unavailable")

    class FailingReportStore:
        def for_attempt(self, *_args: object) -> None:
            events.append("report.for_attempt")
            raise error

    runtime._report_store = FailingReportStore()
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(InfrastructureError) as raised:
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert raised.value is error
    assert events[-3:] == [
        "artifact.for_job",
        "report.for_attempt",
        "artifact.close",
    ]
    assert "verifier.create" not in events
    assert "genesis" not in events


def test_artifact_persistence_failure_never_records_attempt_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    error = InfrastructureError("production artifact store unavailable")
    repository = _FlowRepository(events, error)
    runtime, _state = _flow_runtime(module, events, repository, _FlowFactory(events))
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(InfrastructureError) as raised:
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert raised.value is not error
    assert raised.value.args == ("artifact persistence failed",)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert events[-4:] == [
        "artifact.put",
        "event.FATAL",
        "report.close",
        "artifact.close",
    ]
    assert "event.4" not in events
    assert "verification" not in events
    event = runtime._job_store.appended[-1]
    assert (event.event_type.value, event.from_state.value, event.to_state.value) == (
        "FATAL",
        "GENERATING",
        "JOB_FAILED",
    )
    assert (event.payload.error_family, event.payload.reason) == (
        "UNKNOWN",
        "artifact persistence failed",
    )


def test_artifact_readback_mismatch_uses_the_same_fatal_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []

    class MismatchRepository(_FlowRepository):
        def __call__(self, _reference: ArtifactRef, /) -> None:
            self.events.append("artifact.read")
            return None

    runtime, _state = _flow_runtime(
        module, events, MismatchRepository(events), _FlowFactory(events)
    )
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(InfrastructureError, match="^artifact persistence failed$"):
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert events[-5:] == [
        "artifact.put",
        "artifact.read",
        "event.FATAL",
        "report.close",
        "artifact.close",
    ]
    assert "event.4" not in events


def test_report_persistence_failure_is_fatal_and_cleanup_cannot_mask_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    error = InfrastructureError("sensitive report store failure")
    repository = _FlowRepository(
        events, close_error=InfrastructureError("artifact close failure")
    )
    reports = _FlowReportRepository(
        events,
        put_error=error,
        close_error=InfrastructureError("report close failure"),
    )
    runtime, _state = _flow_runtime(
        module, events, repository, _FlowFactory(events), reports
    )
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(
        InfrastructureError, match="^verification report persistence failed$"
    ) as raised:
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert raised.value is not error
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert events[-4:] == [
        "report.put",
        "event.FATAL",
        "report.close",
        "artifact.close",
    ]
    assert "repair.compose" not in events
    event = runtime._job_store.appended[-1]
    assert (event.event_type.value, event.from_state.value, event.to_state.value) == (
        "FATAL",
        "VERIFYING",
        "JOB_FAILED",
    )
    assert (event.payload.error_family, event.payload.reason) == (
        "UNKNOWN",
        "verification report persistence failed",
    )


def test_report_readback_mismatch_uses_the_same_fatal_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []

    class MismatchRepository(_FlowReportRepository):
        def __call__(self) -> None:
            self.events.append("report.read")
            return None

    runtime, _state = _flow_runtime(
        module,
        events,
        _FlowRepository(events),
        _FlowFactory(events),
        MismatchRepository(events),
    )
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(
        InfrastructureError, match="^verification report persistence failed$"
    ):
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert events[-5:] == [
        "report.put",
        "report.read",
        "event.FATAL",
        "report.close",
        "artifact.close",
    ]
    assert "repair.compose" not in events


def test_successful_attempt_close_failure_attempts_both_and_preserves_report_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, request_type = _request_type()
    events: list[str] = []
    artifact_error = InfrastructureError("artifact close failure")
    report_error = InfrastructureError("report close failure")
    artifacts = _FlowRepository(events, close_error=artifact_error)
    reports = _FlowReportRepository(events, close_error=report_error)
    runtime, _state = _flow_runtime(
        module, events, artifacts, _FlowFactory(events), reports
    )
    _install_flow_mocks(module, monkeypatch, events)

    with pytest.raises(InfrastructureError) as raised:
        runtime._execute_initial_attempt(request_type(**_request_kwargs()))

    assert raised.value is report_error
    assert events[-3:] == ["job.load", "report.close", "artifact.close"]


def _verification_rule() -> RuleDefinition:
    return RuleDefinition(
        RuleId("l1-test"),
        RuleLevel.L1,
        RuleScope.ITEM,
        True,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", "reject", "reject"),
    )


class _PassingVerifier:
    def verify(self, artifacts, rules, /):
        return (
            RuleResult(
                rules[0].rule_id,
                RuleStatus.PASS,
                (artifacts[0].artifact_id,),
                1.0,
            ),
        )


class _FailingVerifier:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def verify(self, _artifacts, _rules, /):
        raise self.error


class _VerificationEventStore:
    def __init__(self) -> None:
        self.events: list[object] = []

    def append_event(self, _job_id: JobId, event: object) -> None:
        self.events.append(event)

    def get_snapshot(self, _job_id: JobId, /) -> None:
        return None


def test_verification_report_preserves_exact_artifact_rules_and_results() -> None:
    module = _request_type()[0]
    artifact, rule = _flow_artifact(), _verification_rule()
    plan = SimpleNamespace(applicable_rule_definitions=(rule,))
    request = SimpleNamespace(job_id=JobId("job-1"))
    store = _VerificationEventStore()

    report = module._run_initial_verification(
        _PassingVerifier(),
        store,
        request,
        artifact,
        plan,
        lambda: "2026-08-01T00:00:00.000Z",
    )

    assert report.artifacts == (artifact.ref,)
    assert report.rules == (rule,)
    assert report.results[0].status is RuleStatus.PASS
    assert store.events == []


@pytest.mark.parametrize(
    "error",
    (
        DomainError("sensitive domain cause"),
        InfrastructureError("sensitive infrastructure cause"),
        RuntimeError("sensitive unknown cause"),
    ),
)
def test_verifier_failure_records_fatal_then_raises_sanitized_boundary_error(
    error: Exception,
) -> None:
    module = _request_type()[0]
    artifact, rule = _flow_artifact(), _verification_rule()
    plan = SimpleNamespace(applicable_rule_definitions=(rule,))
    request = SimpleNamespace(job_id=JobId("job-1"))
    store = _VerificationEventStore()

    with pytest.raises(InfrastructureError, match="^verifier unavailable$") as raised:
        module._run_initial_verification(
            _FailingVerifier(error),
            store,
            request,
            artifact,
            plan,
            lambda: "2026-08-01T00:00:00.000Z",
        )

    assert raised.value is not error
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert len(store.events) == 1
    event = store.events[0]
    assert (event.event_type.value, event.from_state.value, event.to_state.value) == (
        "FATAL",
        "VERIFYING",
        "JOB_FAILED",
    )
    assert (event.payload.error_family, event.payload.reason) == (
        "VERIFIER_UNAVAILABLE",
        "verifier unavailable",
    )
    assert "sensitive" not in event.payload.reason


def test_repair_core_failure_records_unknown_fatal_and_erases_sensitive_context() -> (
    None
):
    module = _request_type()[0]
    store = _VerificationEventStore()
    error = DomainError("sensitive repair invariant")

    def fail() -> None:
        raise error

    with pytest.raises(
        InfrastructureError, match="^repair composition failed$"
    ) as raised:
        module._repair_call(
            fail,
            store,
            JobId("job-1"),
            module.JobStatus.REPAIR_SELECTING,
            lambda: "2026-08-01T00:00:00.000Z",
        )

    assert raised.value is not error
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert len(store.events) == 1
    event = store.events[0]
    assert (event.event_type.value, event.from_state.value, event.to_state.value) == (
        "FATAL",
        "REPAIR_SELECTING",
        "JOB_FAILED",
    )
    assert (event.payload.error_family, event.payload.reason) == (
        "UNKNOWN",
        "repair composition failed",
    )


def test_repair_step_event_failure_closes_both_child_repositories_without_masking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _request_type()[0]
    events: list[str] = []
    artifact_repository = _FlowRepository(
        events, close_error=InfrastructureError("artifact cleanup failure")
    )
    report_repository = _FlowReportRepository(
        events, close_error=InfrastructureError("report cleanup failure")
    )
    runtime = object.__new__(module._ProductionGenerationRuntime)
    runtime._job_store = _VerificationEventStore()
    runtime._clock = lambda: "2026-08-01T00:00:00.000Z"
    runtime._state_lock = threading.RLock()
    runtime._active_job_id = None
    runtime._active_cancel = None
    runtime._active_cancel_reason = None
    runtime._closed = False
    error = InfrastructureError("repair step event failure")
    request = SimpleNamespace(job_id=JobId("job-1"))
    command = SimpleNamespace(request=request)
    prepared = SimpleNamespace(verification_plan=object())

    monkeypatch.setattr(
        module._ProductionGenerationRuntime,
        "_open_attempt",
        lambda *_args: (artifact_repository, report_repository, object()),
    )

    def fail_step(*_args: object) -> None:
        raise error

    monkeypatch.setattr(
        module._ProductionGenerationRuntime, "_record_repair_step", fail_step
    )

    with pytest.raises(InfrastructureError) as raised:
        runtime._run_repair(prepared, object(), command)

    assert raised.value is error
    assert events == ["report.close", "artifact.close"]
