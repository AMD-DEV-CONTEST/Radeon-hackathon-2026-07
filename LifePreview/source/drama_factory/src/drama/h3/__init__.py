"""AMD MiniMax H3 Ref2VA compilation boundaries."""

from .model_registry import H3CapabilityUnavailable, load_h3_amd_capability
from .prompt_renderer import H3PromptRenderer
from .reference_binder import ApprovedH3Asset, bind_h3_references
from .workflows import (
    build_competition_single_reference_comfy_api_workflow,
    build_h3_comfy_api_workflow,
    build_h3_workflow,
)

__all__ = [
    "ApprovedH3Asset",
    "H3CapabilityUnavailable",
    "H3PromptRenderer",
    "bind_h3_references",
    "build_competition_single_reference_comfy_api_workflow",
    "build_h3_comfy_api_workflow",
    "build_h3_workflow",
    "load_h3_amd_capability",
]
