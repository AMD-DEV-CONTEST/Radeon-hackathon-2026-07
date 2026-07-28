"""Adaptive `max_tokens` suggestion for the chat generation budget.

Companion to context_budget.py (which sizes the INPUT/prompt-side budget):
this sizes the OUTPUT/generation-side `max_tokens` when the caller hasn't
made a deliberate choice. Same "explicit wins, otherwise auto-classify"
contract as context_budget.py's `budget_is_explicit` -- keys off the VALUE
(a non-default positive number is a deliberate choice), not presence,
since Flutter's Intelligence slider always sends SOME value (its own
default is 4096) rather than leaving the field unset.

Motivating case: a reasoning-capable backend (`delta.reasoning`, see
vte_bridge.py) can spend its ENTIRE `max_tokens` budget on internal
reasoning before ever producing a visible answer -- measured directly,
4096 tokens (the flat default before this existed) was not enough for
even a plain "explain X in 300 words" prompt against a real reasoning
model via an external OpenAI-compatible API, producing zero visible
output after 122s. VTE's own local models never emit a reasoning channel
at all, so this classifier is deliberately generic (keys off message
complexity, not any specific model) rather than scoped to that one case.

Pure and side-effect free, like context_budget.py, so it's unit-testable
without a running model.
"""

import re
from typing import Optional

DEFAULT_MAX_TOKENS = 4096

# Cheap, no-LLM heuristics -- a regex pass, not a model call, so it costs
# nothing on the request's own critical path. Deliberately conservative:
# an unmatched message falls through to "medium" (today's flat default),
# so a message this doesn't recognize behaves exactly as before this
# existed.
_SIMPLE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(oi|ol[aá]|hey|hello|hi|obrigad[oa]|thanks|thank you)\b",
        r"^(sim|n[aã]o|yes|no|ok|okay)\b",
        r"^(qual|what|who|quando|when|onde|where)\b.{0,40}\?\s*$",
    ]
]
_COMPLEX_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(analis\w*|analyz\w*|compare|explain in detail|explique em detalhe)",
        r"\b(c[oó]digo|code|implement\w*|debug|refactor|refatora\w*)",
        r"\b(step by step|passo a passo|architecture|arquitetura)",
        r"\b(trade-?offs?|pr[oó]s e contras)",
    ]
]

_BUDGETS = {
    "simple": 1024,
    "medium": DEFAULT_MAX_TOKENS,
    "complex": 8192,
}


def classify_complexity(user_message: str) -> str:
    """Returns "simple", "medium", or "complex" from a cheap regex pass
    over the message -- no LLM call involved."""
    text = (user_message or "").strip()
    if not text:
        return "medium"
    if len(text) <= 60 and any(p.search(text) for p in _SIMPLE_PATTERNS):
        return "simple"
    if any(p.search(text) for p in _COMPLEX_PATTERNS):
        return "complex"
    return "medium"


def suggest_max_tokens(
    user_message: str, configured: Optional[int], *, default: int = DEFAULT_MAX_TOKENS
) -> int:
    """`configured`: the value the client actually sent. Honoured exactly
    (the user's deliberate choice always wins) whenever it's a positive
    value different from `default` -- e.g. the Intelligence slider moved
    to 1024 or 65536. Only classifies when `configured` is absent or still
    sitting at the materialized default, mirroring context_budget.py's
    `budget_is_explicit` reasoning for the exact same ambiguity."""
    configured = int(configured or 0)
    if configured > 0 and configured != default:
        return configured
    return _BUDGETS[classify_complexity(user_message)]
