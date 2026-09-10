"""GEN-004R Diffusers loader contract (all dependencies are injected fakes)."""

from __future__ import annotations

import copy
import os
import pickle
import weakref
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

import specstyle.generation.diffusers_loader as diffusers_loader_module
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.diffusers_loader import load_production_pipeline
from specstyle.generation.model_approval import verify_pipeline_supply
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.pipeline_factory import PipelineFactory
from specstyle.generation.weight_manifest import (
    ModelLoadEntrypoint,
    WeightFile,
    WeightManifest,
)
from specstyle.observability.environment import (
    DeviceInventory,
    DeviceSnapshot,
    EnvironmentSnapshot,
    IntegerObservation,
    TextObservation,
)
from specstyle.observability.hashing import hash_bytes


_REVISION = "a" * 40
_FLOAT16 = object()
_FLOAT32 = object()
_INT64 = object()


class _Device:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        return type(other) is _Device and self.name == other.name

    def __str__(self) -> str:
        return self.name


class _ModelTensor:
    def __init__(
        self, device: str = "cuda:0", dtype: object = _FLOAT16, *, floating: bool = True
    ) -> None:
        self.device = _Device(device)
        self.dtype = dtype
        self.floating = floating

    def is_floating_point(self) -> bool:
        return self.floating


class _CLIPVisionModelWithProjection:
    def __init__(self) -> None:
        self.config = type("Config", (), {"image_size": 224})()
        self._parameters = [_ModelTensor()]
        self._buffers = [_ModelTensor(), _ModelTensor(dtype=_INT64, floating=False)]

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.call_impl(*args, **kwargs)

    def parameters(self):
        return iter(self._parameters)

    def buffers(self):
        return iter(self._buffers)


class _CLIPImageProcessor:
    def __init__(self) -> None:
        self.size = {"shortest_edge": 224}
        self.crop_size = {"height": 224, "width": 224}
        self.do_resize = True
        self.do_center_crop = True
        self.do_rescale = True
        self.do_normalize = True
        self.do_convert_rgb = True
        self.resample = Image.Resampling.BICUBIC
        self.rescale_factor = 1 / 255
        self.image_mean = [0.48145466, 0.4578275, 0.40821073]
        self.image_std = [0.26862954, 0.26130258, 0.27577711]

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self.call_impl(*args, **kwargs)

    def to_dict(self) -> dict[str, object]:
        result = {
            "crop_size": dict(self.crop_size),
            "do_center_crop": self.do_center_crop,
            "do_convert_rgb": self.do_convert_rgb,
            "do_normalize": self.do_normalize,
            "do_rescale": self.do_rescale,
            "do_resize": self.do_resize,
            "image_mean": list(self.image_mean),
            "image_std": list(self.image_std),
            "resample": self.resample,
            "rescale_factor": self.rescale_factor,
            "size": dict(self.size),
        }
        if hasattr(self, "provenance_extra"):
            result["provenance_extra"] = self.provenance_extra
        return result


_CLIPImageProcessor.__module__ = "transformers.models.clip.image_processing_clip"


class _Transformers:
    __version__ = "4.57.3"
    CLIPVisionModelWithProjection = _CLIPVisionModelWithProjection
    CLIPImageProcessor = _CLIPImageProcessor


class _Cuda:
    def __init__(self, devices: tuple[tuple[str, int, str], ...] | None = None) -> None:
        self.empty_cache_calls = 0
        self.devices = devices or (("AMD test", 16, "gfx1100"),)

    def is_available(self) -> bool:
        return True

    def device_count(self) -> int:
        return len(self.devices)

    def get_device_name(self, index: int) -> str:
        return self.devices[index][0]

    def get_device_properties(self, index: int):
        name, memory, arch = self.devices[index]
        return type("Properties", (), {"total_memory": memory, "gcnArchName": arch})()

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


class _Torch:
    __version__ = "2.8.0"
    device = _Device
    float16 = _FLOAT16
    float32 = _FLOAT32
    version = type("Version", (), {"hip": "7.2.1"})()

    def __init__(self) -> None:
        self.cuda = _Cuda()


class _Pipeline:
    def __init__(self) -> None:
        self.scheduler = type("Scheduler", (), {"config": {"x": 1}})()
        self.image_encoder = None
        self.feature_extractor = None
        self.to_calls: list[tuple[object, ...]] = []
        self.ip_calls: list[tuple[object, dict[str, object]]] = []
        self.hooks = 0

    def to(self, *args: object) -> _Pipeline:
        self.to_calls.append(args)
        return self

    def load_ip_adapter(self, *args: object, **kwargs: object) -> None:
        self.ip_calls.append((args, kwargs))
        self.image_encoder = _CLIPVisionModelWithProjection()
        self.feature_extractor = _CLIPImageProcessor()

    def maybe_free_model_hooks(self) -> None:
        self.hooks += 1


