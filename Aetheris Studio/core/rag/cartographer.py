"""Cartographer (Blackbox Fase D): maps a codebase file-by-file into short
markdown summaries in the background, indexed with BM25 (rank_bm25 --
additive, does NOT replace core/memory/tfidf.py, which stays untouched
and keeps serving the existing manage_skill tool). Two consumption modes:

- D.1, `search_map` tool: on-demand, zero new architecture, the model
  decides when to reach for it -- exactly how manage_memory/manage_skill
  already work.
- D.2, automatic pre-turn injection: genuinely new plumbing (no
  precedent anywhere else in this codebase, confirmed) at the
  `conversation` assembly seam in agent.py, behind its OWN sub-flag
  (AETHERIS_CARTOGRAPHER_AUTO_INJECT) so it can be disabled independently
  of D.1 if it ever misbehaves without losing the on-demand fallback.

Idle/cancel signal: reuses the existing core/event_bus.py singleton
(chat_turn_start/chat_turn_end, published from agent.py) for
notification, plus a tiny module-level `_busy_since` flag for the
worker's own point-in-time checks between files -- there is no
generation lock anywhere in this codebase to grab instead (confirmed).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.utils.constants import MAPS_DIR

logger = logging.getLogger(__name__)


def cartographer_enabled() -> bool:
    return os.getenv("AETHERIS_CARTOGRAPHER_ENABLED", "true").lower() == "true"


def cartographer_auto_inject_enabled() -> bool:
    return cartographer_enabled() and os.getenv("AETHERIS_CARTOGRAPHER_AUTO_INJECT", "true").lower() == "true"


# --- idle/busy signal -------------------------------------------------

_busy_since: Optional[float] = None


def _on_turn_start(payload=None) -> None:
    global _busy_since
    _busy_since = time.time()


def _on_turn_end(payload=None) -> None:
    global _busy_since
    _busy_since = None


def _subscribe_bus() -> None:
    from core.event_bus import bus
    bus.subscribe("chat_turn_start", _on_turn_start)
    bus.subscribe("chat_turn_end", _on_turn_end)


_subscribe_bus()


def is_chat_busy() -> bool:
    return _busy_since is not None


# --- hashing / paths ----------------------------------------------------

_SKIP_DIR_NAMES = {
    "__pycache__", ".venv", "venv", "node_modules", ".git",
    "build", ".dart_tool", "ephemeral", ".pytest_cache",
}
# Confirmed real gap: .html/.css were missing entirely, so a project with a
# plain web frontend (no .js framework files) had those files completely
# invisible to search_map/auto-injection -- not "low relevance", literally
# never discovered by _discover_files, so a vague "what's in this project"
# answer silently omitted them with no signal anything was missing.
_SOURCE_EXTENSIONS = {
    ".py", ".dart", ".js", ".jsx", ".ts", ".tsx", ".md",
    ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml",
}
MAX_FILES_PER_PASS = 300
_HYSTERESIS_SECONDS = 3.0


def project_hash(project_path: str) -> str:
    return hashlib.sha256(os.path.realpath(project_path).encode("utf-8")).hexdigest()[:16]


def path_hash(abs_path: str) -> str:
    """Path-based wrapper around the same chunked-SHA256 pattern
    core/utils/upload_handler.py::calculate_file_hash uses (that helper
    takes an already-open file object, not a path)."""
    h = hashlib.sha256()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def _map_dir(project_path: str) -> Path:
    return Path(MAPS_DIR) / project_hash(project_path)


def _index_path(project_path: str) -> Path:
    return _map_dir(project_path) / "_index.json"


def _load_index(project_path: str) -> Dict:
    p = _index_path(project_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_index(project_path: str, index: Dict) -> None:
    """Mirrors markdown_memory.py's round-trip-verification integrity
    pattern: never trust a write that can't be read back identically."""
    from core.atomic_io import atomic_write_json

    p = _index_path(project_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, index)
    reloaded = _load_index(project_path)
    if reloaded != index:
        raise IOError("Cartographer index write did not round-trip -- refusing to trust it")


def _discover_files(project_path: str) -> List[str]:
    results = []
    root = Path(project_path)
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIR_NAMES]
        for name in files:
            if Path(name).suffix.lower() in _SOURCE_EXTENSIONS:
                rel = str(Path(current, name).relative_to(root)).replace(os.sep, "/")
                results.append(rel)
        if len(results) >= MAX_FILES_PER_PASS:
            break
    return sorted(results)[:MAX_FILES_PER_PASS]


