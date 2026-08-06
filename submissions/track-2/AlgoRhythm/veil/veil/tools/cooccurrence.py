"""Co-occurrence counting over the auxiliary corpus.

The Journalist persona's central move is: "these three details appear together
in the corpus only twice, and both times they refer to the same person."
This tool makes that a count rather than an assertion.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from veil.config import CONFIG
from veil.tools.registry import REGISTRY


def _chunks() -> list[tuple[str, str]]:
    con = sqlite3.connect(CONFIG.storage.db_path)
    try:
        return con.execute("SELECT text, source FROM corpus_chunks").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _matches(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


@REGISTRY.register(
    name="cooccurrence_count",
    description=(
        "Count how many corpus passages contain ALL of the given terms "
        "together, and how many contain each individually. A low joint count "
        "with high individual counts is the signature of an identifying "
        "combination."
    ),
    parameters={
        "type": "object",
        "properties": {
            "terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 literal terms from the document.",
            },
            "window": {
                "type": "string",
                "enum": ["passage", "sentence"],
                "description": "Co-occurrence scope. Default 'passage'.",
            },
        },
        "required": ["terms"],
    },
)
def cooccurrence_count(terms: list[str], window: str = "passage") -> dict[str, Any]:
    terms = [t.strip() for t in terms if t and t.strip()][:5]
    if len(terms) < 2:
        return {"ok": False, "error": "Provide at least two terms."}

    rows = _chunks()
    if not rows:
        return {"ok": False, "error": "Auxiliary corpus is empty — run ingest/corpus_builder.py."}

    individual = {t: 0 for t in terms}
    joint = 0
    examples: list[dict[str, str]] = []

    for text, source in rows:
        units = (
            re.split(r"(?<=[.!?])\s+", text) if window == "sentence" else [text]
        )
        hit_here = False
        for unit in units:
            present = [t for t in terms if _matches(unit, t)]
            if len(present) == len(terms):
                hit_here = True
                if len(examples) < 3:
                    examples.append({"source": source, "text": unit.strip()[:400]})
        for t in terms:
            if _matches(text, t):
                individual[t] += 1
        if hit_here:
            joint += 1

    total = len(rows)
    if joint == 0:
        reading = "No passage contains all terms — this combination is unattested in the corpus."
    elif joint == 1:
        reading = "Exactly one passage contains all terms. If that passage names a person, this combination identifies them."
    elif joint <= 3:
        reading = f"Only {joint} passages contain all terms — a very narrow combination."
    else:
        reading = f"{joint} passages contain all terms — the combination is not distinctive on its own."

    return {
        "ok": True,
        "terms": terms,
        "window": window,
        "corpus_passages": total,
        "individual_counts": individual,
        "joint_count": joint,
        "reading": reading,
        "examples": examples,
    }