class _Diffusers:
    __version__ = "0.39.0"

    def __init__(self) -> None:
        diffusers_loader_module._import_transformers = lambda: _Transformers
        diffusers_loader_module._installed_transformers_version = lambda: (
            _Transformers.__version__
        )
        self.control_calls: list[tuple[object, dict[str, object]]] = []
        self.pipeline_calls: list[tuple[object, dict[str, object]]] = []
        self.scheduler_calls: list[object] = []
        self.issued_pipelines: list[_Pipeline] = []
        self.track_issued_pipelines = False
        outer = self

        class ControlNetModel:
            @classmethod
            def from_pretrained(cls, *args: object, **kwargs: object) -> object:
                outer.control_calls.append((args, kwargs))
                return object()

        class StableDiffusionXLControlNetImg2ImgPipeline:
            @classmethod
            def from_pretrained(cls, *args: object, **kwargs: object) -> _Pipeline:
                outer.pipeline_calls.append((args, kwargs))
                pipeline = _Pipeline()
                if outer.track_issued_pipelines:
                    outer.issued_pipelines.append(pipeline)
                return pipeline

        class EulerDiscreteScheduler:
            @classmethod
            def from_config(cls, config: object) -> object:
                outer.scheduler_calls.append(config)
                return object()

        self.ControlNetModel = ControlNetModel
        self.StableDiffusionXLControlNetImg2ImgPipeline = (
            StableDiffusionXLControlNetImg2ImgPipeline
        )
        self.EulerDiscreteScheduler = EulerDiscreteScheduler


def _available(value: str) -> TextObservation:
    return TextObservation("AVAILABLE", value, None)


def _environment() -> EnvironmentSnapshot:
    device = DeviceSnapshot(
        0,
        _available("AMD test"),
        IntegerObservation("AVAILABLE", 16, None),
        _available("gfx1100"),
    )
    return EnvironmentSnapshot(
        "1.0",
        *(_available("x") for _ in range(6)),
        _available("7.2.1"),
        _available("7.2.1"),
        _available("2.8.0"),
        _available("0.39.0"),
        DeviceInventory("AVAILABLE", None, (device,)),
    )


def _supply(tmp_path: Path):
    descriptors = []
    manifests = []
    approvals = []
    for model_id, role in (
        ("base", "base"),
        ("ip", "ip_adapter"),
        ("cn", "controlnet"),
    ):
        payload = model_id.encode()
        root = tmp_path / model_id
        payloads = {"pipeline/model.safetensors": payload}
        if role == "ip_adapter":
            payloads.update(
                {
                    "pipeline/image_encoder/config.json": b"{}",
                    "pipeline/image_encoder/model.safetensors": b"encoder",
                }
            )
        for relative_path, content in payloads.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        entrypoint = ModelLoadEntrypoint(
            "diffusers_ip_adapter" if role == "ip_adapter" else "diffusers_pretrained",
            "pipeline",
            "model.safetensors" if role == "ip_adapter" else None,
        )
        manifest = WeightManifest(
            model_id,
            role,
            _REVISION,
            model_id,
            entrypoint,
            tuple(
                WeightFile(relative_path, len(content), hash_bytes(content))
                for relative_path, content in payloads.items()
            ),
            Sha256("0" * 64),
        ).with_computed_root()
        descriptor = ModelDescriptor(
            model_id, role, _REVISION, manifest.root_sha256, "MIT", "APPROVED", "sdxl"
        )
        from specstyle.generation.model_approval import LicenseApproval
        from specstyle.generation.weight_manifest import manifest_sha256

        approvals.append(
            LicenseApproval(
                model_id,
                _REVISION,
                manifest_sha256(manifest),
                "MIT",
                f"https://example.com/{model_id}",
            )
        )
        descriptors.append(descriptor)
        manifests.append(manifest)
    graph = PipelineFactory(
        ModelRegistry(tuple(descriptors)), tmp_path
    ).build_production("base", "ip", "cn")
    root_fd = os.open(tmp_path, os.O_RDONLY)
    return verify_pipeline_supply(
        root_fd, graph, tuple(manifests), tuple(approvals)
    ), graph