def _map_file_path(project_path: str, rel_path: str) -> Path:
    safe_rel = rel_path.replace("/", "__").replace("\\", "__")
    return _map_dir(project_path) / "MAP" / f"{safe_rel}.md"


def _render_map_doc(rel_path: str, source_hash: str, structure: Dict, summary: str, stage: str) -> str:
    from datetime import datetime, timezone

    mapped_at = datetime.now(timezone.utc).isoformat()
    lines = [
        "---",
        f"source: {rel_path}",
        f"source_hash: sha256:{source_hash}",
        f"mapped_at: {mapped_at}",
        f"stage: {stage}",
        "---",
        f"# {rel_path}",
    ]
    if summary:
        lines += ["", "## Responsabilidade", summary]
    lines += ["", "## Estrutura"]
    for cls in structure.get("classes", []):
        lines.append(f"- class {cls}")
    for fn in structure.get("functions", []):
        lines.append(f"- def {fn}")
    if not structure.get("classes") and not structure.get("functions"):
        lines.append(f"- ({structure.get('line_count', 0)} lines, no functions/classes detected)")
    return "\n".join(lines) + "\n"


# --- LLM summarization (stage B) -----------------------------------------

async def _summarize_with_llm(rel_path: str, structure: Dict, text_snippet: str) -> Optional[str]:
    import asyncio

    from core.utils.settings import get_setting
    from core.utils.vte_bridge import VTE_DEFAULT_MODEL, generate_once

    model = get_setting("default_model", "") or VTE_DEFAULT_MODEL
    struct_bits = ", ".join((structure.get("classes", []) + structure.get("functions", []))[:15])
    prompt = (
        f"File: {rel_path}\n"
        f"Detected structure: {struct_bits or '(none detected)'}\n"
        f"First lines:\n{text_snippet[:800]}\n\n"
        "In 2 short sentences: what is this file's responsibility, and any coding "
        "convention it clearly follows? Be concrete, no filler, no preamble."
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        # generate_once is synchronous (a plain httpx.post) -- run it off
        # the event loop so a slow summarization call doesn't block the
        # rest of the backend while the Cartographer worker waits on it.
        result = await asyncio.to_thread(generate_once, model, messages, 0.3, 150)
        return result.strip()
    except Exception as e:
        logger.warning("Cartographer summarization failed for %s (structural-only entry kept): %s", rel_path, e)
        return None


# --- the mapping pass ------------------------------------------------

async def _map_one_pending_file(project_path: str) -> bool:
    """Maps exactly one changed/new file, or returns False if nothing is
    pending. Returns False also (mid-file) if the chat goes busy, so the
    caller's own loop re-checks idleness before trying the next file --
    bounded to at most one file's worth of work past a new message
    arriving, never more."""
    from core.rag.structural_extract import extract_structure

    index = _load_index(project_path)
    files = _discover_files(project_path)

    for rel_path in files:
        if is_chat_busy():
            return False
        abs_path = os.path.join(project_path, rel_path)
        try:
            current_hash = path_hash(abs_path)
        except OSError:
            continue
        entry = index.get(rel_path)
        if entry and entry.get("source_hash") == current_hash and entry.get("stage") == "full":
            continue

        try:
            text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        structure = extract_structure(rel_path, text)

        # Stage A (structural, no LLM) always runs and is saved immediately
        # -- partial progress is never lost even if stage B below fails or
        # gets interrupted by a new chat message.
        index[rel_path] = {"source_hash": current_hash, "mapped_at": time.time(), "stage": "structural"}
        _save_index(project_path, index)
        doc_path = _map_file_path(project_path, rel_path)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(_render_map_doc(rel_path, current_hash, structure, "", "structural"), encoding="utf-8")

        if not is_chat_busy():
            summary = await _summarize_with_llm(rel_path, structure, text)
            if summary and not is_chat_busy():
                index[rel_path] = {"source_hash": current_hash, "mapped_at": time.time(), "stage": "full"}
                _save_index(project_path, index)
                doc_path.write_text(_render_map_doc(rel_path, current_hash, structure, summary, "full"), encoding="utf-8")

        build_bm25_index(project_path)
        return True

    return False


async def mapping_status(project_path: str) -> Dict:
    index = _load_index(project_path)
    total = len(_discover_files(project_path))
    mapped = sum(1 for e in index.values() if e.get("stage") == "full")
    structural_only = sum(1 for e in index.values() if e.get("stage") == "structural")
    state = "idle" if mapped + structural_only >= total and total > 0 else ("mapping" if is_chat_busy() is False else "paused")
    return {"mapped": mapped, "structural_only": structural_only, "total": total, "state": state}


async def run_worker() -> None:
    """Background asyncio task (started from app.py's lifespan). Waits for
    the chat to be idle for _HYSTERESIS_SECONDS before starting -- doesn't
    steal the GPU between two quick back-to-back user messages -- then
    maps one pending file at a time from whatever project is currently
    active, re-checking idleness between every file."""
    import asyncio

    from core.utils.project_path import get_active_project_path

    idle_since: Optional[float] = None
    while True:
        await asyncio.sleep(1.0)
        try:
            if not cartographer_enabled() or is_chat_busy():
                idle_since = None
                continue
            if idle_since is None:
                idle_since = time.time()
            if time.time() - idle_since < _HYSTERESIS_SECONDS:
                continue

            active_project = get_active_project_path()
            if not active_project or not os.path.isdir(active_project):
                continue

            did_work = await _map_one_pending_file(active_project)
            if not did_work:
                await asyncio.sleep(5.0)  # nothing pending -- back off
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Cartographer worker tick failed (skipped): %s", e)


# --- BM25 index -----------------------------------------------------------

# project_path -> (BM25Okapi | None, [(doc_text, meta_dict), ...])
_bm25_cache: Dict[str, Tuple[object, List[Tuple[str, Dict]]]] = {}


def build_bm25_index(project_path: str) -> None:
    """Rebuilds the in-memory BM25 index over the current MAP/*.md corpus.
    Cheap enough to call after every single file re-map (small corpora,
    same cost justification core/memory/tfidf.py's own docstring already
    makes for skills)."""
    from rank_bm25 import BM25Okapi

    docs: List[str] = []
    meta: List[Dict] = []
    map_dir = _map_dir(project_path) / "MAP"
    if map_dir.is_dir():
        for f in sorted(map_dir.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            docs.append(text)
            meta.append({"origin": "map", "file": f.name})

    if not docs:
        _bm25_cache[project_path] = (None, [])
        return

    tokenized = [d.lower().split() for d in docs]
    bm25 = BM25Okapi(tokenized)
    _bm25_cache[project_path] = (bm25, list(zip(docs, meta)))


# Greetings/acks/small-talk -- deliberately not a real intent classifier,
# just the obvious non-questions. PT + EN since the project is used in
# both.
_TRIVIAL_MESSAGE_RE = re.compile(
    r"^(hi|hello|hey|yo|oi|ol[aá]|e a[ií]|salve|tudo bem\??|tudo bom\??|"
    r"beleza\??|blz|obrigad[oa]s?|obg|vlw|valeu|thanks?( you)?|ok(ay)?|"
    r"sim|n[aã]o|yes|nope?|bom dia|boa tarde|boa noite|good (morning|"
    r"afternoon|evening|night))[\s!.,?]*$",
    re.IGNORECASE,
)


def looks_like_codebase_query(text: str) -> bool:
    """Cheap gate for whether a user message is worth spending a
    Cartographer lookup on. Confirmed live: without this, a bare "hi" got
    the map auto-injected anyway -- query_map deliberately never returns
    empty for a non-empty corpus (see its own docstring: BM25 scores can
    all floor to 0 on a small index, and that's not treated as "no
    match") -- so the model saw project file content in its system
    context before replying to a greeting, and answered about "the
    Cartographer map" instead of just greeting back. This only filters
    the obvious non-questions (greetings, short acks); it is not an
    intent classifier and isn't meant to be."""
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    return not _TRIVIAL_MESSAGE_RE.match(stripped)


def query_map(project_path: str, query: str, top_k: int = 3) -> List[Dict]:
    if project_path not in _bm25_cache:
        build_bm25_index(project_path)
    bm25, corpus = _bm25_cache.get(project_path, (None, []))
    if bm25 is None or not corpus or not query.strip():
        return []
    scores = bm25.get_scores(query.lower().split())
    # Not filtering on `score > 0`: rank_bm25's classic Okapi IDF can floor
    # a term's contribution to exactly 0 in a small corpus where it
    # appears in most/all documents (confirmed directly -- see this
    # module's test suite), which is the normal case for an
    # early/small-project Cartographer index, not a sign of irrelevance.
    # Rank order is still meaningful even when the raw scores are tiny or
    # tied; only an empty corpus (handled above) returns nothing.
    ranked = sorted(zip(scores, corpus), key=lambda x: x[0], reverse=True)[:top_k]
    return [
        {"score": float(score), "origin": m["origin"], "file": m.get("file"), "text": text}
        for score, (text, m) in ranked
    ]
