"""Strict production adapter for a loader-issued Diffusers pipeline."""

from __future__ import annotations

import gc
from io import BytesIO
import threading
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError, InfrastructureError, _GpuOutOfMemoryError
from specstyle.generation.diffusers_loader import (
    LoadedPipeline,
    _GPU_LEASE,
    _validate_loaded_pipeline,
)
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes


class StyleAssetResolver(Protocol):
    def __call__(self, reference: AssetRef, /) -> bytes: ...


class _CancelBinding:
    __slots__ = ("_lock", "_event", "_bound", "_frozen")

    def __init__(self, event: threading.Event | None, /) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event() if event is None else event
        self._bound = event is not None
        self._frozen = False

    def bind(self, event: threading.Event, /) -> None:
        if type(event) is not threading.Event:
            raise DomainError("invalid cancellation event")
        with self._lock:
            if self._bound or self._frozen:
                raise DomainError("invalid cancellation event")
            if self._event.is_set():
                event.set()
            self._event = event
            self._bound = True

    def cancel(self) -> None:
        with self._lock:
            self._event.set()

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    def is_set(self) -> bool:
        with self._lock:
            return self._event.is_set()


def _contract_failure() -> InfrastructureError:
    return InfrastructureError("generation contract violation")


def _empty_cache(torch: Any) -> None:
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass


def _is_oom(error: Exception, torch: Any) -> bool:
    candidates = (
        getattr(torch, "OutOfMemoryError", None),
        getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None),
    )
    classes = tuple(item for item in candidates if isinstance(item, type))
    return bool(classes) and isinstance(error, classes)


def _execute_pipeline(
    pipeline: Any, params: Any, seed: int, kwargs: dict[str, Any], torch: Any
) -> Any:
    failure: InfrastructureError | DomainError | None = None
    generator = None
    try:
        pipeline.set_ip_adapter_scale(float(params.ip_adapter_scale))
        generator = torch.Generator(device="cuda:0").manual_seed(seed)
        kwargs["generator"] = generator
        return pipeline(**kwargs)
    except DomainError:
        failure = DomainError("generation cancelled")
    except Exception as error:
        failure = (
            _GpuOutOfMemoryError("generation OOM")
            if _is_oom(error, torch)
            else InfrastructureError("generation failed")
        )
    finally:
        kwargs.clear()
        generator = pipeline = None
        gc.collect()
    if type(failure) is DomainError:
        raise failure
    if failure is not None:
        if type(failure) is _GpuOutOfMemoryError:
            _empty_cache(torch)
        raise failure
    raise AssertionError("pipeline execution must return or raise")


def _close_images(images: list[Image.Image | None]) -> None:
    for image in images:
        if image is not None:
            try:
                image.close()
            except Exception:
                pass


def _decode_rgb(content: object, size: tuple[int, int]) -> Image.Image:
    if type(content) is not bytes:
        raise _contract_failure()
    image: Image.Image | None = None
    try:
        image = Image.open(BytesIO(content))
        if (
            image.size != size
            or image.mode != "RGB"
            or getattr(image, "n_frames", 1) != 1
        ):
            raise _contract_failure()
        image.load()
        result = image
        image = None
        return result
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _contract_failure() from exc
    finally:
        _close_images([image])


def _resolved_rgb(
    resolver: StyleAssetResolver, reference: AssetRef, size: tuple[int, int]
) -> Image.Image:
    try:
        content = resolver(reference)
    except Exception as exc:
        raise InfrastructureError("style asset resolution failed") from exc
    if type(content) is not bytes or hash_bytes(content) != reference.sha256:
        raise _contract_failure()
    return _decode_rgb(content, size)


def _encode_result_png(result: object, size: tuple[int, int]) -> bytes:
    images = getattr(result, "images", None)
    owned = (
        [item for item in images if type(item) is Image.Image]
        if type(images) is list
        else []
    )
    try:
        if (
            type(images) is not list
            or len(images) != 1
            or type(images[0]) is not Image.Image
        ):
            raise _contract_failure()
        image = images[0]
        if (
            image.mode != "RGB"
            or image.size != size
            or getattr(image, "n_frames", 1) != 1
        ):
            raise _contract_failure()
        output = BytesIO()
        image.save(output, format="PNG", optimize=False, compress_level=9)
        content = output.getvalue()
        checked = Image.open(BytesIO(content))
        try:
            if checked.mode != "RGB" or checked.size != size or checked.info:
                raise _contract_failure()
        finally:
            checked.close()
        return content
    except (OSError, ValueError) as exc:
        raise _contract_failure() from exc
    finally:
        _close_images(owned)