def test_loads_local_safetensors_with_torch_dtype_and_sealed_capability(
    tmp_path: Path,
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()

    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )

    assert type(loaded).__name__ == "LoadedPipeline"
    assert diffusers.control_calls[0][1]["torch_dtype"] is torch.float16
    assert "dtype" not in diffusers.control_calls[0][1]
    assert "subfolder" not in diffusers.control_calls[0][1]
    assert "subfolder" not in diffusers.pipeline_calls[0][1]
    assert diffusers.pipeline_calls[0][1]["torch_dtype"] is torch.float16
    assert diffusers.pipeline_calls[0][1]["local_files_only"] is True
    # /proc/self/fd/N + subfolder breaks pipeline load_config; join instead.
    control_root = diffusers.control_calls[0][0][0]
    pipeline_root = diffusers.pipeline_calls[0][0][0]
    assert type(control_root) is str and control_root.endswith("/pipeline")
    assert type(pipeline_root) is str and pipeline_root.endswith("/pipeline")
    assert not hasattr(loaded, "pipeline")
    borrowed = loaded.borrow_pipeline()
    assert borrowed.to_calls == [("cuda:0", torch.float16)]
    assert "dtype" not in borrowed.ip_calls[0][1]
    with pytest.raises(TypeError):
        copy.copy(loaded)
    with pytest.raises(TypeError):
        copy.deepcopy(loaded)
    with pytest.raises(TypeError):
        pickle.dumps(loaded)
    loaded.close()
    loaded.close()
    with pytest.raises(DomainError, match="closed"):
        loaded.borrow_pipeline()
    assert torch.cuda.empty_cache_calls >= 1
    supply.close()


@pytest.mark.parametrize("mutate", ["rocm", "torch", "device"])
def test_rejects_unmatched_runtime_before_loading(tmp_path: Path, mutate: str) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    environment = _environment()
    if mutate == "rocm":
        environment = EnvironmentSnapshot(
            environment.schema_version,
            environment.os_name,
            environment.os_release,
            environment.kernel_version,
            environment.machine,
            environment.python_implementation,
            environment.python_version,
            _available("7.2.0"),
            environment.hip_version,
            environment.pytorch_version,
            environment.diffusers_version,
            environment.hip_devices,
        )
    elif mutate == "torch":
        torch.__version__ = "other"
    else:
        torch.cuda.device_count = lambda: 2  # type: ignore[method-assign]
    with pytest.raises(DomainError):
        load_production_pipeline(
            supply, graph, environment, torch_module=torch, diffusers_module=diffusers
        )
    assert not diffusers.control_calls
    supply.close()


def test_rejects_supply_graph_mismatch_before_loading(tmp_path: Path) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    graph = replace(graph, base=replace(graph.base, model_id="other"))
    with pytest.raises(DomainError, match="mismatch"):
        load_production_pipeline(
            supply,
            graph,
            _environment(),
            torch_module=torch,
            diffusers_module=diffusers,
        )
    assert not diffusers.control_calls
    supply.close()


@pytest.mark.parametrize("field", ["name", "memory", "arch"])
def test_rejects_mismatch_on_second_reported_device(tmp_path: Path, field: str) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    torch.cuda = _Cuda((("AMD test", 16, "gfx1100"), ("AMD second", 32, "gfx1200")))
    second = DeviceSnapshot(
        1,
        _available("wrong" if field == "name" else "AMD second"),
        IntegerObservation("AVAILABLE", 33 if field == "memory" else 32, None),
        _available("wrong" if field == "arch" else "gfx1200"),
    )
    environment = _environment()
    environment = EnvironmentSnapshot(
        environment.schema_version,
        environment.os_name,
        environment.os_release,
        environment.kernel_version,
        environment.machine,
        environment.python_implementation,
        environment.python_version,
        environment.rocm_version,
        environment.hip_version,
        environment.pytorch_version,
        environment.diffusers_version,
        DeviceInventory("AVAILABLE", None, (*environment.hip_devices.devices, second)),
    )
    with pytest.raises(DomainError, match="device|environment"):
        load_production_pipeline(
            supply, graph, environment, torch_module=torch, diffusers_module=diffusers
        )
    supply.close()


