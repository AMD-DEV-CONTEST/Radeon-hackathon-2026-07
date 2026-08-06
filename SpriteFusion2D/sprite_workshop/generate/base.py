"""Small provider contract: the project layer never speaks ComfyUI JSON."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    models: tuple[str, ...]
    styles: tuple[str, ...] = ("pixel",)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    prompt: str
    negative: str = ""
    model: str = "default"
    style: str = "pixel"
    count: int = 4
    size: int = 512
    steps: int = 20
    cfg: float = 7.0
    seed: int = 42


@dataclass(frozen=True, slots=True)
class GeneratedCandidate:
    id: str
    seed: int
    path: Path


class GenerationProvider(Protocol):
    def probe(self) -> ProviderInfo: ...

    def generate(
        self,
        request: GenerationRequest,
        output_dir: Path,
        progress: Callable[[str, int, int], None],
        cancelled: Callable[[], bool],
    ) -> tuple[GeneratedCandidate, ...]: ...

    def interrupt(self) -> None: ...
