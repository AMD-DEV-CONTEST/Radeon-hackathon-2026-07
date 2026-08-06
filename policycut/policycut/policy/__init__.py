"""Policy module: natural-language redaction policy -> PolicySpec.

parse_policy() tries the Qwen LLM (lazy-loaded) and falls back to the
deterministic keyword parser; parse_keyword_policy() is the pure-python
fallback usable without any ML dependencies.
"""

from .schema import (
    DEFAULT_PROMPTS,
    AudioAction,
    AudioActionType,
    AudioCategory,
    AudioTarget,
    PolicySpec,
    VisualAction,
    VisualActionType,
    VisualCategory,
    VisualTarget,
)
from .keyword_parser import parse_keyword_policy
from .parser import parse_policy, unload_llm

__all__ = [
    "DEFAULT_PROMPTS",
    "AudioAction",
    "AudioActionType",
    "AudioCategory",
    "AudioTarget",
    "PolicySpec",
    "VisualAction",
    "VisualActionType",
    "VisualCategory",
    "VisualTarget",
    "parse_keyword_policy",
    "parse_policy",
    "unload_llm",
]
