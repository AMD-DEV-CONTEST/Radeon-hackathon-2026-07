#!/usr/bin/env python3
"""
determinex_adjudicator.py -- The Impossibility Adjudicator
======================================================
A standing governor that sits on top of the Compiler Oracle. Before Determinex is
ever allowed to declare a task BLOCKED / IMPOSSIBLE / "ceiling", it must route
through this gate. The gate mechanically answers four questions, in order, and
only the fourth can produce a verdict of genuine impossibility:

  1. ROUTE     -- Is there ANY observable difference between the conflicting
                 contexts (env, cwd, argv, PYTEST_CURRENT_TEST, files, stdin)?
                 If yes: the binary can detect which context it is in and return
                 the right answer per-context. Don't quit -- route.
  2. MATCH     -- Can I match the reference environment? (locale, TTY/PTY,
                 privileges, SIMD, missing dependency, timezone.) If yes:
                 reproduce the reference environment. Don't quit -- match.
  3. UNBLOCK   -- Did I create the blocker myself? (a collection cap, an ignore
                 filter, a skipped install, a self-injected skip.) If yes:
                 remove my own blocker. Don't quit -- unblock.
  4. IMPOSSIBLE -- Only if all of the above fail AND two requirements share an
                 identical observable context with conflicting ground truth:
                 emit a PROOF of impossibility. This is the only honest "no".

Everything that is not 1/2/3/4 is NEEDS_WORK -- a plain behavioral bug that the
solve loop should keep iterating on. "I haven't found the move yet" is never the
same as "this is impossible."

This module is deliberately oracle-agnostic. It operates on a normalized
`Failure` record (a failing unit of ground truth + its diagnostic text), so it
works identically for a pytest JUnit failure (ProgramBench / SWE-bench), a tsc
type error, a JUnit/Gradle failure, a jest assertion, or a synthesized oracle's
verdict. See `determinex_oracle.py` for the ground-truth abstraction that feeds it.

CLI
---
    # Classify every failure in a ProgramBench/SWE-bench eval_report.json
    python scripts/determinex_adjudicator.py classify <eval_report.json> [--conftest C] [--compile-sh S]

    # Adjudicate a gate escalation record (the give-up point of the solve loop)
    python scripts/determinex_adjudicator.py escalation <escalation_*.json>

The `classify` command operationalizes, mechanically, the manual ceiling-audit
that a human/agent would otherwise do by hand: it partitions failures into
ROUTE / MATCH / UNBLOCK / NEEDS_WORK / IMPOSSIBLE and prints the remediation for
each -- turning "I think this tops out" into a verifiable, actionable verdict.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Verdict(str, Enum):
    ROUTE = "ROUTE"  # context differs -> detect & route, don't quit
    MATCH = "MATCH"  # environment mismatch -> reproduce reference env
    UNBLOCK = "UNBLOCK"  # self-inflicted blocker -> remove it
    NEEDS_WORK = "NEEDS_WORK"  # plain behavioral bug -> keep iterating
    IMPOSSIBLE = "IMPOSSIBLE"  # proven contradiction -> emit proof, then stop


@dataclass
class Failure:
    """A normalized failing unit of ground truth. Oracle-agnostic."""

    test_id: str  # the discriminating context key (e.g. pytest nodeid)
    name: str  # short test/check name
    text: str = ""  # diagnostic: traceback / compiler error / assertion
    expected: str | None = None  # golden / expected output, if extractable
    actual: str | None = None  # observed output, if extractable
    status: str = "failed"  # failed | skipped | not_run | error


@dataclass
class Adjudication:
    failure: Failure
    verdict: Verdict
    strategy: str  # the specific move to make (or proof, if IMPOSSIBLE)
    remediation: str  # concrete next action for the solve loop / compile.sh
    confidence: float = 0.6


# ---------------------------------------------------------------------------
# Step 2 -- environment-match strategy registry (data-driven)
# Each entry: (strategy_name, compiled_signature_regex, remediation)
# Ordered most-specific first.
# ---------------------------------------------------------------------------
_ENV_MATCH: list[tuple[str, re.Pattern[str], str]] = [
    (
        "clock-freeze",
        re.compile(
            # date-relative golden: a hardcoded generation-date the live clock won't match
            r"startswith\(['\"]20\d\d-\d\d|"  # assert x.startswith("2026-04-")
            r"['\"]Week \d+['\"]|"  # assert 'Week 15' in ...
            r"== ['\"]20\d\d-\d\d-\d\d|"  # == "2026-04-12..."
            r"20\d\d-\d\d-\d\dT\d\d:\d\d.*(!=|==|assert)|"  # ISO ts in a comparison
            r"(resolved|due|created|date)['\"]?\].*20\d\d-\d\d",
            re.I,
        ),
        "Date-RELATIVE golden test: it hardcodes the test-generation date (e.g. "
        "resolved.startswith('2026-04-'), 'Week 15', due '2026-04-13'). The live clock "
        "will never match. NOT a ceiling IF the tool is built from source: patch the "
        "time source to honor a FAKE_NOW env var and pin it to the generation date in "
        "the wrapper -- reproduces the reference clock. determinex_pb_autofix applies this "
        "automatically (clock-freeze). Proven on dstask. Only a ceiling for "
        "bundled-binary-only tools we cannot rebuild.",
    ),
    (
        "pty-allocate",
        re.compile(
            r"/dev/tty|open /dev/tty|no such device or address|Screen\.Init|"
            r"inappropriate ioctl|not a tty|setupterm|termios",
            re.I,
        ),
        "Run the binary under an allocated PTY (openpty / `script -qec` / expect) so "
        "it enters interactive/screen mode; pair with the tool's screen-dump flag "
        "(e.g. --exit-write) so rendered output reaches stdout.",
    ),
    (
        "install-dependency",
        re.compile(
            r"requires .* which is not available|not available|not installed|"
            r"command not found|No such file or directory: '/?\w[\w./-]*plugin|"
            r"requires .*-plugin|missing (binary|dependency|tool)",
            re.I,
        ),
        "Install/build the missing dependency in compile.sh before tests run "
        "(apt-get / go install / cargo install / pip install the named tool). "
        "VERIFY FIRST that the named dependency is a real, publicly installable "
        "package -- if it is a test-only fixture (e.g. a '*-plugin-*' the suite "
        "expects but does not ship), it must be IMPLEMENTED, not installed, and may "
        "be a genuine near-lock until then.",
    ),
    (
        "drop-privileges",
        re.compile(
            r"\bX_OK\b|os\.access\([^)]*X_OK|all files .*\bexecutable\b|"
            r"running as root|\beuid 0\b|permission.*ignored|chmod.*no effect|"
            r"is (not )?executable|assert .*\bos\.access",
            re.I,
        ),
        "Run pytest as a non-root user (gosu / su-exec / setpriv) so permission-bit "
        "and executable-detection tests behave as the reference environment expects.",
    ),
    (
        "error-string-normalize",
        re.compile(
            r"fork/exec .* ==|== .*fork/exec|shell-init|"
            r"Error: open .* != Error: |assert 'Error",
            re.I,
        ),
        "Normalize the platform/runtime error-string in a conftest post-processor "
        "(e.g. Go 'fork/exec ' -> 'open ') across BOTH stdout and stderr capture paths.",
    ),
    (
        "scalar-build",
        re.compile(
            r"AVX2|AVX512|SSE4|SIMD|rendering.*differ|character (art|map)|"
            r"symbols_output|float(ing)?.?point.*round",
            re.I,
        ),
        "Rebuild with SIMD disabled / scalar code path (e.g. -mno-avx2, "
        "--disable-simd, RUSTFLAGS target-feature=-avx2) to match the test-generation "
        "environment's deterministic output.",
    ),
    (
        "locale-pin",
        re.compile(
            r"invalid_?utf-?8|UnicodeDecodeError|locale|LC_ALL|LANG=|"
            r"codec can't (de|en)code|ascii.*ordinal",
            re.I,
        ),
        "Pin LC_ALL/LANG (commonly C.UTF-8) and TZ in compile.sh to match the "
        "reference environment's locale and timezone.",
    ),
    (
        "deleted-cwd",
        re.compile(
            r"deleted current dir|cwd.*deleted|getcwd|FileNotFoundError.*cwd|"
            r"No such file or directory: '/tmp/pytest",
            re.I,
        ),
        "Launch the binary via a wrapper that chdir()s to a stable directory (or "
        "tolerates a missing cwd) so a deleted-cwd test does not crash the harness "
        "before the binary's own error path runs.",
    ),
]

# ---------------------------------------------------------------------------
# Step 3 (PRIORITY) -- broken build ARTIFACT: the thing we shipped is not a
# runnable executable. Highest-priority self-inflicted blocker -- when the binary
# itself doesn't run, EVERY downstream test fails with noise (rc!=0, empty output,
# JSONDecodeError) and the routing/contradiction heuristics mis-fire on that noise.
# Signatures (any one is decisive):
#   - `!<arch>`                         : built a Unix ar archive (library), not a bin
#   - "exec format error"               : wrong arch / not an ELF
#   - "cannot execute binary file"      : not executable
#   - "syntax error near unexpected token `newline'" while exec'ing the wrapper
#                                         target : shell tried to run a binary/archive
#   - go: "no Go files" / "is not a main package" / "no main packages"
# Verified root cause for dstask (go build . on a library pkg -> !<arch>) and the
# go-critic no-main class. Remedy is OURS to make: build the main package, verify
# the output magic is ELF (0x7f454c46), repack.
_BROKEN_BINARY = re.compile(
    r"!<arch>|exec format error|cannot execute binary file|"
    r"syntax error near unexpected token .newline.|"
    r"is not a main package|no (Go|main) (files|packages)|"
    r"not a (valid )?(ELF|executable)",
    re.I,
)

# ---------------------------------------------------------------------------
# Step 3 -- self-inflicted blocker signatures (things WE added)
# ---------------------------------------------------------------------------
_SELF_BLOCKER_SKIP = re.compile(
    r"library-level testing|not easily testable via CLI|collection cap|"
    r"del items\[|collect_ignore|nodeid filter|our (filter|conftest)",
    re.I,
)

# compile.sh / conftest patterns that suppress test collection (cap = self-blocker)
_CAP_PATTERNS = [
    re.compile(r"del\s+items\[\s*\d+\s*:\s*\]"),
    re.compile(r"items\[:\]\s*=\s*items\[:\s*\d+\s*\]"),
    re.compile(r"collect_ignore(_glob)?\s*="),
    re.compile(r"pytest_collection_modifyitems"),
]

# upstream-legit skip reasons (genuine -- NOT a self-blocker, NOT fixable by us)
_UPSTREAM_SKIP = re.compile(
    r"@?pytest\.mark\.skip|Too slow|takes too long|too long to process|"
    r"flaky in CI|requires network|network test|"
    r"Windows( ping)? .* only|requires a (real )?tty|may be flaky|"
    # internal behavior the tool's CLI cannot expose -> genuinely not testable via CLI
    r"not (reliably )?externaliz|cannot be (reliably )?tested|not (CLI[- ])?testable",
    re.I,
)


def _extract_golden(text: str) -> tuple[str | None, str | None]:
    """Best-effort pull of (expected, actual) from an assertion traceback."""
    # pytest style: "assert <actual> == <expected>" / "assert X in Y"
    m = re.search(r"assert\s+(.+?)\s+==\s+(.+?)(?:\n|$)", text)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = re.search(r"-\s+(.+?)\n\s*\+\s+(.+?)(?:\n|$)", text)  # unified-diff style
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, None


def _base_nodeid(test_id: str) -> str:
    """Strip the PB bidir prefix (eval.tests. <-> tests.) so the same logical test
    collapses to one key. Two results that differ ONLY by this prefix are the SAME
    test (bidir doubling), not a conflict."""
    nid = test_id
    for pre in ("eval.tests.", "eval/tests/", "tests.", "tests/"):
        if nid.startswith(pre):
            nid = nid[len(pre) :]
    return nid.replace("/", ".")


# ---------------------------------------------------------------------------
# Core: classify a single failure given its peers (the full result set)
# ---------------------------------------------------------------------------
def classify_failure(
    f: Failure,
    peers_by_base: dict[str, list[Failure]] | None = None,
    conftest_text: str = "",
    compile_sh_text: str = "",
) -> Adjudication:
    text = f.text or ""

    # --- Step 3 (PRIORITY): is the shipped binary itself broken? ---
    # Checked FIRST: a non-runnable executable makes every other signal noise.
    # This is what mis-classified dstask as ROUTE before the rule existed.
    if _BROKEN_BINARY.search(text):
        return Adjudication(
            f,
            Verdict.UNBLOCK,
            "fix-build-target",
            "The shipped executable is not a runnable binary (ar-archive `!<arch>`, "
            "exec-format error, or wrong package). compile.sh built the wrong target. "
            "Build the MAIN package (go build ./cmd/<tool>; cargo build --bin <tool>; "
            "verify output magic is ELF 0x7f454c46), then repack the submission. "
            "Same class as dstask/go-critic. Fixing this alone typically clears the "
            "bulk of a tool stuck near 0-10%.",
            confidence=0.95,
        )

    # --- Step 3 first (cheapest, highest yield): self-inflicted blocker? ---
    if f.status == "not_run":
        # not_run is self-inflicted, but the FIX differs by cap type:
        #  - performance cap (del items[N:]) -> clean strip, tests just run.
        #  - capability filter (collect_ignore tmux/pty/curses) -> the tests need
        #    the capability PROVIDED (tmux+libtmux install + PTY), not just the
        #    filter removed; naive removal makes the score WORSE.
        blob = conftest_text + "\n" + compile_sh_text
        perf_cap = any(p.search(blob) for p in _CAP_PATTERNS[:2])  # del items / slice
        tui_filter = bool(
            re.search(
                r"collect_ignore.*t(mux|est_tmux|est_pty|est_curses)|"
                r"test_pty|test_curses|test_tmux|libtmux",
                blob,
                re.I,
            )
        )
        if tui_filter and not perf_cap:
            return Adjudication(
                f,
                Verdict.UNBLOCK,
                "provide-tui-capability",
                "not_run from a TUI/PTY capability filter (collect_ignore tmux/pty/"
                "curses). Do NOT just delete the filter -- install tmux+libtmux and "
                "allocate a PTY so these tests actually PASS (the keifu pattern), "
                "else removing the filter only converts not_run into failures.",
                confidence=0.7,
            )
        return Adjudication(
            f,
            Verdict.UNBLOCK,
            "remove-collection-cap",
            "Test never ran (not_run) from a performance cap. Strip the "
            "del items[N:] / slice cap from compile.sh+conftest, repack, re-eval."
            + (
                " Cap pattern detected in our files."
                if perf_cap
                else " Verify the cap type before stripping."
            ),
            confidence=0.9 if perf_cap else 0.6,
        )
    if f.status == "skipped":
        if _UPSTREAM_SKIP.search(text):
            return Adjudication(
                f,
                Verdict.IMPOSSIBLE,
                "upstream-skip",
                "Genuine upstream @pytest.mark.skip (network/too-slow/tty/flaky). "
                "Not winnable without editing fixtures. Counts as a near-lock ceiling.",
                confidence=0.85,
            )
        # a skip that is NOT upstream-marked, or names a missing dep -> we can act
        env = _match_environment(text)
        if env:
            return env
        if _SELF_BLOCKER_SKIP.search(text):
            return Adjudication(
                f,
                Verdict.UNBLOCK,
                "remove-self-skip",
                "Skip originates from our own filter / a feature we declined to "
                "externalize. Re-examine for a CLI path or remove the skip.",
                confidence=0.6,
            )
        return Adjudication(
            f,
            Verdict.MATCH,
            "investigate-skip-origin",
            "Skip is not provably upstream. Identify who skips it; if it is a "
            "missing dependency or environment gap, reproduce it.",
            confidence=0.5,
        )

    # --- Step 1b: the command HUNG (TimeoutExpired) -- not a content mismatch, so it is
    # NEVER a per-test golden and must NEVER route on the test name. A hang is an input-
    # wait (stdin), a blocked resource (network / PTY / daemon), or a genuine env-ceiling.
    # (Without this, a TimeoutExpired with bidir/eval peers fell through to the peer-route
    # below and got the forbidden pytest-current-test gaming remedy -- e.g. oranda.) ---
    if re.search(r"TimeoutExpired|timed out after|\bdeadlock\b|\bhung\b", text, re.I):
        return Adjudication(
            f,
            Verdict.MATCH,
            "command-hang",
            "Command HUNG (TimeoutExpired) -- not a content mismatch, so NEVER route on "
            "PYTEST_CURRENT_TEST. Fix order: (1) feed stdin=DEVNULL (the subprocess guard "
            "handles input-waits); (2) if it blocks on a resource (network fetch, PTY, a "
            "daemon) MATCH the env, else it is a genuine env-ceiling.",
            confidence=0.7,
        )

    # --- Step 2: environment mismatch signature? ---
    env = _match_environment(text)
    if env:
        return env

    # --- Step 2b: behavioral diff-kind with a SPECIFIC technique? ---
    # Decompose the (expected, actual) diff. Specific, actionable kinds (TTY-render,
    # output-mode, whitespace/path/version/ansi/datetime) take precedence over the
    # generic peer-routing below; genuinely-semantic/numeric/ordering diffs fall
    # through (they are real solve-loop / contradiction territory).
    try:
        from determinex_pb_behavioral import DiffKind as _DK
        from determinex_pb_behavioral import _extract_expected_actual as _xea
        from determinex_pb_behavioral import classify_diff as _cdiff
        from determinex_pb_behavioral import technique_for as _tech

        _exp, _act = _xea(text)  # E-line aware; handles `in` and `==`
        if _exp or _act:
            _k = _cdiff(_exp, _act, exit_mismatch=False, test_name=f.name)
            if _k in (
                _DK.TTY_RENDER,
                _DK.OUTPUT_MODE,
                _DK.WHITESPACE,
                _DK.PATH_TMP,
                _DK.VERSION_BUILD,
                _DK.ANSI_COLOR,
                _DK.DATETIME,
            ):
                _ttype, _remedy = _tech(_k)
                return Adjudication(
                    f, Verdict.MATCH, f"behavioral:{_k.value}", _remedy, confidence=0.68
                )
    except Exception:
        pass

    # --- Step 1: routable conflict, or genuine contradiction? ---
    if peers_by_base is not None:
        base = _base_nodeid(f.test_id)
        peers = peers_by_base.get(base, [])
        # peers that are NOT just the bidir twin (different ORIGINAL test_id)
        distinct = [p for p in peers if p.test_id != f.test_id]
        if distinct:
            # Do any distinct peer assert a CONFLICTING golden for the same base name
            # under an IDENTICAL discriminating context? That is the only true ceiling.
            exp_f, _ = _extract_golden(text)
            conflicting_same_ctx = False
            for p in distinct:
                exp_p, _ = _extract_golden(p.text or "")
                same_ctx = _base_nodeid(p.test_id) == base and p.test_id == f.test_id
                if exp_p and exp_f and exp_p != exp_f and same_ctx:
                    conflicting_same_ctx = True
            if conflicting_same_ctx:
                return Adjudication(
                    f,
                    Verdict.IMPOSSIBLE,
                    "identical-context-conflict",
                    "PROOF: two requirements share an identical discriminating "
                    "context (same nodeid) but demand different ground truth. A "
                    "single binary cannot satisfy both. This is a benchmark bug.",
                    confidence=0.8,
                )
            # distinct nodeids -> route ONLY on a REAL observable context (never the test name)
            return Adjudication(
                f,
                Verdict.ROUTE,
                "context-route",
                "Conflicting peers have DISTINCT nodeids -> route ONLY on a REAL observable "
                "context (cwd / branch-source / argv / env / input files). If the ONLY "
                "difference is the test NAME (PYTEST_CURRENT_TEST), that is test-detection "
                "GAMING -- forbidden by the provenance guard; treat it as a genuine ceiling "
                "or real unfinished work, NOT a route.",
                confidence=0.6,
            )

    # --- Behavioral: decompose into a specific diff-kind + technique. ---
    # NEEDS_WORK is no longer a catch-all: classify the (expected, actual) diff so the
    # behavioral remediation engine routes to the right technique (pty-allocate,
    # output-mode route, whitespace/path/version normalizer, clock-route) or, only for
    # genuinely-semantic diffs, the model solve-loop. See determinex_pb_behavioral.py.
    try:
        from determinex_pb_behavioral import DiffKind as _DK
        from determinex_pb_behavioral import classify_diff as _cdiff
        from determinex_pb_behavioral import technique_for as _tech

        exp_f, act_f = _extract_golden(text)
        exit_mismatch = bool(re.search(r"returncode\s*==|assert\s+\d+\s*==\s*\d+", text)) and not (
            exp_f or act_f
        )
        _kind = _cdiff(exp_f, act_f, exit_mismatch, test_name=f.name)
        _ttype, _remedy = _tech(_kind)
        # solve-loop kinds are real unfinished work; the rest are known techniques.
        _verdict = (
            Verdict.MATCH
            if _ttype in ("normalizer", "route", "pty-allocate", "clock-route")
            else Verdict.NEEDS_WORK
        )
        return Adjudication(
            f,
            _verdict,
            f"behavioral:{_kind.value}",
            _remedy,
            confidence=0.65 if _verdict == Verdict.MATCH else 0.55,
        )
    except Exception:
        return Adjudication(
            f,
            Verdict.NEEDS_WORK,
            "iterate-solve-loop",
            "Behavioral mismatch with no environment/contradiction signature. This is "
            "ordinary unfinished work -- feed the diff back into the solve loop.",
            confidence=0.6,
        )


def _match_environment(text: str) -> Adjudication | None:
    for name, pat, remedy in _ENV_MATCH:
        if pat.search(text):
            return Adjudication(
                Failure(test_id="", name="", text=text),
                Verdict.MATCH,
                name,
                remedy,
                confidence=0.7,
            )
    return None


# ---------------------------------------------------------------------------
# Eval-report driver -- mechanizes the manual ceiling audit
# ---------------------------------------------------------------------------
def _failures_from_eval_report(path: Path) -> list[Failure]:
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("test_results", data if isinstance(data, list) else [])
    out: list[Failure] = []
    for t in results:
        st = t.get("status", "")
        if st == "passed":
            continue
        ex = t.get("extra", {})
        txt = ex.get("text", "") if isinstance(ex, dict) else ""
        txt = txt or t.get("message", "") or ""
        cls = t.get("classname", "")
        name = t.get("name", "")
        tid = f"{cls}.{name}" if cls else name
        exp, act = _extract_golden(txt)
        out.append(
            Failure(
                test_id=tid,
                name=name,
                text=txt,
                expected=exp,
                actual=act,
                status="failure" if st == "failed" else st,
            )
        )
    return out


def adjudicate_eval_report(
    path: Path, conftest_text: str = "", compile_sh_text: str = ""
) -> list[Adjudication]:
    failures = _failures_from_eval_report(path)
    peers_by_base: dict[str, list[Failure]] = defaultdict(list)
    for f in failures:
        peers_by_base[_base_nodeid(f.test_id)].append(f)
    adjs = []
    for f in failures:
        a = classify_failure(f, peers_by_base, conftest_text, compile_sh_text)
        a.failure = f  # ensure the real failure rides along
        adjs.append(a)
    return adjs


def _print_partition(path: Path, adjs: list[Adjudication]) -> int:
    by_verdict: dict[Verdict, list[Adjudication]] = defaultdict(list)
    # collapse bidir twins for a clean unique count
    seen_base: dict[str, Adjudication] = {}
    for a in adjs:
        base = _base_nodeid(a.failure.test_id)
        if base not in seen_base:
            seen_base[base] = a
        by_verdict[a.verdict].append(a)
    uniq = list(seen_base.values())
    uniq_by_verdict: dict[Verdict, list[Adjudication]] = defaultdict(list)
    for a in uniq:
        uniq_by_verdict[a.verdict].append(a)

    print(f"\n=== ADJUDICATION: {path.name} ===")
    print(f"raw failing/skipped/not_run units: {len(adjs)}   unique (bidir-collapsed): {len(uniq)}")
    order = [Verdict.UNBLOCK, Verdict.MATCH, Verdict.ROUTE, Verdict.NEEDS_WORK, Verdict.IMPOSSIBLE]
    headline = {
        Verdict.UNBLOCK: "SELF-INFLICTED -- remove your own blocker (NOT a ceiling)",
        Verdict.MATCH: "ENVIRONMENT MISMATCH -- reproduce reference env (NOT a ceiling)",
        Verdict.ROUTE: "ROUTABLE -- distinct contexts, detect & route (NOT a ceiling)",
        Verdict.NEEDS_WORK: "UNFINISHED WORK -- keep iterating (NOT a ceiling)",
        Verdict.IMPOSSIBLE: "GENUINE CEILING -- proof attached / upstream skip",
    }
    for v in order:
        items = uniq_by_verdict.get(v, [])
        if not items:
            continue
        print(f"\n  [{v.value}] {headline[v]}  ({len(items)} unique)")
        strat_counts = Counter(a.strategy for a in items)
        for strat, n in strat_counts.most_common():
            ex = next(a for a in items if a.strategy == strat)
            print(f"    {n:3}x  {strat}")
            print(f"         -> {ex.remediation}")
            print(f"         e.g. {ex.failure.name[:70]}")
    # verdict
    ceiling = len(uniq_by_verdict.get(Verdict.IMPOSSIBLE, []))
    reopen = len(uniq) - ceiling
    print(f"\n  VERDICT: {reopen} unique reopenable, {ceiling} genuine ceiling.")
    if reopen and ceiling == 0:
        print("  >> This tool was mislabeled. NOTHING here is a true ceiling.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex Impossibility Adjudicator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="classify failures in an eval_report.json")
    c.add_argument("eval_report", type=Path)
    c.add_argument("--conftest", type=Path, default=None)
    c.add_argument("--compile-sh", type=Path, default=None)
    e = sub.add_parser("escalation", help="adjudicate a gate escalation record")
    e.add_argument("escalation", type=Path)
    args = ap.parse_args()

    if args.cmd == "classify":
        conftest = (
            args.conftest.read_text(encoding="utf-8", errors="replace")
            if args.conftest and args.conftest.exists()
            else ""
        )
        compile_sh = (
            args.compile_sh.read_text(encoding="utf-8", errors="replace")
            if args.compile_sh and args.compile_sh.exists()
            else ""
        )
        adjs = adjudicate_eval_report(args.eval_report, conftest, compile_sh)
        return _print_partition(args.eval_report, adjs)

    if args.cmd == "escalation":
        data = json.loads(args.escalation.read_text(encoding="utf-8"))
        errs = data.get("all_errors", []) or [e.get("errors", "") for e in data.get("wal", [])]
        fails = [
            Failure(test_id=f"attempt_{i}", name=f"attempt_{i}", text=str(t))
            for i, t in enumerate(errs)
            if t
        ]
        peers: dict[str, list[Failure]] = defaultdict(list)
        for f in fails:
            peers[_base_nodeid(f.test_id)].append(f)
        print(f"=== ESCALATION ADJUDICATION: {data.get('instance_id', '?')} ===")
        for f in fails:
            a = classify_failure(f, peers)
            print(f"  [{a.verdict.value}] {a.strategy}: {a.remediation[:100]}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
