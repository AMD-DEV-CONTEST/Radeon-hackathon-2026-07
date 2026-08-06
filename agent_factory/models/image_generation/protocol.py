from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ImageGenerationOperation = Literal["text_to_image", "image_to_image", "edit"]


@dataclass(frozen=True, slots=True)
class ImageGenerationSettings:
    provider: str
    model: str
    base_url: str
    profile_id: str = ""
    source: str = "model_pool"
    timeout_seconds: float | None = None
    default_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImageInput:
    source: str
    mime_type: str
    data: bytes | None = None
    url: str | None = None
    filename: str = "image.png"
    attachment_id: str | None = None


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    operation: ImageGenerationOperation
    prompt: str
    input_images: tuple[ImageInput, ...] = ()
    size: str | None = None
    aspect_ratio: str | None = None
    count: int = 1
    seed: int | None = None
    negative_prompt: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeneratedImageSource:
    data: bytes
    mime_type: str = "image/png"
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeneratedAsset:
    asset_id: str
    path: str
    relative_path: str
    mime_type: str
    provider: str
    model: str
    prompt: str
    provider_request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_payload(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "path": self.relative_path,
            "relative_path": self.relative_path,
            "mime_type": self.mime_type,
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "provider_request_id": self.provider_request_id,
            "metadata": dict(self.metadata),
        }
