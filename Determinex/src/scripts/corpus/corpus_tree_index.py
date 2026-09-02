"""corpus_tree_index.py -- vectorless, reasoning-based retrieval over the markdown corpus.

Why this exists (audited 2026-07-26, see the memory note
`project_corpus_retrieval_vs_pageindex_20260726`)
-------------------------------------------------------------------------------
`determinex_corpus_api.hybrid_search()` is token-overlap blended with cosine
similarity over a local embedding cache. That works well for the few hundred
top-level `build_knowledge` entries it covers, but it is bounded by embedding
throughput: `determinex_corpus_api` itself notes that embedding the 591K verdict
records at real Ollama latency is "NOT attempted". Measured at audit time:

    embedded vectors ............. 240
    markdown files under corpus/ + docs/ ... 2999

So the overwhelming majority of the prose corpus is reachable only by literal
token overlap -- a query phrased differently than the document simply misses.

This module closes that gap with the *other* retrieval paradigm (the one
PageIndex popularised: https://github.com/VectifyAI/PageIndex). Instead of
chunking and embedding every document, it exploits the structure markdown
already has: headings form a natural table-of-contents tree. Retrieval is then
a *navigation* problem -- walk the tree the way a human skims a doc -- rather
than a nearest-neighbour problem.

Consequences that matter here:
  * No per-document embedding pass, so it is not bound by the latency ceiling
    that caps the vector cache at a few hundred entries. Indexing 2,999 files
    is pure file parsing.
  * Retrieval is explainable: the path taken through the tree IS the reason a
    section was returned, which suits a project whose thesis is that claims
    must be checkable.
  * It complements rather than replaces hybrid_search. Structure-aware
    navigation is strong on "where is X discussed"; cosine similarity is strong
    on paraphrase within already-embedded entries. `ask()` can use both.

PROJECT CLOAK -- READ BEFORE CHANGING THE NAVIGATOR
-------------------------------------------------------------------------------
The widely-circulated write-up of this technique claims the privacy risk is the
embedding backend ("swap text-embedding-3-small for a local model"). That is
wrong twice over: this approach uses **no embeddings at all**, and Determinex's
existing embedding path is already local (`nomic-embed-text` on localhost).

The real exposure is larger and sits elsewhere: a reasoning-based index calls an
LLM *at query time* to choose branches, and those calls carry document titles
and section text. A cloud navigator would therefore see corpus content on EVERY
retrieval, not merely once at index time.

So the navigator is pinned to a local Ollama model and this module refuses to
use a non-local one. `navigate()` raises rather than silently falling back --
same fail-closed posture as the cloaked-room flow in the agent chat. If a cloud
navigator is ever genuinely wanted, its context must be routed through
`determinex_cloak` first; there is deliberately no flag here to skip that.

CLI
---
    python scripts/corpus/corpus_tree_index.py build [--roots docs corpus]
    python scripts/corpus/corpus_tree_index.py stats
    python scripts/corpus/corpus_tree_index.py search "<query>" [--k 5]
    python scripts/corpus/corpus_tree_index.py navigate "<query>" [--model TAG]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
for _p in (str(_SCRIPTS), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = _SCRIPTS.parent
INDEX_PATH = ROOT / "corpus" / "programbench" / "tree_index.json"

# Only local Ollama tags are acceptable navigators -- see the Cloak note above.
DEFAULT_NAVIGATOR = os.environ.get("DETERMINEX_TREE_NAVIGATOR", "qwen2.5-coder:7b-instruct")
OLLAMA_URL = os.environ.get("DETERMINEX_OLLAMA_URL", "http://localhost:11434")

_DEFAULT_ROOTS = ("docs", "corpus")
_SKIP_PARTS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".next",
    "target",
    "_superseded",
    "locked",  # archived/duplicated PB artifacts
}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_MAX_PREVIEW = 400


# ---------------------------------------------------------------------------
# Tree model
# ---------------------------------------------------------------------------


@dataclass
class TreeNode:
    """One heading (or a whole file, for the synthetic root of each document)."""

    title: str
    level: int  # 0 = file root, 1..6 = markdown heading depth
    path: str  # repo-relative file path
    line: int  # 1-indexed line where this section starts
    preview: str  # first non-empty prose under the heading
    children: list[TreeNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["children"] = [c.to_dict() for c in self.children]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TreeNode:
        node = TreeNode(
            title=d["title"],
            level=d["level"],
            path=d["path"],
            line=d["line"],
            preview=d.get("preview", ""),
        )
        node.children = [TreeNode.from_dict(c) for c in d.get("children", [])]
        return node

    def walk(self) -> Iterable[TreeNode]:
        yield self
        for c in self.children:
            yield from c.walk()


def _iter_markdown(roots: Iterable[str]) -> Iterable[Path]:
    for r in roots:
        base = ROOT / r
        if not base.exists():
            continue
        for p in base.rglob("*.md"):
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            yield p


def build_document_tree(path: Path) -> TreeNode:
    """Parse one markdown file into a heading tree.

    Fenced code blocks are tracked so that a '#' comment inside ```bash never
    registers as a heading -- that would fabricate structure and, worse, make
    the navigator confident about a section that does not exist.
    """
    rel = path.relative_to(ROOT).as_posix()
    root = TreeNode(title=path.stem, level=0, path=rel, line=1, preview="")
    stack: list[TreeNode] = [root]
    pending: TreeNode | None = root
    in_fence = False

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return root

    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        m = _HEADING_RE.match(raw)
        if m:
            level = len(m.group(1))
            node = TreeNode(
                title=m.group(2).strip() or "(untitled)", level=level, path=rel, line=i, preview=""
            )
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(node)
            stack.append(node)
            pending = node
            continue

        # First prose line after a heading becomes that node's preview.
        if pending is not None and stripped and not stripped.startswith(("|", ">", "<!--")):
            pending.preview = stripped[:_MAX_PREVIEW]
            pending = None

    return root


def build_index(roots: Iterable[str] = _DEFAULT_ROOTS) -> dict[str, Any]:
    docs = [build_document_tree(p) for p in _iter_markdown(roots)]
    index = {
        "version": 1,
        "roots": list(roots),
        "documents": [d.to_dict() for d in docs],
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())  # WAL convention: no write-cache races
    tmp.replace(INDEX_PATH)
    return index


def load_index() -> dict[str, Any] | None:
    if not INDEX_PATH.exists():
        return None
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def index_stats(index: dict[str, Any] | None = None) -> dict[str, Any]:
    idx = index if index is not None else load_index()
    if idx is None:
        return {"built": False, "documents": 0, "nodes": 0}
    docs = [TreeNode.from_dict(d) for d in idx.get("documents", [])]
    nodes = sum(1 for d in docs for _ in d.walk())
    return {
        "built": True,
        "documents": len(docs),
        "nodes": nodes,
        "roots": idx.get("roots", []),
        "index_path": str(INDEX_PATH),
    }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9_]+", s.lower()) if len(t) > 2}


def shortlist(query: str, k: int = 12, index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Cheap structural prefilter over heading paths -- no model call.

    Scores a node by overlap of the query with its own title, its ancestors'
    titles, and its preview. Ancestor titles are included deliberately: a
    section called "Known issues" is meaningless alone but highly relevant
    under "Project Cloak".
    """
    idx = index if index is not None else load_index()
    if idx is None:
        return []
    q = _tokens(query)
    if not q:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for d in idx.get("documents", []):
        root = TreeNode.from_dict(d)

        def visit(node: TreeNode, trail: list[str]) -> None:
            crumb = trail + [node.title]
            title_hits = len(q & _tokens(node.title))
            trail_hits = len(q & _tokens(" ".join(trail)))
            prev_hits = len(q & _tokens(node.preview))
            path_hits = len(q & _tokens(node.path))
            score = (3.0 * title_hits) + (1.5 * trail_hits) + prev_hits + (0.5 * path_hits)
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "title": node.title,
                            "breadcrumb": " > ".join(crumb),
                            "path": node.path,
                            "line": node.line,
                            "preview": node.preview,
                            "score": round(score, 2),
                        },
                    )
                )
            for c in node.children:
                visit(c, crumb)

        visit(root, [])

    scored.sort(key=lambda t: -t[0])
    return [hit for _, hit in scored[:k]]


def _is_local_navigator(model: str) -> bool:
    """Only bare Ollama tags qualify. A provider-prefixed id (openai/...,
    anthropic/..., openrouter/...) means the call would leave the machine."""
    return "/" not in model or model.startswith(("ollama/", "local/"))


def navigate(
    query: str, k: int = 5, model: str | None = None, index: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Shortlist structurally, then let a LOCAL model choose which sections answer the query.

    Raises RuntimeError if asked to use a non-local navigator -- see the Cloak
    note at the top of this module. Fails closed; never silently downgrades.
    """
    nav = model or DEFAULT_NAVIGATOR
    if not _is_local_navigator(nav):
        raise RuntimeError(
            f"refusing to navigate with non-local model '{nav}': the navigator sees corpus "
            "section titles and prose on every query. Use a local Ollama tag, or route the "
            "context through determinex_cloak first."
        )

    cands = shortlist(query, k=max(k * 3, 12), index=index)
    if not cands:
        return {
            "query": query,
            "navigator": nav,
            "selected": [],
            "candidates": 0,
            "note": "no structural candidates -- index may not be built (run `build`)",
        }

    listing = "\n".join(
        f"[{i}] {c['breadcrumb']}  ({c['path']}:{c['line']})\n     {c['preview'][:200]}"
        for i, c in enumerate(cands)
    )
    prompt = (
        f"A user asked: {query}\n\n"
        f"Below are candidate sections from a documentation corpus, shown as\n"
        f"breadcrumb paths through each document's heading tree.\n\n{listing}\n\n"
        f"Reply with ONLY a JSON array of the indices of at most {k} sections that genuinely "
        f"help answer the question, best first, e.g. [3,0,7]. If none are relevant reply []."
    )

    try:
        from swe_agent.inference import _ollama  # canonical helper; do not duplicate

        raw = _ollama(
            nav,
            prompt,
            system="You select relevant documentation sections. Reply with JSON only.",
            temperature=0.0,
            timeout=120,
        )
    except Exception as e:  # noqa: BLE001 - surface honestly, never fake a result
        return {
            "query": query,
            "navigator": nav,
            "selected": [],
            "candidates": len(cands),
            "error": f"navigator unavailable: {e}",
            "fallback": cands[:k],
        }

    picked: list[int] = []
    m = re.search(r"\[[^\]]*\]", raw or "")
    if m:
        try:
            picked = [int(x) for x in json.loads(m.group(0)) if isinstance(x, (int, float))]
        except (ValueError, json.JSONDecodeError):
            picked = []

    selected = [cands[i] for i in picked if 0 <= i < len(cands)][:k]
    return {
        "query": query,
        "navigator": nav,
        "candidates": len(cands),
        "selected": selected or cands[:k],
        "model_selected": bool(selected),  # False => structural fallback, stated plainly
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Vectorless tree retrieval over the markdown corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="parse markdown into a heading tree index")
    p_build.add_argument("--roots", nargs="*", default=list(_DEFAULT_ROOTS))

    sub.add_parser("stats", help="index coverage")

    p_search = sub.add_parser("search", help="structural shortlist, no model call")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=8)

    p_nav = sub.add_parser("navigate", help="shortlist + local-model selection")
    p_nav.add_argument("query")
    p_nav.add_argument("--k", type=int, default=5)
    p_nav.add_argument("--model", default=None)

    a = ap.parse_args()
    if a.cmd == "build":
        idx = build_index(a.roots)
        print(json.dumps(index_stats(idx), indent=2))
    elif a.cmd == "stats":
        print(json.dumps(index_stats(), indent=2))
    elif a.cmd == "search":
        print(json.dumps(shortlist(a.query, a.k), indent=2))
    elif a.cmd == "navigate":
        try:
            print(json.dumps(navigate(a.query, a.k, a.model), indent=2))
        except RuntimeError as e:
            print(json.dumps({"error": str(e)}, indent=2))
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
