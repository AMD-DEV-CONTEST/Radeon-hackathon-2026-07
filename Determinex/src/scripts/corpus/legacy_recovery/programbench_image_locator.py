from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ImageLocation:
    image: str
    available: bool
    reason: str = ""


class ProgramBenchImageLocator:
    """Resolve task image identity without pulling or building images."""

    def __init__(
        self, image_roots: list[Path] | None = None, *, require_image: bool = True
    ) -> None:
        self.image_roots = [Path(root) for root in image_roots or []]
        self.require_image = require_image

    def locate(self, candidate: dict[str, Any], task_root: Path | None = None) -> ImageLocation:
        image = str(
            candidate.get("task_image")
            or candidate.get("docker_image")
            or candidate.get("image")
            or _image_from_tool(str(candidate.get("tool") or ""))
        )
        if not self.require_image:
            return ImageLocation(image=image, available=True, reason="image_check_disabled")
        if task_root and (task_root / "Dockerfile").is_file():
            return ImageLocation(image=image, available=True, reason="dockerfile_present")
        for root in self.image_roots:
            if not root.exists():
                continue
            for suffix in (".tar", ".json", ".txt"):
                if (root / f"{_safe_image_name(image)}{suffix}").is_file():
                    return ImageLocation(
                        image=image, available=True, reason="local_image_artifact_present"
                    )
        return ImageLocation(image=image, available=False, reason="missing_docker_image")


def _image_from_tool(tool: str) -> str:
    return f"programbench/{tool.replace('__', '_')}:latest" if tool else ""


def _safe_image_name(image: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in image)[:180]
