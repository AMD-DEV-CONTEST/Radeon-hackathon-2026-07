from __future__ import annotations

import copy
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import pickle

import pytest
from PIL import Image

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import ArtifactId, AssetId, AttemptId, JobId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.model_approval import LicenseApproval
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.pipeline_factory import PipelineFactory
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.preview_adapter_supply import (
    PreviewAdapterEntrypoint,
    PreviewAdapterManifest,
    preview_adapter_manifest_sha256,
    verify_preview_adapter,
)
from specstyle.generation.requests import (
    GenerationRequest,
    PreparedControlInput,
    RenderedPrompt,
)
from specstyle.generation.weight_manifest import WeightFile
from specstyle.observability.environment import hash_environment
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import (
    ModelCapability,
    ResourcePin,
    RuntimeCapability,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from tests.unit.generation.test_diffusers_loader import (
    _FLOAT16,
    _FLOAT32,
    _Pipeline,
    _Torch,
    _environment,
    _supply,
)
from tests.unit.spec.test_compiler import context, raw_spec

_REVISION = "b" * 40
_ADAPTER = b"lcm-lora-adapter"


class _VersionedParameter:
    def __init__(self) -> None:
        self._version = 0
        self._data_ptr = id(self)
        self.dtype = "torch.float16"
        self.shape = (2,)
        self._content = bytearray(b"\x00<\x00@")

    def data_ptr(self) -> int:
        return self._data_ptr

    def detach(self) -> _VersionedParameter:
        return self

    def to(self, *, device: str, copy: bool) -> _VersionedParameter:
        assert device == "cpu"
        assert copy is True
        snapshot = _VersionedParameter()
        snapshot.dtype = self.dtype
        snapshot.shape = self.shape
        snapshot._content = bytearray(self._content)
        return snapshot

    def contiguous(self) -> _VersionedParameter:
        return self

    def numpy(self) -> bytearray:
        return self._content


class _FakeVae:
    def __init__(self) -> None:
        self.dtype = _FLOAT16
        self.weight = _VersionedParameter()
        self.to_calls: list[dict[str, object]] = []

    def to(self, **kwargs: object) -> _FakeVae:
        self.to_calls.append(kwargs)
        self.dtype = kwargs["dtype"]
        self.weight.dtype = (
            "torch.float16" if self.dtype is _FLOAT16 else "torch.float32"
        )
        self.weight._data_ptr += 1
        return self

    def named_modules(self):
        return (("", self),)

    def named_parameters(self):
        return (("weight", self.weight),)

    def named_buffers(self):
        return ()


class _FakeLoraLayer:
    def __init__(self) -> None:
        self.merged_adapters: list[str] = []
        self.scaling: dict[str, float] = {}
        self.weight = _VersionedParameter()


class _FakeLoraComponent:
    def __init__(self) -> None:
        self.layer = _FakeLoraLayer()

    def named_modules(self):
        return (("", self), ("lora", self.layer))

    def named_parameters(self):
        return (("lora.weight", self.layer.weight),)

    def named_buffers(self):
        return ()


class _PreviewPipeline(_Pipeline):
    def __init__(self, scheduler_config: dict[str, object]) -> None:
        super().__init__()
        self.scheduler.config = scheduler_config
        self.unet = _FakeLoraComponent()
        self.controlnet = object()
        self.vae = _FakeVae()
        self.text_encoder = object()
        self.text_encoder_2 = object()
        self.lora_calls: list[tuple[object, dict[str, object]]] = []
        self.fuse_calls: list[dict[str, object]] = []
        self._available_adapters: set[str] = set()
        self._active_adapters: list[str] = []
        self._merged_adapters: set[str] = set()

    def load_lora_weights(self, *args: object, **kwargs: object) -> None:
        self.lora_calls.append((args, kwargs))
        name = kwargs.get("adapter_name", f"default_{len(self._available_adapters)}")
        self._available_adapters.add(name)
        self._active_adapters = [name]

    def fuse_lora(self, **kwargs: object) -> None:
        self.fuse_calls.append(kwargs)
        adapters = kwargs.get("adapter_names") or self._active_adapters
        scale = kwargs.get("lora_scale", 1.0)
        self._merged_adapters.update(adapters)
        self.unet.layer.merged_adapters = list(adapters)
        self.unet.layer.scaling = {name: scale for name in adapters}
        self.unet.layer.weight._version += 1

    def unfuse_lora(self) -> None:
        self._merged_adapters.clear()
        self.unet.layer.merged_adapters.clear()
        self.unet.layer.weight._version += 1

    def get_active_adapters(self) -> list[str]:
        return list(self._active_adapters)

    def get_list_adapters(self) -> dict[str, list[str]]:
        return {"unet": sorted(self._available_adapters)}

    @property
    def fused_loras(self) -> set[str]:
        return set(self._merged_adapters)

    @property
    def num_fused_loras(self) -> int:
        return len(self._merged_adapters)

    @property
    def lora_scale(self) -> float:
        return 1.0


class _PreviewDiffusers:
    __version__ = "0.39.0"
    utils = type("Utils", (), {"USE_PEFT_BACKEND": True})()

    def __init__(self, scheduler_config: dict[str, object] | None = None) -> None:
        self.scheduler_config = scheduler_config or {"beta_schedule": "scaled_linear"}
        self.control_calls: list[tuple[object, dict[str, object]]] = []
        self.pipeline_calls: list[tuple[object, dict[str, object]]] = []
        self.scheduler_calls: list[object] = []
        self.issued_pipelines: list[_PreviewPipeline] = []
        outer = self

        class ControlNetModel:
            @classmethod
            def from_pretrained(cls, *args: object, **kwargs: object) -> object:
                outer.control_calls.append((args, kwargs))
                return object()

        class StableDiffusionXLControlNetImg2ImgPipeline:
            @classmethod
            def from_pretrained(
                cls, *args: object, **kwargs: object
            ) -> _PreviewPipeline:
                outer.pipeline_calls.append((args, kwargs))
                pipeline = _PreviewPipeline(dict(outer.scheduler_config))
                outer.issued_pipelines.append(pipeline)
                return pipeline

        class LCMScheduler:
            def __init__(self, config: object) -> None:
                self.config = config

            @classmethod
            def from_config(cls, config: object) -> LCMScheduler:
                outer.scheduler_calls.append(config)
                return cls(config)

        self.ControlNetModel = ControlNetModel
        self.StableDiffusionXLControlNetImg2ImgPipeline = (
            StableDiffusionXLControlNetImg2ImgPipeline
        )
        self.LCMScheduler = LCMScheduler


class _Peft:
    __version__ = "0.18.1"


def _png(size: tuple[int, int], color: str = "red") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


def _adapter(root: Path, *, evidence_url: str = "https://licenses.example.test/lcm"):
    component = root / "preview" / "lcm"
    weight = component / "adapter" / "pytorch_lora_weights.safetensors"
    weight.parent.mkdir(parents=True, exist_ok=True)
    weight.write_bytes(_ADAPTER)
    manifest = PreviewAdapterManifest(
        "org/lcm-lora-sdxl",
        "preview_adapter",
        _REVISION,
        "preview/lcm",
        PreviewAdapterEntrypoint(
            "diffusers_lora", "adapter", "pytorch_lora_weights.safetensors"
        ),
        (
            WeightFile(
                "adapter/pytorch_lora_weights.safetensors",
                len(_ADAPTER),
                hash_bytes(_ADAPTER),
            ),
        ),
        Sha256("0" * 64),
    ).with_computed_root()
    descriptor = ModelDescriptor(
        manifest.model_id,
        "preview_adapter",
        manifest.revision,
        manifest.root_sha256,
        "MIT",
        "APPROVED",
        "sdxl",
    )
    approval = LicenseApproval(
        manifest.model_id,
        manifest.revision,
        preview_adapter_manifest_sha256(manifest),
        "MIT",
        evidence_url,
    )
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        verified = verify_preview_adapter(root_fd, descriptor, manifest, approval)
    finally:
        os.close(root_fd)
    return verified, descriptor


def _preview_graph(root: Path, production_graph, preview_descriptor):
    registry = ModelRegistry(
        (
            production_graph.base,
            production_graph.ip_adapter,
            production_graph.controlnet,
            preview_descriptor,
        )
    )
    return PipelineFactory(registry, root).build_preview(
        production_graph.base.model_id,
        production_graph.ip_adapter.model_id,
        production_graph.controlnet.model_id,
        preview_descriptor.model_id,
    )


def _request(production_graph, style: bytes) -> GenerationRequest:
    raw = raw_spec().model_dump(mode="python")
    raw["runtime"] = {
        "backend": "rocm",
        "rocm_version": "7.2.1",
        "torch_version": "2.8.0",
        "diffusers_version": "0.39.0",
        "dtype": "float16",
    }
    raw["profiles"]["preview"].update(
        pipeline="lcm", resolution=(512, 512), steps=4, guidance_scale=0.0
    )
    for key, descriptor in (
        ("base", production_graph.base),
        ("ip_adapter", production_graph.ip_adapter),
        ("controlnet", production_graph.controlnet),
    ):
        raw["models"][key]["id"] = descriptor.model_id
        raw["models"][key]["revision"] = descriptor.revision
        raw["models"][key]["sha256"] = descriptor.expected_sha256.value
    raw["assets"]["style_references"] = (
        {
            "asset_sha256": hash_bytes(style).value,
            "source_url": "https://example.com/style",
            "license": "CC0",
            "attribution": "author",
            "consent": "not_applicable",
        },
    )
    base_context = context()
    runtime_pin = ResourcePin(
        "runtime", "r1", base_context.runtime_capabilities[0].pin.sha256
    )
    capabilities = tuple(
        ModelCapability(
            descriptor.role,
            ResourcePin(
                descriptor.model_id, descriptor.revision, descriptor.expected_sha256
            ),
            "canny" if descriptor.role == "controlnet" else None,
            ("lcm", "sdxl_base"),
            ("float16",),
            (runtime_pin.sha256,),
        )
        for descriptor in (
            production_graph.base,
            production_graph.ip_adapter,
            production_graph.controlnet,
        )
    )
    compiled = compile_style_spec(
        StyleSpecV1.model_validate(raw),
        replace(
            base_context,
            runtime_capabilities=(
                RuntimeCapability(
                    runtime_pin, "rocm", "7.2.1", "2.8.0", "0.39.0", "float16"
                ),
            ),
            model_capabilities=capabilities,
        ),
    )
    source_content = _png((512, 512), "white")
    source = preprocess_image(
        source_content,
        AssetRef(AssetId("source"), hash_bytes(source_content)),
        PreprocessPlan(
            (512, 512),
            "contain_pad",
            (0, 0, 0),
            ResourcePin("processor", "r1", hash_bytes(b"processor")),
        ),
    )
    graph = compiled.preview_graphs[0]
    return GenerationRequest(
        JobId("preview-job"),
        AttemptId("preview-attempt"),
        None,
        compiled,
        "preview",
        "xhs_grid",
        source,
        (AssetRef(AssetId("style"), hash_bytes(style)),),
        RenderedPrompt(
            ResourcePin("template", "r1", hash_bytes(b"template")),
            graph.preset_id,
            "positive",
            "negative",
        ),
        PreparedControlInput("canny", source),
        0,
        hash_environment(_environment()),
    )


def _runtime(
    tmp_path: Path,
    *,
    evidence_url: str = "https://licenses.example.test/lcm",
    style: bytes | None = None,
):
    production_supply, production_graph = _supply(tmp_path)
    adapter, descriptor = _adapter(tmp_path, evidence_url=evidence_url)
    graph = _preview_graph(tmp_path, production_graph, descriptor)
    style = _png((512, 512)) if style is None else style
    return production_supply, adapter, graph, _request(production_graph, style)


def _changed_request(request: GenerationRequest, **graph_changes: object):
    graph = replace(request.graph, **graph_changes)
    compiled = replace(request.compiled_spec, preview_graphs=(graph,))
    return replace(request, compiled_spec=compiled)


def test_loader_applies_exact_lcm_scheduler_adapter_and_fuse_contract(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    torch, diffusers = _Torch(), _PreviewDiffusers()
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=torch,
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )

    pipeline = diffusers.issued_pipelines[0]
    assert type(pipeline.scheduler) is diffusers.LCMScheduler
    assert diffusers.scheduler_calls == [{"beta_schedule": "scaled_linear"}]
    assert len(pipeline.ip_calls) == 1
    assert pipeline.lora_calls[0][1] == {
        "subfolder": "adapter",
        "weight_name": "pytorch_lora_weights.safetensors",
        "local_files_only": True,
        "use_safetensors": True,
        "adapter_name": "specstyle_lcm",
    }
    assert pipeline.fuse_calls == [
        {"lora_scale": 1.0, "adapter_names": ["specstyle_lcm"]}
    ]
    assert pipeline.vae.dtype is torch.float16
    assert pipeline.vae.to_calls == []
    assert not hasattr(loaded, "_borrow_image_evidence_encoder")
    assert not hasattr(loaded, "borrow_pipeline")
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(loaded)
    loaded.close()
    loaded.close()
    with pytest.raises(DomainError, match="closed"):
        bind_preview_execution(loaded, request)
    adapter.close()
    supply.close()


def test_loader_snapshots_pinned_peft_layer_scaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    real_fuse = _PreviewPipeline.fuse_lora

    def fuse_with_peft_scaling(pipeline: _PreviewPipeline, **kwargs: object) -> None:
        real_fuse(pipeline, **kwargs)
        pipeline.unet.layer.scaling = {"specstyle_lcm": 0.125}

    monkeypatch.setattr(_PreviewPipeline, "fuse_lora", fuse_with_peft_scaling)
    supply, adapter, graph, request = _runtime(tmp_path)
    diffusers = _PreviewDiffusers()
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]

    bind_preview_execution(loaded, request)
    pipeline.unet.layer.scaling["specstyle_lcm"] = 0.25
    with pytest.raises(DomainError, match="capability"):
        bind_preview_execution(loaded, request)

    loaded.close()
    adapter.close()
    supply.close()


