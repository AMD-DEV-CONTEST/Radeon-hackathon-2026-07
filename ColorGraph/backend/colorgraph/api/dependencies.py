from __future__ import annotations

from functools import lru_cache

from colorgraph.agent import LocalSceneAnalyzer
from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.storage import ProjectStore
from colorgraph.vision import DepthMaskProvider, SemanticMaskProvider, VideoMaskGenerator


@lru_cache(maxsize=1)
def compute_backend() -> TorchComputeBackend:
    return TorchComputeBackend(settings.device_preference)


@lru_cache(maxsize=1)
def project_store() -> ProjectStore:
    return ProjectStore()


@lru_cache(maxsize=1)
def scene_analyzer() -> LocalSceneAnalyzer:
    return LocalSceneAnalyzer(compute_backend())


@lru_cache(maxsize=1)
def video_mask_generator() -> VideoMaskGenerator:
    backend = compute_backend()
    return VideoMaskGenerator(
        SemanticMaskProvider(backend),
        DepthMaskProvider(backend),
    )
