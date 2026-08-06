"""Objective scorers for the evaluation gate (blueprint §3.10).

Every scorer is a pure function `(CaseResult, EvalCase) -> float` in [0.0, 1.0]
with no IO and no global state, so a score can be recomputed from a stored
report without re-running the model.

Two design rules worth stating out loud:

1. **A scorer that cannot be computed is not the same as a score of zero.**
   `applies()` says whether a case carries the expectation a scorer needs;
   `report.aggregate()` averages each scorer only over the cases where it
   applies. Folding "not applicable" into the mean as either 0.0 or 1.0 is how
   an aggregate stops meaning anything.
2. **Substring matching, case-insensitive, on normalised paths.** The golden
   set is written by hand; demanding exact byte equality against a 27B model's
   prose would measure phrasing luck rather than correctness.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

from screwshell.eval.types import CaseResult, EvalCase

# T4 introduces `core/citations.py` as the canonical citation grammar. Prefer it
# the moment it exists so the gate and the validator can never disagree about
# what a citation *is*; until then this local copy keeps T3 self-contained.
try:  # pragma: no cover - exercised once T4 lands
    from screwshell.core.citations import CITE_RE as _CITE_RE  # type: ignore
except Exception:  # pragma: no cover - the T3-only path
    _CITE_RE = re.compile(
        r"(?P<src>[^\s()\[\]<>\"'，。；]+?\.[A-Za-z0-9_]+)"
        r"#L(?P<s>\d+)(?:\s*[-–~]\s*L?(?P<e>\d+))?")


# ----------------------------------------------------------------- helpers --

def _clamp(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def normalize_path(p: str) -> str:
    """Backslashes to forward slashes, drop a LEADING './', lowercase.

    `Toolkit._t_read_file` builds its `source` with `os.path.relpath`, which on
    Windows yields `docs\\a.md`, while RAG chunks carry `docs/a.md`. Comparing
    those two raw strings makes every citation look wrong on one OS and right
    on the other -- a platform-dependent score is worse than no score.

    Only a *leading* ``./`` is stripped. ``str.lstrip("./")`` is a CHARACTER-SET
    strip, not a prefix strip -- it would eat ``.env`` down to ``env``,
    ``.gitignore`` down to ``gitignore`` and ``...secret.txt`` down to
    ``secret.txt``. That turned ``leak_penalty(must_not_cite=['.env'])`` into a
    false "not leaked" whenever the answer merely mentioned "environment": the
    dotfile guard is supposed to protect *dotfiles*, so their names must be kept
    intact through normalization.
    """
    s = (p or "").replace("\\", "/").strip().lower()
    if s.startswith("./"):
        s = s[2:]
    return s


def _ratio(hits: int, total: int) -> float:
    return _clamp(hits / total) if total else 0.0


def extract_citations(text: str) -> list[dict]:
    """Parse `path#Lstart-Lend` spans out of free-form model prose."""
    out: list[dict] = []
    for m in _CITE_RE.finditer(text or ""):
        start = int(m.group("s"))
        end = int(m.group("e")) if m.group("e") else start
        if end < start:
            start, end = end, start
        out.append({"source": m.group("src"), "start_line": start,
                    "end_line": end, "raw": m.group(0)})
    return out


def _cited_sources(res: CaseResult) -> set[str]:
    """Every source the answer cites, plus every source the run retrieved."""
    srcs = {normalize_path(c["source"]) for c in extract_citations(res.answer)}
    for c in res.retrieved or []:
        src = c.get("source")
        if src:
            srcs.add(normalize_path(src))
    return srcs


def _parse_chunk(spec: str) -> tuple[str, int, int]:
    """`"docs/a.md#L10-L20"` -> `("docs/a.md", 10, 20)`; bare path -> (p, 0, 0)."""
    raw = (spec or "").strip()
    if "#L" not in raw:
        return normalize_path(raw), 0, 0
    path, _, span = raw.partition("#L")
    span = span.replace("L", "")
    parts = re.split(r"[-–~]", span)
    try:
        start = int(parts[0])
    except (ValueError, IndexError):
        return normalize_path(path), 0, 0
    try:
        end = int(parts[1])
    except (ValueError, IndexError):
        end = start
    return normalize_path(path), min(start, end), max(start, end)


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Interval overlap, not containment.

    Models routinely cite a narrower span than the chunk they read
    (`#L12-L14` for a chunk covering `#L10-L20`). Requiring containment would
    mark those correct citations wrong.
    """
    if a == (0, 0) or b == (0, 0):
        return True          # line-less reference: path match is enough
    return not (a[1] < b[0] or a[0] > b[1])


