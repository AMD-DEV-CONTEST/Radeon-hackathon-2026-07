"""GEN-004R backend hard contract tests."""

from __future__ import annotations

import importlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import threading
import weakref

import pytest
from PIL import Image

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, AttemptId, JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.diffusers_backend import DiffusersBackend
from specstyle.generation.diffusers_loader import load_production_pipeline
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.requests import (
    GenerationRequest,
    PreparedControlInput,
    RenderedPrompt,
)
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
    _Diffusers,
    _Torch,
    _environment,
    _supply,
)
from tests.unit.spec.test_compiler import context, raw_spec


def _png(size=(64, 64), mode="RGB", metadata=None, color="red") -> bytes:
    output = BytesIO()
    image = Image.new(mode, size, color)
    image.save(output, "PNG", pnginfo=metadata)
    return output.getvalue()


class _FrameSentinel:
    pass


def _raise_with_frame_cycle(
    error_type: type[Exception], refs: list[weakref.ReferenceType[_FrameSentinel]]
) -> None:
    sentinel = _FrameSentinel()
    refs.append(weakref.ref(sentinel))
    try:
        raise error_type("boom")
    except Exception as error:
        retained_error = [error]
        assert retained_error[0] is error
        raise


def _track_opened_image_closes(
    monkeypatch: pytest.MonkeyPatch, *, fail_load_at: int | None = None
) -> list[int]:
    real_open = Image.open
    close_counts: list[int] = []

    def tracked_open(*args, **kwargs):
        image = real_open(*args, **kwargs)
        index = len(close_counts)
        close_counts.append(0)
        real_close = image.close

        def tracked_close() -> None:
            close_counts[index] += 1
            real_close()

        image.close = tracked_close
        if index == fail_load_at:
            image.load = lambda: (_ for _ in ()).throw(OSError("decode failed"))
        return image

    monkeypatch.setattr(Image, "open", tracked_open)
    return close_counts


def test_constructor_requires_loaded_capability() -> None:
    with pytest.raises(DomainError):
        DiffusersBackend(object(), lambda _ref: b"")


def test_output_contract_rejects_bytes_dict_and_non_rgb_images() -> None:
    # This contract is deliberately tested through the exported strict helper;
    # production backend must not coerce or synthesize an output.
    from specstyle.generation.diffusers_backend import _encode_result_png

    for result in (
        b"png",
        {},
        type("Result", (), {"images": []})(),
        Image.new("RGBA", (64, 64)),
    ):
        with pytest.raises(InfrastructureError):
            _encode_result_png(result, (64, 64))


def test_output_contract_emits_clean_png_only() -> None:
    from specstyle.generation.diffusers_backend import _encode_result_png

    content = _encode_result_png(
        type("Result", (), {"images": [Image.new("RGB", (64, 64))]})(), (64, 64)
    )
    image = Image.open(BytesIO(content))
    assert image.mode == "RGB"
    assert image.size == (64, 64)
    assert not image.info


def test_invalid_output_closes_every_owned_pil_image() -> None:
    from specstyle.generation.diffusers_backend import _encode_result_png

    first, second = Image.new("RGB", (64, 64)), Image.new("RGB", (64, 64))
    closed: list[str] = []
    first_close, second_close = first.close, second.close
    first.close = lambda: (closed.append("first"), first_close())[1]
    second.close = lambda: (closed.append("second"), second_close())[1]
    with pytest.raises(InfrastructureError):
        _encode_result_png(type("Result", (), {"images": [first, second]})(), (64, 64))
    assert closed == ["first", "second"]