def _validate_request(loaded: LoadedPipeline, request: object) -> GenerationRequest:
    if type(request) is not GenerationRequest:
        raise DomainError("invalid generation request")
    graph = request.graph
    loaded_graph = loaded._graph
    if (
        request.generation_profile != "production"
        or request.environment_hash != loaded._environment_hash
        or graph.generation_profile != "production"
        or graph.pipeline != "sdxl_base"
        or graph.scheduler != "euler"
        or graph.controlnet.controlnet_type != "canny"
        or graph.runtime.backend != "rocm"
        or graph.runtime.dtype != "float16"
        or (
            graph.runtime.rocm_version,
            graph.runtime.torch_version,
            graph.runtime.diffusers_version,
            graph.runtime.dtype,
        )
        != loaded._runtime
    ):
        raise DomainError("production generation binding mismatch")
    for resolved, descriptor in (
        (graph.base_model, loaded_graph.base),
        (graph.ip_adapter, loaded_graph.ip_adapter),
        (graph.controlnet, loaded_graph.controlnet),
    ):
        if (
            resolved.pin.id != descriptor.model_id
            or resolved.pin.revision != descriptor.revision
            or resolved.pin.sha256 != descriptor.expected_sha256
        ):
            raise DomainError("production model binding mismatch")
    return request


class DiffusersBackend:
    """Only a genuine :class:`LoadedPipeline` can execute production requests."""

    __slots__ = ("_loaded", "_resolver", "_cancelled")

    def __init__(
        self,
        loaded: LoadedPipeline,
        resolver: StyleAssetResolver,
        /,
        *,
        cancel_event: threading.Event | None = None,
    ) -> None:
        try:
            _validate_loaded_pipeline(loaded, require_open=True)
        except DomainError:
            raise DomainError("invalid loaded production pipeline") from None
        if not callable(resolver):
            raise DomainError("invalid style asset resolver")
        if cancel_event is not None and type(cancel_event) is not threading.Event:
            raise DomainError("invalid cancellation event")
        self._loaded = loaded
        self._resolver = resolver
        self._cancelled = _CancelBinding(cancel_event)

    def _bind_cancel_event(self, cancel_event: threading.Event) -> None:
        self._cancelled.bind(cancel_event)

    def cancel(self) -> None:
        self._cancelled.cancel()

    def _callback(self, _pipe: Any, _step: int, _timestep: Any, kwargs: Any) -> Any:
        if self._cancelled.is_set():
            raise DomainError("generation cancelled")
        return kwargs

    def generate(self, request: GenerationRequest) -> GeneratedArtifact:
        self._cancelled.freeze()
        if self._cancelled.is_set():
            raise DomainError("generation cancelled")
        with _GPU_LEASE:
            if self._cancelled.is_set():
                raise DomainError("generation cancelled")
            return self._generate_under_lease(request)

    def _generate_under_lease(self, request: GenerationRequest) -> GeneratedArtifact:
        _validate_loaded_pipeline(self._loaded, require_open=True)
        if self._cancelled.is_set():
            raise DomainError("generation cancelled")
        request = _validate_request(self._loaded, request)
        size = request.graph.resolution
        source = control = None
        styles: list[Image.Image] = []
        try:
            if hash_bytes(request.source.content) != request.source.sha256:
                raise _contract_failure()
            if (
                hash_bytes(request.control_input.image.content)
                != request.control_input.image.sha256
            ):
                raise _contract_failure()
            source = _decode_rgb(request.source.content, size)
            control = _decode_rgb(request.control_input.image.content, size)
            for reference in request.style_references:
                styles.append(_resolved_rgb(self._resolver, reference, size))
            params = request.execution_parameters
            if params is None:
                raise _contract_failure()
            pipe = self._loaded.borrow_pipeline()
            result = _execute_pipeline(
                pipe,
                params,
                request.seed.seed,
                {
                    "prompt": request.prompt.positive,
                    "negative_prompt": request.prompt.negative,
                    "image": source,
                    "control_image": control,
                    "ip_adapter_image": [styles],
                    "strength": params.img2img_strength,
                    "num_inference_steps": request.graph.steps,
                    "guidance_scale": request.graph.guidance_scale,
                    "controlnet_conditioning_scale": params.controlnet_scale,
                    "height": size[1],
                    "width": size[0],
                    "num_images_per_prompt": 1,
                    "output_type": "pil",
                    "return_dict": True,
                    "callback_on_step_end": self._callback,
                    "callback_on_step_end_tensor_inputs": [],
                },
                self._loaded._torch,
            )
            content = _encode_result_png(result, size)
            result = None
        finally:
            _close_images([source, control, *styles])
            source = control = None
            styles.clear()
            gc.collect()
        ref = ArtifactRef(
            ArtifactId(f"artifact-{request.request_hash.value[:64]}"),
            hash_bytes(content),
        )
        return GeneratedArtifact(
            ref, content, request.request_hash, request.generation_fingerprint
        )
