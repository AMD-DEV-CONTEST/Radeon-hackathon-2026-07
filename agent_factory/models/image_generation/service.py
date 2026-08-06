from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.artifact_system import ArtifactStore
from agent_factory.models.image_generation.adapters import adapter_for_image_provider
from agent_factory.models.image_generation.protocol import (
    GeneratedAsset,
    ImageGenerationRequest,
    ImageGenerationSettings,
    ImageInput,
)

GENERATED_IMAGE_DIR = "images"


class ImageGenerationService:
    def __init__(self, *, settings: ImageGenerationSettings, artifact_store: ArtifactStore) -> None:
        self.settings = settings
        self.artifact_store = artifact_store
        self.adapter = adapter_for_image_provider(settings)

    def generate(
        self,
        request: ImageGenerationRequest,
        *,
        artifact_store: ArtifactStore | None = None,
    ) -> list[GeneratedAsset]:
        target_store = artifact_store or self.artifact_store
        assets: list[GeneratedAsset] = []
        for index, source in enumerate(self.adapter.generate(request), start=1):
            mime_type = source.mime_type or "image/png"
            suffix = mimetypes.guess_extension(mime_type) or ".png"
            relative_path = f"{GENERATED_IMAGE_DIR}/{uuid4().hex}_{index}{suffix}"
            record = target_store.write_bytes(
                kind="artifact",
                relative_path=relative_path,
                content=source.data,
                metadata={
                    "artifact_type": "generated_image",
                    "provider": self.settings.provider,
                    "model": self.settings.model,
                    "profile_id": self.settings.profile_id,
                    "prompt": request.prompt,
                    "operation": request.operation,
                    "provider_metadata": dict(source.provider_metadata),
                },
            )
            assets.append(
                GeneratedAsset(
                    asset_id=str(record["artifact_id"]),
                    path=str(record["path"]),
                    relative_path=str(record["relative_path"]),
                    mime_type=mime_type,
                    provider=self.settings.provider,
                    model=self.settings.model,
                    prompt=request.prompt,
                    provider_request_id=_metadata_text(source.provider_metadata, "id", "request_id"),
                    metadata=dict(source.provider_metadata),
                )
            )
        return assets


def image_input_from_path(path: str | Path, *, attachment_id: str | None = None) -> ImageInput:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"image input file does not exist: {path}")
    mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise ValueError(f"image input is not an image: {path}")
    return ImageInput(
        source=str(target),
        mime_type=mime_type,
        data=target.read_bytes(),
        filename=target.name,
        attachment_id=attachment_id,
    )


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
