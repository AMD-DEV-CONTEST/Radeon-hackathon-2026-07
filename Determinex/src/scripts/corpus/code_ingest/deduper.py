"""
Near-duplicate detector for corpus code ingest.

Two stages:
  1. Exact dedup: BLAKE2b-256 hash of normalized content
  2. Near-dedup: MinHash Jaccard similarity on token shingles (k=5)

A corpus entry is a duplicate if:
  - Exact hash matches an existing entry, OR
  - Jaccard similarity exceeds NEAR_DUP_THRESHOLD with any seen entry

Both thresholds configurable via env vars:
  DETERMINEX_NEAR_DUP_THRESHOLD  (default 0.80)
  DETERMINEX_MINHASH_PERMUTATIONS (default 128)
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

_NEAR_DUP_THRESHOLD = float(os.environ.get("DETERMINEX_NEAR_DUP_THRESHOLD", "0.80"))
_MINHASH_PERMS = int(os.environ.get("DETERMINEX_MINHASH_PERMUTATIONS", "128"))
_MERSENNE_PRIME = (1 << 61) - 1
_MAX_HASH = 1 << 32


@dataclass
class DedupResult:
    content_hash: str
    is_exact_duplicate: bool
    is_near_duplicate: bool
    similarity: float  # Jaccard estimate; 0.0 if not near-dup
    matched_hash: str | None  # hash of the existing entry it matched

    @property
    def is_duplicate(self) -> bool:
        return self.is_exact_duplicate or self.is_near_duplicate


def _normalize(content: str) -> str:
    """Strip comments, collapse whitespace for dedup comparison."""
    # Remove single-line comments (Python/JS/Java/Go style)
    content = re.sub(r"//[^\n]*", "", content)
    content = re.sub(r"#[^\n]*", "", content)
    # Remove block comments
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    # Collapse whitespace
    content = re.sub(r"\s+", " ", content)
    return content.strip().lower()


def _content_hash(content: str) -> str:
    normalized = _normalize(content)
    return hashlib.blake2b(normalized.encode(), digest_size=32).hexdigest()


def _shingles(content: str, k: int = 5) -> set[int]:
    tokens = _normalize(content).split()
    if len(tokens) < k:
        return {hash(tuple(tokens))}
    return {hash(tuple(tokens[i : i + k])) for i in range(len(tokens) - k + 1)}


class _MinHashSignature:
    """Lightweight MinHash using numpy-free integer hashing."""

    __slots__ = ("sig",)

    def __init__(self, shingles: set[int], n_perm: int = _MINHASH_PERMS):
        # Random-ish hash parameters (deterministic seed)
        import random

        rng = random.Random(42)
        a = [rng.randint(1, _MERSENNE_PRIME) for _ in range(n_perm)]
        b = [rng.randint(0, _MERSENNE_PRIME) for _ in range(n_perm)]
        self.sig = [_MAX_HASH] * n_perm
        for shingle in shingles:
            for i in range(n_perm):
                h = (a[i] * shingle + b[i]) % _MERSENNE_PRIME
                if h < self.sig[i]:
                    self.sig[i] = h

    def jaccard(self, other: _MinHashSignature) -> float:
        matches = sum(a == b for a, b in zip(self.sig, other.sig))
        return matches / len(self.sig)


class Deduper:
    """
    Stateful deduplicator. Call add() for each candidate content string.
    Returns DedupResult indicating if it's a duplicate.

    Not thread-safe. Use one instance per ingestion run.
    """

    def __init__(self, near_dup_threshold: float = _NEAR_DUP_THRESHOLD):
        self._threshold = near_dup_threshold
        self._exact: dict[str, str] = {}  # hash → first seen hash (same)
        self._sigs: list[tuple[str, _MinHashSignature]] = []  # (hash, sig)

    def check(self, content: str) -> DedupResult:
        """Check whether content is a duplicate (without adding it)."""
        h = _content_hash(content)

        if h in self._exact:
            return DedupResult(
                content_hash=h,
                is_exact_duplicate=True,
                is_near_duplicate=False,
                similarity=1.0,
                matched_hash=h,
            )

        sig = _MinHashSignature(_shingles(content))
        best_sim = 0.0
        best_hash = None
        for existing_hash, existing_sig in self._sigs:
            sim = sig.jaccard(existing_sig)
            if sim > best_sim:
                best_sim = sim
                best_hash = existing_hash

        is_near = best_sim >= self._threshold
        return DedupResult(
            content_hash=h,
            is_exact_duplicate=False,
            is_near_duplicate=is_near,
            similarity=best_sim,
            matched_hash=best_hash if is_near else None,
        )

    def add(self, content: str) -> DedupResult:
        """Check and add. Returns DedupResult. If duplicate, does not add."""
        result = self.check(content)
        if not result.is_duplicate:
            self._exact[result.content_hash] = result.content_hash
            sig = _MinHashSignature(_shingles(content))
            self._sigs.append((result.content_hash, sig))
        return result

    @property
    def size(self) -> int:
        return len(self._exact)
