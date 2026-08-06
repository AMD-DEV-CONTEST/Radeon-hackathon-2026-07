"""T4 citation validator — programmatic check of `file#Lx-Ly` references.

Blueprint: ``docs/_e2e_plan/ARCHITECT_BLUEPRINT.md`` §3.3. "Evidence-based
answers" are ScrewShell's core selling point, but a 27B Q4 model will happily
invent ``file#L42-L58`` line numbers. This module validates every citation in a
generated answer before it reaches the user, in three cheap-to-expensive
layers:

    layer 1 syntax   regex hit; 0 < start <= end           O(1)
    layer 2 file     realpath inside the workspace; file
                     exists; end <= line count            one stat + one read
    layer 3 source   the range actually overlaps what was
                     retrieved this run (not containment --
                     models routinely narrow ranges)      O(#ranges)

Three modes (ADR-2 — every optimization must be switchable for A/B):

    off      -> return the text unchanged (control arm)
    annotate -> never delete anything; mark unverified cites inline and append
                a summary line (production default: fixing citations must
                never change answer semantics)
    strip    -> drop only the unverifiable citation marks, keep the sentence

Stdlib only (blueprint §6.2 rule 6): no torch / gradio / numpy.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# `a/b.py#L42-L58`, `a/b.py#L42`, `a/b.py#L42-58`; tolerates CJK punctuation
# and whitespace around the range. Source part excludes spaces/brackets.
CITE_RE = re.compile(
    r"(?P<src>[^\s()\[\]<>\"'，。；、]+?\.[A-Za-z0-9_]+)"
    r"#L(?P<s>\d+)(?:\s*[-–~]\s*L?(?P<e>\d+))?")

# quoted fragments right before a citation mark (for the quote round-trip
# check, Gemini Approach C): "..." / '...' / 「...」
_QUOTE_RE = re.compile(r"[\"\'「]([^\"\'」]{4,80})[\"\'」]")

_MISSING = object()  # sentinel for the per-file line-count LRU


def normalize_source(p: str) -> str:
    """The single entry point for cross-platform source paths.

    ``Toolkit._t_read_file`` uses ``os.path.relpath`` which produces
    ``a\\b.py`` on Windows while RAG chunk sources use forward slashes. If they
    are not unified here, the validator would always rule "file_missing".
    """
    p = p.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


@dataclass(frozen=True)
class Citation:
    source: str
    start_line: int
    end_line: int
    raw: str
    span: tuple[int, int]          # char interval in the original text


@dataclass
class CitationIssue:
    kind: str                      # malformed | outside_workspace |
                                   # file_missing | line_out_of_range |
                                   # not_retrieved
    citation: Optional[Citation]
    detail: str


@dataclass
class ValidationReport:
    total: int
    valid: int
    issues: list[CitationIssue] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """valid/total; no citations at all = 0.0 (an uncited answer is not an
        evidence-based answer)."""
        return round(self.valid / self.total, 3) if self.total else 0.0

    def to_dict(self) -> dict:
        return {"total": self.total, "valid": self.valid,
                "accuracy": self.accuracy,
                "issues": [{"kind": i.kind, "detail": i.detail}
                           for i in self.issues[:10]]}


class CitationValidator:
    def __init__(self, workspace: str,
                 retrieved: Optional[list[dict]] = None,
                 mode: str = "annotate"):
        self.workspace = os.path.realpath(workspace)
        self.mode = mode
        # layer-3 index: {normalized source: [(start, end), ...]} built from
        # the citations of every evidence card collected this run.
        self._retrieved: dict[str, list[tuple[int, int]]] = {}
        self._line_cache: dict[str, tuple[float, int]] = {}
        if retrieved:
            for c in retrieved:
                src = normalize_source(str(c.get("source", "")))
                s, e = c.get("start_line"), c.get("end_line")
                if src and isinstance(s, int) and isinstance(e, int):
                    self._retrieved.setdefault(src, []).append((s, e))

    # ------------------------------------------------------------- helpers
    def _line_count(self, path: str) -> int:
        """Cached line count, invalidated by mtime (files can change mid-run)."""
        try:
            st = os.stat(path)
            hit = self._line_cache.get(path)
            if hit and hit[0] == st.st_mtime:
                return hit[1]
        except OSError:
            return 0
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
        except OSError:
            return 0
        self._line_cache[path] = (os.stat(path).st_mtime, n)
        return n

    # ------------------------------------------------------------ pipeline
    def extract(self, text: str) -> list[Citation]:
        out = []
        for m in CITE_RE.finditer(text):
            s = int(m.group("s"))
            e = int(m.group("e")) if m.group("e") else s
            out.append(Citation(
                source=normalize_source(m.group("src")),
                start_line=s, end_line=e, raw=m.group(0),
                span=m.span()))
        return out

    def _quote_in_lines(self, path: str, s: int, e: int, quote: str) -> bool:
        """Is `quote` literally present inside source lines Ls-Le?"""
        if not quote or "\n" in quote:
            return True  # multiline / empty quotes are not judged
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if i > e:
                        break
                    if s <= i <= e and quote in line:
                        return True
        except OSError:
            return False
        return False

    def check(self, c: Citation, context: str = "") -> Optional[CitationIssue]:
        """Layers 2-3 + optional quote round-trip (Gemini Approach C).

        `context` is the answer text right before the citation mark. When it
        carries a quoted fragment (``"..."`` / ``'...'`` / ``「…」``), we verify
        that fragment literally appears in the cited source lines; without a
        quote fragment the check passes (never penalize a bare citation).
        """
        if not (0 < c.start_line <= c.end_line):
            return CitationIssue("malformed", c, f"bad range L{c.start_line}-L{c.end_line}")
        path = os.path.realpath(os.path.join(self.workspace, c.source))
        if not (path == self.workspace or path.startswith(self.workspace + os.sep)):
            return CitationIssue("outside_workspace", c, c.source)
        if not os.path.isfile(path):
            return CitationIssue("file_missing", c, c.source)
        n = self._line_count(path)
        if c.end_line > n:
            return CitationIssue("line_out_of_range", c,
                                 f"{c.source} has {n} lines, cited L{c.end_line}")
        ranges = self._retrieved.get(c.source)
        if ranges:
            overlap = any(not (c.end_line < rs or c.start_line > re)
                          for rs, re in ranges)
            if not overlap:
                return CitationIssue("not_retrieved", c, c.source)
        if context:
            for m in _QUOTE_RE.finditer(context):
                quote = m.group(1)
                if not self._quote_in_lines(path, c.start_line, c.end_line, quote):
                    return CitationIssue(
                        "quote_not_found", c,
                        f"quote {quote[:40]!r} not found in {c.source} "
                        f"L{c.start_line}-L{c.end_line}")
        return None

    def validate(self, text: str) -> tuple[str, ValidationReport]:
        """Mode-aware validation. Never touches text the regex did not match."""
        if self.mode == "off":
            return text, ValidationReport(0, 0)
        cites = self.extract(text)
        issues: list[CitationIssue] = []
        bad_spans: set[tuple[int, int]] = set()
        for c in cites:
            # ~80 chars of answer text right before the citation mark feeds
            # the quote round-trip layer (no quote -> check passes)
            ctx = text[max(0, c.span[0] - 80):c.span[0]]
            issue = self.check(c, context=ctx)
            if issue:
                issues.append(issue)
                bad_spans.add(c.span)
        valid = len(cites) - len(issues)
        report = ValidationReport(len(cites), valid, issues)
        if not cites or not issues:
            return text, report
        if self.mode == "strip":
            # delete the citation marks themselves, keep the sentences
            chunks, pos = [], 0
            for s, e in sorted(bad_spans):
                chunks.append(text[pos:s])
                pos = e
            chunks.append(text[pos:])
            text = "".join(chunks)
        elif self.mode == "annotate":
            # mark inline, never delete; append a summary line
            marks = {sp: True for sp in bad_spans}
            chunks, pos = [], 0
            for (s, e) in sorted(marks):
                chunks.append(text[pos:s])
                chunks.append(text[s:e] + " ⚠未证实")
                pos = e
            chunks.append(text[pos:])
            text = "".join(chunks)
            text += (f"\n\n⚠ 引用校验：{report.total} 条引用中 "
                     f"{len(issues)} 条未证实"
                     f"（{', '.join(sorted({i.kind for i in issues}))}）")
        return text, report


def validate_citations(text: str,
                       workspace: str = ".",
                       retrieved: Optional[list[dict]] = None,
                       mode: str = "annotate") -> tuple[str, ValidationReport]:
    """Functional entry point (thin wrapper over a one-shot validator)."""
    return CitationValidator(workspace, retrieved=retrieved,
                             mode=mode).validate(text)


def merge_citations(cites: list[dict], max_n: int = 8) -> list[dict]:
    """Merge adjacent/overlapping ranges per source, drop weak scores, cap."""
    by_src: dict[str, dict] = {}
    for c in cites:
        src = normalize_source(str(c.get("source", "")))
        if not src:
            continue
        s, e = int(c.get("start_line", 0)), int(c.get("end_line", 0))
        if not (0 < s <= e):
            continue
        cur = by_src.get(src)
        if cur is None:
            by_src[src] = {"source": src, "start_line": s, "end_line": e,
                           "score": float(c.get("score", 0.0))}
            continue
        cur["start_line"] = min(cur["start_line"], s)
        cur["end_line"] = max(cur["end_line"], e)
        cur["score"] = max(cur["score"], float(c.get("score", 0.0)))
    merged = sorted(by_src.values(), key=lambda d: -d["score"])[:max_n]
    return [{k: v for k, v in d.items()} for d in merged]