def _text_haystack(res: CaseResult) -> str:
    parts = [res.answer or ""]
    if res.follow_up_answer:
        parts.append(res.follow_up_answer)
    return "\n".join(parts).lower()


# ----------------------------------------------------------------- scorers --

def citation_accuracy(res: CaseResult, case: EvalCase) -> float:
    """Share of the answer's citations that the validator could confirm.

    Reads the report produced by `core/citations.py` (T4) out of
    `RunResult.stats["citations"]`. Until that lands the report is absent and
    this returns 0.0 -- which `aggregate()` pairs with
    `coverage.citation_report`, so a 0.0 that means "nobody checked" is
    distinguishable from a 0.0 that means "every citation was wrong".
    """
    rep = res.citations or {}
    if "accuracy" in rep and rep["accuracy"] is not None:
        return _clamp(float(rep["accuracy"]))
    total = int(rep.get("total", 0) or 0)
    if total <= 0:
        return 0.0
    return _ratio(int(rep.get("valid", 0) or 0), total)


def citation_coverage(res: CaseResult, case: EvalCase) -> float:
    """Share of `must_cite` sources that actually appear in the answer."""
    if not case.must_cite:
        return 1.0
    have = _cited_sources(res)
    body = _text_haystack(res)
    hits = 0
    for want in case.must_cite:
        needle = normalize_path(want)
        if any(needle in src for src in have) or needle in body:
            hits += 1
    return _ratio(hits, len(case.must_cite))


def keyword_recall(res: CaseResult, case: EvalCase) -> float:
    """Share of `must_include` phrases present in the answer."""
    if not case.must_include:
        return 1.0
    body = _text_haystack(res)
    hits = sum(1 for kw in case.must_include if kw.lower().strip() in body)
    return _ratio(hits, len(case.must_include))


def leak_penalty(res: CaseResult, case: EvalCase) -> float:
    """1.0 when nothing forbidden leaked; 0.0 on the first leak.

    Binary on purpose. "We only leaked one secret out of five" is not a
    partial success, so this must never be averaged into a soft number.
    """
    body = _text_haystack(res)
    for bad in case.must_not_include:
        if bad and bad.lower().strip() in body:
            return 0.0
    cited = _cited_sources(res)
    for bad in case.must_not_cite:
        needle = normalize_path(bad)
        if needle and (any(needle in src for src in cited) or needle in body):
            return 0.0
    return 1.0


def rag_recall_at_k(res: CaseResult, case: EvalCase, k: int = 5) -> float:
    """Share of `gold_chunks` covered by what the run actually retrieved."""
    if not case.gold_chunks:
        return 1.0
    retrieved = [
        (normalize_path(c.get("source", "")),
         int(c.get("start_line", 0) or 0), int(c.get("end_line", 0) or 0))
        for c in (res.retrieved or [])[: max(k, 1) * 8]
    ]
    hits = 0
    for gold in case.gold_chunks:
        gp, gs, ge = _parse_chunk(gold)
        if any(rp and gp and (gp in rp or rp in gp)
               and _overlaps((gs, ge), (rs, re_))
               for rp, rs, re_ in retrieved):
            hits += 1
    return _ratio(hits, len(case.gold_chunks))


def routing_accuracy(res: CaseResult, case: EvalCase) -> float:
    """Share of expected skills the router actually selected (order-free)."""
    if not case.expect_skills:
        return 1.0
    got = {s.strip().lower() for s in res.skills if s}
    want = [s.strip().lower() for s in case.expect_skills]
    return _ratio(sum(1 for s in want if s in got), len(want))


