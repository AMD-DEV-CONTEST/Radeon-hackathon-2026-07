#!/usr/bin/env python3
"""determinex_corpus_api.py -- READ-ONLY query surface over corpus/programbench/build_knowledge.json
(prose knowledge) AND corpus/programbench/canonical_tasks.json (structured per-task ground truth).

Every other corpus consumer (_build_knowledge_playbook, the absorber, the flywheel) reads this file
ad hoc with its own bespoke json.loads + key-poking. There has never been a single place a HUMAN (via
the frontend/Learning Studio) or a NEW script could ask the corpus a question. This is that place.

Read-only by design: nothing here writes to build_knowledge.json or canonical_tasks.json. Writers stay
exactly where they already are (determinex_pb_amplified_fix.learn_class, determinex_pb_absorb.absorb,
pb_canonical_tasks.py) -- this module only ever loads and searches.

Sections queried:
  * _topic_index          -- coarse topic -> [{key, summary}] index of the ~70 dated corpus entries
  * class_patterns         -- the proven (detect/symptom/fix[/applies_to/generalized_in]) playbook
  * learned_classes        -- (symptom->fix) pairs from TWO sources, and the split matters. The
                              2026-07-16 quarantine emptied it and this doc then claimed it "grows
                              ONLY from verified=True entries going forward" -- which was true for
                              two days. The 2026-07-18 salvage readmitted 234 quarantined entries as
                              UNVERIFIED hints, and determinex_pb_absorb still writes verified=false.
                              Actual state 2026-07-28: 272 entries, 5 verified, 267 absorbed prose.
                              Sound anyway -- the oracle gates the next use, so a wrong hint costs an
                              attempt and never a false pass -- but do not read this as a verified
                              corpus. determinex_pb_amplified_fix tags each line with its provenance.
  * top-level dated entries -- every other key in the file (the ~70+ named corpus write-ups)
  * canonical_tasks.json   -- per-task ground truth (repository, pinned commit, language, test counts)
                              for all ~200 ProgramBench tasks, built by pb_canonical_tasks.py from the
                              harness's own task.yaml files. Added 2026-07-16 after a real miss: a
                              provenance check re-derived repository/commit by manually grepping the
                              T: drive instead of querying this already-built index -- see
                              corpus_gap_canonical_tasks_not_queryable_20260716 in build_knowledge.json.
                              A keyed lookup (task_provenance) is used here, not the token-overlap
                              search() below -- this is an exact structured record, not fuzzy prose.
  * general_engineering_playbook -- corpus/general_engineering_playbook.json, a SEPARATE file
                              (not build_knowledge.json). General, non-ProgramBench-specific
                              engineering lessons distilled FROM the PB campaign's class_patterns,
                              stripped of tool-specific framing -- see general_engineering_
                              playbook()'s docstring. Searched only for the default corpus.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "corpus" / "programbench" / "build_knowledge.json"
)
CANONICAL_TASKS_PATH = (
    Path(__file__).resolve().parent.parent / "corpus" / "programbench" / "canonical_tasks.json"
)
SWEBENCH_DIR = Path(__file__).resolve().parent.parent / "corpus" / "swebench"
TERMINAL_BENCH_DIR = Path(__file__).resolve().parent.parent / "corpus" / "terminal_bench"
VERDICT_CORPUS_PATH = (
    Path(__file__).resolve().parent.parent
    / "corpus"
    / "programbench"
    / "training_corpus"
    / "pb_verdict_corpus.jsonl"
)
# General, non-tool-specific engineering lessons distilled FROM the ProgramBench campaign's
# class_patterns (build_knowledge.json), stripped of PB-specific framing so they transfer to any
# project a user brings through the Hive loop. Deliberately top-level in corpus/, not under
# corpus/programbench/ -- this is general knowledge, not PB campaign data. See the file's own
# _doc field for the full rationale.
GENERAL_PLAYBOOK_PATH = (
    Path(__file__).resolve().parent.parent / "corpus" / "general_engineering_playbook.json"
)

# Keys that are structural/bookkeeping, not searchable knowledge entries.
_NON_ENTRY_KEYS = frozenset(
    {
        "_topic_index",
        "class_patterns",
        "learned_classes",
        "absorbed_sources",
    }
)


@dataclass
class SearchHit:
    source: str  # "topic" | "class_pattern" | "learned_class" | "entry"
    key: str
    title: str
    snippet: str
    score: int
    topic: str = ""


@dataclass
class CorpusStats:
    total_top_level_entries: int
    topics: list[str] = field(default_factory=list)
    class_pattern_count: int = 0
    learned_class_count: int = 0
    learned_class_verified_count: int = 0
    quarantined_keys: list[str] = field(default_factory=list)
    quarantined_count: int = 0


def load_corpus(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def topics(corpus: dict[str, Any] | None = None) -> list[str]:
    kn = corpus if corpus is not None else load_corpus()
    ti = kn.get("_topic_index", {})
    return sorted(ti.keys()) if isinstance(ti, dict) else []


def topic_entries(topic: str, corpus: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """The [{key, summary}] list the _topic_index carries for one topic, resolved against the
    top-level corpus entry for each key when the index summary is blank (many index rows were
    written with an empty summary and rely on the entry itself)."""
    kn = corpus if corpus is not None else load_corpus()
    ti = kn.get("_topic_index", {})
    rows = ti.get(topic, []) if isinstance(ti, dict) else []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", ""))
        summary = str(row.get("summary", "") or "")
        if not summary:
            entry = kn.get(key)
            if isinstance(entry, str):
                summary = entry[:240]
            elif isinstance(entry, dict):
                summary = str(entry.get("_doc") or entry.get("summary") or "")[:240]
        out.append({"key": key, "summary": summary})
    return out


def get_entry(key: str, corpus: dict[str, Any] | None = None) -> Any:
    """Resolve any top-level corpus key (a dated write-up, class_patterns entry, etc.)."""
    kn = corpus if corpus is not None else load_corpus()
    return kn.get(key)


def class_patterns(corpus: dict[str, Any] | None = None) -> dict[str, Any]:
    kn = corpus if corpus is not None else load_corpus()
    cp = kn.get("class_patterns", {})
    return cp if isinstance(cp, dict) else {}


def get_class_pattern(key: str, corpus: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cp = class_patterns(corpus)
    v = cp.get(key)
    return v if isinstance(v, dict) else None


def learned_classes(
    verified_only: bool = True, corpus: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The live flywheel. By construction (post 2026-07-16 quarantine + the learn_class writer)
    every entry here has verified=True; `verified_only` is kept as an explicit safety filter so a
    future writer can never silently leak an unverified row into what callers treat as trustworthy."""
    kn = corpus if corpus is not None else load_corpus()
    lc = kn.get("learned_classes", {})
    if not isinstance(lc, dict):
        return {}
    if not verified_only:
        return dict(lc)
    return {k: v for k, v in lc.items() if isinstance(v, dict) and v.get("verified")}