@pytest.mark.parametrize(
    "invalid_scaling",
    (0.0, -0.125, float("inf"), float("nan"), True, 1),
)
def test_loader_rejects_invalid_peft_layer_scaling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_scaling: object,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    real_fuse = _PreviewPipeline.fuse_lora

    def fuse_with_invalid_scaling(pipeline: _PreviewPipeline, **kwargs: object) -> None:
        real_fuse(pipeline, **kwargs)
        pipeline.unet.layer.scaling = {"specstyle_lcm": invalid_scaling}

    monkeypatch.setattr(_PreviewPipeline, "fuse_lora", fuse_with_invalid_scaling)
    supply, adapter, graph, _ = _runtime(tmp_path)

    with pytest.raises(InfrastructureError, match="preview pipeline loading failed"):
        load_preview_pipeline(
            supply,
            adapter,
            graph,
            _environment(),
            torch_module=_Torch(),
            diffusers_module=_PreviewDiffusers(),
            peft_module=_Peft(),
        )

    adapter.close()
    supply.close()


def test_loader_rejects_non_preview_graph_and_mismatched_adapter(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    supply, adapter, graph, _ = _runtime(tmp_path)
    for invalid in (
        replace(graph, profile="production"),
        replace(graph, preview_adapter=None),
        replace(
            graph, preview_adapter=replace(graph.preview_adapter, revision="c" * 40)
        ),
    ):
        with pytest.raises(DomainError):
            load_preview_pipeline(
                supply,
                adapter,
                invalid,
                _environment(),
                torch_module=_Torch(),
                diffusers_module=_PreviewDiffusers(),
                peft_module=_Peft(),
            )
    adapter.close()
    supply.close()


def test_loader_requires_exact_pinned_peft_runtime(tmp_path: Path) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    supply, adapter, graph, _ = _runtime(tmp_path)
    wrong_peft = type("WrongPeft", (), {"__version__": "0.17.1"})()
    with pytest.raises(InfrastructureError, match="preview runtime unavailable"):
        load_preview_pipeline(
            supply,
            adapter,
            graph,
            _environment(),
            torch_module=_Torch(),
            diffusers_module=_PreviewDiffusers(),
            peft_module=wrong_peft,
        )
    adapter.close()
    supply.close()


@pytest.mark.parametrize("stage", ("scheduler", "lora", "fuse"))
def test_loader_releases_partial_pipeline_on_lcm_stage_failure(
    tmp_path: Path, stage: str
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    supply, adapter, graph, _ = _runtime(tmp_path)
    diffusers = _PreviewDiffusers()
    if stage == "scheduler":
        diffusers.LCMScheduler.from_config = lambda _config: (_ for _ in ()).throw(
            RuntimeError("scheduler")
        )
    pipeline_type = diffusers.StableDiffusionXLControlNetImg2ImgPipeline
    original = pipeline_type.from_pretrained

    def issue(*args: object, **kwargs: object):
        pipeline = original(*args, **kwargs)
        if stage == "lora":
            pipeline.load_lora_weights = lambda *a, **k: (_ for _ in ()).throw(
                RuntimeError("lora")
            )
        if stage == "fuse":
            pipeline.fuse_lora = lambda **k: (_ for _ in ()).throw(RuntimeError("fuse"))
        return pipeline

    pipeline_type.from_pretrained = staticmethod(issue)
    with pytest.raises(InfrastructureError, match="loading"):
        load_preview_pipeline(
            supply,
            adapter,
            graph,
            _environment(),
            torch_module=_Torch(),
            diffusers_module=diffusers,
            peft_module=_Peft(),
        )
    if diffusers.issued_pipelines:
        assert diffusers.issued_pipelines[0].hooks == 1
    adapter.close()
    supply.close()


def test_execution_binding_is_distinct_and_binds_four_models_and_runtime(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers(),
        peft_module=_Peft(),
    )
    binding = bind_preview_execution(loaded, request)
    material = json.loads(binding.material_json)

    assert binding.compiled_request_fingerprint != binding.execution_fingerprint
    assert material["schema_version"] == "specstyle.preview.execution.v3"
    assert material["runtime"]["dtype"] == "float16"
    assert material["runtime"]["vae_at_rest_dtype"] == "float16"
    assert material["runtime"]["vae_compute_dtype"] == "float32"
    assert material["runtime"]["vae_precision_policy"] == (
        "diffusers_force_upcast_roundtrip_v1"
    )
    compiled = material["compiled_request"]
    assert compiled["schema_version"] == "specstyle.preview.compiled-request.v2"
    assert compiled["run_id"] == request.job_id.value
    assert compiled["variation_index"] == request.variation_index
    assert compiled["seed"] == {
        "algorithm": request.seed.algorithm,
        "value": request.seed.seed,
    }
    assert compiled["resolution"] == list(request.graph.resolution)
    assert [item["descriptor"]["role"] for item in material["models"]] == [
        "base",
        "ip_adapter",
        "controlnet",
        "preview_adapter",
    ]
    assert material["scheduler"]["identity"] == "diffusers.LCMScheduler"
    assert material["lora_fuse_scale"] == 1.0
    assert material["runtime"]["peft_version"] == "0.18.1"
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(binding)
    frozen_material = binding.material_json
    loaded.close()
    assert binding.material_json == frozen_material
    adapter.close()
    supply.close()


def test_execution_fingerprint_changes_when_only_preview_approval_changes(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    first = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers(),
        peft_module=_Peft(),
    )
    first_binding = bind_preview_execution(first, request)
    first.close()
    adapter.close()

    changed_adapter, _ = _adapter(
        tmp_path, evidence_url="https://licenses.example.test/lcm-review-2"
    )
    second = load_preview_pipeline(
        supply,
        changed_adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers(),
        peft_module=_Peft(),
    )
    second_binding = bind_preview_execution(second, request)

    assert (
        first_binding.compiled_request_fingerprint
        == second_binding.compiled_request_fingerprint
    )
    assert first_binding.execution_fingerprint != second_binding.execution_fingerprint
    second.close()
    changed_adapter.close()
    supply.close()


def test_execution_v3_rejects_legacy_vae_dtype_runtime_shape(tmp_path: Path) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import (
        _canonical_json,
        _fingerprint,
        _validate_execution_binding,
        bind_preview_execution,
    )

    supply, adapter, graph, request = _runtime(tmp_path)
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers(),
        peft_module=_Peft(),
    )
    try:
        binding = bind_preview_execution(loaded, request)
        material = json.loads(binding.material_json)
        material["runtime"] = {
            "rocm_version": "7.2.1",
            "torch_version": "2.8.0",
            "diffusers_version": "0.39.0",
            "peft_version": "0.18.1",
            "dtype": "float16",
            "vae_dtype": "float32",
        }
        material_json = _canonical_json(material)
        object.__setattr__(binding, "material_json", material_json)
        object.__setattr__(
            binding, "execution_fingerprint", _fingerprint(material_json)
        )
        with pytest.raises(DomainError, match="execution binding"):
            _validate_execution_binding(binding)
    finally:
        loaded.close()
        adapter.close()
        supply.close()


def test_execution_fingerprint_binds_scheduler_config_and_valid_graph_changes(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    first = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers({"original_inference_steps": 50}),
        peft_module=_Peft(),
    )
    first_binding = bind_preview_execution(first, request)
    five_step_binding = bind_preview_execution(
        first, _changed_request(request, steps=5)
    )
    assert (
        first_binding.compiled_request_fingerprint
        != five_step_binding.compiled_request_fingerprint
    )
    assert (
        first_binding.execution_fingerprint != five_step_binding.execution_fingerprint
    )
    first.close()

    second = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers({"original_inference_steps": 32}),
        peft_module=_Peft(),
    )
    second_binding = bind_preview_execution(second, request)
    assert (
        first_binding.compiled_request_fingerprint
        == second_binding.compiled_request_fingerprint
    )
    assert first_binding.execution_fingerprint != second_binding.execution_fingerprint
    second_pipeline = second._pipeline
    second_pipeline.scheduler.config["tampered"] = True
    with pytest.raises(DomainError, match="capability"):
        bind_preview_execution(second, request)
    second.close()
    adapter.close()
    supply.close()


