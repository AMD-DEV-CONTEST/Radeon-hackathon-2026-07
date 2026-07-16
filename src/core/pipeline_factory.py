"""Pipeline factory: build concrete model instances by name.

Why a factory: callers ask for "text2image" / "img2img" / "style_transfer"
by key, not by importing the concrete class. This makes swapping
implementations (SDXL -> FLUX) a one-line change in the model module.
"""
from __future__ import annotations

import logging
from typing import Callable, Type

from .base_model import BaseModel

log = logging.getLogger(__name__)

# Populated by concrete model modules via @register_model
_REGISTRY: dict[str, Type[BaseModel]] = {}


def register_model(key: str) -> Callable[[Type[BaseModel]], Type[BaseModel]]:
    """Class decorator: register a `BaseModel` subclass under `key`.

    Usage:
        @register_model("text2image")
        class Text2ImageSDXL(BaseModel):
            ...

    The key becomes `cls.model_key` so the model can introspect itself.
    """

    def deco(cls: Type[BaseModel]) -> Type[BaseModel]:
        if key in _REGISTRY:
            log.warning("overwriting registered model %r -> %s", key, cls.__name__)
        _REGISTRY[key] = cls
        cls.model_key = key  # type: ignore[attr-defined]
        return cls

    return deco


def create_model(key: str, **kwargs) -> BaseModel:
    """Instantiate a registered model by key.

    Raises:
        KeyError: if `key` is not registered, with a helpful message listing
            what's available. The hint usually points to a missing import.
    """
    if key not in _REGISTRY:
        raise KeyError(
            f"Unknown model {key!r}. Registered: {sorted(_REGISTRY)}. "
            "Did you forget to import the model module so the @register_model decorator runs?"
        )
    cls = _REGISTRY[key]
    log.info("creating model %s (%s)", key, cls.__name__)
    return cls(**kwargs)


def available_models() -> list[str]:
    """Return the sorted list of registered model keys (for UI / CLI listings)."""
    return sorted(_REGISTRY)


def load_default_registry() -> None:
    """Import all concrete model modules so their @register_model runs.

    Called once at app startup. Wrapped in a function (not top-level) so
    import side-effects stay explicit and we can avoid circular imports.

    Modules that are not yet implemented (e.g. during D1 bootstrap) are
    silently skipped with a log message — the app stays bootable, just
    without those capabilities. Add the import as the module lands.
    """
    import importlib

    for name in ("text2image", "img2img", "style_transfer"):
        try:
            importlib.import_module(f"src.models.{name}")
            log.info("registered model: %s", name)
        except ImportError as e:
            # Expected during D1 bootstrap; remove this branch once all
            # three modules exist.
            log.info("model %s not yet implemented (skip): %s", name, e)

    log.info("loaded default model registry: %s", available_models())