_GENERAL_PLAYBOOK_CACHE: dict[str, Any] | None = None


def general_engineering_playbook(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The general (non-PB-tool-specific) engineering lessons in corpus/general_engineering_
    playbook.json, keyed by entry id. Read-only, separate file from build_knowledge.json (it is
    NOT ProgramBench campaign data -- it is what was distilled OUT of that campaign's
    class_patterns once stripped of tool-specific framing), so it is loaded and cached
    independently rather than folded into load_corpus()'s single big JSON.

    Missing file -> {} rather than raising: this playbook is additive value, never a hard
    dependency of the query surface (same contract as corpus_embeddings/corpus_fts).
    """
    global _GENERAL_PLAYBOOK_CACHE
    p = path or GENERAL_PLAYBOOK_PATH
    if path is None and _GENERAL_PLAYBOOK_CACHE is not None:
        return _GENERAL_PLAYBOOK_CACHE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return {}
    result = {e["id"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str)}
    if path is None:
        _GENERAL_PLAYBOOK_CACHE = result
    return result


def stats(corpus: dict[str, Any] | None = None) -> CorpusStats:
    kn = corpus if corpus is not None else load_corpus()
    tops = topics(kn)
    cp = class_patterns(kn)
    lc_all = kn.get("learned_classes", {})
    lc_all = lc_all if isinstance(lc_all, dict) else {}
    lc_verified = learned_classes(verified_only=True, corpus=kn)
    quarantine_keys = sorted(k for k in kn if k.startswith("learned_classes_quarantine_"))
    quarantined_count = 0
    for qk in quarantine_keys:
        q = kn.get(qk)
        if isinstance(q, dict):
            entries = q.get("entries")
            quarantined_count += (
                len(entries) if isinstance(entries, dict) else int(q.get("count") or 0)
            )
    entry_keys = [k for k in kn if k not in _NON_ENTRY_KEYS and not k.startswith("_")]
    return CorpusStats(
        total_top_level_entries=len(entry_keys),
        topics=tops,
        class_pattern_count=len(cp),
        learned_class_count=len(lc_all),
        learned_class_verified_count=len(lc_verified),
        quarantined_keys=quarantine_keys,
        quarantined_count=quarantined_count,
    )


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def search(query: str, limit: int = 10, corpus: dict[str, Any] | None = None) -> list[SearchHit]:
    """Token-overlap ranked search across topic-index summaries, class_patterns, verified
    learned_classes, and every top-level dated entry's stringified content. No embeddings, no
    network -- deterministic and fast, matching the rest of this corpus's query style
    (_build_knowledge_playbook uses the identical token-overlap approach for ranking)."""
    kn = corpus if corpus is not None else load_corpus()
    qtoks = _tokens(query)
    if not qtoks:
        return []
    hits: list[SearchHit] = []

    ti = kn.get("_topic_index", {})
    if isinstance(ti, dict):
        for topic, rows in ti.items():
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                key, summary = str(row.get("key", "")), str(row.get("summary", "") or "")
                score = len(qtoks & _tokens(key + " " + summary))
                if score:
                    hits.append(
                        SearchHit(
                            "topic",
                            key,
                            key.replace("_", " "),
                            summary[:220] or "(no summary; see full entry)",
                            score,
                            topic,
                        )
                    )

    for key, v in class_patterns(kn).items():
        if not isinstance(v, dict):
            continue
        blob = " ".join(str(v.get(f, "")) for f in ("detect", "symptom", "fix", "applies_to"))
        score = len(qtoks & _tokens(key + " " + blob))
        if score:
            hits.append(
                SearchHit(
                    "class_pattern", key, key.replace("_", " "), str(v.get("fix", ""))[:220], score
                )
            )

    # general_engineering_playbook is a SEPARATE file (not part of `kn`/build_knowledge.json --
    # see general_engineering_playbook()'s docstring), so it is only searched when the caller is
    # querying the default corpus, matching how corpus=None means "the real deployed corpus."
    # An explicit scoped `corpus` argument (tests, hybrid_search's contamination guard) must not
    # pull in this always-loaded-from-disk file.
    if corpus is None:
        for key, v in general_engineering_playbook().items():
            if not isinstance(v, dict):
                continue
            blob = " ".join(str(v.get(f, "")) for f in ("lesson", "why_it_generalizes", "category"))
            score = len(qtoks & _tokens(key + " " + blob))
            if score:
                hits.append(
                    SearchHit(
                        "general_playbook",
                        key,
                        key.replace("_", " "),
                        str(v.get("lesson", ""))[:220],
                        score,
                        str(v.get("category", "")),
                    )
                )

    for key, v in learned_classes(verified_only=True, corpus=kn).items():
        if not isinstance(v, dict):
            continue
        blob = str(v.get("detect", "")) + " " + str(v.get("fix", ""))
        score = len(qtoks & _tokens(blob))
        if score:
            hits.append(
                SearchHit(
                    "learned_class",
                    key,
                    str(v.get("source_tool", key)),
                    str(v.get("fix", ""))[:220],
                    score,
                )
            )

    for key, v in kn.items():
        if (
            key in _NON_ENTRY_KEYS
            or key.startswith("_")
            or key.startswith("learned_classes_quarantine_")
        ):
            continue
        blob = (
            v
            if isinstance(v, str)
            else json.dumps(v)[:4000]
            if isinstance(v, (dict, list))
            else str(v)
        )
        score = len(qtoks & _tokens(key + " " + blob[:2000]))
        if score:
            snippet = blob[:220] if isinstance(blob, str) else ""
            hits.append(SearchHit("entry", key, key.replace("_", " "), snippet, score))

    # DEDUPE by key: the SAME key can score differently across categories (a topic-index
    # summary vs the fuller raw top-level entry commonly disagree, e.g. 3 vs 6) -- without this,
    # any consumer building a {key: hit} index (hybrid_search below; any future one) silently
    # keeps whichever hit happened to sort last, which is the LOWER score, not the best one.
    # Found 2026-07-19 while hybrid_search was demoting entries that plain search() ranked #1.
    best_by_key: dict[str, SearchHit] = {}
    for h in hits:
        prior = best_by_key.get(h.key)
        if prior is None or h.score > prior.score:
            best_by_key[h.key] = h
    deduped = sorted(best_by_key.values(), key=lambda h: h.score, reverse=True)
    return deduped[:limit]


# corpus_embeddings._entries() (and corpus_fts, which reuses it) namespace class_pattern and
# learned_class keys to avoid colliding with an unrelated top-level entry. search() above emits
# those same rows under their BARE key and already dedupes across categories by bare key. So the
# two key spaces disagreed, and a class_pattern could never blend in hybrid_search -- its lexical
# hit ("collection_cap") and its semantic hit ("class_pattern::collection_cap") were two separate
# rows competing with each other instead of one reinforced row. Normalising here makes the blend
# agree with search()'s own long-standing bare-key contract.
_BLEND_NS_PREFIXES = ("class_pattern::", "learned_class::")


def _blend_key(key: str) -> str:
    for prefix in _BLEND_NS_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix) :]
    return key


def hybrid_search(
    query: str,
    limit: int = 10,
    corpus: dict[str, Any] | None = None,
    semantic_weight: float = 0.5,
    bm25_share: float = 0.7,
) -> list[SearchHit]:
    """search() finds a query only if it shares literal tokens with an entry -- "missing
    dependency" will not find an entry written as "package not found" (2026-07-18 audit finding:
    "no embeddings, no BM25, no reranking, deliberately... synonyms and paraphrases... are
    invisible"). This blends three signals:

      * token overlap        -- search() above
      * BM25                 -- scripts/corpus/corpus_fts.py, SQLite FTS5, stdlib-only
      * cosine similarity    -- scripts/corpus/corpus_embeddings.py (Ollama nomic-embed-text,
                                NOT Postgres/pgvector, so basic operation never depends on an
                                external service)

    BM25 and token overlap measure the SAME thing (literal match), so BM25 does not get its own
    third of the weight -- that would count lexical twice and drown the semantic signal. Instead
    the existing lexical budget `(1 - semantic_weight)` is split between them, `bm25_share` to
    BM25 and the rest to token overlap. The semantic/lexical balance callers already tuned via
    semantic_weight is therefore unchanged; only the quality of the lexical half improves.

    Every non-token-overlap leg is best-effort: if Ollama is unreachable, or SQLite was built
    without FTS5, or the FTS index has not been built, those legs return [] and this degrades to
    exactly search()'s token-overlap ranking. Neither is a hard dependency of the query surface.

    Passing an explicit `corpus` ALSO disables both auxiliary legs, because their indexes are
    built from the default corpus and cannot answer for a different one -- see the comment at
    use_global_indexes. A scoped query therefore returns pure token-overlap ranking.
    """
    lexical = search(query, limit=max(limit * 3, 20), corpus=corpus)
    lex_by_key = {_blend_key(h.key): h for h in lexical}
    max_lex = max((h.score for h in lexical), default=1) or 1

    # Both auxiliary legs read PREBUILT GLOBAL indexes (the embeddings cache; the FTS5 db) that
    # were derived from the DEFAULT corpus. Neither takes a corpus argument, so against an
    # explicit `corpus` they would inject hits from documents the caller did not ask about --
    # scoring a subset query with the full corpus's contents. Only token overlap actually honours
    # `corpus`, so when one is supplied this narrows to that sound leg alone.
    # Found via test_ask_composes_search_related_and_supersession_warnings: with a synthetic
    # fixture corpus, real-corpus BM25 hits outranked the fixture's own entry and displaced it
    # out of ask()'s top-5 supersession check. The semantic leg had the same latent flaw but hid
    # it by returning [] whenever Ollama was unreachable.
    use_global_indexes = corpus is None
    sem_hits: list[dict[str, Any]] = []
    fts_hits: list[dict[str, Any]] = []

    # Package-qualified (`corpus` is a package via scripts/corpus/__init__.py) so these resolve
    # under pyrightconfig.json's extraPaths=["scripts"]. Both imports stay INSIDE the function:
    # corpus_embeddings imports this module at its top level, so a module-level import here
    # would be circular. Lazy import keeps that cycle from ever forming.
    _scripts_dir = str(Path(__file__).resolve().parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)

    if use_global_indexes:
        try:
            from corpus import corpus_embeddings  # noqa: PLC0415

            sem_hits = corpus_embeddings.semantic_search(query, k=max(limit * 3, 20))
        except Exception:
            sem_hits = []
    sem_by_key: dict[str, float] = {}
    sem_meta: dict[str, dict[str, Any]] = {}
    for h in sem_hits:
        k = _blend_key(h["key"])
        if h["score"] > sem_by_key.get(k, float("-inf")):
            sem_by_key[k] = h["score"]
            sem_meta[k] = h

    if use_global_indexes:
        try:
            from corpus import corpus_fts  # noqa: PLC0415

            fts_hits = corpus_fts.bm25_search(query, k=max(limit * 3, 20))
        except Exception:
            fts_hits = []
    fts_by_key: dict[str, float] = {}
    fts_meta: dict[str, dict[str, Any]] = {}
    for h in fts_hits:
        k = _blend_key(h["key"])
        if h["score"] > fts_by_key.get(k, float("-inf")):
            fts_by_key[k] = h["score"]
            fts_meta[k] = h

    lex_total = 1 - semantic_weight
    # No BM25 leg (no FTS5, or index unbuilt) -> token overlap keeps the whole lexical budget,
    # which reproduces this function's pre-BM25 behavior exactly.
    w_bm25 = lex_total * bm25_share if fts_by_key else 0.0
    w_tok = lex_total - w_bm25

    all_keys = set(lex_by_key) | set(sem_by_key) | set(fts_by_key)
    scored: list[tuple[float, SearchHit]] = []
    for key in all_keys:
        lex_norm = (lex_by_key[key].score / max_lex) if key in lex_by_key else 0.0
        sem_norm = max(sem_by_key.get(key, 0.0), 0.0)  # cosine in [-1,1]; clip negative to 0
        bm_norm = fts_by_key.get(key, 0.0)  # already normalised to (0,1]
        blended = w_tok * lex_norm + semantic_weight * sem_norm + w_bm25 * bm_norm
        if key in lex_by_key:
            h = lex_by_key[key]
        else:
            meta = fts_meta.get(key) or sem_meta.get(key) or {}
            source = "bm25" if key in fts_meta else "semantic"
            h = SearchHit(
                source,
                key,
                key.replace("_", " "),
                str(meta.get("snippet", ""))[:220],
                0,
                str(meta.get("topic", "")),
            )
        scored.append((blended, h))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [h for _, h in scored[:limit]]


@dataclass
class TaskProvenance:
    id: str
    repository: str | None
    commit: str | None
    language: str | None
    difficulty: str | None
    total_tests: int | None
    expected_active_tests: int | None
    source_citation: dict[str, str]
    match_field: str  # "id" | "repo_name" | "repo_full" | "slug_base"


def load_canonical_tasks(path: Path | None = None) -> dict[str, Any]:
    p = path or CANONICAL_TASKS_PATH
    if not p.exists():
        return {"official_task_count": 0, "tasks": []}
    return json.loads(p.read_text(encoding="utf-8"))


def task_provenance(query: str, canonical: dict[str, Any] | None = None) -> TaskProvenance | None:
    """Look up the ground-truth (repository, pinned commit) for a ProgramBench task by id
    ('isona__dirble.e2dea9f'), bare slug ('dirble'), or full 'owner/repo'. This is the single
    place any provenance check (or any other script) should get this fact -- never re-derive
    it by grepping T:/Dev/ProgramBench's filesystem directly; that path was the exact miss this
    function exists to close."""
    ct = canonical if canonical is not None else load_canonical_tasks()
    q = query.strip().lower()
    for task in ct.get("tasks", []):
        task_id = str(task.get("id", ""))
        repo = str(task.get("repository") or "")
        repo_name = repo.split("/")[-1].lower()
        base = task_id.rsplit(".", 1)[0]
        slug = base.split("__", 1)[1] if "__" in base else base

        match_field = None
        if q == task_id.lower():
            match_field = "id"
        elif q == repo.lower():
            match_field = "repo_full"
        elif q == repo_name:
            match_field = "repo_name"
        elif q == slug.lower() or q == base.lower():
            match_field = "slug_base"

        if match_field:
            return TaskProvenance(
                id=task_id,
                repository=task.get("repository"),
                commit=task.get("commit"),
                language=task.get("language"),
                difficulty=task.get("difficulty"),
                total_tests=task.get("total_tests"),
                expected_active_tests=task.get("expected_active_tests"),
                source_citation=task.get("source_citation", {}),
                match_field=match_field,
            )
    return None


def _pb_json(name: str) -> Any:
    p = CANONICAL_TASKS_PATH.parent / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def tool_status(query: str) -> dict[str, Any]:
    """FEDERATED per-tool view: one query joins every siloed store's row for a tool -- provenance
    (canonical_tasks), eval standing (eval_index), lock status (verified_locks), capability_map,
    ceiling_register, and build_knowledge.per_tool. This is the 'all-seeing' single answer to
    'where does <tool> stand?' that previously required opening 6 files by hand. Keyed matching
    (slug / task id / owner__repo), same discipline as task_provenance -- structured facts get
    keyed lookups, not token-overlap search."""
    q = query.strip().lower()
    out: dict[str, Any] = {"query": query}

    prov = task_provenance(query)
    out["provenance"] = prov.__dict__ if prov else None
    ids = {q}
    if prov:
        ids |= {prov.id.lower(), prov.id.rsplit(".", 1)[0].lower()}
        base = prov.id.rsplit(".", 1)[0]
        ids.add((base.split("__", 1)[1] if "__" in base else base).lower())

    def _m(s: str) -> bool:
        s = s.lower()
        return s in ids or any(
            s.startswith(i + ".")
            or i.endswith("__" + s)
            or s.endswith("__" + i)
            or s.split("__")[-1].split(".")[0] == i
            for i in ids
            if i
        )

    ei = _pb_json("eval_index.json")
    out["eval_index"] = next(
        (r for r in ei or [] if isinstance(r, dict) and _m(str(r.get("slug", "")))), None
    )
    vl = _pb_json("verified_locks.json") or {}
    locks = vl.get("locks", {}) if isinstance(vl, dict) else {}
    out["verified_lock"] = next((v for k, v in locks.items() if _m(k)), None)
    cm = _pb_json("capability_map.json") or {}
    bt = cm.get("by_tool", {}) if isinstance(cm, dict) else {}
    out["capability"] = next((v for k, v in bt.items() if _m(k)), None)
    cr = _pb_json("ceiling_register.json") or {}
    crt = cr.get("tools", {}) if isinstance(cr, dict) else {}
    out["ceiling"] = next((v for k, v in crt.items() if _m(k)), None)
    kn = load_corpus()
    pt = kn.get("per_tool", {})
    out["build_knowledge_per_tool"] = next(
        (v for k, v in pt.items() if isinstance(k, str) and _m(k)), None
    )
    # X-RAY: the per-eval failure-function breakdown (mode, %, to_fix_by_category) from
    # xray_index.json -- summarized (fail_funcs elided) so the federated view stays readable.
    xr = _pb_json("xray_index.json")
    row = next((r for r in xr or [] if isinstance(r, dict) and _m(str(r.get("slug", "")))), None)
    out["xray"] = {k: v for k, v in row.items() if k != "fail_funcs"} if row else None
    out["found_in"] = [
        k
        for k in (
            "provenance",
            "eval_index",
            "verified_lock",
            "capability",
            "ceiling",
            "build_knowledge_per_tool",
            "xray",
        )
        if out.get(k)
    ]
    return out


def _swe_json(name: str) -> Any:
    try:
        return json.loads((SWEBENCH_DIR / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def swebench_stats() -> dict[str, Any]:
    """The corpus/swebench/README.md summary (datasets, global_repos, totals) as structured
    data -- was documented but had no code consumer (2026-07-19 wiring census)."""
    return _swe_json("swebench_inventory.json") or {}


def swebench_repo_info(repo: str) -> dict[str, Any] | None:
    """Per-repo aggregated metadata (instance count, languages, dataset breakdown, most-touched
    files) from swebench_repo_clusters.json, keyed 'owner/repo' (e.g. 'astropy/astropy'). Same
    keyed-lookup discipline as task_provenance -- an exact structured record, not fuzzy search."""
    clusters = _swe_json("swebench_repo_clusters.json")
    if not isinstance(clusters, dict):
        return None
    if repo in clusters:
        return clusters[repo]
    low = repo.lower()
    for k, v in clusters.items():
        if k.lower() == low or k.lower().endswith("/" + low):
            return v
    return None


def _tb_json(name: str) -> Any:
    try:
        return json.loads((TERMINAL_BENCH_DIR / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def terminal_bench_stats() -> dict[str, Any]:
    """The corpus/terminal_bench/README.md inventory (task count, difficulty breakdown, harness
    shape) as structured data -- was documented but had no code consumer (2026-07-19)."""
    return _tb_json("inventory.json") or {}


def terminal_bench_task(name: str) -> dict[str, Any] | None:
    """Look up one Terminal-Bench task's {task, difficulty, author} by slug, e.g.
    'acl-permissions-inheritance'. Keyed lookup over task_index.json's 241 rows."""
    rows = _tb_json("task_index.json")
    if not isinstance(rows, list):
        return None
    low = name.lower()
    return next(
        (r for r in rows if isinstance(r, dict) and str(r.get("task", "")).lower() == low), None
    )


# ---------------------------------------------------------------------------
# Verdict corpus (corpus/programbench/training_corpus/pb_verdict_corpus.jsonl)
# ---------------------------------------------------------------------------
# 9GB, ~591K lines, mixed schema (model-training "conversations" records +
# per-tool "slug"/"verdict"/"root_cause"/"fix_summary" records) -- was
# entirely unreachable through this API (2026-07-20 audit finding: the file
# every PB gate result feeds ("rejects are training signal, not waste" per
# the project's own framing) had no query surface at all). Full semantic
# embedding of 591K records the way build_knowledge.json's ~450 entries are
# handled is NOT attempted here -- at real Ollama embedding latency that's
# days of wall-clock time and a fundamentally different scale problem
# (a real vector DB, not a flat numpy cache) -- these two functions instead
# stream the file line-by-line (never loading it into memory) to make it at
# least genuinely discoverable and literal-text-searchable today.


@dataclass
class VerdictCorpusStats:
    exists: bool
    total_lines: int = 0
    verdict_counts: dict[str, int] = field(default_factory=dict)
    conversation_records: int = 0
    file_bytes: int = 0


def verdict_corpus_stats(max_lines: int | None = None) -> VerdictCorpusStats:
    """Streaming (never loads the 9GB file into memory) line count + verdict
    breakdown. max_lines caps the scan for a fast approximate read; omit for
    an exact count (a full pass over 591K short JSON lines, not the whole
    9GB of conversation payloads, since most of that per-line size lives in
    "conversations" records this function only classifies, not parses in
    full -- json.loads still runs per line, so this is still a real, if
    bounded, cost, not free)."""
    if not VERDICT_CORPUS_PATH.is_file():
        return VerdictCorpusStats(exists=False)
    total = 0
    conv = 0
    verdicts: dict[str, int] = {}
    with VERDICT_CORPUS_PATH.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if max_lines is not None and total >= max_lines:
                break
            total += 1
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if "conversations" in row:
                conv += 1
            elif "verdict" in row:
                v = str(row.get("verdict", "?"))
                verdicts[v] = verdicts.get(v, 0) + 1
    return VerdictCorpusStats(
        exists=True,
        total_lines=total,
        verdict_counts=verdicts,
        conversation_records=conv,
        file_bytes=VERDICT_CORPUS_PATH.stat().st_size,
    )


def verdict_corpus_grep(
    query: str, limit: int = 20, max_scan: int = 200_000
) -> list[dict[str, Any]]:
    """Literal (case-insensitive) substring search over verdict-shaped rows
    only (slug/verdict/root_cause/fix_summary) -- streams the file, stops
    early at `limit` matches or after scanning `max_scan` lines, whichever
    comes first, so a query never pays for reading the full 9GB. Does NOT
    search "conversations"-shaped training records (those are large
    generation payloads, not the kind of short knowledge-lookup this API's
    other search()/hybrid_search() are for) -- use verdict_corpus_stats()
    to see how many of those exist if that's what's needed instead."""
    if not VERDICT_CORPUS_PATH.is_file():
        return []
    q = query.lower()
    hits: list[dict[str, Any]] = []
    scanned = 0
    with VERDICT_CORPUS_PATH.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if len(hits) >= limit or scanned >= max_scan:
                break
            scanned += 1
            if q not in line.lower():
                continue
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or "verdict" not in row:
                continue
            hits.append(row)
    return hits


_XREF_RE = re.compile(r"[Ss]ee (?:also )?([A-Za-z][A-Za-z0-9_]{4,60})")


@dataclass
class CrossReference:
    from_key: str
    to_key: str
    to_key_exists: bool


def extract_cross_references(corpus: dict[str, Any] | None = None) -> list[CrossReference]:
    """Every 'see X' / 'see also X' mention across the corpus -- the corpus's own citation
    network, built from literal substrings the corpus's own writers already use as its
    established cross-referencing convention (confirmed: ~97 real hits as of 2026-07-16),
    not inferred or guessed at."""
    kn = corpus if corpus is not None else load_corpus()
    refs: list[CrossReference] = []
    for key, v in kn.items():
        if (
            key in _NON_ENTRY_KEYS
            or key.startswith("_")
            or key.startswith("learned_classes_quarantine_")
        ):
            continue
        blob = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        for m in _XREF_RE.finditer(blob):
            target = m.group(1)
            refs.append(CrossReference(from_key=key, to_key=target, to_key_exists=target in kn))
    return refs


def related_entries(key: str, corpus: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Both directions of the citation graph for one entry: what it cites (outbound) and
    what cites IT (inbound -- often more useful, since it shows what depends on this entry
    being correct, e.g. a class_pattern that three later postmortems all point back to)."""
    kn = corpus if corpus is not None else load_corpus()
    refs = extract_cross_references(kn)
    outbound = sorted({r.to_key for r in refs if r.from_key == key})
    inbound = sorted({r.from_key for r in refs if r.to_key == key})
    return {"outbound": outbound, "inbound": inbound}


_SUPERSESSION_MARKERS = (
    "invalidat",
    "CORRECTED",
    "supersed",
    "now stale",
    "was wrong",
    "demoted",
    "DEMOTED",
    "WRONG",
)


@dataclass
class SupersessionFlag:
    key: str
    marker: str
    snippet: str


def find_superseded_claims(corpus: dict[str, Any] | None = None) -> list[SupersessionFlag]:
    """Entries that flag a claim (their own history, or another entry) as corrected /
    invalidated / stale / demoted. Surfaces exactly the class of problem that let the
    ProgramBench '65 locks' figure stand uncorrected across multiple sessions before the
    2026-06-30 provenance audit caught it -- a caller consulting the corpus should treat
    whatever an entry HERE says is superseded as untrustworthy, and prefer this entry's own
    corrected account instead."""
    kn = corpus if corpus is not None else load_corpus()
    out: list[SupersessionFlag] = []
    for key, v in kn.items():
        if (
            key in _NON_ENTRY_KEYS
            or key.startswith("_")
            or key.startswith("learned_classes_quarantine_")
        ):
            continue
        blob = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        for marker in _SUPERSESSION_MARKERS:
            idx = blob.find(marker)
            if idx >= 0:
                snippet = blob[max(0, idx - 60) : idx + 200].replace("\n", " ")
                out.append(SupersessionFlag(key=key, marker=marker, snippet=snippet))
    return out


_MATURITY_MARKERS = (
    "NOT YET BUILT",
    "HIGH RISK, UNRESOLVED",
    "UNRESOLVED",
    "STILL_NEEDED",
    "remaining_work",
    "REMAINING_WORK",
    "TODO",
    "NEEDS_RE",
)
_MATURITY_WEAK_MARKERS = ("gap", "GAP")  # common word -- lower-confidence bucket


@dataclass
class OpenItem:
    key: str
    marker: str
    topic: str
    snippet: str


@dataclass
class MaturityReport:
    """A GROUNDED self-report of what the corpus itself flags as open/unresolved --
    built by scanning for the corpus's own established convention (literal section
    headers like 'NOT YET BUILT', 'HIGH RISK, UNRESOLVED' inside entries such as
    HACKATHON_LEVER_MAP_2026_07_13). This is NOT an LLM guessing at gaps; every open_item
    below is a literal substring match you can go verify in build_knowledge.json yourself.
    """

    generated_from: str
    stats: CorpusStats
    flywheel_is_empty: bool
    # NOT a backlog: see the accessor's docstring. Kept under the old key in to_dict()
    # so existing readers do not break, with an honest sibling added beside it.
    quarantined_rejected: int
    open_items: list[OpenItem] = field(default_factory=list)
    weak_open_items: list[OpenItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_from": self.generated_from,
            "stats": self.stats.__dict__,
            "flywheel_is_empty": self.flywheel_is_empty,
            # The old key is retained for compatibility but it was misleading: these
            # entries were REJECTED, not queued. The quarantine's own _doc records 0
            # verified and 0 ever used by the flywheel, 76% extracted from vague spec
            # prose, and the 2026-07-18 salvage already readmitted the 234 that passed
            # a quality gate. Reporting the remainder as "pending reabsorption" invited
            # re-absorbing material that was deliberately gated out.
            "quarantine_pending_reabsorption": self.quarantined_rejected,
            "quarantined_rejected": self.quarantined_rejected,
            "quarantine_note": (
                "rejected, not queued: 0 verified and 0 ever used at quarantine; the "
                "2026-07-18 salvage already readmitted the 234 that passed the quality gate"
            ),
            "open_items": [i.__dict__ for i in self.open_items],
            "weak_open_items": [i.__dict__ for i in self.weak_open_items],
        }


def _entry_topic(key: str, topic_of_key: dict[str, str]) -> str:
    return topic_of_key.get(key, "")


def maturity_report(
    topic_filter: str | None = None, corpus: dict[str, Any] | None = None
) -> MaturityReport:
    """Scan every top-level entry for the corpus's own open/unresolved convention.
    Pass topic_filter='HACKATHON_CAMPAIGN' to scope the report to just that track --
    exactly what a session mid-hackathon needs, without wading through PB-only entries."""
    kn = corpus if corpus is not None else load_corpus()
    s = stats(kn)

    topic_of_key: dict[str, str] = {}
    ti = kn.get("_topic_index", {})
    if isinstance(ti, dict):
        for topic, rows in ti.items():
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and row.get("key"):
                    topic_of_key[str(row["key"])] = topic

    open_items: list[OpenItem] = []
    weak_items: list[OpenItem] = []
    for key, v in kn.items():
        if (
            key in _NON_ENTRY_KEYS
            or key.startswith("_")
            or key.startswith("learned_classes_quarantine_")
        ):
            continue
        topic = _entry_topic(key, topic_of_key)
        if topic_filter and topic != topic_filter:
            continue
        blob = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        for marker in _MATURITY_MARKERS:
            idx = blob.find(marker)
            if idx >= 0:
                snippet = blob[max(0, idx - 40) : idx + 160].replace("\n", " ")
                open_items.append(OpenItem(key=key, marker=marker, topic=topic, snippet=snippet))
        for marker in _MATURITY_WEAK_MARKERS:
            idx = blob.find(marker)
            if idx >= 0:
                snippet = blob[max(0, idx - 40) : idx + 160].replace("\n", " ")
                weak_items.append(OpenItem(key=key, marker=marker, topic=topic, snippet=snippet))

    quarantine_count = sum(
        len(v.get("entries", {})) if isinstance((v := kn.get(k)), dict) else 0
        for k in kn
        if k.startswith("learned_classes_quarantine_")
    )

    return MaturityReport(
        generated_from=DEFAULT_PATH.name if corpus is None else "(in-memory corpus)",
        stats=s,
        flywheel_is_empty=(s.learned_class_verified_count == 0),
        quarantined_rejected=quarantine_count,
        open_items=open_items,
        weak_open_items=weak_items,
    )


@dataclass
class AskResult:
    query: str
    hits: list[SearchHit]
    top_hit_related: dict[str, list[str]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [h.__dict__ for h in self.hits],
            "top_hit_related": self.top_hit_related,
            "warnings": self.warnings,
        }


def ask(query: str, corpus: dict[str, Any] | None = None) -> AskResult:
    """The single entry point a caller should actually use: hybrid (lexical+semantic) search +
    the top hit's citation graph + an automatic cross-check against every known supersession flag
    in the corpus, so a stale/corrected entry is never handed back silently, AND a paraphrased
    query still finds its match. This composes hybrid_search(), related_entries(), and
    find_superseded_claims() -- it invents nothing new, it just saves a caller from having to
    remember and chain all three themselves. hybrid_search degrades to search()'s pure
    token-overlap ranking if Ollama/the embeddings cache is unavailable, so ask() has no new
    hard dependency versus before this was wired in (2026-07-19)."""
    kn = corpus if corpus is not None else load_corpus()
    hits = hybrid_search(query, corpus=kn)
    top_related = related_entries(hits[0].key, kn) if hits else {"outbound": [], "inbound": []}
    superseded_keys = {f.key: f.marker for f in find_superseded_claims(kn)}
    warnings: list[str] = []
    for h in hits[:5]:
        if h.key in superseded_keys:
            warnings.append(
                f"'{h.key}' contains {superseded_keys[h.key]!r} correction/supersession language -- "
                "read the full entry before trusting it; it may describe its OWN earlier mistake."
            )
    return AskResult(query=query, hits=hits, top_hit_related=top_related, warnings=warnings)


_DATE_IN_KEY_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})")


@dataclass
class TimelineEntry:
    key: str
    date: str  # "YYYY-MM-DD"
    topic: str


def timeline(
    topic_filter: str | None = None, corpus: dict[str, Any] | None = None
) -> list[TimelineEntry]:
    """Every top-level entry with a YYYY_MM_DD date in its own key, sorted chronologically --
    a real 'how did understanding of X evolve' view (85 of 112 entries carry this convention
    as of 2026-07-16). Dates come from the corpus's own naming convention, not inferred."""
    kn = corpus if corpus is not None else load_corpus()
    topic_of_key: dict[str, str] = {}
    ti = kn.get("_topic_index", {})
    if isinstance(ti, dict):
        for topic, rows in ti.items():
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and row.get("key"):
                    topic_of_key[str(row["key"])] = topic

    out: list[TimelineEntry] = []
    for key in kn:
        if (
            key in _NON_ENTRY_KEYS
            or key.startswith("_")
            or key.startswith("learned_classes_quarantine_")
        ):
            continue
        m = _DATE_IN_KEY_RE.search(key)
        if not m:
            continue
        topic = topic_of_key.get(key, "")
        if topic_filter and topic != topic_filter:
            continue
        out.append(
            TimelineEntry(key=key, date=f"{m.group(1)}-{m.group(2)}-{m.group(3)}", topic=topic)
        )
    out.sort(key=lambda e: e.date)
    return out


_CLAIM_RE = re.compile(r"\b\d{1,3}(\.\d+)?%|\b\d+/\d+\b|score|count|locked|ceiling", re.I)


def stale_report(days: int = 30, corpus: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Entries older than `days` that carry NUMERIC/status claims (scores, X/Y counts, lock or
    ceiling wording). These are the rows most likely to have rotted into anti-knowledge -- the
    board-staleness protocol ('never trust a number older than 48h') applied to the corpus
    itself. The 2026-07-18 audit found the gap ledgers were 3+ weeks stale and actively
    misleading sessions; this verb makes that failure mode visible on demand."""
    import datetime as _dt

    kn = corpus if corpus is not None else load_corpus()
    today = _dt.date.today()
    out = []
    for e in timeline(None, corpus=kn):
        try:
            d = _dt.date.fromisoformat(e.date)
        except ValueError:
            continue
        age = (today - d).days
        if age <= days:
            continue
        blob = json.dumps(kn.get(e.key, ""), ensure_ascii=False)
        if _CLAIM_RE.search(blob):
            out.append(
                {
                    "key": e.key,
                    "date": e.date,
                    "age_days": str(age),
                    "topic": e.topic,
                    "hint": "carries numeric/status claims; reconcile against code/board "
                    "before planning from it",
                }
            )
    out.sort(key=lambda r: r["date"])
    return out


@dataclass
class BriefHit:
    key: str
    why: str  # what matched -- so a reader can judge the hit instead of trusting it
    detect: str
    symptom: str
    fix: str
    score: int


def brief(paths: list[str], corpus: dict[str, Any] | None = None, limit: int = 6) -> list[BriefHit]:
    """What the corpus already knows about the code someone is about to touch.

    THE GAP THIS CLOSES. Every other mode here is PULL -- search, ask, topic, related --
    and each one requires already suspecting that the corpus has something to say. That is
    exactly the knowledge a cold-start reader does not have, so the corpus goes unconsulted
    and a solved problem gets re-solved. Measured 2026-08-01: the Ollama num_ctx truncation
    had already been diagnosed and fixed once, months earlier, inside
    determinex_pb_reimpl._ollama_generate's "ROTATING CAP" -- as a CODE COMMENT in one
    module. It was never a corpus entry (grep: `num_ctx` 0 hits, `prompt_eval` 0 hits), so
    no query could have surfaced it, and the identical bug was rediscovered from scratch on
    the shared provider path that every other caller uses.

    So the failure was not that nobody asked. It was that asking could not have worked. A
    push surface plus `code_paths` on the entries is what makes the second half true.

    Matching is deliberately two-tier: `code_paths` globs are an explicit author claim and
    rank first; a keyword overlap fallback means the 40+ entries written before this mode
    existed still surface, without anyone backfilling metadata. Precision over recall --
    a brief that cries wolf gets ignored, which is the same outcome as not having one.
    """
    import fnmatch

    kn = corpus if corpus is not None else load_corpus()
    norm = [str(p).replace("\\", "/") for p in paths]
    stems = {Path(p).stem.lower() for p in norm}
    # Split snake_case/kebab stems into words: determinex_providers -> {determinex, providers}
    words: set[str] = set()
    for s in stems:
        words.update(w for w in re.split(r"[_\-.]+", s) if len(w) > 3)

    hits: list[BriefHit] = []
    for key, val in class_patterns(kn).items():
        if not isinstance(val, dict):
            continue
        globs = val.get("code_paths") or []
        matched_glob = next((g for g in globs if any(fnmatch.fnmatch(p, g) for p in norm)), None)
        text = " ".join(str(val.get(f, "")) for f in ("detect", "symptom", "fix", "rule")).lower()
        overlap = sorted(w for w in words if w in text)

        if matched_glob:
            score, why = 100 + len(overlap), f"declared for {matched_glob}"
        elif len(overlap) >= 2:
            # One shared word is noise ("build", "test" appear everywhere); two is a signal.
            score, why = len(overlap), "mentions " + ", ".join(overlap[:4])
        else:
            continue
        hits.append(
            BriefHit(
                key=key,
                why=why,
                score=score,
                detect=str(val.get("detect", val.get("rule", "")))[:400],
                symptom=str(val.get("symptom", ""))[:400],
                fix=str(val.get("fix", ""))[:400],
            )
        )

    hits.sort(key=lambda h: (-h.score, h.key))
    return hits[:limit]


def format_brief(hits: list[BriefHit], paths: list[str]) -> str:
    if not hits:
        return ""
    out = [f"[corpus] {len(hits)} known failure class(es) touch {', '.join(paths[:3])}:"]
    for h in hits:
        out.append(f"  - {h.key}  ({h.why})")
        if h.symptom:
            out.append(f"      symptom: {h.symptom[:160]}")
        if h.fix:
            out.append(f"      fix:     {h.fix[:160]}")
    out.append("  full text: python scripts/determinex_corpus_api.py related <key>")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    usage = (
        "usage: determinex_corpus_api.py <brief PATH... | search QUERY | topics | topic TOPIC | stats | "
        "maturity [TOPIC] | related KEY | superseded | ask QUERY | timeline [TOPIC] | "
        "provenance TASK_ID_OR_SLUG_OR_REPO | tool SLUG | stale [DAYS] | "
        "swebench-stats | swebench-repo OWNER/REPO | "
        "terminal-bench-stats | terminal-bench-task SLUG>"
    )
    if len(argv) < 2:
        print(usage)
        return 1
    cmd = argv[1]
    if cmd == "brief" and len(argv) > 2:
        paths = argv[2:]
        hits = brief(paths)
        # Exit 0 whether or not anything matched: this is advisory, and a gate that can
        # block an edit because the corpus is quiet would be turned off within a day.
        text = format_brief(hits, paths)
        if text:
            print(text)
        return 0
    if cmd == "stats":
        s = stats()
        print(json.dumps(s.__dict__, indent=2))
    elif cmd == "topics":
        print(json.dumps(topics(), indent=2))
    elif cmd == "topic" and len(argv) > 2:
        print(json.dumps(topic_entries(argv[2]), indent=2))
    elif cmd == "search" and len(argv) > 2:
        q = " ".join(argv[2:])
        print(json.dumps([h.__dict__ for h in search(q)], indent=2))
    elif cmd == "maturity":
        topic_filter = argv[2] if len(argv) > 2 else None
        print(json.dumps(maturity_report(topic_filter).to_dict(), indent=2))
    elif cmd == "related" and len(argv) > 2:
        print(json.dumps(related_entries(argv[2]), indent=2))
    elif cmd == "superseded":
        print(json.dumps([f.__dict__ for f in find_superseded_claims()], indent=2))
    elif cmd == "ask" and len(argv) > 2:
        q = " ".join(argv[2:])
        print(json.dumps(ask(q).to_dict(), indent=2))
    elif cmd == "timeline":
        topic_filter = argv[2] if len(argv) > 2 else None
        print(json.dumps([e.__dict__ for e in timeline(topic_filter)], indent=2))
    elif cmd == "provenance" and len(argv) > 2:
        result = task_provenance(argv[2])
        print(json.dumps(result.__dict__ if result else None, indent=2))
    elif cmd == "tool" and len(argv) > 2:
        print(json.dumps(tool_status(argv[2]), indent=2))
    elif cmd == "stale":
        days = int(argv[2]) if len(argv) > 2 else 30
        print(json.dumps(stale_report(days), indent=2))
    elif cmd == "swebench-stats":
        print(json.dumps(swebench_stats(), indent=2))
    elif cmd == "swebench-repo" and len(argv) > 2:
        print(json.dumps(swebench_repo_info(argv[2]), indent=2))
    elif cmd == "terminal-bench-stats":
        print(json.dumps(terminal_bench_stats(), indent=2))
    elif cmd == "terminal-bench-task" and len(argv) > 2:
        print(json.dumps(terminal_bench_task(argv[2]), indent=2))
    else:
        print(usage)
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
