"""Chunk retrieval over seed documents for datagen grounding.

Dependency-free tf-idf selection: seed docs split on markdown headings
(oversized sections re-split on paragraph boundaries), scored per
request against the target class + facets, greedily packed into a
character budget. Retrieval only activates when the corpus exceeds the
budget — small corpora keep the proven whole-document grounding.
"""

import math
import re
from collections import Counter
from pathlib import Path

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or "
    "that the this to was were will with you your we our they their "
    "not no if all any one per when what which how".split()
)


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9_]+", text.lower())
            if w not in STOPWORDS and len(w) > 1]


def build_chunks(docs: list[tuple[str, str]], max_chunk_chars: int = 1500) -> list[dict]:
    """docs: (doc_name, text) pairs. Returns [{doc, title, text, terms}]."""
    chunks = []
    for doc_name, text in docs:
        sections, title, buf = [], "(intro)", []
        for line in text.splitlines():
            if line.startswith("#"):
                if buf and "".join(buf).strip():
                    sections.append((title, "\n".join(buf).strip()))
                title, buf = line.lstrip("# ").strip() or "(untitled)", []
            else:
                buf.append(line)
        if buf and "".join(buf).strip():
            sections.append((title, "\n".join(buf).strip()))

        for title, body in sections:
            if len(body) <= max_chunk_chars:
                parts = [body]
            else:  # re-split long sections on paragraph boundaries
                parts, cur = [], ""
                for para in re.split(r"\n\s*\n", body):
                    if cur and len(cur) + len(para) + 2 > max_chunk_chars:
                        parts.append(cur)
                        cur = para
                    else:
                        cur = f"{cur}\n\n{para}" if cur else para
                if cur:
                    parts.append(cur)
            for i, part in enumerate(parts):
                label = title if len(parts) == 1 else f"{title} ({i + 1})"
                # title terms weigh into matching: a section headed
                # "Priorities" should match a priority-focused query
                chunks.append({"doc": doc_name, "title": label, "text": part,
                               "terms": Counter(_terms(part) + _terms(label) * 3)})
    return chunks


def select(chunks: list[dict], query: str, budget_chars: int) -> list[dict]:
    """tf-idf rank chunks against the query, greedily pack the budget."""
    n = len(chunks)
    df = Counter()
    for c in chunks:
        df.update(set(c["terms"]))
    q_terms = _terms(query)
    scored = []
    for c in chunks:
        score = sum(
            c["terms"][t] * math.log(1 + n / df[t])
            for t in q_terms if t in c["terms"]
        ) / (1 + math.log(1 + sum(c["terms"].values())))
        scored.append((score, c))
    scored.sort(key=lambda sc: -sc[0])

    picked, used = [], 0
    for score, c in scored:
        if picked and (used + len(c["text"]) > budget_chars or score <= 0):
            continue
        picked.append(c)
        used += len(c["text"])
    return picked or [scored[0][1]]


def render(picked: list[dict]) -> str:
    return "\n\n".join(f"## [{c['doc']}] {c['title']}\n{c['text']}" for c in picked)