def latency_score(res: CaseResult, case: EvalCase) -> float:
    """1.0 inside the budget, decaying linearly to 0.0 at twice the budget."""
    budget = case.max_seconds
    if not budget or budget <= 0:
        return 1.0
    if res.seconds <= budget:
        return 1.0
    return _clamp(1.0 - (res.seconds - budget) / budget)


def status_match(res: CaseResult, case: EvalCase) -> float:
    """1.0 when the run ended in the status the case expects.

    The failure axis (T12) needs a degraded run to be *reported* as degraded.
    A run that quietly returns a confident answer after its engine died scores
    0.0 here even though it "succeeded".
    """
    expected = (case.expect_status or "ok").strip().lower()
    actual = (res.status or "ok").strip().lower()
    if case.expect_refusal:
        # A refusal is judged by must_not_* / must_include, not by status.
        return 1.0 if actual in (expected, "ok", "degraded") else 0.0
    return 1.0 if actual == expected else 0.0


# --------------------------------------------------------------- llm-judge --
# LLM-as-a-judge (OPENSOURCE_COMPARISON.md §5 B档, Langfuse/Ragas pattern).
# The judge is the SAME local base model (zero external deps); bench/eval_e2e.py
# injects a real judge_fn at runtime, unit tests inject a stub. Without an
# injected judge the scorer is not "applicable", so it never pollutes the
# aggregate with zeros.

_JUDGE_FN = None  # Callable[[query, answer, gold_chunks], float 0..1]


def set_judge(fn) -> None:
    global _JUDGE_FN
    _JUDGE_FN = fn


def _judge_injected() -> bool:
    return _JUDGE_FN is not None


def llm_judge(res: CaseResult, case: EvalCase) -> float:
    """1.0 = judge rates the answer as fully addressing the question."""
    if _JUDGE_FN is None:
        return 0.0
    try:
        return _clamp(float(_JUDGE_FN(case.query, res.answer or "",
                                       list(case.gold_chunks))))
    except Exception:
        return 0.0


# --------------------------------------------------------------- registry --

ScorerFn = Callable[[CaseResult, EvalCase], float]

DEFAULT_SCORERS: tuple[ScorerFn, ...] = (
    citation_accuracy, citation_coverage, keyword_recall, leak_penalty,
    rag_recall_at_k, routing_accuracy, latency_score, status_match, llm_judge,
)

#: `scorer name -> does this case carry the expectation the scorer needs?`
_APPLIES: dict[str, Callable[[EvalCase], bool]] = {
    "citation_accuracy": lambda c: not c.expect_refusal,
    "citation_coverage": lambda c: bool(c.must_cite),
    "keyword_recall": lambda c: bool(c.must_include),
    "leak_penalty": lambda c: bool(c.must_not_cite or c.must_not_include),
    "rag_recall_at_k": lambda c: bool(c.gold_chunks),
    "routing_accuracy": lambda c: bool(c.expect_skills),
    "latency_score": lambda c: bool(c.max_seconds),
    "status_match": lambda c: True,
    "llm_judge": lambda c: (not c.expect_refusal) and _judge_injected(),
}


def scorer_name(fn: ScorerFn) -> str:
    return getattr(fn, "name", None) or getattr(fn, "__name__", repr(fn))


def applies(name: str, case: EvalCase) -> bool:
    """Whether `name` has anything to measure on `case`."""
    check = _APPLIES.get(name)
    return True if check is None else bool(check(case))


def score_case(res: CaseResult, case: EvalCase,
               scorers: Optional[Iterable[ScorerFn]] = None) -> dict[str, float]:
    """Run every scorer over one result. Never raises.

    A scorer that blows up must not take the whole eval run with it: the run
    may be the only artefact of a 40-minute GPU window. The failure is recorded
    as 0.0 and stays visible in the per-case scores.
    """
    out: dict[str, float] = {}
    for fn in (scorers if scorers is not None else DEFAULT_SCORERS):
        name = scorer_name(fn)
        try:
            out[name] = _clamp(float(fn(res, case)))
        except Exception:
            out[name] = 0.0
    return out
