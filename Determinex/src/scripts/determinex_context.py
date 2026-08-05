#!/usr/bin/env python3
"""
determinex_context.py -- Context Provisioner (Amplifier piece #4)
==============================================================
A weak model drowns in noise. Hand it the whole repo and it flails; hand it the
exact 200 lines that matter and its per-attempt success p jumps. This assembles
MINIMAL-SUFFICIENT context for a task: the symbols the task/failure references,
the files that define them, ranked by relevance, trimmed to a token budget.

Deterministic and dependency-free (token-overlap ranking, no embeddings needed,
so it runs anywhere a small local model runs). It composes with the Ingester
(language) and the Adjudicator/Explainer (the failing test text drives what
symbols to pull in).

    from determinex_context import provision
    bundle = provision(repo=Path("."), task_text=failure_text, budget_chars=8000)
    prompt = bundle.render()     # ready to prepend to the model prompt
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_SKIP_DIRS = {".git", "node_modules", "target", "vendor", "__pycache__", "dist", "build"}
_CODE_EXT = {
    ".py",
    ".rs",
    ".go",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".kt",
    ".java",
    ".swift",
    ".cs",
    ".rb",
    ".php",
}
_DEF_PAT = re.compile(
    r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|func|def|class|struct|impl|interface|"
    r"type|enum|trait|function|public|private|static)\b.*",
    re.M,
)


@dataclass
class Snippet:
    path: str
    score: float
    text: str


@dataclass
class ContextBundle:
    task_keywords: list[str]
    snippets: list[Snippet] = field(default_factory=list)
    budget_chars: int = 8000

    def render(self) -> str:
        out = ["# Relevant context (minimal-sufficient, ranked):"]
        used = 0
        for s in self.snippets:
            block = f"\n## {s.path}  (relevance {s.score:.1f})\n{s.text}\n"
            if used + len(block) > self.budget_chars:
                break
            out.append(block)
            used += len(block)
        return "\n".join(out)


def _keywords(task_text: str) -> list[str]:
    toks = [t for t in _IDENT.findall(task_text)]
    # keep identifiers that look like symbols (snake/camel/Pascal), drop common words
    common = {
        "the",
        "and",
        "for",
        "test",
        "assert",
        "self",
        "result",
        "stdout",
        "stderr",
        "returncode",
        "error",
        "value",
        "expected",
        "actual",
    }
    seen, out = set(), []
    for t in toks:
        low = t.lower()
        if low in common or low in seen:
            continue
        seen.add(low)
        out.append(t)
    return out[:40]


def _relevant_definitions(text: str, keywords: list[str]) -> list[str]:
    """Pull definition blocks whose signature mentions a keyword."""
    blocks = []
    lines = text.splitlines()
    kwset = {k.lower() for k in keywords}
    for m in _DEF_PAT.finditer(text):
        start = text[: m.start()].count("\n")
        sig = lines[start] if start < len(lines) else m.group(0)
        if any(k in sig.lower() for k in kwset):
            # grab the def + a short body window
            body = "\n".join(lines[start : start + 25])
            blocks.append(body)
    return blocks


def provision(
    repo: Path, task_text: str, budget_chars: int = 8000, max_files: int = 200
) -> ContextBundle:
    keywords = _keywords(task_text)
    kwset = {k.lower() for k in keywords}
    scored: list[Snippet] = []
    n = 0
    for p in repo.rglob("*"):
        if n >= max_files:
            break
        if not p.is_file() or p.suffix.lower() not in _CODE_EXT:
            continue
        if any(seg in _SKIP_DIRS for seg in p.parts):
            continue
        n += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        low = text.lower()
        hits = sum(low.count(k) for k in kwset)
        if hits == 0:
            continue
        defs = _relevant_definitions(text, keywords)
        snippet_text = "\n...\n".join(defs[:4]) if defs else text[:1200]
        # relevance: keyword hits, boosted if definitions matched
        score = hits + (5.0 * len(defs))
        rel = str(p.relative_to(repo)) if repo in p.parents or p.parent == repo else str(p)
        scored.append(Snippet(path=rel, score=score, text=snippet_text[:2000]))
    scored.sort(key=lambda s: s.score, reverse=True)
    return ContextBundle(task_keywords=keywords, snippets=scored[:12], budget_chars=budget_chars)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Context Provisioner")
    ap.add_argument("repo", type=Path)
    ap.add_argument("--task", required=True, help="task / failure text")
    ap.add_argument("--budget", type=int, default=8000)
    args = ap.parse_args()
    b = provision(args.repo, args.task, args.budget)
    print(f"keywords: {' '.join(b.task_keywords[:15])}")
    print(f"selected {len(b.snippets)} snippets (budget {b.budget_chars} chars)")
    for s in b.snippets[:8]:
        print(f"  {s.score:6.1f}  {s.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