@pytest.mark.parametrize(
    "tamper", ("unfuse", "refuse_half", "reload", "unet", "controlnet")
)
def test_execution_refuses_mutated_pipeline_models_or_lora_state(
    tmp_path: Path, tamper: str
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    diffusers = _PreviewDiffusers()
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    if tamper == "unfuse":
        pipeline.unfuse_lora()
    elif tamper == "refuse_half":
        pipeline.unfuse_lora()
        pipeline.fuse_lora(lora_scale=0.5, adapter_names=["specstyle_lcm"])
    elif tamper == "reload":
        pipeline.load_lora_weights("/tmp/other", adapter_name="other")
    else:
        setattr(pipeline, tamper, object())
    with pytest.raises(DomainError, match="capability"):
        bind_preview_execution(loaded, request)
    loaded.close()
    adapter.close()
    supply.close()


@pytest.mark.parametrize(
    "changes",
    (
        {"pipeline": "sdxl_turbo"},
        {"steps": 3},
        {"steps": 9},
        {"guidance_scale": -0.0},
        {"guidance_scale": 1.0},
    ),
)
def test_backend_rejects_every_non_lcm_graph_before_execution(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    from specstyle.generation.preview_diffusers_backend import PreviewDiffusersBackend
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    supply, adapter, graph, request = _runtime(tmp_path)
    diffusers = _PreviewDiffusers()
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    backend = PreviewDiffusersBackend(loaded, lambda _ref: _png((512, 512)))
    with pytest.raises(DomainError, match="binding"):
        backend.generate(_changed_request(request, **changes))
    assert not hasattr(diffusers.issued_pipelines[0], "kwargs")
    loaded.close()
    adapter.close()
    supply.close()


def test_backend_generates_bound_preview_artifact_and_real_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.generation.preview_diffusers_backend import PreviewDiffusersBackend
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    style = _png((512, 512), "blue")
    supply, adapter, graph, request = _runtime(tmp_path, style=style)
    torch, diffusers = _Torch(), _PreviewDiffusers()

    class Generator:
        def __init__(self, device: str) -> None:
            self.device = device

        def manual_seed(self, seed: int) -> Generator:
            self.seed = seed
            return self

    torch.Generator = Generator
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=torch,
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    pipeline.scales = []
    pipeline.set_ip_adapter_scale = lambda scale: pipeline.scales.append(scale)

    def call(_self, **kwargs: object):
        pipeline.kwargs = kwargs
        pipeline.style_color = kwargs["ip_adapter_image"][0][0].getpixel((0, 0))
        return type("Result", (), {"images": [Image.new("RGB", (512, 512))]})()

    monkeypatch.setattr(pipeline.__class__, "__call__", call)
    artifact = PreviewDiffusersBackend(loaded, lambda _ref: style).generate(request)

    assert artifact.content.startswith(b"\x89PNG")
    assert artifact.content_sha256 == hash_bytes(artifact.content)
    assert artifact.artifact_id.value.startswith("preview-")
    assert artifact.execution_fingerprint == artifact.binding.execution_fingerprint
    assert pipeline.scales == [request.execution_parameters.ip_adapter_scale]
    assert pipeline.kwargs["num_inference_steps"] == 4
    assert pipeline.kwargs["guidance_scale"] == 0.0
    assert pipeline.style_color == (0, 0, 255)
    with pytest.raises(DomainError):
        type(artifact)(
            ArtifactId("preview-forged"),
            artifact.content,
            artifact.content_sha256,
            artifact.binding,
            artifact.execution_fingerprint,
        )
    loaded.close()
    adapter.close()
    supply.close()


def test_backend_reuses_pipeline_after_diffusers_vae_upcast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.generation.preview_diffusers_backend import PreviewDiffusersBackend
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    style = _png((512, 512), "blue")
    supply, adapter, graph, request = _runtime(tmp_path, style=style)
    torch, diffusers = _Torch(), _PreviewDiffusers()

    class Generator:
        def __init__(self, device: str) -> None:
            self.device = device

        def manual_seed(self, seed: int) -> Generator:
            self.seed = seed
            return self

    torch.Generator = Generator
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=torch,
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    pipeline.set_ip_adapter_scale = lambda _scale: None
    calls = 0

    def call(_self, **_kwargs: object):
        nonlocal calls
        calls += 1
        pipeline.vae.to(dtype=_FLOAT32)
        pipeline.vae.to(dtype=_FLOAT16)
        return type("Result", (), {"images": [Image.new("RGB", (512, 512))]})()

    monkeypatch.setattr(pipeline.__class__, "__call__", call)
    try:
        first = PreviewDiffusersBackend(loaded, lambda _ref: style).generate(request)
        second = PreviewDiffusersBackend(loaded, lambda _ref: style).generate(request)
        assert first.content == second.content
        assert calls == 2
        assert pipeline.vae.dtype is _FLOAT16
        assert pipeline.vae.to_calls == [
            {"dtype": _FLOAT32},
            {"dtype": _FLOAT16},
            {"dtype": _FLOAT32},
            {"dtype": _FLOAT16},
        ]
    finally:
        loaded.close()
        adapter.close()
        supply.close()


def test_execution_allows_vae_storage_move_but_rejects_content_tamper(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    diffusers = _PreviewDiffusers()
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    try:
        pipeline.vae.weight._data_ptr += 1
        bind_preview_execution(loaded, request)
        pipeline.vae.weight._content[0] ^= 1
        with pytest.raises(DomainError, match="capability"):
            bind_preview_execution(loaded, request)

    finally:
        loaded.close()
        adapter.close()
        supply.close()


def test_execution_rejects_vae_dtype_and_non_vae_storage_tamper(
    tmp_path: Path,
) -> None:
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import bind_preview_execution

    supply, adapter, graph, request = _runtime(tmp_path)
    diffusers = _PreviewDiffusers()
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    try:
        pipeline.vae.dtype = _FLOAT32
        with pytest.raises(DomainError, match="capability"):
            bind_preview_execution(loaded, request)
        pipeline.vae.dtype = _FLOAT16
        pipeline.unet.layer.weight._data_ptr += 1
        with pytest.raises(DomainError, match="capability"):
            bind_preview_execution(loaded, request)
    finally:
        loaded.close()
        adapter.close()
        supply.close()


def test_backend_postcondition_poisoning_overrides_inference_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.generation.preview_diffusers_backend import (
        PreviewDiffusersBackend,
        _PreviewRuntimeIntegrityError,
    )
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    style = _png((512, 512), "blue")
    supply, adapter, graph, request = _runtime(tmp_path, style=style)
    torch, diffusers = _Torch(), _PreviewDiffusers()

    class Generator:
        def __init__(self, device: str) -> None:
            self.device = device

        def manual_seed(self, seed: int) -> Generator:
            self.seed = seed
            return self

    torch.Generator = Generator
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=torch,
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    pipeline.set_ip_adapter_scale = lambda _scale: None

    def corrupt_then_fail(_self, **_kwargs: object):
        pipeline.vae.weight._content[0] ^= 1
        raise RuntimeError("inference failed after corruption")

    monkeypatch.setattr(pipeline.__class__, "__call__", corrupt_then_fail)
    backend = PreviewDiffusersBackend(loaded, lambda _ref: style)
    try:
        with pytest.raises(_PreviewRuntimeIntegrityError):
            backend.generate(request)
        with pytest.raises(_PreviewRuntimeIntegrityError):
            backend.generate(request)
    finally:
        loaded.close()
        adapter.close()
        supply.close()


def test_backend_does_not_build_artifact_when_success_corrupts_vae(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.generation.preview_diffusers_backend import (
        PreviewDiffusersBackend,
        _PreviewRuntimeIntegrityError,
    )
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline

    style = _png((512, 512), "blue")
    supply, adapter, graph, request = _runtime(tmp_path, style=style)
    torch, diffusers = _Torch(), _PreviewDiffusers()

    class Generator:
        def __init__(self, device: str) -> None:
            self.device = device

        def manual_seed(self, seed: int) -> Generator:
            self.seed = seed
            return self

    torch.Generator = Generator
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=torch,
        diffusers_module=diffusers,
        peft_module=_Peft(),
    )
    pipeline = diffusers.issued_pipelines[0]
    pipeline.set_ip_adapter_scale = lambda _scale: None

    def corrupt_then_return(_self, **_kwargs: object):
        pipeline.vae.weight._content[0] ^= 1
        return type("Result", (), {"images": [Image.new("RGB", (512, 512))]})()

    monkeypatch.setattr(pipeline.__class__, "__call__", corrupt_then_return)
    try:
        with pytest.raises(_PreviewRuntimeIntegrityError):
            PreviewDiffusersBackend(loaded, lambda _ref: style).generate(request)
    finally:
        loaded.close()
        adapter.close()
        supply.close()


@pytest.mark.parametrize("failure_call", (3, 4))
def test_backend_poisons_nested_integrity_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_call: int,
) -> None:
    import specstyle.generation.preview_diffusers_loader as loader_module
    from specstyle.generation.preview_diffusers_backend import (
        PreviewDiffusersBackend,
        _PreviewRuntimeIntegrityError,
    )

    supply, adapter, graph, request = _runtime(tmp_path)
    loaded = loader_module.load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers(),
        peft_module=_Peft(),
    )
    real_hash = loader_module._vae_content_sha256
    calls = 0

    def fail_nested_read(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise DomainError("injected VAE read failure")
        return real_hash(*args, **kwargs)

    monkeypatch.setattr(loader_module, "_vae_content_sha256", fail_nested_read)
    try:
        backend = PreviewDiffusersBackend(loaded, lambda _ref: _png((512, 512)))
        with pytest.raises(_PreviewRuntimeIntegrityError):
            backend.generate(request)
        assert loaded._poisoned is True
    finally:
        loaded.close()
        adapter.close()
        supply.close()
