"""
Tests for scripts/hive/executor.py's builder health-check response parser.

Regression coverage for the bug found live 2026-07-02 during a corpus-
center audit: the health preflight required an EXACT match on "ok", which
the production DSL-fine-tuned Builder (determinex-engineer-v11-dsl) failed
100% of 3 independent live calls -- its fine-tuning trained it to always
wrap even a trivial reply in structured formatting. The three response
strings below are the exact, real, unmodified responses captured live
from `ollama/determinex-engineer-v11-dsl` -- not synthesized examples.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hive.executor import _is_healthy_builder_response

# The exact, real responses captured live 2026-07-02 (see commit message).
REAL_RESPONSE_1 = (
    "### Assistant\nok\n\n### Code:\n\n```python\ndef health_check():\n"
    '    return "ok"\n```\n\n\n### Validation:\n\n```sh\necho $(python3 -c '
    "'import sys; print(sys.version_info.major >= 3 and sys.version_info.minor >= 8"
)
REAL_RESPONSE_2 = (
    "### Assistant\nok\n\n### Code:\n\n```python\ndef health_check():\n"
    '    return "ok"\n```\n\n\n### Validation:\n\n```sh\necho $(python3 -c '
    "'import sys; print(sys.version_info.major == 3 and sys.version_info.minor >= 8"
)
REAL_RESPONSE_3 = (
    "### Created Question:\nWhat is the status of a Python package "
    "installation? How can you determine if it's installed successfully?"
    "\n\n### Created Answer:\nok"
)


def test_real_captured_dsl_responses_all_pass():
    """The whole point of the fix: these 3 real responses, which all
    failed the old exact-match check 3/3, must now pass."""
    assert _is_healthy_builder_response(REAL_RESPONSE_1) is True
    assert _is_healthy_builder_response(REAL_RESPONSE_2) is True
    assert _is_healthy_builder_response(REAL_RESPONSE_3) is True


def test_bare_ok_still_passes():
    assert _is_healthy_builder_response("ok") is True
    assert _is_healthy_builder_response("OK") is True
    assert _is_healthy_builder_response("  ok  ") is True


def test_empty_response_fails():
    assert _is_healthy_builder_response("") is False
    assert _is_healthy_builder_response(None) is False


def test_garbage_without_ok_token_fails():
    assert _is_healthy_builder_response("I don't understand the request.") is False
    assert _is_healthy_builder_response("Error: connection refused") is False


def test_word_boundary_prevents_false_positive_substring_match():
    """'ok' must be a standalone token -- 'broken'/'book'/'smoke' must not
    count, or a genuinely broken model's error message could accidentally
    pass health just by containing one of these words."""
    assert _is_healthy_builder_response("the model is broken and smoking") is False
    assert _is_healthy_builder_response("I am reading a book") is False


def test_runaway_length_response_fails_even_with_ok_token():
    """A wildly long response (even one containing 'ok' somewhere)
    suggests the model is looping/rambling, not healthy."""
    huge = ("some text " * 300) + " ok"  # well over 2000 chars
    assert len(huge) > 2000
    assert _is_healthy_builder_response(huge) is False


def test_reasonably_sized_response_with_ok_at_the_end_passes():
    text = "Sure, here is my response to your health check request. ok"
    assert len(text) < 2000
    assert _is_healthy_builder_response(text) is True
