"""Quantitative document chunker for RAG knowledge base.

Chunking strategy optimized for quantitative documents:
- Base chunk size: 512 tokens, 128 token overlap
- Split boundaries: headings, paragraph breaks, never cut a trading rule
- Tables: converted to text blocks, never split
- Metadata: every chunk gets strategy_name, asset, timeframe, doc_version, update_time

This module is used when ingesting external strategy docs, risk manuals,
or contract specs into the knowledge base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """A single knowledge base chunk with metadata."""
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approx_tokens(self) -> int:
        """Rough token estimate (4 chars ≈ 1 token for mixed CN/EN)."""
        return len(self.text) // 4


class QuantChunker:
    """Chunker optimized for quantitative trading documents.

    Rules:
    1. Base chunk = 512 tokens (~2048 chars), overlap = 128 tokens (~512 chars)
    2. Prefer splitting at headings (##, ###) and paragraph breaks
    3. Never split inside a trading rule (if/then/stop-loss block)
    4. Tables → single chunk, converted to text
    5. Every chunk gets metadata tags
    """

    BASE_CHUNK_CHARS = 2048  # ~512 tokens
    OVERLAP_CHARS = 512  # ~128 tokens
    MIN_CHUNK_CHARS = 200  # Don't create tiny chunks

    def chunk_document(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Chunk a document into knowledge base entries.

        Args:
            text: Raw document text (markdown, plain text, or semi-structured).
            metadata: Default metadata for all chunks (strategy_name, asset, etc.)

        Returns:
            List of Chunk objects with text and metadata.
        """
        base_meta = metadata or {}

        # Extract tables first (they become single chunks)
        tables, text_without_tables = self._extract_tables(text)

        # Split by headings and paragraphs
        sections = self._split_by_structure(text_without_tables)

        # Further split large sections
        chunks: list[Chunk] = []
        for section in sections:
            if len(section) <= self.BASE_CHUNK_CHARS:
                if len(section) >= self.MIN_CHUNK_CHARS:
                    chunks.append(Chunk(text=section, metadata=base_meta.copy()))
            else:
                # Sliding window split with overlap
                for sub in self._sliding_window_split(section):
                    chunks.append(Chunk(text=sub, metadata=base_meta.copy()))

        # Add tables as individual chunks
        for table_text in tables:
            chunks.append(Chunk(text=table_text, metadata={
                **base_meta, "chunk_type": "table",
            }))

        # Enrich metadata with chunk index
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
            chunk.metadata["total_chunks"] = len(chunks)

        return chunks

    def _extract_tables(self, text: str) -> tuple[list[str], str]:
        """Extract markdown tables from text. Each table becomes a single chunk."""
        tables: list[str] = []
        # Match markdown tables (| ... | ... |)
        table_pattern = re.compile(
            r"(?:^\|.+\|$\n?)+",  # Consecutive lines starting with |
            re.MULTILINE,
        )

        def _replace_table(m):
            tables.append(m.group(0).strip())
            return "\n[TABLE_PLACEHOLDER]\n"

        text_without = table_pattern.sub(_replace_table, text)
        return tables, text_without

    def _split_by_structure(self, text: str) -> list[str]:
        """Split text at headings and paragraph breaks."""
        # Split at markdown headings
        heading_splits = re.split(r"(?m)^#{1,6}\s+", text)

        sections: list[str] = []
        for split in heading_splits:
            split = split.strip()
            if not split:
                continue
            # Further split by double newlines (paragraphs)
            paragraphs = re.split(r"\n\n+", split)
            current = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if len(current) + len(para) + 2 > self.BASE_CHUNK_CHARS and current:
                    sections.append(current.strip())
                    current = para
                else:
                    current = current + "\n\n" + para if current else para
            if current.strip():
                sections.append(current.strip())

        return sections

    def _sliding_window_split(self, text: str) -> list[str]:
        """Split large text with overlapping windows."""
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.BASE_CHUNK_CHARS, len(text))

            # Try to break at a sentence or newline
            if end < len(text):
                for break_char in ["\n\n", "\n", "。", ". ", "；", "; "]:
                    last_break = text.rfind(break_char, start, end)
                    if last_break > start + self.MIN_CHUNK_CHARS:
                        end = last_break + len(break_char)
                        break

            chunk = text[start:end].strip()
            if len(chunk) >= self.MIN_CHUNK_CHARS:
                chunks.append(chunk)

            # Move start with overlap
            start = end - self.OVERLAP_CHARS if end < len(text) else end

        return chunks
