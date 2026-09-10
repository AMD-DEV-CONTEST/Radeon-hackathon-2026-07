"""Strict backend for a loader-issued LCM Preview pipeline."""

from __future__ import annotations

import gc
import threading
from typing import Any

from PIL import Image

from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.diffusers_backend import (
    StyleAssetResolver,
    _CancelBinding,
    _close_images,
    _contract_failure,
    _decode_rgb,
    _encode_result_png,
    _execute_pipeline,
    _resolved_rgb,
)
from specstyle.generation.diffusers_loader import _GPU_LEASE
from specstyle.generation.preview_diffusers_loader import (
    LoadedPreviewPipeline,
    _PreviewPipelineIntegrityError,
    _poison_loaded_preview_pipeline,
    _validate_loaded_preview_pipeline,
)
from specstyle.generation.preview_execution import (
    PreviewGeneratedArtifact,
    _validate_preview_request,
    bind_preview_execution,
    build_preview_artifact,
)
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes


class _PreviewRuntimeIntegrityError(InfrastructureError):
    pass


def _raise_runtime_integrity_failure(
    loaded: object, error: BaseException | None = None
) -> None:
    try:
        _poison_loaded_preview_pipeline(loaded)
    except DomainError:
        pass
    failure = _PreviewRuntimeIntegrityError("preview runtime integrity failed")
    if error is None:
        raise failure
    raise failure from error


def _verify_runtime_integrity(loaded: object) -> None:
    try:
        _validate_loaded_preview_pipeline(loaded, require_open=True)
    except Exception as exc:
        _raise_runtime_integrity_failure(loaded, exc)


class PreviewDiffusersBackend:
    """Execute only the strict LCM Preview contract and return Preview artifacts."""

    __slots__ = ("_loaded", "_resolver", "_cancelled")

    def __init__(
        self,
        loaded: LoadedPreviewPipeline,
        resolver: StyleAssetResolver,
        /,
        *,
        cancel_event: threading.Event | None = None,
    ) -> None:
        try:
            _validate_loaded_preview_pipeline(loaded, require_open=True)
        except Exception as exc:
            _raise_runtime_integrity_failure(loaded, exc)
        if not callable(resolver):
            raise DomainError("invalid preview style asset resolver")
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

    def generate(self, request: GenerationRequest) -> PreviewGeneratedArtifact:
        self._cancelled.freeze()
        if self._cancelled.is_set():
            raise DomainError("generation cancelled")
        with _GPU_LEASE:
            if self._cancelled.is_set():
                raise DomainError("generation cancelled")
            return self._generate_under_lease(request)

    def _generate_under_lease(
        self, request: GenerationRequest
    ) -> PreviewGeneratedArtifact:
        _verify_runtime_integrity(self._loaded)
        try:
            request = _validate_preview_request(self._loaded, request)
            binding = bind_preview_execution(self._loaded, request)
        except _PreviewPipelineIntegrityError as exc:
            _raise_runtime_integrity_failure(self._loaded, exc)
        try:
            content = self._generate_content(request)
        finally:
            _verify_runtime_integrity(self._loaded)
        return build_preview_artifact(content, binding)

    def _generate_content(self, request: GenerationRequest) -> bytes:
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
            return self._invoke_pipeline(request, source, control, styles)
        finally:
            _close_images([source, control, *styles])
            source = control = None
            styles.clear()
            gc.collect()

    def _invoke_pipeline(
        self,
        request: GenerationRequest,
        source: Image.Image,
        control: Image.Image,
        styles: list[Image.Image],
    ) -> bytes:
        params = request.execution_parameters
        if params is None:
            raise _contract_failure()
        result = _execute_pipeline(
            self._loaded._borrow_pipeline(),
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
                "height": request.graph.resolution[1],
                "width": request.graph.resolution[0],
                "num_images_per_prompt": 1,
                "output_type": "pil",
                "return_dict": True,
                "callback_on_step_end": self._callback,
                "callback_on_step_end_tensor_inputs": [],
            },
            self._loaded._torch,
        )
        return _encode_result_png(result, request.graph.resolution)
