"""Utility scoring — the other axis of the privacy/utility curve.

A redaction system that only measures privacy will happily return an empty
page. Utility is measured three ways and reported separately, because they
fail differently:

  token_retention   — how much text survived (cheap, gameable, still useful)
  semantic_fidelity — cosine similarity of embeddings before/after
  structure_intact  — headings, numbers and dates still parseable

The headline number is the minimum of the three, not the mean. A document that
kept 95% of its words but lost every date is not 95% useful.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_TOKEN = re.compile(r"\b[\w'-]+\b")
_REDACTED = re.compile(r"\[REDACTED\]")
_NUMBER = re.compile(r"\b\d[\d,.]*\b")
_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+\S|[A-Z][A-Z \d.'-]{4,}$)", re.MULTILINE)


@lru_cache(maxsize=1)
def _embedder() -> Any:
    from sentence_transformers import SentenceTransformer

    from veil.config import CONFIG

    return SentenceTransformer(CONFIG.storage.embedding_model)


@dataclass
class UtilityScore:
    value: float
    token_retention: float
    semantic_fidelity: float | None
    structure_intact: float
    redaction_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "utility_retained": self.value,
            "token_retention": self.token_retention,
            "semantic_fidelity": self.semantic_fidelity,
            "structure_intact": self.structure_intact,
            "redaction_count": self.redaction_count,
        }


def token_retention(original: str, redacted: str) -> float:
    before = len(_TOKEN.findall(original))
    if before == 0:
        return 1.0
    after = len(_TOKEN.findall(_REDACTED.sub("", redacted)))
    return round(min(1.0, after / before), 4)


def semantic_fidelity(original: str, redacted: str) -> float | None:
    try:
        import numpy as np

        vecs = _embedder().encode([original, redacted], normalize_embeddings=True)
        return round(float(np.dot(vecs[0], vecs[1])), 4)
    except Exception:  # noqa: BLE001 - utility must never break a run
        return None


def structure_intact(original: str, redacted: str) -> float:
    parts = []
    for pattern in (_NUMBER, _HEADING):
        before = len(pattern.findall(original))
        after = len(pattern.findall(redacted))
        parts.append(1.0 if before == 0 else min(1.0, after / before))
    return round(sum(parts) / len(parts), 4)


def score(original: str, redacted: str) -> UtilityScore:
    tok = token_retention(original, redacted)
    sem = semantic_fidelity(original, redacted)
    struct = structure_intact(original, redacted)

    candidates = [tok, struct] + ([sem] if sem is not None else [])
    return UtilityScore(
        value=round(min(candidates), 4),
        token_retention=tok,
        semantic_fidelity=sem,
        structure_intact=struct,
        redaction_count=len(_REDACTED.findall(redacted)),
    )
