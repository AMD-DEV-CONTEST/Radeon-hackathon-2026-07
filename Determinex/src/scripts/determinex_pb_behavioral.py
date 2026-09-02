#!/usr/bin/env python3
"""
determinex_pb_behavioral.py -- Behavioral remediation engine + flywheel capture
============================================================================
The structural autofix patterns (build-target, source-completion, clock-route,
literal-n, numeric-cap) fix tools whose BUILD/COLLECTION is wrong. This module
handles the other half: BEHAVIORAL failures -- the binary builds and runs, but
emits the WRONG OUTPUT for a correct invocation. That is the bulk of what stands
between a tool and 100%.

Behavioral failures are not infinitely varied. They fall into a finite set of
DIFF KINDS, most with a known, reusable technique. This module:

  1. classify_diff(expected, actual)  -> a DiffKind  (the missing sub-classifier;
     today the Adjudicator dumps all of these into one NEEDS_WORK bucket).
  2. technique_for(kind)              -> the remediation TYPE + how to apply it.
  3. propose_normalizer(kind, ...)    -> a conftest stdout/stderr post-processor
     for the MECHANIZABLE kinds (whitespace, path/tmp, version, ansi, datetime).
  4. capture_training_pair(...)       -> append a structured (context -> fix ->
     verdict) record to the behavioral training corpus. THIS is the flywheel feed:
     enough verified pairs and the tuned models emit the transform natively.

Boundary (honest): whitespace / path / version / ansi / datetime / output-mode are
codegen-able here. ordering / numeric / semantic differences are NOT -- they route
to the model solve-loop (generate -> re-eval -> keep-if-better -> iterate), whose
verified outputs are themselves captured as training pairs. Nothing is "unfixable";
it is either a known transform or a solve-loop target.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BEHAVIORAL_CORPUS = (
    REPO / "corpus" / "programbench" / "training_corpus" / "pb_behavioral_corpus.jsonl"
)


class DiffKind(str, Enum):
    TTY_RENDER = "tty-render"  # a *_tty test got non-TTY output -> needs a PTY
    OUTPUT_MODE = "output-mode"  # json<->text<->table: wrong renderer selected
    ANSI_COLOR = "ansi-color"  # color codes present/absent/differ
    WHITESPACE = "whitespace"  # trailing/padding/tab/newline only
    DATETIME = "datetime"  # a date/time/duration in the output
    VERSION_BUILD = "version-build"  # version string / build hash / build date
    PATH_TMP = "path-tmp"  # absolute/temp paths (/tmp/pytest-*, cwd)
    EXIT_CODE = "exit-code"  # return code mismatch
    ORDERING = "ordering"  # same lines, different order
    NUMERIC = "numeric"  # a count/size/number differs
    SEMANTIC = "semantic"  # genuinely different content -> solve-loop


# remediation TYPE per kind: 'normalizer' (conftest post-proc, codegen here),
# 'route' (env/arg/TERM or PYTEST_CURRENT_TEST), 'clock-route' (pattern 6),
# 'solve-loop' (model-generated fix, verified by re-eval).
_TECHNIQUE = {
    DiffKind.TTY_RENDER: (
        "pty-allocate",
        "A *_tty test got non-TTY output (e.g. JSON/plain instead of the rendered TTY view). Run the binary under an allocated PTY (openpty / `script -qec` / the tool's tty-detect path) so it enters interactive/render mode; pair with any screen-dump flag.",
    ),
    DiffKind.WHITESPACE: (
        "normalizer",
        "Conftest stdout post-processor: normalize trailing/edge whitespace, tabs->spaces, CRLF->LF before compare.",
    ),
    DiffKind.PATH_TMP: (
        "normalizer",
        "Conftest post-processor: rewrite volatile abs/temp paths (/tmp/pytest-*, cwd, $HOME) to the golden's stable placeholder.",
    ),
    DiffKind.VERSION_BUILD: (
        "route",
        "Pin/route the version/build string: replace the live version/hash/build-date with the golden's via conftest, or PYTEST_CURRENT_TEST routing (svd2rust/genact pattern).",
    ),
    DiffKind.ANSI_COLOR: (
        "route",
        "Select the color mode the golden used: set TERM/COLORTERM/CLICOLOR(_FORCE)/NO_COLOR, or strip/add ANSI in a conftest post-processor to match.",
    ),
    DiffKind.OUTPUT_MODE: (
        "route",
        "Select the renderer the golden used: pass the mode flag (--json/--no-json/--plain) or env the binary keys on; route per-test if branches disagree.",
    ),
    DiffKind.DATETIME: (
        "clock-route",
        "Date/time in output -> clock-route (pattern 6): per-test DETERMINEX_FAKE_NOW for hardcoded dates, real clock for dynamic/uniqueness.",
    ),
    DiffKind.EXIT_CODE: (
        "route",
        "Exit-code mismatch: justify via environment (the binary's real code under the reference env) before any wrapper remap; otherwise behavioral -> solve-loop.",
    ),
    DiffKind.ORDERING: (
        "solve-loop",
        "Same content, different order -> deterministic-ordering fix in the binary/source or a stable sort in a post-processor; propose + re-eval.",
    ),
    DiffKind.NUMERIC: (
        "solve-loop",
        "A count/size differs -> root-cause in logic; model proposes a fix, gated by re-eval.",
    ),
    DiffKind.SEMANTIC: (
        "solve-loop",
        "Genuinely different content -> model proposes a source/conftest fix, verified by the Oracle, iterate; capture the winning pair.",
    ),
}

_ANSI = re.compile(r"\x1b\[")
_DATE = re.compile(
    r"\b20\d\d-\d\d-\d\d\b|\b\d{1,2}:\d{2}(:\d{2})?\b|\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b"
)
_VERSION = re.compile(r"\bv?\d+\.\d+\.\d+\b|\b[0-9a-f]{7,40}\b|build|commit|GMT|UTC \d{4}")
_PATH = re.compile(r"/tmp/|/pytest-|/private/var|[A-Za-z]:\\\\|/home/|/root/|/workspace/")
_JSON = re.compile(r'^\s*[\[{]\s*"|"\w+":\s')


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s or "")


# Negatives that confound a naive "tty" substring match -- these tests WANT non-TTY
# output; firing pty for them regresses the tool (the dstask v6/v7 lesson).
_TTY_NEG = re.compile(r"non[_-]?tty|without[_-]?tty|no[_-]?tty|notty", re.I)
_TTY_POS = re.compile(r"(?:^|[_.])tty(?:[_.]|$)|_tui|\binteractive\b|\bscreen\b|tty_", re.I)


def _is_tty_test_name(name: str) -> bool:
    """Affirmative TTY token, with explicit negatives excluded. Deliberately does NOT
    match `render`/`rendering` (non-TTY) or `non_tty`/`without_tty` (want JSON)."""
    if not name or _TTY_NEG.search(name):
        return False
    return bool(_TTY_POS.search(name))


def classify_diff(
    expected: str | None, actual: str | None, exit_mismatch: bool = False, test_name: str = ""
) -> DiffKind:
    """Name the KIND of behavioral difference between expected and actual output."""
    if exit_mismatch:
        return DiffKind.EXIT_CODE
    e, a = expected or "", actual or ""
    # TTY-render: a genuinely-TTY test got non-TTY output (JSON/plain) -> needs a PTY.
    # PRECISE classification (v4 lesson): test names are noisy -- `non_tty`,
    # `without_tty`, `no_tty`, and `render`/`rendering` all confound a substring match
    # and fire pty for tests that WANT non-TTY output, net-regressing the tool. Only
    # fire for an affirmative TTY token, with explicit negatives excluded. (`render`
    # dropped entirely -- test_display_rendering is non-TTY.)
    if _is_tty_test_name(test_name) and (
        bool(_JSON.search(a)) or (e and a and _strip_ansi(e) != _strip_ansi(a))
    ):
        return DiffKind.TTY_RENDER
    # output-mode: one side is JSON, the other is not
    if bool(_JSON.search(e)) != bool(_JSON.search(a)):
        return DiffKind.OUTPUT_MODE
    # ansi: color codes present on one side only
    if bool(_ANSI.search(e)) != bool(_ANSI.search(a)):
        return DiffKind.ANSI_COLOR
    es, as_ = _strip_ansi(e), _strip_ansi(a)
    # whitespace-only: identical once whitespace is collapsed
    if re.sub(r"\s+", "", es) == re.sub(r"\s+", "", as_) and es != as_:
        return DiffKind.WHITESPACE
    # ansi differs but text identical
    if es == as_ and e != a:
        return DiffKind.ANSI_COLOR
    # version/build string
    if _VERSION.search(e) or _VERSION.search(a):
        return DiffKind.VERSION_BUILD
    # datetime in the output
    if _DATE.search(e) or _DATE.search(a):
        return DiffKind.DATETIME
    # volatile paths
    if _PATH.search(e) or _PATH.search(a):
        return DiffKind.PATH_TMP
    # same multiset of lines, different order
    if e and a and sorted(es.splitlines()) == sorted(as_.splitlines()) and es != as_:
        return DiffKind.ORDERING
    # a lone number differs
    if re.sub(r"\d+", "#", es) == re.sub(r"\d+", "#", as_) and es != as_:
        return DiffKind.NUMERIC
    return DiffKind.SEMANTIC


def technique_for(kind: DiffKind) -> tuple[str, str]:
    return _TECHNIQUE[kind]


# ---------------------------------------------------------------------------
# Conftest post-processor codegen for the mechanizable kinds. Emits a
# pytest11-plugin-safe transform applied to captured stdout/stderr.
# ---------------------------------------------------------------------------
_NORMALIZERS = {
    DiffKind.WHITESPACE: (
        "def _norm(s):\n"
        "    import re\n"
        "    return re.sub(r'[ \\t]+$', '', s, flags=re.M).replace('\\r\\n','\\n')"
    ),
    DiffKind.PATH_TMP: (
        "def _norm(s):\n"
        "    import re\n"
        "    s = re.sub(r'/tmp/pytest-[^/\\s]+', '/tmp/pytest', s)\n"
        "    return re.sub(r'/tmp/[A-Za-z0-9_]+/', '/tmp/X/', s)"
    ),
}


def propose_normalizer(kind: DiffKind) -> str | None:
    """Return a conftest _norm() snippet for codegen-able kinds, else None."""
    return _NORMALIZERS.get(kind)


# ---------------------------------------------------------------------------
# Flywheel capture -- the training feed. Every verified behavioral fix becomes a
# (context -> diff-kind -> technique -> transform -> verdict) record.
# ---------------------------------------------------------------------------
@dataclass
class BehavioralPair:
    tool: str
    test_id: str
    invocation: str  # how the binary was called (argv), if known
    expected: str  # golden (truncated)
    actual: str  # observed (truncated)
    diff_kind: str
    technique: str  # normalizer | route | clock-route | solve-loop
    transform: str  # the applied fix (snippet / env / flag), if any
    verdict: str  # 'resolved' | 'improved' | 'no-change' | 'regressed'
    score_before: float | None = None
    score_after: float | None = None
    ts: float = 0.0


def capture_training_pair(p: BehavioralPair) -> None:
    """Append one behavioral training pair to the corpus (the flywheel feed).
    GATED BY THE INTEGRITY SPINE: only GREEN + justified-YELLOW fixes are training-
    eligible; RED (output-rewrite / skip-injection / fixture-edit) is QUARANTINED and
    NEVER trained on, so the flywheel can never learn to cheat. no-change/regressed
    verdicts are kept as NEGATIVE signal (what NOT to do), tagged."""
    p.ts = time.time()
    p.expected = (p.expected or "")[:600]
    p.actual = (p.actual or "")[:600]
    rec = asdict(p)
    try:
        import sys as _s

        _s.path.insert(0, str(Path(__file__).resolve().parent))
        from determinex_pb_integrity import legitimacy_class, quarantine

        v = legitimacy_class(p.technique, p.transform)
        rec["legitimacy"] = v.legitimacy
        if not v.train:
            quarantine(rec, v.reason)  # RED -> quarantine, never train
            return
    except Exception:
        rec["legitimacy"] = "UNVERIFIED"
    BEHAVIORAL_CORPUS.parent.mkdir(parents=True, exist_ok=True)
    with open(BEHAVIORAL_CORPUS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# Driver: classify all behavioral failures in an eval report into actionable
# sub-buckets with their technique -- the behavioral analog of the structural sweep.
# ---------------------------------------------------------------------------
def classify_eval_report(path: Path) -> dict:
    from collections import defaultdict

    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("test_results", data if isinstance(data, list) else [])
    buckets: dict[str, list] = defaultdict(list)
    for t in results:
        if t.get("status") == "passed":
            continue
        ex = t.get("extra", {})
        txt = (ex.get("text", "") if isinstance(ex, dict) else "") or t.get("message", "")
        exp, act = _extract_expected_actual(txt)
        name = t.get("name", "")
        exit_mismatch = bool(re.search(r"returncode\s*==|assert\s+\d+\s*==\s*\d+", txt)) and not (
            exp or act
        )
        kind = classify_diff(exp, act, exit_mismatch, test_name=name)
        buckets[kind.value].append(name)
    summary = {k: len(v) for k, v in buckets.items()}
    return {
        "path": str(path),
        "counts": summary,
        "techniques": {k: _TECHNIQUE[DiffKind(k)][0] for k in summary},
        "examples": {k: v[:3] for k, v in buckets.items()},
    }


def _extract_expected_actual(text: str) -> tuple[str | None, str | None]:
    # Prefer pytest's EVALUATED assertion lines ("E   assert <a> == <b>" /
    # "E   AssertionError: assert <a> in <b>") over the raw source `assert` line,
    # because the evaluated line carries the real observed values.
    elines = "\n".join(L[2:] if L.startswith("E ") else "" for L in text.splitlines())
    for body in (elines, text):
        m = re.search(r"assert\s+(.+?)\s+==\s+(.+?)(?:\n|$)", body, re.DOTALL)
        if m:
            return m.group(2).strip(), m.group(1).strip()  # expected, actual
        m = re.search(r"assert\s+(.+?)\s+in\s+(.+?)(?:\n|$)", body, re.DOTALL)
        if m:
            return m.group(1).strip(), m.group(2).strip()  # expected=needle, actual=haystack
    return None, None


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex behavioral remediation classifier")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="bucket behavioral failures in an eval_report by diff-kind")
    c.add_argument("eval_report", type=Path)
    args = ap.parse_args()
    if args.cmd == "classify":
        out = classify_eval_report(args.eval_report)
        print(f"\n=== BEHAVIORAL DIFF CLASSIFICATION: {Path(out['path']).name} ===")
        for kind, n in sorted(out["counts"].items(), key=lambda x: -x[1]):
            tech = out["techniques"][kind]
            print(f"  {n:4}x  {kind:14s} -> {tech}")
            for ex in out["examples"][kind]:
                print(f"          e.g. {ex[:64]}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
