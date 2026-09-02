"""Is retrieval actually finding the right file?

The agent can only answer from what search returns, so a wrong ranking is
indistinguishable from a wrong model. This measures the ranking directly,
against questions whose correct file is not in dispute, and sweeps the weight
that balances dense cosine against literal term overlap.

Run it on any indexed repository; the default cases describe this one.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import rag
from .config import Config
from .llm import LLM
from .rag import Index

#: (question, the file that answers it). Chosen so the answer is unambiguous.
CASES: tuple[tuple[str, str], ...] = (
    ("which module implements the semantic index", "rag.py"),
    ("where is persistent memory stored", "memory.py"),
    ("which module talks to the LLM", "llm.py"),
    ("where are the sandboxed tools defined", "tools.py"),
    ("where is the ReAct agent loop", "agent.py"),
    ("which module measures throughput", "bench.py"),
    ("where is runtime configuration loaded", "config.py"),
)

WEIGHTS = (0.0, 0.15, 0.25, 0.5, 1.0)


def sweep(index_name: str = "default", out: str = "bench-results/retrieval.json",
          cases: tuple[tuple[str, str], ...] = CASES) -> dict:
    cfg = Config()
    idx = Index(cfg, LLM(cfg), index_name)
    rows = idx.db.execute("SELECT path, start_line, end_line, text, vec FROM chunks").fetchall()
    if not rows:
        raise SystemExit(f"index '{index_name}' is empty; run `vulcan index .` first")
    mat = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])

    # Embed each question once and reuse across weights, so the sweep compares
    # ranking rules rather than embedding noise.
    qvecs = {}
    for q, _ in cases:
        v = np.asarray(idx.llm.embed([q])[0], dtype=np.float32)
        qvecs[q] = v / (np.linalg.norm(v) or 1.0)

    results = {}
    for w in WEIGHTS:
        top1 = top3 = 0
        detail = []
        for q, want in cases:
            scores = mat @ qvecs[q] + w * idx._lexical(q, rows)
            order = np.argsort(-scores)[:3]
            paths = [rows[i][0] for i in order]
            hit1 = want in paths[0]
            hit3 = any(want in p for p in paths)
            top1 += hit1
            top3 += hit3
            detail.append({"question": q, "expected": want, "top3": paths,
                           "hit1": bool(hit1), "hit3": bool(hit3)})
        results[str(w)] = {"weight": w, "top1": top1, "top3": top3,
                           "of": len(cases), "detail": detail}
        print(f"weight {w:<5} top1 {top1}/{len(cases)}  top3 {top3}/{len(cases)}", flush=True)

    result = {
        "index": index_name,
        "chunks": len(rows),
        "embed_model": cfg.embed_model,
        "shipped_weight": rag.LEXICAL_WEIGHT,
        "weights": results,
    }
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {p}")
    return result
