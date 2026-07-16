"""Abstract base class for all generation models (Strategy pattern).

Every concrete model (text2image / img2img / style_transfer) inherits from
`BaseModel` and implements `load()`, `generate()`, and optionally `unload()`.

Why a base class: we want a single, typed, version-controlled contract for
"what a model is and how to talk to it". New params (seed, batch_size, ...)
get added to `GenerationRequest`, not scattered across call sites.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

log = logging.getLogger(__name__)


@dataclass
class GenerationRequest:
    """Input contract for every model.generate() call.

    Keep this generic. Model-specific knobs go in `extra` so we don't bloat
    the base contract with SDXL-only or IP-Adapter-only fields.
    """

    prompt: str
    negative_prompt: str = ""
    height: int = 1024
    width: int = 1024
    num_inference_steps: int = 30
    guidance_scale: float = 7.5
    seed: int | None = None

    # Image inputs (None for text-only models)
    init_image: Image.Image | None = None
    style_image: Image.Image | None = None
    mask_image: Image.Image | None = None

    # Catch-all for model-specific overrides; preferred over adding new fields
    # every time SDXL or IP-Adapter needs a new knob.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    """Output contract: list of PIL images + minimal metadata for logging."""

    images: list[Image.Image]
    seed: int
    duration_seconds: float
    model_id: str
    extra: dict[str, Any] = field(default_factory=dict)


class BaseModel(abc.ABC):
    """Strategy interface for all generation models.

    Lifecycle:
        instance = MyModel(model_id=...)   # cheap, no I/O
        instance.load()                    # load weights, idempotent
        instance.generate(request)         # many times
        instance.unload()                  # free GPU memory

    Subclasses MUST be cheap to instantiate — no model load in __init__.
    """

    def __init__(self, model_id: str, device: str = "cuda", dtype: str = "float16") -> None:
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self._loaded = False

    @abc.abstractmethod
    def load(self) -> None:
        """Load model weights into memory. Must be idempotent (safe to call twice)."""
        ...

    @abc.abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Run inference. Caller MUST have called load() first."""
        ...

    def unload(self) -> None:
        """Free GPU memory. Default impl drops the `pipe` attribute if present."""
        if hasattr(self, "pipe") and getattr(self, "pipe", None) is not None:
            del self.pipe
        self._loaded = False
        try:
            import torch
            if self.device.startswith("cuda"):
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            # OK if torch is not installed; we'll just leak the cache pointer.
            log.debug("torch.cuda.empty_cache() skipped (torch not available).")

    @property
    def is_loaded(self) -> bool:
        return self._loaded
