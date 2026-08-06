"""The context budget every model call is bounded by.

## Where the numbers come from

`APPROVED_CONTEXT_BUDGET_TOKENS` is the business budget ratified by the
benchmark owner on PR #39 (`#issuecomment-5188...`): `tokenized_input +
reserved_output <= 20480`, with overflow to be trimmed, chunked, summarized or
staged rather than left to the server to truncate silently.

`VERIFIED_CONTEXT_TOKENS` is a different number and is deliberately kept beside
it. **8192 is the only window empirically proven on the W7900.** The 20K
qualification is PR #44, which is `PLAN IMPLEMENTED / RUNTIME NOT EXECUTED`.

Keeping both means no line of code can be read as a claim that 20K works. A
single constant would have merged an approved target with a measured capability,
and the merge is silent — the number looks equally authoritative either way.

## Why bounds are in tokens and not in item counts

The stages previously bounded payloads by counting decisions, statements and
graphs. That cannot be made safe at any window: one projection in the frozen
fixtures is 1,306 characters and another is 2,484, and the contract permits 400
characters per node with no cap on node count. A count bound must be sized for
the worst item to be safe, which wastes most of the window on the common one.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal, Protocol

APPROVED_CONTEXT_BUDGET_TOKENS = 20480
"""Approved business budget. **Not** a verified deployment capability."""

VERIFIED_CONTEXT_TOKENS = 8192
"""The only window empirically proven on the W7900, as of PR #39."""

CONTEXT_BUDGET_AUTHORITY = "PR #39 benchmark owner ruling; 20K qualification is PR #44"

TOKENIZER_MODEL_ID = "Qwen/Qwen3.5-9B"
TOKENIZER_REVISION = "460979c3d11864dd16408d860ac930a360a2fac2"
TOKENIZER_JSON_SHA256 = "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
TOKENIZER_CONFIG_SHA256 = "316230d6a809701f4db5ea8f8fc862bc3a6f3229c937c174e674ff3ca0a64ac8"
TOKENIZER_SNAPSHOT_ENV = "E5_TOKENIZER_PATH"
DEFAULT_TOKENIZER_SNAPSHOT = "/workspace/amd-track2-agent/models/Qwen3.5-9B-460979c3d118"

CountingMethod = Literal["tokenizer", "character-ratio-estimate"]

_ESTIMATE_CHARS_PER_TOKEN = 2.5
"""Superseded by real counting wherever the tokenizer is present.

Retained only so a developer machine without the snapshot still bounds payloads
instead of not bounding them. Every recorded bound says which method produced
it, because an estimate read later as a measurement is how a budget stops
meaning anything.
"""


class TokenCounter(Protocol):
    method: CountingMethod

    def count(self, text: str) -> int: ...


class CharacterRatioEstimator:
    """Fallback. Never sufficient evidence for a capability claim."""

    method: CountingMethod = "character-ratio-estimate"

    def count(self, text: str) -> int:
        return int(len(text) / _ESTIMATE_CHARS_PER_TOKEN) + 1


class SnapshotTokenizerCounter:
    """The pinned Qwen tokenizer, verified by hash before it is trusted.

    The hashes are checked rather than assumed. A tokenizer that differs from
    the one the benchmark measured would produce counts that disagree with the
    server at exactly the boundary the budget exists to defend, and nothing
    would report it — the numbers would simply be wrong by a little.
    """

    method: CountingMethod = "tokenizer"

    def __init__(self, snapshot: Path) -> None:
        from tokenizers import Tokenizer  # imported lazily; optional dependency

        verify_tokenizer_snapshot(snapshot)
        self._tokenizer = Tokenizer.from_file(str(snapshot / "tokenizer.json"))

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)


def verify_tokenizer_snapshot(snapshot: Path) -> None:
    for name, expected in (
        ("tokenizer.json", TOKENIZER_JSON_SHA256),
        ("tokenizer_config.json", TOKENIZER_CONFIG_SHA256),
    ):
        path = snapshot / name
        if not path.is_file():
            raise FileNotFoundError(f"tokenizer snapshot is missing {name}: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(
                f"{name} hash {digest} does not match the pinned {expected}; this is "
                "not the tokenizer the serving benchmark measured"
            )


def resolve_counter() -> TokenCounter:
    """The real tokenizer where the verified snapshot exists, else the estimate.

    Silent fallback is the point of failure to avoid, so the choice is recorded
    on every bound this module produces rather than being inferred from the
    environment at read time.
    """
    snapshot = Path(os.environ.get(TOKENIZER_SNAPSHOT_ENV, DEFAULT_TOKENIZER_SNAPSHOT))
    try:
        return SnapshotTokenizerCounter(snapshot)
    except (ImportError, FileNotFoundError, ValueError):
        return CharacterRatioEstimator()


def context_budget_tokens() -> int:
    """The configured budget, overridable for a stricter run, never a looser one.

    Raising it above the approved figure is refused: a budget a caller can widen
    is not a budget, and the one number nobody has verified is the larger one.
    """
    raw = os.environ.get("E5_CONTEXT_BUDGET_TOKENS")
    if raw is None:
        return APPROVED_CONTEXT_BUDGET_TOKENS
    value = int(raw)
    if value < 1 or value > APPROVED_CONTEXT_BUDGET_TOKENS:
        raise ValueError(
            f"context budget must be in 1..{APPROVED_CONTEXT_BUDGET_TOKENS}; "
            f"{value} would exceed the approved budget"
        )
    return value


def prompt_budget_tokens(reserved_output: int) -> int:
    """What the prompt may occupy once the output reservation is subtracted.

    Reserved output counts against the same total. Before this, each stage
    carried an independent `max_output_tokens` with no relationship to the
    window, which is the actual defect: a per-stage output cap and a per-window
    input bound that never meet cannot jointly guarantee anything.
    """
    if reserved_output < 1:
        raise ValueError("a stage must reserve at least one output token")
    budget = context_budget_tokens() - reserved_output
    if budget < 1:
        raise ValueError(
            f"reserved output {reserved_output} leaves no room inside "
            f"{context_budget_tokens()}"
        )
    return budget


def describe_budget(counter: TokenCounter, reserved_output: int) -> dict:
    """The bound recorded beside a run, carrying its own provenance.

    `counting_method` is on the record because a run whose bound was estimated
    and a run whose bound was measured are different evidence, and nothing
    downstream can tell them apart afterwards without it.
    """
    return {
        "context_budget_tokens": context_budget_tokens(),
        "reserved_output_tokens": reserved_output,
        "prompt_budget_tokens": prompt_budget_tokens(reserved_output),
        "counting_method": counter.method,
        "verified_context_tokens": VERIFIED_CONTEXT_TOKENS,
        "budget_authority": CONTEXT_BUDGET_AUTHORITY,
        "tokenizer_model_id": TOKENIZER_MODEL_ID,
        "tokenizer_revision": TOKENIZER_REVISION,
    }
