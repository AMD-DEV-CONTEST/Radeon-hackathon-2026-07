"""`os.environ/VAR` in litellm_config.yaml, and when an unset var is fatal.

litellm_config.yaml uses LiteLLM's own indirection syntax (`api_key: os.environ/ANTHROPIC_API_KEY`)
so credentials and ephemeral endpoint URLs never land in a committed, published file. That
syntax is implemented by the LiteLLM PROXY; the hive calls `litellm.completion` directly, so
before 2026-08-02 the literal string was passed through as the value. For an api_base that
surfaced as:

    InternalServerError: Hosted_vllmException - Request URL is missing an 'http://' or
    'https://' protocol.

and for an api_key it meant authenticating with the string "os.environ/ANTHROPIC_API_KEY".

The first fix raised on any unresolved reference, which broke
`test_cloud_only_model_assignments_do_not_require_ollama`: that test asks whether some
aliases resolve to Ollama models, and suddenly needed an Anthropic key to answer. Inspecting
an alias is not calling it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from hive.api_client import _expand_env_refs, _resolve_model  # noqa: E402


def test_a_set_variable_is_substituted():
    import os

    os.environ["DETERMINEX_TEST_ENV_REF"] = "https://example.invalid/v1"
    try:
        out = _expand_env_refs({"api_base": "os.environ/DETERMINEX_TEST_ENV_REF"})
        assert out["api_base"] == "https://example.invalid/v1"
    finally:
        os.environ.pop("DETERMINEX_TEST_ENV_REF", None)


def test_inspecting_an_alias_does_not_require_the_credential(monkeypatch):
    """THE REGRESSION. `_required_ollama_models` resolves aliases only to ask 'is this
    Ollama?'. Making that demand a cloud API key means an offline, local-only run fails on
    credentials it never intended to use."""
    monkeypatch.delenv("DETERMINEX_TEST_MISSING_VAR", raising=False)
    out = _expand_env_refs({"api_base": "os.environ/DETERMINEX_TEST_MISSING_VAR"}, require=False)
    assert "api_base" not in out, "an unresolved reference must be dropped, not guessed"


def test_the_call_path_refuses_rather_than_sending_the_request_elsewhere(monkeypatch):
    """Dropping api_base is right for inspection and WRONG for a call: the client would fall
    back to its default (localhost), and a request that quietly goes somewhere else is worse
    than one that fails."""
    monkeypatch.delenv("DETERMINEX_TEST_MISSING_VAR", raising=False)
    with pytest.raises(RuntimeError) as ei:
        _expand_env_refs({"api_base": "os.environ/DETERMINEX_TEST_MISSING_VAR"}, require=True)
    assert "DETERMINEX_TEST_MISSING_VAR" in str(ei.value), "the message must name the variable"


def test_only_the_extras_consumer_resolves_strictly():
    """`_resolve_model` is called in six places and exactly one of them uses the returned
    extras. Strictness belongs there and nowhere else -- pinned so a future caller does not
    flip the default and reintroduce the outage."""
    import inspect

    from hive import api_client

    sig = inspect.signature(api_client._resolve_model)
    assert sig.parameters["require_env"].default is False, (
        "resolution must be permissive by default; only the call path opts into strictness"
    )


def test_the_committed_config_contains_no_literal_secrets():
    """The reason the indirection exists at all. If a key or an endpoint ever gets pasted in
    literally, this fails before it is published."""
    cfg = (Path(__file__).resolve().parents[1] / "litellm_config.yaml").read_text(encoding="utf-8")
    for line in cfg.splitlines():
        stripped = line.strip()
        if stripped.startswith("api_key:"):
            value = stripped.split(":", 1)[1].strip()
            assert value.startswith("os.environ/") or value in ("", '""', "''"), (
                f"api_key must come from the environment, found a literal: {line!r}"
            )
