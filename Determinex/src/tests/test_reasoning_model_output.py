"""Reasoning models must not be mistaken for models that produced nothing.

`_openai_compatible_factory` ended with `return resp.choices[0].message.content or ""`, so a
model whose answer lives somewhere other than `content` produced a silent empty generation
and the caller recorded a MODEL failure for a HARNESS defect. Measured live 2026-08-02
against AMD's Radeon Token Factory:

  Qwen3.6-35B-A3B   content=null, answer in a separate `reasoning` field, and the completion
                    budget goes to thinking: 199/200 reasoning tokens at max_tokens=200, and
                    1110/1200 at max_tokens=1200 -- more budget buys more thinking, not an
                    answer.
  MiniCPM5-1B       `<think> ... </think>` INLINE at the head of content.

These tests pin the three behaviours that matter, including the one that is easy to get
wrong in the other direction: stripping must never eat part of a real answer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from determinex_providers import _strip_reasoning_tags  # noqa: E402


class TestInlineThinkBlocks:
    def test_a_closed_leading_block_is_removed(self):
        out = _strip_reasoning_tags("<think>weighing options</think>\ndef f():\n    pass\n")
        assert out.strip().startswith("def f()")
        assert "weighing options" not in out

    @pytest.mark.parametrize("tag", ["think", "thinking", "reasoning", "THINK"])
    def test_the_known_tag_spellings_are_all_handled(self, tag):
        out = _strip_reasoning_tags(f"<{tag}>x</{tag}>\ncode_here")
        assert out.strip() == "code_here"

    def test_ordinary_output_is_returned_untouched(self):
        src = "def g():\n    return 1\n"
        assert _strip_reasoning_tags(src) == src

    def test_the_word_think_in_prose_is_not_a_tag(self):
        """NEGATIVE CONTROL. An over-eager stripper would silently delete a real answer."""
        src = "I think this handles the empty case:\ndef h(): pass"
        assert _strip_reasoning_tags(src) == src

    def test_an_unterminated_block_is_left_alone(self):
        """A truncated completion is evidence, not garbage. Deleting from an opening tag to
        the end of the string would discard whatever the model did manage to produce."""
        src = "<think>cut off mid-thought and never closed"
        assert _strip_reasoning_tags(src) == src

    def test_stripping_never_returns_nothing(self):
        """If the block was the ENTIRE response, return it rather than an empty string --
        an empty return is the exact claim ('the model said nothing') this module exists to
        stop making falsely."""
        src = "<think>all of it was reasoning</think>"
        assert _strip_reasoning_tags(src) == src

    def test_only_the_leading_block_is_touched(self):
        """A later occurrence is content, not preamble."""
        src = "def f():\n    # <think>not a real tag here</think>\n    pass"
        assert _strip_reasoning_tags(src) == src


def test_factory_requests_content_rather_than_thinking():
    """The request must ask the endpoint to stop reasoning. Without
    chat_template_kwargs.enable_thinking=false, Qwen3.6 returned nothing at any budget."""
    src = (_SCRIPTS / "determinex_providers.py").read_text(encoding="utf-8")
    assert "enable_thinking" in src
    assert "chat_template_kwargs" in src
    # Sent through extra_body: it is a vLLM extension, not an OpenAI parameter.
    assert "extra_body" in src


def test_empty_content_with_spent_reasoning_raises_instead_of_returning_empty():
    """The whole point. Returning '' asserts the model had nothing to say; when the budget
    went to reasoning that assertion is false, and it is the kind of false verdict this
    project exists to refuse."""
    src = (_SCRIPTS / "determinex_providers.py").read_text(encoding="utf-8")
    factory = src.split("def _openai_compatible_factory", 1)[1].split("\ndef ", 1)[0]
    assert "raise RuntimeError" in factory, "must not silently return empty for a reasoning model"
    assert "reasoning" in factory
    assert 'return resp.choices[0].message.content or ""' not in factory, (
        "the original silent-empty return is back"
    )
