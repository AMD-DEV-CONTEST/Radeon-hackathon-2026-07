"""Knowledge retriever for crypto trading RAG.

Retrieves relevant trading knowledge entries for a user query.

Two layers:
  1. Keyword/alias retriever (default, CPU-only, zero deps):
     - matches against each entry's `keywords` + `aliases`
     - English terms: exact word match
     - Chinese terms: multi-character substring / bigram match (NOT single
       characters), which fixes the old false-positive problem where any
       lone Chinese char in the query would partially match many entries.
     - uses an inverted index for candidate lookup (no linear scan).
  2. Optional semantic retriever — see `semantic.py`. Activated only when an
     embedding model is installed; otherwise the keyword path stays active.

The knowledge base covers:
- Indicator documentation (what each indicator does, typical params)
- Strategy patterns (crossover, mean reversion, breakout, etc.)
- Risk management rules (position sizing, stop placement, drawdown)
- Market context rules (asset traits, regime, funding, correlation)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .knowledge_entries import KNOWLEDGE_ENTRIES

# Token patterns --------------------------------------------------------------
_EN_RE = re.compile(r"[a-z0-9]+")          # english / number word
_CN_RE = re.compile(r"[一-鿿]+")           # CJK run (multi-char phrase)
_HAS_ALNUM = re.compile(r"[a-z0-9]")        # distinguishes EN terms from CN


@dataclass
class KnowledgeEntry:
    """A single knowledge base entry."""
    keywords: list[str]
    category: str  # indicator | strategy | risk | market
    title: str
    content: str
    weight: float = 1.0  # Priority weight for ranking
    aliases: list[str] = field(default_factory=list)  # synonyms / paraphrases

    @property
    def terms(self) -> list[str]:
        """All matchable trigger terms (keywords + aliases)."""
        return self.keywords + self.aliases


def _bigrams(s: str) -> list[str]:
    return [s[i:i + 2] for i in range(len(s) - 1)]


class KnowledgeRetriever:
    """Retrieves relevant knowledge entries based on user query.

    Keyword/alias based, CPU-only, no external dependencies.
    """

    def __init__(self, entries: list[KnowledgeEntry] | None = None):
        self._entries = entries or _load_entries()

    # ── Public API ──────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> list[KnowledgeEntry]:
        """Retrieve relevant knowledge entries for a query.

        Args:
            query: User's natural language input.
            max_results: Maximum entries to return.
            min_score: Minimum relevance score threshold.

        Returns:
            List of KnowledgeEntry sorted by relevance.
        """
        q_en, q_cn_runs, q_cn_bigrams = self._tokenize(query)
        if not q_en and not q_cn_runs:
            return []

        # Corpus is tiny (tens of entries); a full scan is correct and cheap,
        # and avoids the substring-miss bug an inverted index would cause for
        # multi-character CJK terms that are substrings of the query.
        scored: list[tuple[float, KnowledgeEntry]] = []
        for entry in self._entries:
            score = self._score_entry(entry, q_en, q_cn_runs, q_cn_bigrams)
            if score >= min_score:
                scored.append((score, entry))

        scored.sort(key=lambda x: (-x[0], -x[1].weight))
        return [entry for _, entry in scored[:max_results]]

    def retrieve_as_context(
        self,
        query: str,
        max_results: int = 5,
        max_chars: int = 2000,
    ) -> str:
        """Retrieve knowledge and format as LLM prompt context string.

        Args:
            query: User's natural language input.
            max_results: Max entries to retrieve.
            max_chars: Truncate context to this many characters.

        Returns:
            Formatted context string for LLM prompt injection.
        """
        entries = self.retrieve(query, max_results=max_results)
        if not entries:
            return ""

        sections: list[str] = []
        current_category = ""
        total_chars = 0

        for entry in entries:
            if entry.category != current_category:
                current_category = entry.category
                section_header = f"\n## {current_category.title()}"
                if total_chars + len(section_header) > max_chars:
                    break
                sections.append(section_header)
                total_chars += len(section_header)

            entry_text = f"\n### {entry.title}\n{entry.content}"
            if total_chars + len(entry_text) > max_chars:
                # Truncate
                remaining = max_chars - total_chars
                if remaining > 50:
                    sections.append(entry_text[:remaining] + "...")
                break
            sections.append(entry_text)
            total_chars += len(entry_text)

        return "\n".join(sections)

    # ── Internals ───────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> tuple[set[str], list[str], set[str]]:
        """Return (english_words, cjk_runs, cjk_bigrams).

        Chinese is kept as whole runs + adjacent bigrams, deliberately NOT
        split into single characters (that caused false positives before).
        """
        text = text.lower()
        en = set(_EN_RE.findall(text))
        cn_runs = _CN_RE.findall(text)
        cn_bigrams: set[str] = set()
        for run in cn_runs:
            cn_bigrams.update(_bigrams(run))
        return en, cn_runs, cn_bigrams

    def _score_entry(
        self,
        entry: KnowledgeEntry,
        q_en: set[str],
        q_cn_runs: list[str],
        q_cn_bigrams: set[str],
    ) -> float:
        """Score an entry's relevance to the query tokens.

        EN terms: exact word match (1.0 * weight).
        CN terms: multi-char substring in a CJK run (1.0 * weight) or CJK
        bigram match (0.6 * weight). Single isolated chars never inflate.
        """
        score = 0.0
        for term in entry.terms:
            tl = term.lower()
            if _HAS_ALNUM.search(tl):          # English-ish term
                if tl in q_en:
                    score += 1.0 * entry.weight
            else:                                   # CJK term
                if any(tl in run for run in q_cn_runs):
                    score += 1.0 * entry.weight
                elif len(tl) >= 2 and tl in q_cn_bigrams:
                    score += 0.6 * entry.weight
                # single-char CJK terms: intentionally ignored to avoid noise
        return score


def _load_entries() -> list[KnowledgeEntry]:
    """Load knowledge entries from knowledge_entries.py."""
    entries: list[KnowledgeEntry] = []
    for raw in KNOWLEDGE_ENTRIES:
        entries.append(KnowledgeEntry(**raw))
    return entries


# Module-level convenience function
_retriever: KnowledgeRetriever | None = None


def retrieve_knowledge(query: str, max_results: int = 5) -> str:
    """Retrieve knowledge context for a query.

    Convenience function that caches the retriever instance.

    Args:
        query: User's natural language input.
        max_results: Max entries to retrieve.

    Returns:
        Formatted context string for LLM prompt injection.
    """
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeRetriever()
    return _retriever.retrieve_as_context(query, max_results=max_results)
