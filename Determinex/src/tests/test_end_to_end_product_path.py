"""Does the SHIPPED path work -- prompt in, an answer about THAT prompt out.

WHY THIS FILE EXISTS
--------------------
On 2026-08-01 the full suite ran 5,589 tests green while the local provider lane silently
discarded ~90% of every prompt over 2,048 tokens and the model answered from the surviving
tail. Nineteen test files touch the provider layer; three made a real call, and all three
checked registry, pricing and locality -- properties of the wiring, not of the product.
Nothing sent a realistically-sized prompt and asked whether the reply was about it.

That is the shape of the gap: the suite tested the parts, and every part was fine. The
failure lived in the composition, which nothing exercised.

WHAT IT ASSERTS
---------------
One property, chosen because it is the one that breaks first and breaks silently:
**the model must answer the prompt that was actually sent.** A truncated, clipped, or
mangled prompt produces a fluent, plausible, wrong answer -- never an error -- so the only
reliable detector is a marker the model cannot produce unless it received the whole thing.

SIZE MATTERS AND IS EASY TO GET WRONG. Repetitive filler tokenises at ~6.7 chars/token
where real code runs ~4.4, so a padded prompt of the same character length fits where real
source would not. These prompts are built from this repository's own source.

HONEST SKIPPING. With no local model this cannot run, and it says so rather than passing
vacuously -- a green tick for a check that never executed is the thing this file exists to
prevent. Model quality is irrelevant here: the assertion is that plumbing preserves a
prompt, so the smallest available model is the right one.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

OLLAMA = "http://127.0.0.1:11434"
# Small on purpose: this measures the harness, not the model.
PREFERRED = (
    "qwen2.5-coder:1.5b-instruct",
    "determinex-engineer-v11-dsl:latest",
    "qwen2.5-coder:7b-instruct",
)


def _available_model() -> str | None:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            tags = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return None
    for want in PREFERRED:
        if want in tags:
            return want
    return tags[0] if tags else None


MODEL = _available_model()
needs_model = pytest.mark.skipif(
    MODEL is None,
    reason="no local Ollama model reachable; the end-to-end product path CANNOT be verified "
    "here and is being skipped rather than assumed",
)


def _real_source(min_chars: int) -> str:
    """Real code, because that is what a real prompt carries and it tokenises densely."""
    out, total = [], 0
    for path in sorted((REPO / "scripts").glob("determinex_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        out.append(text)
        total += len(text)
        if total >= min_chars:
            break
    return "\n".join(out)[:min_chars]


@needs_model
def test_a_repair_sized_prompt_reaches_the_model_intact():
    """The regression. 25,048 chars of real source with the instruction on line 1: before
    the num_ctx fix the model returned 'TASK-12345', invented, having never seen the task."""
    import determinex_providers as P

    marker = "QX-9931-END-TO-END"
    prompt = (
        f"TASK-ID {marker}: after reading the code below, reply with ONLY the TASK-ID.\n"
        + _real_source(25_000)
        + "\nReply with ONLY the TASK-ID given on the first line."
    )
    answer = P._litellm_generator(f"ollama/{MODEL}")(prompt, 0.0)
    assert marker in answer, (
        f"the model answered {answer.strip()[:60]!r} for a prompt whose task line it "
        f"evidently never saw. The prompt was clipped somewhere between here and the "
        f"model, and nothing raised."
    )


@needs_model
def test_a_prompt_far_past_the_context_window_raises_instead_of_fabricating():
    """The other half. When the prompt genuinely cannot fit, the correct outcome is a loud
    failure -- not a confident answer about whatever survived."""
    import determinex_providers as P

    prompt = (
        "TASK-ID QX-0001: reply with ONLY the TASK-ID.\n"
        + _real_source(600_000)
        + "\nReply with ONLY the TASK-ID given on the first line."
    )
    with pytest.raises(RuntimeError, match="PROMPT TRUNCATED"):
        P._litellm_generator(f"ollama/{MODEL}")(prompt, 0.0)


@needs_model
def test_a_fenced_candidate_reaches_the_oracle_as_code():
    """The fence bug, as a product-level property rather than a unit test.

    The prompt asks for a fenced block, which is what the real harness asks for. If the
    fence survives to the oracle the module fails to import and twelve correct answers
    score 0.00 -- which is exactly what happened on the first Radeon run.
    """
    from determinex_build_from_idea import _fence_safe, _strip_fence

    fenced = "```python\ndef add(a, b):\n    return a + b\n```"
    assert _strip_fence(fenced).startswith("def add"), "fence stripping is broken outright"

    # The property that actually matters: it is applied at the boundary EVERY candidate
    # crosses, so no provider can bypass it. A provider that never strips is the real case.
    naive = _fence_safe(lambda prompt, temperature: fenced)
    got = naive("irrelevant", 0.0)
    assert "```" not in got, (
        "a provider that returns fenced output still reaches the oracle with the fence "
        "attached -- the strip is not at the shared boundary"
    )
    compile(got, "<candidate>", "exec")  # what the oracle does; the whole point


def test_this_file_reports_when_it_could_not_verify_anything():
    """A suite that silently runs nothing is indistinguishable from one that passed.

    This always runs, so `-k end_to_end` never comes back empty and green while the checks
    above were all skipped.
    """
    if MODEL is None:
        pytest.skip("NO LOCAL MODEL: the end-to-end product path was NOT verified in this run")
    assert MODEL
