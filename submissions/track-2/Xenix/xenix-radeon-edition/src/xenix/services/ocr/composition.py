"""Spawn-safe ordinary OCR provider construction.

This module is intentionally complete without importing the AMD deployment package. A
managed parent may hand a KServe spec to the child, but the child never resolves
manager state or imports a deployment adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...config import AppPaths
from .contracts import OcrAttempt, OcrAttemptFactory, OcrSpawnSpec


@dataclass(slots=True)
class _StaticOcrAttempt(OcrAttempt):
    _spawn_spec: OcrSpawnSpec
    _closed: bool = False

    @property
    def spawn_spec(self) -> OcrSpawnSpec:
        return self._spawn_spec

    def close(self) -> None:
        self._closed = True


class LocalPaddleOcrAttemptFactory(OcrAttemptFactory):
    """Default ordinary OCR selection with no deployment-manager dependency."""

    def prepare(self) -> OcrAttempt:
        return _StaticOcrAttempt(OcrSpawnSpec(kind="paddle"))


def build_ocr_service_from_spawn_spec(paths: AppPaths, spawn_spec: OcrSpawnSpec):
    if spawn_spec.kind == "paddle":
        from ..paddle_ocr_service import PaddleOcrDeploymentService, PaddleOcrService

        return PaddleOcrService(PaddleOcrDeploymentService(paths))
    if spawn_spec.kind == "kserve_v2":
        from .kserve_v2 import KServeV2OcrService

        return KServeV2OcrService.from_spawn_spec(spawn_spec)
    raise ValueError("OCR spawn provider is unsupported.")


__all__ = [
    "LocalPaddleOcrAttemptFactory",
    "build_ocr_service_from_spawn_spec",
]
