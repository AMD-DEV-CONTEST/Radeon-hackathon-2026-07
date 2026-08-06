"""Chunking for the auxiliary corpus.

Chunks are sentence-bounded with overlap, because a quasi-identifier and the
name it identifies are frequently in adjacent sentences — cut between them and
the co-occurrence tool stops finding the very links it exists to find.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


@dataclass
class Chunk:
    text: str
    source: str
    index: int


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


def chunk_text(
    text: str,
    source: str,
    target_chars: int = 900,
    overlap_sentences: int = 1,
) -> list[Chunk]:
    """Greedy sentence packing up to target_chars, with sentence overlap."""
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    idx = 0

    for sent in sentences:
        if buf and size + len(sent) > target_chars:
            chunks.append(Chunk(" ".join(buf), source, idx))
            idx += 1
            buf = buf[-overlap_sentences:] if overlap_sentences else []
            size = sum(len(s) for s in buf)
        buf.append(sent)
        size += len(sent)

    if buf:
        chunks.append(Chunk(" ".join(buf), source, idx))

    return chunks
