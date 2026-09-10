"""APP-COMPOSE-001A real production generation composition slice."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import specstyle.workflow.production_service as production_service
from specstyle.domain.artifacts import AssetRef
from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleScope,
    RuleStatus,
)
from specstyle.domain.identifiers import AssetId, Identifier, JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.image_evidence import (
    _build_processor_provenance,
    _derive_preprocessing_version,
)
from specstyle.generation.output_profile_contracts import (
    production_output_profile_capabilities,
)
from specstyle.generation.preprocess import (
    PreprocessPlan,
    PreparedImage,
    preprocess_image,
)
from specstyle.generation.requests import PreparedControlInput, RenderedPrompt
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import (
    CompilerContext,
    ResourcePin,
    ThresholdMetricCapability,
)
from specstyle.workflow.job_models import EventType, JobStatus
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.production_service import (
    ProductionJobRequest,
    ProductionL1RuleBinding,
    open_production_runtime,
    production_l1_rule_bindings,
)
from tests.unit.generation.test_diffusers_loader import (
    _CLIPImageProcessor,
    _Diffusers,
    _Pipeline,
    _Torch,
    _Transformers,
    _environment,
    _supply,
)
from tests.unit.spec.test_compiler import context
from tests.unit.verification._production_builders import (
    _compiler_context as _verification_compiler_context,
    _raw_spec as _verification_raw_spec,
)

_TIMESTAMP = "2026-08-01T00:00:00.000Z"


def _png(color: str, size: tuple[int, int] = (1024, 1024)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


def _compiler_inputs(
    pipeline_graph: object,
    style_contents: tuple[bytes, ...],
    *,
    applicable_batch: bool = False,
    mismatch: str | None = None,
    rendered_output: bool = False,
    output_profile: str = "xhs_grid",
    native_resolution: tuple[int, int] = (1024, 1024),
) -> tuple[str, CompilerContext, tuple[ProductionL1RuleBinding, ...]]:
    provenance = _build_processor_provenance(
        _Transformers, _CLIPImageProcessor(), _Transformers.__version__
    )
    compiler_context = _verification_compiler_context(
        pipeline_graph,
        _derive_preprocessing_version(provenance),
        l2_status="DRAFT",
        l3_status="DRAFT",
        l3_kind="L3_DIAGNOSTIC",
        l3_requirement="always_advisory",
    )
    raw = _verification_raw_spec(
        pipeline_graph, compiler_context, style_contents, fidelity_required=False
    ).model_dump(mode="json")
    raw["profiles"]["production"]["resolution"] = list(native_resolution)
    raw["outputs"]["profiles"] = [output_profile]
    if output_profile in {"talking_head_cover", "background_sequence"}:
        raw["verification"]["l3"] = None
    raw["repair"] = {
        "policy_version": "1.0",
        "max_rounds": 1,
        "stop_after_no_improvement": 1,
    }
    compiler_context, raw = _apply_compiler_mismatch(compiler_context, raw, mismatch)
    if rendered_output:
        catalog = compiler_context.rule_catalogs[0]
        rules = tuple(
            replace(
                rule,
                supported_output_profiles=(
                    "xhs_grid",
                    "talking_head_cover",
                    "background_sequence",
                ),
            )
            if rule.kind in {"L1_TECHNICAL", "L2_STYLE_FIDELITY"}
            else replace(
                rule,
                metric_id=Identifier("batch_style_consistency"),
            )
            if rule.kind == "L2_BATCH_CONSISTENCY"
            else rule
            for rule in catalog.rules
        )
        profiles = compiler_context.threshold_profiles
        if output_profile == "background_sequence":
            item_profile = profiles[0]
            profiles = (
                replace(
                    item_profile,
                    metrics=(
                        *item_profile.metrics,
                        ThresholdMetricCapability(
                            Identifier("batch_style_consistency"), "<=", 0.25
                        ),
                    ),
                ),
                *profiles[1:],
            )
        compiler_context = replace(
            compiler_context,
            output_profile_capabilities=production_output_profile_capabilities(),
            rule_catalogs=(replace(catalog, rules=rules),),
            threshold_profiles=profiles,
        )
    if applicable_batch:
        compiler_context = _add_applicable_batch_rule(compiler_context)
    bindings = production_l1_rule_bindings()
    return json.dumps(raw), compiler_context, bindings


def _apply_compiler_mismatch(
    compiler_context: CompilerContext, raw: dict[str, Any], mismatch: str | None
) -> tuple[CompilerContext, dict[str, Any]]:
    if mismatch == "runtime":
        runtime = compiler_context.runtime_capabilities[0]
        compiler_context = replace(
            compiler_context,
            runtime_capabilities=(replace(runtime, rocm_version="7.2.0"),),
        )
        raw["runtime"]["rocm_version"] = "7.2.0"
    if mismatch in {"model", "control"}:
        changed = []
        for capability in compiler_context.model_capabilities:
            if mismatch == "model" and capability.role == "base":
                changed.append(
                    replace(
                        capability,
                        pin=replace(capability.pin, id="other-base"),
                    )
                )
                raw["models"]["base"]["id"] = "other-base"
            elif mismatch == "control" and capability.role == "controlnet":
                changed.append(replace(capability, controlnet_type="depth"))
                raw["models"]["controlnet"]["type"] = "depth"
            else:
                changed.append(capability)
        compiler_context = replace(compiler_context, model_capabilities=tuple(changed))
    return compiler_context, raw


def _add_applicable_batch_rule(
    compiler_context: CompilerContext,
) -> CompilerContext:
    legacy = context()
    batch_rule = next(
        rule for rule in legacy.rule_catalogs[0].rules if rule.scope is RuleScope.BATCH
    )
    batch_metric = next(
        metric
        for metric in legacy.threshold_profiles[0].metrics
        if metric.metric_id.value == "batch-metric"
    )
    catalog = compiler_context.rule_catalogs[0]
    l2, l3 = compiler_context.threshold_profiles
    return replace(
        compiler_context,
        rule_catalogs=(replace(catalog, rules=(*catalog.rules, batch_rule)),),
        threshold_profiles=(replace(l2, metrics=(*l2.metrics, batch_metric)), l3),
    )


def _source(size: tuple[int, int] = (1024, 1024)) -> PreparedImage:
    content = _png("white", size)
    return preprocess_image(
        content,
        AssetRef(AssetId("source"), hash_bytes(content)),
        PreprocessPlan(
            size,
            "contain_pad",
            (0, 0, 0),
            ResourcePin("processor", "r1", hash_bytes(b"processor")),
        ),
    )


class _CannyBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[PreparedImage, object]] = []

    def build(self, source: PreparedImage, graph: object) -> PreparedControlInput:
        self.calls.append((source, graph))
        return PreparedControlInput("canny", source)


class _Generator:
    def __init__(self, device: str) -> None:
        self.device = device

    def manual_seed(self, seed: int) -> _Generator:
        self.seed = seed
        return self


def _job_request(
    job_id: str,
    spec_text: str,
    style_references: tuple[AssetRef, ...],
    *,
    output_profile: str = "xhs_grid",
    native_resolution: tuple[int, int] = (1024, 1024),
) -> ProductionJobRequest:
    return ProductionJobRequest(
        JobId(job_id),
        spec_text,
        _source(native_resolution),
        style_references,
        RenderedPrompt(
            ResourcePin("template", "r1", hash_bytes(b"template")),
            Identifier("preset"),
            "positive",
            "negative",
        ),
        output_profile,
        0,
        f"bundle-{job_id}",
    )


def _open_runtime(
    tmp_path: Path,
    supply: object,
    pipeline_graph: object,
    environment: object,
    compiler_context: CompilerContext,
    style_assets: object,
    control_builder: object,
    l1_rule_bindings: tuple[ProductionL1RuleBinding, ...],
    job_store: JobStore,
    **kwargs: object,
):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    root_fd = os.open(artifact_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return open_production_runtime(
            supply,
            pipeline_graph,
            environment,
            lambda _preprocessing_version: compiler_context,
            style_assets,
            control_builder,
            l1_rule_bindings,
            job_store,
            root_fd,
            **kwargs,
        )
    finally:
        os.close(root_fd)


@pytest.mark.parametrize(
    ("rendered_output", "output_profile", "native_resolution", "expected_size"),
    (
        (False, "xhs_grid", (1024, 1024), (1024, 1024)),
        (True, "xhs_grid", (1024, 1024), (1080, 1080)),
        (True, "talking_head_cover", (768, 768), (1080, 1440)),
        (True, "background_sequence", (768, 768), (1920, 1080)),
    ),
)
def test_real_initial_attempt_reaches_terminal_with_exact_durable_audit_history(
    tmp_path: Path,
    monkeypatch,
    rendered_output: bool,
    output_profile: str,
    native_resolution: tuple[int, int],
    expected_size: tuple[int, int],
) -> None:
    style_contents = (
        _png("red", native_resolution),
        _png("blue", native_resolution),
    )
    supply, pipeline_graph = _supply(tmp_path / "weights")
    spec_text, compiler_context, allowlist = _compiler_inputs(
        pipeline_graph,
        style_contents,
        rendered_output=rendered_output,
        output_profile=output_profile,
        native_resolution=native_resolution,
    )
    style_references = tuple(
        AssetRef(AssetId(f"style-{index}"), hash_bytes(content))
        for index, content in enumerate(style_contents)
    )
    request = _job_request(
        "job-success",
        spec_text,
        style_references,
        output_profile=output_profile,
        native_resolution=native_resolution,
    )
    builder = _CannyBuilder()
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = JobStore(store_root)
    torch, diffusers = _Torch(), _Diffusers()
    torch.Generator = _Generator
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        _Pipeline, "set_ip_adapter_scale", lambda self, value: None, raising=False
    )

    def generate(pipeline: _Pipeline, **kwargs: object) -> object:
        observed["style_colors"] = tuple(
            image.getpixel((0, 0)) for image in kwargs["ip_adapter_image"][0]
        )
        observed["control_image"] = kwargs["control_image"]
        return type(
            "Result",
            (),
            {
                "images": [
                    Image.new("RGB", (kwargs["width"], kwargs["height"]), "green")
                ]
            },
        )()

    monkeypatch.setattr(_Pipeline, "__call__", generate, raising=False)
    runtime = _open_runtime(
        tmp_path,
        supply,
        pipeline_graph,
        _environment(),
        compiler_context,
        dict(zip(style_references, style_contents)).__getitem__,
        builder,
        allowlist,
        store,
        torch_module=torch,
        diffusers_module=diffusers,
        clock=lambda: _TIMESTAMP,
    )
    try:
        result = runtime._execute_initial_attempt(request)

        assert result.graph.output_profile == output_profile
        assert result.graph.resolution == native_resolution
        assert result.verification_plan.output_profile == output_profile
        assert result.request.attempt_id.value == (f"job-success-a0-{output_profile}-0")
        assert result.artifact.content.startswith(b"\x89PNG")
        with Image.open(BytesIO(result.artifact.content)) as rendered:
            assert rendered.size == expected_size
        assert result.artifact.request_hash == result.request.request_hash
        assert result.report.artifacts == (result.artifact.ref,)
        assert (
            result.report.rules == result.verification_plan.applicable_rule_definitions
        )
        assert tuple(item.status for item in result.report.results) == (
            *(RuleStatus.PASS for _ in range(4)),
            RuleStatus.UNVERIFIABLE,
            *(
                ()
                if output_profile == "talking_head_cover"
                else (RuleStatus.UNVERIFIABLE,)
            ),
        )
        assert all(
            item.score is None
            for item in result.report.results
            if item.status is RuleStatus.UNVERIFIABLE
        )
        if output_profile in {"talking_head_cover", "background_sequence"}:
            assert result.verification_plan.l3_status == "NOT_APPLICABLE"
            assert result.verification_plan.l3_reason == "NO_L3_CONFIG"
            batch = next(
                rule
                for rule in result.verification_plan.rules
                if rule.definition.scope is RuleScope.BATCH
            )
            expected = (
                "APPLICABLE"
                if output_profile == "background_sequence"
                else "NOT_APPLICABLE"
            )
            assert batch.definition.applicability.value == expected
        assert (
            result.terminal.artifact_decision.artifact_status is ArtifactStatus.APPROVED
        )
        assert (
            result.terminal.artifact_decision.decision_reason
            is DecisionReason.ALL_REQUIRED_PASS
        )
        assert (
            result.terminal.artifact_decision.repair_stop_reason
            is RepairStopReason.PASS_ALL_REQUIRED
        )
        assert result.job_state.job.status is JobStatus.APPROVED
        assert result.job_state.last_sequence == 5
        assert len(builder.calls) == 1
        assert observed["style_colors"] == ((255, 0, 0), (0, 0, 255))
        assert observed["control_image"].size == native_resolution
        root = tmp_path / "artifacts" / "jobs" / request.job_id.value
        artifact_dir = root / "artifacts" / result.artifact.ref.artifact_id.value
        report_dir = root / "reports" / result.request.attempt_id.value
        assert tuple(sorted(path.name for path in artifact_dir.iterdir())) == (
            "artifact.png",
            "metadata.json",
        )
        assert tuple(sorted(path.name for path in report_dir.iterdir())) == (
            "metadata.json",
            "report.json",
        )
        events = store.list_events(request.job_id)
        assert tuple(event.event_type for event in events) == (
            EventType.JOB_STARTED,
            EventType.SPEC_COMPILED,
            EventType.ATTEMPT_STARTED,
            EventType.ATTEMPT_FINISHED,
            EventType.VERIFIER_FINISHED,
        )
        assert tuple((event.from_state, event.to_state) for event in events) == (
            (JobStatus.CREATED, JobStatus.SPEC_VALIDATED),
            (JobStatus.SPEC_VALIDATED, JobStatus.SPEC_COMPILED),
            (JobStatus.SPEC_COMPILED, JobStatus.GENERATING),
            (JobStatus.GENERATING, JobStatus.VERIFYING),
            (JobStatus.VERIFYING, JobStatus.APPROVED),
        )
        indexed = tuple(
            event.payload for event in events if hasattr(event.payload, "cohort_index")
        )
        assert indexed
        assert all(
            (payload.cohort_index, payload.item_index) == (0, 0) for payload in indexed
        )
    finally:
        runtime.close()
        supply.close()


@pytest.mark.parametrize("case", ["batch", "model", "runtime", "control", "style"])
def test_preflight_rejects_before_genesis_and_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    style_contents = (_png("red"), _png("blue"))
    supply, pipeline_graph = _supply(tmp_path / "weights")
    spec_text, compiler_context, allowlist = _compiler_inputs(
        pipeline_graph,
        style_contents,
        applicable_batch=case == "batch",
        mismatch=case if case in {"model", "runtime", "control"} else None,
    )
    style_references = tuple(
        AssetRef(AssetId(f"style-{index}"), hash_bytes(content))
        for index, content in enumerate(style_contents)
    )
    if case == "style":
        style_references = (
            AssetRef(AssetId("style-0"), hash_bytes(b"wrong-style")),
            style_references[1],
        )
    request = _job_request(f"job-{case}", spec_text, style_references)
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = JobStore(store_root)
    builder = _CannyBuilder()
    inference_calls: list[object] = []
    monkeypatch.setattr(
        _Pipeline,
        "__call__",
        lambda self, **kwargs: inference_calls.append(kwargs),
        raising=False,
    )
    runtime = _open_runtime(
        tmp_path,
        supply,
        pipeline_graph,
        _environment(),
        compiler_context,
        dict(zip(style_references, style_contents)).__getitem__,
        builder,
        allowlist,
        store,
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
        clock=lambda: _TIMESTAMP,
    )
    try:
        with pytest.raises(DomainError):
            runtime._execute_initial_attempt(request)
        assert store.get_snapshot(request.job_id) is None
        assert store.list_events(request.job_id) == ()
        assert inference_calls == []
        assert builder.calls == []
    finally:
        runtime.close()
        supply.close()


@pytest.mark.parametrize("failure", ["oom", "style", "output"])
def test_generation_failure_is_fatal_and_reraises_the_same_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    style_contents = (_png("red"),)
    supply, pipeline_graph = _supply(tmp_path / "weights")
    spec_text, compiler_context, allowlist = _compiler_inputs(
        pipeline_graph, style_contents
    )
    style_references = (AssetRef(AssetId("style-0"), hash_bytes(style_contents[0])),)
    request = _job_request(f"job-{failure}", spec_text, style_references)
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = JobStore(store_root)
    torch, diffusers = _Torch(), _Diffusers()
    torch.Generator = _Generator

    class OutOfMemoryError(Exception):
        pass

    torch.cuda.OutOfMemoryError = OutOfMemoryError
    monkeypatch.setattr(
        _Pipeline, "set_ip_adapter_scale", lambda self, value: None, raising=False
    )

    def generate(_pipeline: _Pipeline, **_kwargs: object) -> object:
        if failure == "oom":
            raise OutOfMemoryError("GPU exhausted")
        size = (64, 64) if failure == "output" else (1024, 1024)
        return type("Result", (), {"images": [Image.new("RGB", size)]})()

    monkeypatch.setattr(_Pipeline, "__call__", generate, raising=False)
    resolver = (
        (lambda _reference: b"not-an-image")
        if failure == "style"
        else dict(zip(style_references, style_contents)).__getitem__
    )
    original_run_generation = production_service.run_generation
    observed: dict[str, InfrastructureError] = {}

    def capture_error(backend: object, generation_request: object):
        try:
            return original_run_generation(backend, generation_request)
        except InfrastructureError as error:
            observed["error"] = error
            raise

    monkeypatch.setattr(production_service, "run_generation", capture_error)
    runtime = _open_runtime(
        tmp_path,
        supply,
        pipeline_graph,
        _environment(),
        compiler_context,
        resolver,
        _CannyBuilder(),
        allowlist,
        store,
        torch_module=torch,
        diffusers_module=diffusers,
        clock=lambda: _TIMESTAMP,
    )
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime._execute_initial_attempt(request)

        assert raised.value is observed["error"]
        assert raised.value.args == (
            ("generation OOM",) if failure == "oom" else raised.value.args
        )
        events = store.list_events(request.job_id)
        assert tuple(event.event_type for event in events) == (
            EventType.JOB_STARTED,
            EventType.SPEC_COMPILED,
            EventType.ATTEMPT_STARTED,
            EventType.FATAL,
        )
        assert events[-1].from_state is JobStatus.GENERATING
        assert events[-1].to_state is JobStatus.JOB_FAILED
        assert events[-1].payload.error_family == (
            "GENERATION_OOM" if failure == "oom" else "GENERATION_FAILED"
        )
        assert store.load(request.job_id).job.status is JobStatus.JOB_FAILED
    finally:
        runtime.close()
        supply.close()


def test_duplicate_job_is_rejected_without_events_or_inference_and_backends_are_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    style_contents = (_png("red"),)
    supply, pipeline_graph = _supply(tmp_path / "weights")
    spec_text, compiler_context, allowlist = _compiler_inputs(
        pipeline_graph, style_contents
    )
    style_references = (AssetRef(AssetId("style-0"), hash_bytes(style_contents[0])),)
    first = _job_request("job-first", spec_text, style_references)
    second = _job_request("job-second", spec_text, style_references)
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = JobStore(store_root)
    torch, diffusers = _Torch(), _Diffusers()
    torch.Generator = _Generator
    inference_calls: list[object] = []
    monkeypatch.setattr(
        _Pipeline, "set_ip_adapter_scale", lambda self, value: None, raising=False
    )

    def generate(_pipeline: _Pipeline, **kwargs: object) -> object:
        inference_calls.append(kwargs)
        return type("Result", (), {"images": [Image.new("RGB", (1024, 1024))]})()

    monkeypatch.setattr(_Pipeline, "__call__", generate, raising=False)
    real_backend = production_service.DiffusersBackend
    backend_instances: list[object] = []

    def create_backend(*args: object) -> object:
        backend = real_backend(*args)
        backend_instances.append(backend)
        return backend

    monkeypatch.setattr(production_service, "DiffusersBackend", create_backend)
    runtime = _open_runtime(
        tmp_path,
        supply,
        pipeline_graph,
        _environment(),
        compiler_context,
        dict(zip(style_references, style_contents)).__getitem__,
        _CannyBuilder(),
        allowlist,
        store,
        torch_module=torch,
        diffusers_module=diffusers,
        clock=lambda: _TIMESTAMP,
    )
    try:
        runtime._execute_initial_attempt(first)
        original_events = store.list_events(first.job_id)
        with pytest.raises(DomainError, match="duplicate"):
            runtime._execute_initial_attempt(first)
        assert store.list_events(first.job_id) == original_events
        assert len(inference_calls) == 1

        runtime._execute_initial_attempt(second)
        assert len(inference_calls) == 2
        assert len(backend_instances) == 2
        assert backend_instances[0] is not backend_instances[1]
    finally:
        runtime.close()
        supply.close()


@pytest.mark.parametrize("failure_stage", ["finish", "fatal"])
def test_job_store_write_failure_propagates_the_original_infrastructure_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    style_contents = (_png("red"),)
    supply, pipeline_graph = _supply(tmp_path / "weights")
    spec_text, compiler_context, allowlist = _compiler_inputs(
        pipeline_graph, style_contents
    )
    style_references = (AssetRef(AssetId("style-0"), hash_bytes(style_contents[0])),)
    request = _job_request(f"job-store-{failure_stage}", spec_text, style_references)
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = JobStore(store_root)
    torch, diffusers = _Torch(), _Diffusers()
    torch.Generator = _Generator
    monkeypatch.setattr(
        _Pipeline, "set_ip_adapter_scale", lambda self, value: None, raising=False
    )

    def generate(_pipeline: _Pipeline, **_kwargs: object) -> object:
        size = (64, 64) if failure_stage == "fatal" else (1024, 1024)
        return type("Result", (), {"images": [Image.new("RGB", size)]})()

    monkeypatch.setattr(_Pipeline, "__call__", generate, raising=False)
    original_run_generation = production_service.run_generation
    generation_errors: list[InfrastructureError] = []

    def capture_error(backend: object, generation_request: object):
        try:
            return original_run_generation(backend, generation_request)
        except InfrastructureError as error:
            generation_errors.append(error)
            raise

    monkeypatch.setattr(production_service, "run_generation", capture_error)
    write_error = InfrastructureError("injected job store write failure")
    real_append = store.append_event

    def append_event(job_id: JobId, event: object) -> object:
        target = (
            EventType.ATTEMPT_FINISHED if failure_stage == "finish" else EventType.FATAL
        )
        if event.event_type is target:
            raise write_error
        return real_append(job_id, event)

    monkeypatch.setattr(store, "append_event", append_event)
    runtime = _open_runtime(
        tmp_path,
        supply,
        pipeline_graph,
        _environment(),
        compiler_context,
        dict(zip(style_references, style_contents)).__getitem__,
        _CannyBuilder(),
        allowlist,
        store,
        torch_module=torch,
        diffusers_module=diffusers,
        clock=lambda: _TIMESTAMP,
    )
    try:
        with pytest.raises(InfrastructureError) as raised:
            runtime._execute_initial_attempt(request)
        expected = write_error if failure_stage == "finish" else generation_errors[0]
        assert raised.value is expected
        assert tuple(
            event.event_type for event in store.list_events(request.job_id)
        ) == (
            EventType.JOB_STARTED,
            EventType.SPEC_COMPILED,
            EventType.ATTEMPT_STARTED,
        )
        assert store.load(request.job_id).job.status is JobStatus.GENERATING
    finally:
        runtime.close()
        supply.close()


def _configure_clock_pipeline(
    monkeypatch: pytest.MonkeyPatch, torch: object, failure: str | None
) -> dict[str, InfrastructureError]:
    class OutOfMemoryError(Exception):
        pass

    torch.Generator = _Generator
    torch.cuda.OutOfMemoryError = OutOfMemoryError
    monkeypatch.setattr(
        _Pipeline, "set_ip_adapter_scale", lambda self, value: None, raising=False
    )

    def generate(_pipeline: _Pipeline, **_kwargs: object) -> object:
        if failure == "oom":
            raise OutOfMemoryError("GPU exhausted")
        if failure == "generation":
            raise RuntimeError("inference failed")
        return type("Result", (), {"images": [Image.new("RGB", (1024, 1024))]})()

    monkeypatch.setattr(_Pipeline, "__call__", generate, raising=False)
    original_run_generation = production_service.run_generation
    observed: dict[str, InfrastructureError] = {}

    def capture_error(backend: object, generation_request: object):
        try:
            return original_run_generation(backend, generation_request)
        except InfrastructureError as error:
            observed["error"] = error
            raise

    monkeypatch.setattr(production_service, "run_generation", capture_error)
    return observed


def _open_clock_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timestamps: tuple[str, ...],
    *,
    failure: str | None = None,
) -> tuple[Any, Any, JobStore, ProductionJobRequest, dict[str, InfrastructureError]]:
    style_contents = (_png("red"),)
    supply, pipeline_graph = _supply(tmp_path / "weights")
    spec_text, compiler_context, allowlist = _compiler_inputs(
        pipeline_graph, style_contents
    )
    style_references = (AssetRef(AssetId("style-0"), hash_bytes(style_contents[0])),)
    request = _job_request("job-clock", spec_text, style_references)
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = JobStore(store_root)
    torch, diffusers = _Torch(), _Diffusers()
    observed = _configure_clock_pipeline(monkeypatch, torch, failure)
    clock = iter(timestamps).__next__
    runtime = _open_runtime(
        tmp_path,
        supply,
        pipeline_graph,
        _environment(),
        compiler_context,
        dict(zip(style_references, style_contents)).__getitem__,
        _CannyBuilder(),
        allowlist,
        store,
        torch_module=torch,
        diffusers_module=diffusers,
        clock=clock,
    )
    return runtime, supply, store, request, observed


def test_start_event_clock_rollbacks_are_clamped_through_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, supply, store, request, _observed = _open_clock_case(
        tmp_path,
        monkeypatch,
        (
            "2026-08-01T00:00:00.400Z",
            "2026-08-01T00:00:00.300Z",
            "2026-08-01T00:00:00.200Z",
            "2026-08-01T00:00:00.100Z",
            "2026-08-01T00:00:00.500Z",
            "2026-08-01T00:00:00.450Z",
            "2026-08-01T00:00:00.600Z",
        ),
    )
    try:
        result = runtime._execute_initial_attempt(request)

        assert result.job_state.job.status is JobStatus.REJECTED
        assert (
            result.terminal.artifact_decision.repair_stop_reason
            is RepairStopReason.NO_ACTION
        )
        assert tuple(
            event.timestamp for event in store.list_events(request.job_id)
        ) == (
            "2026-08-01T00:00:00.400Z",
            "2026-08-01T00:00:00.400Z",
            "2026-08-01T00:00:00.400Z",
            "2026-08-01T00:00:00.500Z",
            "2026-08-01T00:00:00.500Z",
            "2026-08-01T00:00:00.600Z",
        )
    finally:
        runtime.close()
        supply.close()


def test_finish_clock_rollback_is_clamped_without_changing_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, supply, store, request, _observed = _open_clock_case(
        tmp_path,
        monkeypatch,
        (
            "2026-08-01T00:00:00.000Z",
            "2026-08-01T00:00:00.100Z",
            "2026-08-01T00:00:00.200Z",
            "2026-08-01T00:00:00.300Z",
            "2026-08-01T00:00:00.250Z",
            "2026-08-01T00:00:00.240Z",
            "2026-08-01T00:00:00.230Z",
        ),
    )
    try:
        result = runtime._execute_initial_attempt(request)

        events = store.list_events(request.job_id)
        assert result.job_state.job.status is JobStatus.REJECTED
        assert (
            result.terminal.artifact_decision.repair_stop_reason
            is RepairStopReason.NO_ACTION
        )
        assert events[-1].event_type is EventType.VERIFIER_FINISHED
        assert events[-1].timestamp == "2026-08-01T00:00:00.300Z"
    finally:
        runtime.close()
        supply.close()


@pytest.mark.parametrize(
    ("failure", "error_family", "message"),
    [
        ("oom", "GENERATION_OOM", "generation OOM"),
        ("generation", "GENERATION_FAILED", "generation failed"),
    ],
)
def test_fatal_clock_rollback_persists_fatal_and_reraises_original_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    error_family: str,
    message: str,
) -> None:
    runtime, supply, store, request, observed = _open_clock_case(
        tmp_path,
        monkeypatch,
        (
            "2026-08-01T00:00:00.000Z",
            "2026-08-01T00:00:00.100Z",
            "2026-08-01T00:00:00.200Z",
            "2026-08-01T00:00:00.300Z",
            "2026-08-01T00:00:00.250Z",
        ),
        failure=failure,
    )
    try:
        with pytest.raises(InfrastructureError, match=message) as raised:
            runtime._execute_initial_attempt(request)

        events = store.list_events(request.job_id)
        assert raised.value is observed["error"]
        assert events[-1].event_type is EventType.FATAL
        assert events[-1].timestamp == "2026-08-01T00:00:00.300Z"
        assert events[-1].payload.error_family == error_family
        assert store.load(request.job_id).job.status is JobStatus.JOB_FAILED
    finally:
        runtime.close()
        supply.close()


def test_invalid_clock_value_is_still_rejected_by_job_event_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, supply, store, request, _observed = _open_clock_case(
        tmp_path,
        monkeypatch,
        ("2026-08-01T00:00:00.000Z", "!"),
    )
    try:
        with pytest.raises(DomainError, match="invalid timestamp"):
            runtime._execute_initial_attempt(request)
        assert store.get_snapshot(request.job_id) is not None
        assert store.list_events(request.job_id) == ()
    finally:
        runtime.close()
        supply.close()