def test_cleans_gpu_cache_after_pipeline_stage_failure(tmp_path: Path) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained = classmethod(
        lambda cls, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(Exception, match="pipeline loading failed"):
        load_production_pipeline(
            supply,
            graph,
            _environment(),
            torch_module=torch,
            diffusers_module=diffusers,
        )
    assert torch.cuda.empty_cache_calls >= 1
    assert supply.borrow_component("base").model_id == "base"
    supply.close()


@pytest.mark.parametrize("stage", ["control", "base", "scheduler", "to", "ip"])
def test_loader_stage_failure_has_no_exception_chain_and_keeps_supply_open(
    tmp_path: Path, stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    if stage == "control":
        diffusers.ControlNetModel.from_pretrained = classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    elif stage == "base":
        diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained = (
            classmethod(
                lambda cls, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )
    elif stage == "scheduler":
        diffusers.EulerDiscreteScheduler.from_config = classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    elif stage == "to":
        monkeypatch.setattr(
            _Pipeline,
            "to",
            lambda self, *args: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    else:
        monkeypatch.setattr(
            _Pipeline,
            "load_ip_adapter",
            lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    with pytest.raises(InfrastructureError, match="pipeline loading failed") as raised:
        load_production_pipeline(
            supply,
            graph,
            _environment(),
            torch_module=torch,
            diffusers_module=diffusers,
        )
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert supply.borrow_component("controlnet").model_id == "cn"
    assert torch.cuda.empty_cache_calls >= 1
    supply.close()


def test_close_failure_detaches_exception_and_releases_cache(tmp_path: Path) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    pipeline = loaded.borrow_pipeline()
    pipeline.maybe_free_model_hooks = lambda: (_ for _ in ()).throw(
        RuntimeError("boom")
    )
    with pytest.raises(InfrastructureError, match="pipeline release failed") as raised:
        loaded.close()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert torch.cuda.empty_cache_calls >= 1
    with pytest.raises(DomainError, match="closed"):
        loaded.borrow_pipeline()
    supply.close()


def test_close_failure_collects_pipeline_and_hook_frame_before_empty_cache(
    tmp_path: Path,
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    borrowed = loaded.borrow_pipeline()
    pipeline_ref = weakref.ref(borrowed)

    class FrameSentinel:
        pass

    sentinel_refs: list[weakref.ReferenceType[FrameSentinel]] = []
    cache_observations: list[tuple[bool, bool]] = []

    def failing_hook() -> None:
        sentinel = FrameSentinel()
        sentinel_refs.append(weakref.ref(sentinel))
        try:
            raise RuntimeError("boom")
        except Exception as error:
            retained_error = [error]
            assert retained_error[0] is error
            raise

    def empty_cache() -> None:
        cache_observations.append(
            (pipeline_ref() is None, all(ref() is None for ref in sentinel_refs))
        )
        assert cache_observations[-1] == (True, True)
        torch.cuda.empty_cache_calls += 1

    borrowed.maybe_free_model_hooks = failing_hook
    del borrowed
    torch.cuda.empty_cache = empty_cache

    try:
        with pytest.raises(
            InfrastructureError, match="pipeline release failed"
        ) as raised:
            loaded.close()
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert pipeline_ref() is None
        assert sentinel_refs and all(ref() is None for ref in sentinel_refs)
        assert cache_observations == [(True, True)]
        assert torch.cuda.empty_cache_calls == 1
        with pytest.raises(DomainError, match="closed"):
            loaded.borrow_pipeline()
    finally:
        loaded.close()
        supply.close()


def test_failed_load_releases_pipeline_before_empty_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    released: list[weakref.ReferenceType[_Pipeline]] = []

    def issue_pipeline(cls, *args, **kwargs):
        pipeline = _Pipeline()
        released.append(weakref.ref(pipeline))
        return pipeline

    monkeypatch.setattr(
        diffusers.StableDiffusionXLControlNetImg2ImgPipeline,
        "from_pretrained",
        classmethod(issue_pipeline),
    )
    monkeypatch.setattr(
        _Pipeline,
        "load_ip_adapter",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    torch.cuda.empty_cache = lambda: (
        (_ for _ in ()).throw(AssertionError("pipeline retained"))
        if released[0]() is not None
        else setattr(torch.cuda, "empty_cache_calls", torch.cuda.empty_cache_calls + 1)
    )
    with pytest.raises(InfrastructureError, match="pipeline loading failed"):
        load_production_pipeline(
            supply,
            graph,
            _environment(),
            torch_module=torch,
            diffusers_module=diffusers,
        )
    assert supply.borrow_component("base").model_id == "base"
    supply.close()


@pytest.mark.parametrize("real_oom", (True, False))
def test_load_classifies_only_the_real_torch_oom_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_oom: bool
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()

    class PublicOom(Exception):
        pass

    class FakeNamedOutOfMemoryError(Exception):
        pass

    torch.cuda.OutOfMemoryError = PublicOom
    failure_type = PublicOom if real_oom else FakeNamedOutOfMemoryError
    monkeypatch.setattr(
        diffusers.ControlNetModel,
        "from_pretrained",
        classmethod(lambda cls, *args, **kwargs: (_ for _ in ()).throw(failure_type())),
    )
    try:
        with pytest.raises(InfrastructureError) as raised:
            load_production_pipeline(
                supply,
                graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        errors = __import__("specstyle.errors", fromlist=["_GpuOutOfMemoryError"])
        expected_type = (
            getattr(errors, "_GpuOutOfMemoryError") if real_oom else InfrastructureError
        )
        assert type(raised.value) is expected_type
        assert str(raised.value) == (
            "pipeline loading OOM" if real_oom else "pipeline loading failed"
        )
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
    finally:
        supply.close()


def _inject_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        diffusers_loader_module,
        "_import_transformers",
        lambda: _Transformers,
        raising=False,
    )


def _assert_failed_pipeline_released(diffusers: _Diffusers, torch: _Torch) -> None:
    assert len(diffusers.issued_pipelines) == 1
    pipeline = diffusers.issued_pipelines[0]
    assert pipeline.hooks == 1
    assert pipeline.to_calls[-1] == ("cpu",)
    assert torch.cuda.empty_cache_calls >= 1


@pytest.mark.parametrize("field", ["image_encoder", "feature_extractor"])
def test_loader_rejects_preloaded_image_evidence_objects_and_releases_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    _inject_transformers(monkeypatch)
    original_factory = (
        diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained
    )

    def issue_preloaded(cls, *args: object, **kwargs: object) -> _Pipeline:
        pipeline = original_factory(*args, **kwargs)
        setattr(pipeline, field, object())
        return pipeline

    monkeypatch.setattr(
        diffusers.StableDiffusionXLControlNetImg2ImgPipeline,
        "from_pretrained",
        classmethod(issue_preloaded),
    )
    try:
        with pytest.raises(InfrastructureError, match="pipeline loading failed"):
            load_production_pipeline(
                supply,
                graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        _assert_failed_pipeline_released(diffusers, torch)
    finally:
        supply.close()


@pytest.mark.parametrize(
    "mode",
    [
        "missing_encoder",
        "wrong_encoder",
        "subclass_encoder",
        "missing_processor",
        "wrong_processor",
        "subclass_processor",
    ],
)
def test_loader_rejects_missing_or_nonexact_postload_image_evidence_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    _inject_transformers(monkeypatch)

    class EncoderSubclass(_CLIPVisionModelWithProjection):
        pass

    class ProcessorSubclass(_CLIPImageProcessor):
        pass

    def load_invalid(self: _Pipeline, *args: object, **kwargs: object) -> None:
        self.ip_calls.append((args, kwargs))
        self.image_encoder = {
            "missing_encoder": None,
            "wrong_encoder": object(),
            "subclass_encoder": EncoderSubclass(),
        }.get(mode, _CLIPVisionModelWithProjection())
        self.feature_extractor = {
            "missing_processor": None,
            "wrong_processor": object(),
            "subclass_processor": ProcessorSubclass(),
        }.get(mode, _CLIPImageProcessor())

    monkeypatch.setattr(_Pipeline, "load_ip_adapter", load_invalid)
    try:
        with pytest.raises(InfrastructureError, match="pipeline loading failed"):
            load_production_pipeline(
                supply,
                graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        _assert_failed_pipeline_released(diffusers, torch)
    finally:
        supply.close()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("image_size", 0),
        ("size", {"shortest_edge": 225}),
        ("crop_size", {"height": 224, "width": 225}),
        ("do_resize", False),
        ("do_center_crop", False),
        ("do_rescale", False),
        ("do_normalize", False),
        ("do_convert_rgb", False),
        ("resample", Image.Resampling.NEAREST),
        ("rescale_factor", 0.5),
        ("image_mean", [0.1, 0.2, 0.3]),
        ("image_std", [0.1, 0.2, 0.3]),
    ],
)
def test_loader_rejects_each_unfrozen_image_processor_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    _inject_transformers(monkeypatch)
    original_load = _Pipeline.load_ip_adapter

    def load_invalid(self: _Pipeline, *args: object, **kwargs: object) -> None:
        original_load(self, *args, **kwargs)
        target = (
            self.image_encoder.config
            if field == "image_size"
            else self.feature_extractor
        )
        setattr(target, field, invalid_value)

    monkeypatch.setattr(_Pipeline, "load_ip_adapter", load_invalid)
    try:
        with pytest.raises(InfrastructureError, match="pipeline loading failed"):
            load_production_pipeline(
                supply,
                graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        _assert_failed_pipeline_released(diffusers, torch)
    finally:
        supply.close()
