"""
swe_agent/rag.py — Latent RAG (Track 2 mini).

Embeds auto_curriculum.jsonl with nomic-embed-text, retrieves top-K similar
verified patches, prepends as context to the Builder prompt.

Retrieval mode selection:
  top_score >= ADAPT_THRESHOLD  → ADAPT mode (adapt retrieved patch directly)
  top_score >= HINT_THRESHOLD   → HINT mode (prepend as context hint)
  top_score <  HINT_THRESHOLD   → GENERATE mode (pure generation, no retrieval)

As the flywheel corpus grows, ADAPT hits more often — effective score rises
without model parameter changes, purely from accumulated compiler-verified knowledge.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("determinex_swe")

_ROOT = Path(__file__).resolve().parent.parent.parent

_FLYWHEEL_PATH = Path(os.getenv("DETERMINEX_FLYWHEEL_PATH", str(_ROOT / "auto_curriculum.jsonl")))
_LATENT_RAG_K = int(os.getenv("DETERMINEX_LATENT_RAG_K", "2"))
_NO_ROSETTA = os.getenv("DETERMINEX_NO_ROSETTA", "0") == "1"

_ADAPT_THRESHOLD = float(os.getenv("DETERMINEX_ADAPT_THRESHOLD", "0.70"))
_HINT_THRESHOLD = float(os.getenv("DETERMINEX_HINT_THRESHOLD", "0.50"))

# Process-level state — loaded once, reused across all solve() calls
_latent_index: list[tuple[list[float], str, str]] = []  # (embedding, issue, patch)
_latent_index_loaded = False
_latent_embedder = None


def _entry_patch_text(entry: dict) -> str:
    """Return the verified patch text from current or legacy flywheel rows."""
    patch = entry.get("output") or entry.get("patch") or ""
    return patch if isinstance(patch, str) else ""


def _load_latent_index() -> None:
    global _latent_index, _latent_index_loaded
    if _latent_index_loaded:
        return
    _latent_index_loaded = True
    if not _FLYWHEEL_PATH.exists():
        return
    try:
        from fastembed import TextEmbedding  # type: ignore[import-untyped]

        embedder = TextEmbedding("nomic-ai/nomic-embed-text-v1.5")
        entries: list[dict] = []
        with _FLYWHEEL_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        if not entries:
            return
        issues = [e.get("issue", "")[:500] for e in entries]
        embeddings = list(embedder.embed(issues))
        _latent_index = [
            (list(embeddings[i]), entries[i].get("issue", ""), _entry_patch_text(entries[i]))
            for i in range(len(entries))
        ]
        log.info("Latent index loaded: %d verified patches", len(_latent_index))
    except Exception as e:
        log.debug("Latent index unavailable: %s", e)


def _get_latent_embedder():
    global _latent_embedder
    if _latent_embedder is None:
        try:
            from fastembed import TextEmbedding  # type: ignore[import-untyped]

            _latent_embedder = TextEmbedding("nomic-ai/nomic-embed-text-v1.5")
        except Exception as e:
            log.debug("fastembed unavailable: %s", e)
    return _latent_embedder


def _latent_retrieve(query: str) -> tuple[str, float]:
    """
    Retrieve top-K most similar verified patches from the flywheel corpus.
    Returns (context_str, top_score).
    """
    if _NO_ROSETTA or not _latent_index or _LATENT_RAG_K == 0:
        return "", 0.0
    try:
        import numpy as np  # type: ignore[import-untyped]

        embedder = _get_latent_embedder()
        if embedder is None:
            return "", 0.0
        q_emb = np.array(list(embedder.embed([query[:500]]))[0])
        scores: list[tuple[float, str, str]] = []
        for emb, issue, patch in _latent_index:
            e = np.array(emb)
            cos = float(np.dot(q_emb, e) / (np.linalg.norm(q_emb) * np.linalg.norm(e) + 1e-9))
            scores.append((cos, issue, patch))
        scores.sort(reverse=True)
        top = scores[:_LATENT_RAG_K]
        if not top or top[0][0] < _HINT_THRESHOLD:
            return "", top[0][0] if top else 0.0
        top_score = top[0][0]
        ctx = "[SIMILAR VERIFIED FIXES FROM CORPUS]\n"
        for score, sim_issue, sim_patch in top:
            ctx += (
                f"Issue (similarity {score:.2f}): {sim_issue[:300]}\n"
                f"Verified patch:\n{sim_patch[:500]}\n---\n"
            )
        return ctx, top_score
    except Exception as e:
        log.debug("Latent retrieval failed: %s", e)
        return "", 0.0
