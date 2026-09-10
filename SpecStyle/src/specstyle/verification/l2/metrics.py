"""L2 similarity metrics on style feature vectors."""

from __future__ import annotations

import math

from specstyle.errors import DomainError
from specstyle.verification.l2.encoder import StyleFeature


def cosine_similarity(a: StyleFeature, b: StyleFeature) -> float:
    if type(a) is not StyleFeature or type(b) is not StyleFeature:
        raise DomainError("invalid features")
    if len(a.vector) != len(b.vector):
        raise DomainError("feature dimension mismatch")
    if a.pin != b.pin:
        raise DomainError("encoder pin mismatch")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a.vector, b.vector, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        raise DomainError("zero feature norm")
    return dot / (math.sqrt(na) * math.sqrt(nb))


def robust_reference_similarity(
    output: StyleFeature, references: tuple[StyleFeature, ...]
) -> float:
    """Median of cosine similarities to references (order-invariant)."""
    if type(references) is not tuple or not references:
        raise DomainError("empty references")
    scores = sorted(cosine_similarity(output, ref) for ref in references)
    mid = len(scores) // 2
    if len(scores) % 2 == 1:
        return scores[mid]
    return (scores[mid - 1] + scores[mid]) / 2.0
