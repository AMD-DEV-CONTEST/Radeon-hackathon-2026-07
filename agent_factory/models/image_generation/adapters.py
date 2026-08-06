from __future__ import annotations

import base64
import json
from typing import Any, Protocol

import httpx

from agent_factory.local_inference.config import LocalInferenceEndpoint
from agent_factory.local_inference.http_client import create_private_http_client
from agent_factory.models.image_generation.protocol import (
    GeneratedImageSource,
    ImageGenerationRequest,
    ImageGenerationSettings,
)


class ImageGenerationAdapter(Protocol):
    def generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]: ...


class ImageGenerationAdapterError(RuntimeError):
    pass


class StableDiffusionCppImageAdapter:
    """OpenAI-compatible stable-diffusion.cpp sd-server adapter."""

    def __init__(self, settings: ImageGenerationSettings) -> None:
        self.settings = settings

    def generate(self, request: ImageGenerationRequest) -> list[GeneratedImageSource]:
        if request.operation != "text_to_image":
            raise ImageGenerationAdapterError("the configured FLUX.1-dev profile only supports text_to_image")
        options = {**self.settings.default_options, **request.provider_options}
        native = {
            "negative_prompt": request.negative_prompt or "",
            "seed": request.seed if request.seed is not None else -1,
            "sample_params": {
                "sample_steps": options.pop("steps", 20),
                "sample_method": options.pop("sampler", "euler"),
                "guidance": {"txt_cfg": options.pop("cfg_scale", 1.0)},
            },
            **options,
        }
        prompt = f"{request.prompt} <sd_cpp_extra_args>{json.dumps(native, separators=(',', ':'))}</sd_cpp_extra_args>"
        default_size = f"{self.settings.default_options.get('width', 768)}x{self.settings.default_options.get('height', 768)}"
        payload = {
            "prompt": prompt,
            "n": request.count,
            "size": request.size or default_size,
            "output_format": "png",
        }
        endpoint = f"{self.settings.base_url.rstrip('/')}/images/generations"
        timeout_seconds = float(self.settings.timeout_seconds or 900.0)
        try:
            private_endpoint = LocalInferenceEndpoint(
                base_url=self.settings.base_url,
                timeout_seconds=timeout_seconds,
            )
            with create_private_http_client(private_endpoint) as client:
                response = client.post(endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _response_error_detail(exc.response)
            suffix = f": {detail}" if detail else ""
            raise ImageGenerationAdapterError(
                f"stable-diffusion.cpp request failed with HTTP {exc.response.status_code}{suffix}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ImageGenerationAdapterError(f"stable-diffusion.cpp request failed: {exc}") from exc
        return _parse_openai_images(body)


def adapter_for_image_provider(settings: ImageGenerationSettings) -> ImageGenerationAdapter:
    if settings.provider.strip().lower() == "stable_diffusion_cpp":
        return StableDiffusionCppImageAdapter(settings)
    raise ImageGenerationAdapterError(f"unsupported image generation provider: {settings.provider}")


def _response_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return response.text.strip()
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or "").strip()
    return str(payload.get("detail") or payload.get("message") or "").strip()


def _parse_openai_images(body: Any) -> list[GeneratedImageSource]:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ImageGenerationAdapterError("stable-diffusion.cpp response does not contain image data")
    result: list[GeneratedImageSource] = []
    for item in body["data"]:
        if not isinstance(item, dict):
            continue
        encoded = item.get("b64_json")
        if isinstance(encoded, str) and encoded.strip():
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ImageGenerationAdapterError("stable-diffusion.cpp returned invalid base64 image data") from exc
            result.append(
                GeneratedImageSource(
                    data=data,
                    provider_metadata={key: value for key, value in item.items() if key != "b64_json"},
                )
            )
    if not result:
        raise ImageGenerationAdapterError("stable-diffusion.cpp response contained no generated images")
    return result
