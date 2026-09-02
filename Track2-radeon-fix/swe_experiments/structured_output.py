"""Provider-neutral structured-output request helpers.

The request bodies mirror current vLLM and its older compatibility API.  The
caller controls the server-side backend; this module only adds per-request
constraints and never assumes that a hosted endpoint supports them.
"""

from __future__ import annotations

from typing import Any, Mapping

from .actions import ACTION_SCHEMA


JSON_MODES = frozenset({"J0", "J1", "J2", "J3", "J4", "J5"})


def structured_output_extra_body(
    mode: str,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the OpenAI-compatible ``extra_body`` for a JSON mode.

    J0/J1/J2 intentionally return no constrained-decoding parameters.  J3/J4
    use the current vLLM API.  J5 targets vLLM versions that still expose the
    legacy LM Format Enforcer fields.
    """
    normalized = mode.upper()
    if normalized not in JSON_MODES:
        raise ValueError(f"unknown JSON mode: {mode!r}")
    if normalized in {"J0", "J1", "J2"}:
        return {}
    schema_value = dict(schema or ACTION_SCHEMA)
    if normalized in {"J3", "J4"}:
        return {"structured_outputs": {"json": schema_value}}
    return {
        "guided_json": schema_value,
        "guided_decoding_backend": "lm-format-enforcer",
    }


def merge_extra_body(
    mode: str,
    schema: Mapping[str, Any] | None = None,
    *,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Combine sampling extensions and structured-output constraints.

    vLLM accepts ``top_k`` and ``structured_outputs`` in ``extra_body``.  A
    single helper prevents the agent from accidentally dropping top-k when it
    switches from native tools to J3 JSON actions.
    """
    body = structured_output_extra_body(mode, schema)
    if top_k is not None:
        body["top_k"] = int(top_k)
    return body


def json_system_instructions(mode: str) -> str:
    """Return concise instructions suitable for a small coding model."""
    if mode.upper() == "J0":
        return "Use the terminal tool when you need to inspect or modify the repository."
    return (
        "Return exactly one JSON action object and no surrounding explanation. "
        "The action must contain action, path, query, command, patch, old_text, new_text, and reason "
        "(use null for unused values). Use command for shell work, patch for a unified diff, "
        "replace for one exact old_text/new_text edit, and finish only after verification."
    )
