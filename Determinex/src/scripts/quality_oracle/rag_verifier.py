"""rag_verifier.py — Verify claims against the Determinex knowledge base.

Uses the existing sqlite-vec + fastembed infrastructure (same as the agent's
rag_retrieve_for_task). Flips the use from retrieve-to-generate to
retrieve-to-validate: if no KB chunk supports a claim, it's ungrounded.

Threshold tuning:
  similarity >= 0.72  → SUPPORTED  (claim is in KB)
  similarity  0.55-0.72 → UNCERTAIN (weak match, flag for review)
  similarity < 0.55   → UNGROUNDED (hallucination candidate)
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import struct
from dataclasses import dataclass

_EMBEDDER = None
_DB_PATH: str | None = None

SUPPORT_THRESHOLD = 0.72
UNCERTAIN_THRESHOLD = 0.55


def _init_rag() -> bool:
    global _EMBEDDER, _DB_PATH
    if _EMBEDDER is not None:
        return True
    try:
        from fastembed import TextEmbedding

        _EMBEDDER = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        _DB_PATH = os.environ.get(
            "DETERMINEX_DB",
            # run.determinex.app is the Tauri BUNDLE IDENTIFIER, so this directory is the
            # right place -- only the hardcoded user-profile prefix was wrong. Derive it.
            str(
                pathlib.Path(
                    os.environ.get("APPDATA") or pathlib.Path.home() / "AppData" / "Roaming"
                )
                / "run.determinex.app"
                / "determinex.sqlite"
            ),
        )
        return True
    except Exception as e:
        print(f"  [rag_verifier] init failed: {e}; verification disabled")
        return False


def _embed(text: str) -> list[float] | None:
    if _EMBEDDER is None:
        return None
    try:
        vecs = list(_EMBEDDER.embed([text]))
        return vecs[0].tolist() if vecs else None
    except Exception:
        return None


@dataclass
class ClaimVerification:
    claim_text: str
    supported: bool  # True if KB supports this claim
    uncertain: bool = False  # True if evidence is weak but present
    similarity: float = 0.0  # Best cosine similarity found
    evidence: str = ""  # Best-matching KB chunk (for feedback)
    evidence_source: str = ""  # Metadata / source of the evidence chunk


class RagVerifier:
    """Verify claims against the sqlite-vec knowledge base."""

    def __init__(self, tables: list[tuple[str, str]] | None = None, top_k: int = 3):
        """
        Args:
            tables: List of (content_table, vss_table) pairs to search.
                    Defaults to all standard tables.
            top_k: Number of nearest neighbors to retrieve per claim.
        """
        self.tables = tables or [
            ("wisdom", "vss_wisdom"),
            ("knowledge_rust", "vss_code_rust"),
            ("knowledge_web", "vss_code_web"),
            ("knowledge_architecture", "vss_architecture"),
            ("knowledge_companion", "vss_companion"),
        ]
        self.top_k = top_k

    def verify(self, claim_text: str) -> ClaimVerification:
        """Verify a single claim against the KB."""
        if not _init_rag():
            return ClaimVerification(
                claim_text=claim_text,
                supported=True,
                uncertain=True,
                evidence="[RAG unavailable — cannot verify]",
            )

        vec = _embed(claim_text)
        if vec is None:
            return ClaimVerification(
                claim_text=claim_text, supported=True, uncertain=True, evidence="[embedding failed]"
            )

        vec_bytes = struct.pack(f"{len(vec)}f", *vec)
        best_sim = 0.0
        best_chunk = ""
        best_source = ""

        try:
            import sqlite_vec

            con = sqlite3.connect(_DB_PATH)
            con.enable_load_extension(True)
            sqlite_vec.load(con)
            con.enable_load_extension(False)

            for content_table, vss_table in self.tables:
                try:
                    rows = con.execute(
                        f"""
                        SELECT c.content, c.metadata,
                               (1 - vec_distance_cosine(v.embedding_vector, ?)) AS similarity
                        FROM {vss_table} v
                        JOIN {content_table} c ON c.rowid = v.rowid
                        WHERE v.embedding_vector MATCH ? AND k = ?
                        ORDER BY similarity DESC
                        """,
                        (vec_bytes, vec_bytes, self.top_k),
                    ).fetchall()
                    for content, metadata, sim in rows:
                        if sim > best_sim:
                            best_sim = sim
                            best_chunk = content[:400]
                            best_source = metadata or content_table
                except Exception:
                    continue
            con.close()
        except Exception as e:
            return ClaimVerification(
                claim_text=claim_text, supported=True, uncertain=True, evidence=f"[DB error: {e}]"
            )

        supported = best_sim >= SUPPORT_THRESHOLD
        uncertain = not supported and best_sim >= UNCERTAIN_THRESHOLD

        return ClaimVerification(
            claim_text=claim_text,
            supported=supported,
            uncertain=uncertain,
            similarity=round(best_sim, 3),
            evidence=best_chunk,
            evidence_source=best_source,
        )

    def verify_all(self, claims: list, min_confidence: float = 0.6) -> list[ClaimVerification]:
        """Verify a list of Claim objects. Skips low-confidence claims."""
        results = []
        for claim in claims:
            c = claim if isinstance(claim, str) else claim.text
            conf = 1.0 if isinstance(claim, str) else getattr(claim, "confidence", 1.0)
            if conf < min_confidence:
                continue
            results.append(self.verify(c))
        return results

    def verify_inline(self, text: str, context_chunks: list[str]) -> list[ClaimVerification]:
        """Verify against provided context chunks instead of the global KB.

        Used when the 'truth' is the task's own context (SWE-bench, ProgramBench).
        Each claim is checked against cosine similarity to the provided chunks.
        """
        if not _init_rag():
            return []

        from .claim_extractor import ClaimExtractor

        extractor = ClaimExtractor()
        claims = extractor.extract(text)

        results = []
        for claim in claims:
            vec = _embed(claim.text)
            if vec is None:
                continue
            import numpy as np

            claim_arr = np.array(vec, dtype=np.float32)
            best_sim = 0.0
            best_chunk = ""
            for chunk in context_chunks:
                chunk_vec = _embed(chunk)
                if chunk_vec is None:
                    continue
                chunk_arr = np.array(chunk_vec, dtype=np.float32)
                sim = float(
                    np.dot(claim_arr, chunk_arr)
                    / (np.linalg.norm(claim_arr) * np.linalg.norm(chunk_arr) + 1e-9)
                )
                if sim > best_sim:
                    best_sim = sim
                    best_chunk = chunk[:400]
            supported = best_sim >= SUPPORT_THRESHOLD
            uncertain = not supported and best_sim >= UNCERTAIN_THRESHOLD
            results.append(
                ClaimVerification(
                    claim_text=claim.text,
                    supported=supported,
                    uncertain=uncertain,
                    similarity=round(best_sim, 3),
                    evidence=best_chunk,
                    evidence_source="inline_context",
                )
            )
        return results
