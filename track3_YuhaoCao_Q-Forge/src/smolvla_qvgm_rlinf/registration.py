"""RLinf model registration kept separate from model implementation imports."""

from typing import Any


MODEL_TYPE = "smolvla"


def build_smolvla(cfg: Any, torch_dtype):
    from .models.smolvla_rlinf_policy import SmolVLARLinfPolicy

    return SmolVLARLinfPolicy.from_config(cfg, torch_dtype=torch_dtype)


def register_smolvla(*, force: bool = False) -> None:
    from rlinf.config import SupportedModel
    from rlinf.models import register_model

    # register() is intentionally idempotent: driver and workers may import
    # the extension through more than one initialization path.
    if MODEL_TYPE in SupportedModel.models and not force:
        return
    register_model(MODEL_TYPE, build_smolvla, category="embodied", force=force)
