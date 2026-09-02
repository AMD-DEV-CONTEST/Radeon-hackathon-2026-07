"""Reusable building blocks for the Track 2 SWE-agent experiments.

The package is intentionally dependency-light.  It can be used with the
existing Hermes runner, an OpenAI-compatible remote endpoint, or a local
vLLM server on an AMD GPU.
"""

from .actions import (
    ACTION_SCHEMA,
    VERIFIER_SCHEMA,
    ActionEnvelope,
    ActionParseError,
    parse_json_object,
    parse_action_envelope,
)
from .structured_output import structured_output_extra_body
from .verifier import CodeVerifier, VerifierReport, rank_verifier_reports

__all__ = [
    "ACTION_SCHEMA",
    "VERIFIER_SCHEMA",
    "ActionEnvelope",
    "ActionParseError",
    "CodeVerifier",
    "VerifierReport",
    "parse_action_envelope",
    "parse_json_object",
    "rank_verifier_reports",
    "structured_output_extra_body",
]
