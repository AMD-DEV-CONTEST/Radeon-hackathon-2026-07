"""Outlines-style constrained decoding for VTE: forces generation to
complete exactly one of a fixed set of literal choice strings, by masking
the logits at each decode step so nothing else is reachable. Equivalent in
spirit to `outlines.generate.choice(model, choices)`, deliberately scoped
to "pick one of N known strings" rather than a full JSON-Schema/regex
grammar engine -- VTE's own decode loop treats per-token latency as the
scarce resource (see docs/PERFORMANCE.md), so the runtime cost here is a
single precomputed dict lookup + boolean mask per token, not a general DFA
walk with an on-the-fly token/character index like a full Outlines port
would need.

Real motivating case (see Aetheris's core/utils/tools.py -- the consumer
of this): a small model asked a vague question guesses a plausible but
nonexistent tool name (`read_files` instead of the real `read_file`) right
after opening a ```fence, and nothing catches it until the whole turn has
already been spent producing unusable output. Masking so only real tool
names are reachable from that point makes that entire failure class
structurally impossible instead of merely detected after the fact.

Scope note: activation is detected off already-DECODED text (mirrors
ThinkingSectionScanner's reasoning for the same choice -- see
thinking_scanner.py's module docstring), so the token that itself
completes `trigger` is never masked. For a non-empty trigger (VTE's real
use: `"```"`, whose literal characters are never the hallucination site --
only what follows them is) this doesn't matter. A caller using
`trigger=""` to constrain a generation from its very first token should
know that first token is unmasked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


def _decode_single_token(piece: str, byte_decoder: Dict[str, int], special_tokens: set) -> Optional[str]:
    """Literal text one vocab entry represents, using the same GPT-2
    byte-to-unicode scheme every VTE tokenizer shares (see
    vte/compiler/tokenizer.py::_bytes_to_unicode). None for special tokens
    (never a valid choice-name continuation) or pieces that don't stand on
    their own as clean UTF-8 (half of a multi-byte character split across
    a BPE merge boundary) -- irrelevant here since every real choice
    string this is built for is plain ASCII, so a piece that can't decode
    alone could never match one anyway."""
    if piece in special_tokens:
        return None
    try:
        raw = bytes(byte_decoder[ch] for ch in piece)
    except KeyError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _prefix_states(choices: List[str]) -> set:
    """Every string that is a prefix of at least one choice, including the
    empty string (the starting state) and each choice in full (kept out of
    the final token index deliberately -- see ChoiceConstraint._build_index)."""
    states = {""}
    for choice in choices:
        for i in range(1, len(choice) + 1):
            states.add(choice[:i])
    return states


@dataclass(frozen=True)
class ConstraintState:
    """Immutable per-generation cursor -- one instance flows through a
    single generate() call via observe_text/observe_token, never shared
    across calls (mirrors ThinkingSectionScanner's one-instance-per-
    generation contract, just persisted as returned values here instead of
    mutated in place, since the caller already threads state through a
    loop variable either way)."""
    matched: str = ""
    active: bool = False
    pending: str = ""


class ChoiceConstraint:
    """Build once per (tokenizer, choices, trigger) and reuse across every
    generate() call on that model -- the token-index precomputation below
    is the only non-trivial cost (a handful of seconds at worst for VTE's
    128K-152K vocabularies), everything used per decode step afterward is
    O(1) dict/array lookups."""

    def __init__(self, tokenizer, choices: List[str], trigger: str = ""):
        if not choices:
            raise ValueError("ChoiceConstraint needs at least one choice")
        if len(choices) != len(set(choices)):
            raise ValueError("ChoiceConstraint choices must be unique")
        self.choices = list(choices)
        self.trigger = trigger
        self._choice_set = set(self.choices)
        self._token_pieces = self._decode_vocab(tokenizer)
        self._index = self._build_index()

    @staticmethod
    def _decode_vocab(tokenizer) -> Dict[int, str]:
        special = set(tokenizer.special_tokens)
        pieces = {}
        for token_id, piece in tokenizer.inv_vocab.items():
            decoded = _decode_single_token(piece, tokenizer._byte_decoder, special)
            if decoded:
                pieces[token_id] = decoded
        return pieces

    def _build_index(self) -> Dict[str, np.ndarray]:
        # Bucketing by first character means each state below only scans
        # the (usually tiny -- a handful of letters) slice of the
        # vocabulary that could possibly extend it, instead of the whole
        # vocabulary every time: total work stays close to O(vocab), not
        # O(states x vocab).
        by_first_char: Dict[str, List[int]] = {}
        for token_id, text in self._token_pieces.items():
            by_first_char.setdefault(text[0], []).append(token_id)

        index: Dict[str, np.ndarray] = {}
        for state in _prefix_states(self.choices):
            if state in self._choice_set:
                continue  # terminal: constraint deactivates on reaching it, no mask needed
            next_chars = {c[len(state)] for c in self.choices if c.startswith(state) and len(c) > len(state)}
            allowed: List[int] = []
            for ch in next_chars:
                for token_id in by_first_char.get(ch, ()):
                    candidate = state + self._token_pieces[token_id]
                    if candidate in self._choice_set or any(c.startswith(candidate) for c in self.choices):
                        allowed.append(token_id)
            index[state] = np.array(sorted(set(allowed)), dtype=np.int64)
        return index

    def new_state(self) -> ConstraintState:
        return ConstraintState()

    def _advance(self, matched: str) -> ConstraintState:
        # A single condition covers both ways a match can end: `matched`
        # completing a real choice, or falling off every choice entirely
        # (shouldn't happen once masking is actually active -- see the
        # module docstring's scope note for the one gap where it can:
        # trigger-tail text or a from-scratch trigger="" first token that
        # was never masked in the first place). Either way, _build_index
        # never stores an entry for a complete choice, so `matched in
        # self._index` is False for both cases -- deactivating and
        # falling back to ordinary unconstrained decoding is correct and
        # safe for both: never force a dead end.
        if matched in self._index:
            return ConstraintState(matched=matched, active=True, pending="")
        return ConstraintState()

    # Deliberate tradeoff, not an oversight: when one choice is itself a
    # strict prefix of another (e.g. "write_file" / "write_files"),
    # `matched` reaching the SHORTER complete choice deactivates the
    # constraint just like reaching any other terminal -- it doesn't force
    # a stop, the model is simply unconstrained again from there, so it
    # can still naturally continue toward the longer choice on its own.
    # What this gives up: a one-off garbled continuation right at that
    # exact boundary (e.g. "write_filex") is no longer blocked by masking.
    # That residual case is exactly what a second, independent layer
    # (Aetheris's find_unmatched_tool_attempt, core/utils/tools.py) exists
    # to catch -- this class only needs to close the FAR more common and
    # costly failure (an entirely invented name), not every possible typo.

    def observe_text(self, state: ConstraintState, text: str) -> ConstraintState:
        """Feed newly-decoded text (call every decode step, active or
        not -- a no-op once already active). Detects `trigger` appearing
        in the stream and activates the constraint on whatever text
        immediately followed it in the same chunk, if any."""
        if state.active or not text:
            return state
        pending = state.pending + text
        idx = pending.find(self.trigger) if self.trigger else 0
        if idx == -1:
            keep_len = min(len(pending), max(len(self.trigger) - 1, 0))
            return ConstraintState(pending=pending[len(pending) - keep_len:] if keep_len else "")
        return self._advance(pending[idx + len(self.trigger):])

    def observe_token(self, state: ConstraintState, token_id: int) -> ConstraintState:
        """Advance by the token actually sampled (call every decode step,
        active or not -- a no-op while inactive, since observe_text is
        what drives activation)."""
        if not state.active:
            return state
        return self._advance(state.matched + self._token_pieces.get(token_id, ""))

    def allowed_token_ids(self, state: ConstraintState) -> Optional[np.ndarray]:
        return self._index.get(state.matched) if state.active else None

    def apply_mask(self, logits: np.ndarray, state: ConstraintState) -> np.ndarray:
        """Returns a masked COPY of `logits` (never mutates the caller's
        array -- the decode loop reuses/rewrites its own logits buffer
        every step, so aliasing it here would corrupt state the caller
        still needs). Returns `logits` itself, unmasked, if there's
        nothing to constrain (inactive state, or -- shouldn't happen, see
        _advance -- an active state with an empty allowed set)."""
        allowed = self.allowed_token_ids(state)
        if allowed is None or allowed.size == 0:
            return logits
        masked = np.full_like(logits, -np.inf)
        masked[allowed] = logits[allowed]
        return masked
