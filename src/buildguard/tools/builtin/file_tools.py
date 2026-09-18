"""Allowlisted inspection image discovery."""

from __future__ import annotations

import logging
from pathlib import Path

from buildguard.security.path_guard import PathGuard
from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ListInspectionImagesInput, ListInspectionImagesOutput

LOGGER = logging.getLogger(__name__)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _looks_like_image(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(8)
        return header.startswith(b"\xff\xd8") if path.suffix.lower() in {".jpg", ".jpeg"} else (
            header == b"\x89PNG\r\n\x1a\n"
        )
    except OSError as exc:
        LOGGER.warning("Cannot read inspection image %s: %s", path, exc)
        return False


def register_file_tools(
    registry: ToolRegistry,
    guard: PathGuard,
    root: Path,
    *,
    max_items: int = 100,
    timeout_seconds: float = 10,
) -> None:
    allowed_root = root.resolve()

    def list_images(raw: object) -> ListInspectionImagesOutput:
        request = ListInspectionImagesInput.model_validate(raw)
        directory = guard.resolve_read(request.directory, root=allowed_root)
        if not directory.is_dir():
            raise ValueError(f"Inspection image directory does not exist: {directory}")
        iterator = directory.rglob("*") if request.recursive else directory.iterdir()
        limit = min(request.max_items or max_items, max_items)
        images: list[Path] = []
        skipped = 0
        for candidate in sorted(iterator):
            if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                resolved = guard.resolve_read(candidate, root=allowed_root)
            except (OSError, PermissionError) as exc:
                LOGGER.warning("Skipping unauthorized inspection image %s: %s", candidate, exc)
                skipped += 1
                continue
            if not _looks_like_image(resolved):
                LOGGER.warning("Skipping damaged inspection image: %s", resolved)
                skipped += 1
                continue
            images.append(resolved.relative_to(allowed_root))
            if len(images) >= limit:
                break
        return ListInspectionImagesOutput(images=images, skipped=skipped)

    registry.register(
        ToolDefinition(
            name="list_inspection_images",
            description="List valid local construction inspection images from an allowed directory.",
            input_schema=ListInspectionImagesInput,
            output_schema=ListInspectionImagesOutput,
            permission="confirm",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="inspection",
            allowed_roots=[allowed_root],
            allowed_extensions=sorted(IMAGE_EXTENSIONS),
            max_items=max_items,
        ),
        list_images,
    )

