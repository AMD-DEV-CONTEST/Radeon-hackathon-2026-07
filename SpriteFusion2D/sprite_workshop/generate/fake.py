"""Dependency-free provider used by contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from ..errors import CancelledError
from ..image_io import save_rgba
from ..model import RgbaImage
from .base import GeneratedCandidate, GenerationRequest, ProviderInfo


class FakeProvider:
    def probe(self) -> ProviderInfo:
        return ProviderInfo("Fake", ("fake-model",))

    def generate(
        self,
        request: GenerationRequest,
        output_dir: Path,
        progress: Callable[[str, int, int], None],
        cancelled: Callable[[], bool],
    ) -> tuple[GeneratedCandidate, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates = []
        for index in range(request.count):
            if cancelled():
                raise CancelledError("job cancelled")
            rgba = np.zeros((32, 32, 4), dtype=np.uint8)
            rgba[4:28, 8 + index % 4 : 24 + index % 4] = (
                40 + index * 20,
                120,
                220,
                255,
            )
            path = output_dir / f"candidate-{index + 1}.png"
            save_rgba(RgbaImage(rgba), path)
            candidates.append(
                GeneratedCandidate(f"candidate-{index + 1}", request.seed + index, path)
            )
            progress("generating", index + 1, request.count)
        return tuple(candidates)

    def interrupt(self) -> None:
        return None