def _production_request(
    tmp_path: Path, style_bytes: tuple[bytes, ...], *, dtype: str = "float16"
):
    supply, pipeline_graph = _supply(tmp_path)
    raw = raw_spec().model_dump(mode="python")
    raw["runtime"] = {
        "backend": "rocm",
        "rocm_version": "7.2.1",
        "torch_version": "2.8.0",
        "diffusers_version": "0.39.0",
        "dtype": dtype,
    }
    for role, descriptor in (
        ("base", pipeline_graph.base),
        ("ip_adapter", pipeline_graph.ip_adapter),
        ("controlnet", pipeline_graph.controlnet),
    ):
        name = "ip_adapter" if role == "ip_adapter" else role
        raw["models"][name]["id"] = descriptor.model_id
        raw["models"][name]["revision"] = descriptor.revision
        raw["models"][name]["sha256"] = descriptor.expected_sha256.value
    raw["assets"]["style_references"] = tuple(
        {
            "asset_sha256": hash_bytes(content).value,
            "source_url": f"https://example.com/{index}",
            "license": "CC0",
            "attribution": "author",
            "consent": "not_applicable",
        }
        for index, content in enumerate(style_bytes)
    )
    base_context = context()
    runtime_pin = ResourcePin(
        "runtime", "r1", base_context.runtime_capabilities[0].pin.sha256
    )
    model_capabilities = tuple(
        ModelCapability(
            descriptor.role,
            ResourcePin(
                descriptor.model_id, descriptor.revision, descriptor.expected_sha256
            ),
            "canny" if descriptor.role == "controlnet" else None,
            ("sdxl_turbo", "sdxl_base"),
            (dtype,),
            (runtime_pin.sha256,),
        )
        for descriptor in (
            pipeline_graph.base,
            pipeline_graph.ip_adapter,
            pipeline_graph.controlnet,
        )
    )
    compiler_context = replace(
        base_context,
        runtime_capabilities=(
            RuntimeCapability(runtime_pin, "rocm", "7.2.1", "2.8.0", "0.39.0", dtype),
        ),
        model_capabilities=model_capabilities,
    )
    compiled = compile_style_spec(StyleSpecV1.model_validate(raw), compiler_context)
    payload = _png((1024, 1024))
    source = preprocess_image(
        payload,
        AssetRef(AssetId("source"), hash_bytes(payload)),
        PreprocessPlan(
            (1024, 1024),
            "contain_pad",
            (0, 0, 0),
            ResourcePin("processor", "r1", hash_bytes(b"processor")),
        ),
    )
    graph = compiled.production_graphs[0]
    request = GenerationRequest(
        JobId("job"),
        AttemptId("attempt"),
        None,
        compiled,
        "production",
        "xhs_grid",
        source,
        tuple(
            AssetRef(AssetId(f"style-{index}"), hash_bytes(content))
            for index, content in enumerate(style_bytes)
        ),
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
    return supply, pipeline_graph, request


def test_generate_uses_nested_style_order_scale_callback_and_real_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _png((1024, 1024), color="red"), _png((1024, 1024), color="blue")
    supply, graph, request = _production_request(tmp_path, (first, second))
    torch, diffusers = _Torch(), _Diffusers()

    class Generator:
        def __init__(self, device: str) -> None:
            self.device = device

        def manual_seed(self, seed: int) -> Generator:
            self.seed = seed
            return self

    torch.Generator = Generator
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    pipe = loaded.borrow_pipeline()
    pipe.scales = []
    pipe.set_ip_adapter_scale = lambda value: pipe.scales.append(value)

    def call(**kwargs):
        pipe.kwargs = kwargs
        pipe.style_colors = [
            image.getpixel((0, 0)) for image in kwargs["ip_adapter_image"][0]
        ]
        assert kwargs["callback_on_step_end"](pipe, 0, 0, {"x": 1}) == {"x": 1}
        return type("Result", (), {"images": [Image.new("RGB", (1024, 1024))]})()

    pipe.__call__ = call
    # Special methods are resolved on the type, so use a one-off class method.
    monkeypatch.setattr(
        pipe.__class__, "__call__", lambda self, **kwargs: call(**kwargs)
    )

    def resolver(ref: AssetRef) -> bytes:
        return {
            request.style_references[0]: first,
            request.style_references[1]: second,
        }[ref]

    artifact = DiffusersBackend(loaded, resolver).generate(request)

    assert artifact.content.startswith(b"\x89PNG")
    assert pipe.scales == [request.execution_parameters.ip_adapter_scale]
    assert len(pipe.kwargs["ip_adapter_image"]) == 1
    assert pipe.style_colors == [(255, 0, 0), (0, 0, 255)]
    assert pipe.kwargs["callback_on_step_end_tensor_inputs"] == []
    loaded.close()
    supply.close()


def test_cancelled_step_preserves_cancel_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    style = _png((1024, 1024))
    supply, graph, request = _production_request(tmp_path, (style,))
    torch, diffusers = _Torch(), _Diffusers()
    torch.Generator = type(
        "Generator",
        (),
        {"__init__": lambda self, device: None, "manual_seed": lambda self, seed: self},
    )
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    backend = DiffusersBackend(loaded, lambda _ref: style)
    loaded.borrow_pipeline().set_ip_adapter_scale = lambda _scale: None
    monkeypatch.setattr(
        loaded.borrow_pipeline().__class__,
        "__call__",
        lambda self, **kwargs: (
            backend.cancel(),
            kwargs["callback_on_step_end"](self, 0, 0, {}),
        )[1],
    )
    with pytest.raises(DomainError, match="cancelled"):
        backend.generate(request)
    loaded.close()
    supply.close()


def test_cancel_event_is_shared_across_job_scoped_backends(tmp_path: Path) -> None:
    style = _png((1024, 1024))
    supply, graph, request = _production_request(tmp_path, (style,))
    loaded = load_production_pipeline(
        supply,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
    )
    cancel_event = threading.Event()
    first = DiffusersBackend(loaded, lambda _ref: style, cancel_event=cancel_event)
    second = DiffusersBackend(loaded, lambda _ref: style, cancel_event=cancel_event)

    first.cancel()

    assert cancel_event.is_set()
    with pytest.raises(DomainError, match="^generation cancelled$"):
        second.generate(request)
    loaded.close()
    supply.close()


def test_private_cancel_binding_propagates_before_first_use(
    tmp_path: Path,
) -> None:
    style = _png((1024, 1024))
    supply, graph, _request = _production_request(tmp_path, (style,))
    loaded = load_production_pipeline(
        supply,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
    )
    shared = threading.Event()
    backend = DiffusersBackend(loaded, lambda _ref: style)

    backend._bind_cancel_event(shared)

    backend.cancel()
    assert shared.is_set()

    cancelled = DiffusersBackend(loaded, lambda _ref: style)
    cancelled.cancel()
    shared_after_cancel = threading.Event()
    cancelled._bind_cancel_event(shared_after_cancel)
    assert shared_after_cancel.is_set()

    started = DiffusersBackend(loaded, lambda _ref: style)
    with pytest.raises(DomainError, match="invalid generation request"):
        started.generate(object())  # type: ignore[arg-type]
    with pytest.raises(DomainError, match="invalid cancellation event"):
        started._bind_cancel_event(threading.Event())
    loaded.close()
    supply.close()


def test_private_cancel_binding_serializes_bind_commit_with_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    style = _png((1024, 1024))
    supply, graph, _request = _production_request(tmp_path, (style,))
    loaded = load_production_pipeline(
        supply,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
    )
    backend = DiffusersBackend(loaded, lambda _ref: style)
    shared = threading.Event()
    captured = threading.Barrier(2)
    release = threading.Barrier(2)
    errors: list[BaseException] = []

    def captured_cancel(active_backend: DiffusersBackend) -> None:
        binding = active_backend._cancelled
        captured.wait(2)
        release.wait(2)
        if isinstance(binding, threading.Event):
            binding.set()
        else:
            binding.cancel()

    def run_cancel() -> None:
        try:
            backend.cancel()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(DiffusersBackend, "cancel", captured_cancel)
    cancel_thread = threading.Thread(target=run_cancel)
    cancel_thread.start()
    captured.wait(2)
    backend._bind_cancel_event(shared)
    release.wait(2)
    cancel_thread.join(2)

    try:
        assert not cancel_thread.is_alive()
        assert errors == []
        assert shared.is_set()
    finally:
        release.abort()
        loaded.close()
        supply.close()


def test_process_gpu_lease_serializes_backend_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    style = _png((1024, 1024))
    first_supply, first_graph, first_request = _production_request(
        tmp_path / "first", (style,)
    )
    second_supply, second_graph, second_request = _production_request(
        tmp_path / "second", (style,)
    )
    loaded_instances = []
    for supply, graph in (
        (first_supply, first_graph),
        (second_supply, second_graph),
    ):
        torch, diffusers = _Torch(), _Diffusers()
        torch.Generator = type(
            "Generator",
            (),
            {
                "__init__": lambda self, device: None,
                "manual_seed": lambda self, seed: self,
            },
        )
        loaded_instances.append(
            load_production_pipeline(
                supply,
                graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        )
    for loaded in loaded_instances:
        loaded.borrow_pipeline().set_ip_adapter_scale = lambda _scale: None
    guard = threading.Lock()
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    active = maximum = calls = 0

    def call_pipeline(_self, **_kwargs):
        nonlocal active, maximum, calls
        with guard:
            calls += 1
            active += 1
            maximum = max(maximum, active)
            marker = first_entered if calls == 1 else second_entered
            marker.set()
        assert release.wait(2)
        with guard:
            active -= 1
        return type("Result", (), {"images": [Image.new("RGB", (1024, 1024))]})()

    monkeypatch.setattr(
        loaded_instances[0].borrow_pipeline().__class__, "__call__", call_pipeline
    )
    failures: list[BaseException] = []

    def generate(loaded, request) -> None:
        try:
            DiffusersBackend(loaded, lambda _ref: style).generate(request)
        except BaseException as error:
            failures.append(error)

    first = threading.Thread(target=generate, args=(loaded_instances[0], first_request))
    second = threading.Thread(
        target=generate, args=(loaded_instances[1], second_request)
    )
    first.start()
    assert first_entered.wait(2)
    second.start()
    assert not second_entered.wait(0.1)
    release.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert failures == []
    assert maximum == 1
    for loaded in loaded_instances:
        loaded.close()
    first_supply.close()
    second_supply.close()


def test_pipeline_load_and_generation_share_process_gpu_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    style = _png((1024, 1024))
    ready_supply, ready_graph, request = _production_request(
        tmp_path / "ready", (style,)
    )
    ready_torch, ready_diffusers = _Torch(), _Diffusers()
    ready_torch.Generator = type(
        "Generator",
        (),
        {"__init__": lambda self, device: None, "manual_seed": lambda self, seed: self},
    )
    loaded = load_production_pipeline(
        ready_supply,
        ready_graph,
        _environment(),
        torch_module=ready_torch,
        diffusers_module=ready_diffusers,
    )
    loaded.borrow_pipeline().set_ip_adapter_scale = lambda _scale: None
    generation_entered = threading.Event()

    def generate_pipeline(_self, **_kwargs):
        generation_entered.set()
        return type("Result", (), {"images": [Image.new("RGB", (1024, 1024))]})()

    monkeypatch.setattr(
        loaded.borrow_pipeline().__class__, "__call__", generate_pipeline
    )
    loading_supply, loading_graph = _supply(tmp_path / "loading")
    loading_torch, loading_diffusers = _Torch(), _Diffusers()
    load_entered = threading.Event()
    release_load = threading.Event()
    original_control = loading_diffusers.ControlNetModel.from_pretrained

    def blocked_control(_cls, *args, **kwargs):
        load_entered.set()
        assert release_load.wait(2)
        return original_control(*args, **kwargs)

    monkeypatch.setattr(
        loading_diffusers.ControlNetModel,
        "from_pretrained",
        classmethod(blocked_control),
    )
    failures: list[BaseException] = []
    loaded_results = []

    def load() -> None:
        try:
            loaded_results.append(
                load_production_pipeline(
                    loading_supply,
                    loading_graph,
                    _environment(),
                    torch_module=loading_torch,
                    diffusers_module=loading_diffusers,
                )
            )
        except BaseException as error:
            failures.append(error)

    def generate() -> None:
        try:
            DiffusersBackend(loaded, lambda _ref: style).generate(request)
        except BaseException as error:
            failures.append(error)

    loader_thread = threading.Thread(target=load)
    generation_thread = threading.Thread(target=generate)
    loader_thread.start()
    assert load_entered.wait(2)
    generation_thread.start()
    overlapped = generation_entered.wait(0.1)
    release_load.set()
    loader_thread.join(2)
    generation_thread.join(2)
    try:
        assert not loader_thread.is_alive() and not generation_thread.is_alive()
        assert not overlapped
        assert failures == []
    finally:
        for loaded_result in loaded_results:
            loaded_result.close()
        loaded.close()
        loading_supply.close()
        ready_supply.close()


def test_rejects_legal_bfloat16_request_graph(tmp_path: Path) -> None:
    style = _png((1024, 1024))
    supply, graph, request = _production_request(tmp_path, (style,), dtype="bfloat16")
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    with pytest.raises(DomainError, match="binding mismatch"):
        DiffusersBackend(loaded, lambda _ref: style).generate(request)
    loaded.close()
    supply.close()


def test_corrupted_loaded_runtime_dtype_is_rejected(tmp_path: Path) -> None:
    style = _png((1024, 1024))
    supply, graph, _request = _production_request(tmp_path, (style,))
    loaded = load_production_pipeline(
        supply,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
    )
    object.__setattr__(loaded, "_runtime", ("7.2.1", "2.8.0", "0.39.0", "bfloat16"))
    with pytest.raises(DomainError, match="invalid loaded production pipeline"):
        DiffusersBackend(loaded, lambda _ref: style)
    object.__setattr__(loaded, "_runtime", ("7.2.1", "2.8.0", "0.39.0", "float16"))
    loaded.close()
    supply.close()


def test_second_style_resolution_failure_closes_all_previously_opened_images_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _png((1024, 1024), color="red")
    second = _png((1024, 1024), color="blue")
    supply, graph, request = _production_request(tmp_path, (first, second))
    loaded = load_production_pipeline(
        supply,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
    )
    close_counts = _track_opened_image_closes(monkeypatch)
    resolved: list[AssetRef] = []

    def resolver(reference: AssetRef) -> bytes:
        resolved.append(reference)
        if reference == request.style_references[1]:
            raise RuntimeError("resolver failed")
        return first

    try:
        with pytest.raises(InfrastructureError, match="style asset resolution failed"):
            DiffusersBackend(loaded, resolver).generate(request)
        assert resolved == list(request.style_references)
        assert close_counts == [1, 1, 1]
    finally:
        loaded.close()
        supply.close()


@pytest.mark.parametrize("failure", ["wrong_size_rgb", "rgba", "load_error"])
def test_second_style_decode_failure_closes_every_opened_image_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    first = _png((1024, 1024), color="red")
    if failure == "wrong_size_rgb":
        second = _png((512, 512), color="blue")
    elif failure == "rgba":
        second = _png((1024, 1024), mode="RGBA", color="blue")
    else:
        second = _png((1024, 1024), color="blue")
    supply, graph, request = _production_request(tmp_path, (first, second))
    loaded = load_production_pipeline(
        supply,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_Diffusers(),
    )
    close_counts = _track_opened_image_closes(
        monkeypatch, fail_load_at=3 if failure == "load_error" else None
    )
    contents = dict(zip(request.style_references, (first, second)))

    try:
        with pytest.raises(InfrastructureError, match="generation contract violation"):
            DiffusersBackend(loaded, contents.__getitem__).generate(request)
        assert close_counts == [1, 1, 1, 1]
    finally:
        loaded.close()
        supply.close()


@pytest.mark.parametrize(
    ("stage", "oom", "expected"),
    [
        ("scale", False, "generation failed"),
        ("scale", True, "generation OOM"),
        ("generator", False, "generation failed"),
        ("generator", True, "generation OOM"),
        ("call", False, "generation failed"),
        ("call", True, "generation OOM"),
        ("fake_name", False, "generation failed"),
    ],
)
def test_generate_normalizes_every_execution_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    oom: bool,
    expected: str,
) -> None:
    style = _png((1024, 1024))
    supply, graph, request = _production_request(tmp_path, (style,))
    torch, diffusers = _Torch(), _Diffusers()

    class PublicOom(Exception):
        pass

    class FakeNamedOutOfMemoryError(Exception):
        pass

    torch.cuda.OutOfMemoryError = PublicOom
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    pipe = loaded.borrow_pipeline()
    error_type = PublicOom if oom else RuntimeError
    if stage == "fake_name":
        error_type = FakeNamedOutOfMemoryError
    if stage == "scale":
        pipe.set_ip_adapter_scale = lambda _value: (_ for _ in ()).throw(error_type())
    elif stage == "generator":
        pipe.set_ip_adapter_scale = lambda _value: None
        torch.Generator = lambda **_kwargs: (_ for _ in ()).throw(error_type())
    else:
        pipe.set_ip_adapter_scale = lambda _value: None
        torch.Generator = type(
            "Generator",
            (),
            {
                "__init__": lambda self, **_kwargs: None,
                "manual_seed": lambda self, _seed: self,
            },
        )
        monkeypatch.setattr(
            pipe.__class__,
            "__call__",
            lambda self, **_kwargs: (_ for _ in ()).throw(error_type()),
        )
    with pytest.raises(InfrastructureError, match=expected) as raised:
        DiffusersBackend(loaded, lambda _ref: style).generate(request)
    oom_type = getattr(
        importlib.import_module("specstyle.errors"), "_GpuOutOfMemoryError"
    )
    assert type(raised.value) is (oom_type if oom else InfrastructureError)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert torch.cuda.empty_cache_calls == (1 if expected == "generation OOM" else 0)
    loaded.close()
    supply.close()


@pytest.mark.parametrize(
    ("stage", "fake_name", "expected", "expected_calls", "expected_cache"),
    [
        ("scale", False, "generation OOM", (1, 0, 0), 1),
        ("generator", False, "generation OOM", (1, 1, 0), 1),
        ("pipeline", False, "generation OOM", (1, 1, 1), 1),
        ("pipeline", True, "generation failed", (1, 1, 1), 0),
    ],
)
def test_execution_oom_collects_failure_frame_before_cache_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    fake_name: bool,
    expected: str,
    expected_calls: tuple[int, int, int],
    expected_cache: int,
) -> None:
    style = _png((1024, 1024))
    supply, graph, request = _production_request(tmp_path, (style,))
    torch, diffusers = _Torch(), _Diffusers()

    class PublicOom(Exception):
        pass

    class FakeNamedOutOfMemoryError(Exception):
        pass

    torch.cuda.OutOfMemoryError = PublicOom
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    pipe = loaded.borrow_pipeline()
    calls = {"scale": 0, "generator": 0, "pipeline": 0}
    sentinel_refs: list[weakref.ReferenceType[_FrameSentinel]] = []
    cache_observations: list[bool] = []
    failure_type = FakeNamedOutOfMemoryError if fake_name else PublicOom

    def set_scale(_value: float) -> None:
        calls["scale"] += 1
        if stage == "scale":
            _raise_with_frame_cycle(failure_type, sentinel_refs)

    class Generator:
        def manual_seed(self, _seed: int) -> Generator:
            return self

    def make_generator(**_kwargs) -> Generator:
        calls["generator"] += 1
        if stage == "generator":
            _raise_with_frame_cycle(failure_type, sentinel_refs)
        return Generator()

    def call_pipeline(_self, **_kwargs):
        calls["pipeline"] += 1
        _raise_with_frame_cycle(failure_type, sentinel_refs)

    def empty_cache() -> None:
        cache_observations.append(all(ref() is None for ref in sentinel_refs))
        assert cache_observations[-1]
        torch.cuda.empty_cache_calls += 1

    pipe.set_ip_adapter_scale = set_scale
    torch.Generator = make_generator
    monkeypatch.setattr(pipe.__class__, "__call__", call_pipeline)
    torch.cuda.empty_cache = empty_cache

    try:
        with pytest.raises(InfrastructureError, match=expected) as raised:
            DiffusersBackend(loaded, lambda _ref: style).generate(request)
        assert tuple(calls.values()) == expected_calls
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert torch.cuda.empty_cache_calls == expected_cache
        assert cache_observations == ([True] if expected_cache else [])
        assert sentinel_refs and all(ref() is None for ref in sentinel_refs)
    finally:
        loaded.close()
        supply.close()
