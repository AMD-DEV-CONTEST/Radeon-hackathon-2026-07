"""Model artifact discovery for local and cloud-produced assets."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Artifact:
    name: str
    kind: str
    path: str
    size_mb: float

    def to_dict(self) -> dict:
        return asdict(self)


class ArtifactStore:
    """Finds model artifacts without forcing heavyweight dependencies."""

    DEFAULT_DIRS = [
        ROOT / "ai_pc_operator" / "data" / "models",
        ROOT / "hackathon_ui_operator_distill" / "data",
        ROOT / "hackathon_ui_operator_distill" / "runs",
    ]

    PATTERNS = {
        "ocr-mobile": (
            "ocr_det*.onnx",
            "ocr_rec*.onnx",
            "paddleocr*.onnx",
            "*.pdmodel",
        ),
        "ui-detector-int8": ("*ui*detector*.onnx", "*int8*.onnx", "best.onnx"),
        "qwen-1.5b-q4": ("*qwen*.gguf", "*1.5b*.gguf", "*.gguf"),
        "vault-crypto": (),
        "browser-warmup": (),
    }

    def __init__(self, extra_dirs: Iterable[Path] | None = None) -> None:
        env_dirs = [
            Path(item)
            for item in os.environ.get("SCREEN_AI_MODEL_DIR", "").split(os.pathsep)
            if item
        ]
        dirs = [*env_dirs, *(extra_dirs or []), *self.DEFAULT_DIRS]
        self.search_dirs = list(dict.fromkeys(path.resolve() for path in dirs))

    def find(self, name: str) -> Artifact | None:
        """Return the best artifact for a registered model name."""
        candidates = self.find_all(name)
        if not candidates:
            return None

        # Prefer explicit INT8/quantized artifacts, then newest file.
        candidates.sort(
            key=lambda path: (
                "int8" in path.name.lower() or "q4" in path.name.lower(),
                path.stat().st_mtime,
            ),
            reverse=True,
        )
        path = candidates[0]
        return self._artifact(name, path)

    def find_all(self, name: str) -> list[Path]:
        """Return every artifact path matching a registered model name."""
        patterns = self.PATTERNS.get(name, ())
        candidates: list[Path] = []
        for root in self.search_dirs:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.extend(path for path in root.rglob(pattern) if path.is_file())

        return list(dict.fromkeys(candidates))

    def _artifact(self, name: str, path: Path) -> Artifact:
        return Artifact(
            name=name,
            kind=path.suffix.lower().lstrip("."),
            path=str(path),
            size_mb=round(path.stat().st_size / (1024**2), 2),
        )

    def inventory(self) -> dict[str, dict | None]:
        """Return discovery status for every known model slot."""
        return {
            name: artifact.to_dict() if artifact else None
            for name in self.PATTERNS
            for artifact in [self.find(name)]
        }
