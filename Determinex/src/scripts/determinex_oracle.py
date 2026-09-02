#!/usr/bin/env python3
"""
determinex_oracle.py -- The Universal Ground-Truth Oracle
======================================================
Determinex's entire moat is the Compiler Oracle: a deterministic source of ground
truth that the solve loop iterates against, with zero LLM judging. ProgramBench
proved this works for systems languages (Rust/Go/C/C++/Python) because PB SHIPS
the ground truth (a real test suite per task).

To make the IDE "natively know how to fix anything, any system, any language,"
two things must generalize:

  1. The oracle must be PLUGGABLE per language/domain. A tsc type error, a jest
     assertion, a JUnit/Gradle failure, an eslint diagnostic, a SQL planner
     error -- each is just another deterministic ground-truth surface. Register
     it, and the same closed loop (generate -> verify -> adjudicate -> iterate)
     runs unchanged. This is how we reach the JVM/JS-TS/mobile/web worlds that
     PB's language distribution never covers (and that Determinex's own products --
     Hook=Kotlin, SwingSwap/Aide=TypeScript -- actually live in).

  2. Where NO ground truth is shipped (greenfield work, or a domain PB has no
     task for), the system must SYNTHESIZE the oracle: derive an executable
     specification (characterization tests, property tests, type/contract checks,
     golden captures) BEFORE writing the fix, then run the same loop against it.
     "It should make tests for the ones it doesn't have" -- that is this module.

Design contract
---------------
An Oracle answers one question deterministically: does the work-tree satisfy
ground truth right now? It returns an `OracleResult` whose failures are already
normalized into `determinex_adjudicator.Failure` records, so the Adjudicator's
4-step gate runs identically regardless of language or domain.

    oracle = get_oracle("typescript")          # or "rust", "go", "kotlin", ...
    result = oracle.verify(workdir)             # deterministic; no LLM
    if not result.passed:
        for f in result.failures:
            adj = classify_failure(f, ...)      # ROUTE/MATCH/UNBLOCK/NEEDS_WORK/IMPOSSIBLE
            ...

This file ships REAL implementations for the surfaces Determinex already has
toolchains for, and explicit, typed STUBS (with the exact command they will run)
for the surfaces on the day-one roadmap. A stub raises OracleUnavailable with the
install hint rather than silently passing -- the oracle never lies.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

try:
    from determinex_adjudicator import Failure
except ImportError:  # allow `python scripts/determinex_oracle.py` from repo root
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from determinex_adjudicator import Failure


class OracleUnavailable(RuntimeError):
    """Raised when an oracle's toolchain is not installed. Carries the fix hint."""


class OracleTimedOut(RuntimeError):
    """Raised when a verification run exceeded its time budget.

    A timeout is NOT a verdict about the code. Before this existed, `_run` rebuilt a
    `subprocess.CompletedProcess` from the hardened runner's result and DISCARDED
    `res.timed_out`, so every one of the 19 verify_fns fell through to its "non-zero exit
    with no parsed failures" branch. Measured 2026-08-02 on a workspace containing a single
    healthy test that merely slept:

        passed=False
        test_id=pytest  name=collection/run
        "pytest exited -3 with no parsed test failures (collection or environment error)"

    The repository was fine. Determinex ran out of patience and reported a defect in the
    user's environment -- a check stating an outcome it never established, which is the one
    thing this project forbids everywhere else.

    Raising keeps the doctrine intact in both directions: it is not a pass, and it is not a
    finding either. The caller is told what actually happened.
    """

    def __init__(self, message: str, *, seconds: int = 0, oracle: str = "") -> None:
        super().__init__(message)
        self.seconds = seconds
        self.oracle = oracle


class OracleNeedsApproval(RuntimeError):
    """Raised when verification is predicted to cost more time than the caller allowed.

    Ryan, 2026-08-02, on watching `repair_diagnose` block for ten minutes and then misreport
    the result: "if it needs it it should tell you it will take that long, get permission to
    run and then come back, if not not do it."

    That is the correct shape. Silently blocking a UI for ten minutes is a bad experience;
    silently blocking it and then reporting a fabricated defect is a correctness bug. Both
    disappear if the system measures the job first, states the cost, and asks.

    Carries `estimate_s` and `detail` so a frontend can render "this will take about N
    minutes -- run it?" rather than inventing its own guess.
    """

    def __init__(self, message: str, *, estimate_s: float = 0.0, detail: str = "") -> None:
        super().__init__(message)
        self.estimate_s = estimate_s
        self.detail = detail


@dataclass
class OracleResult:
    passed: bool
    failures: list[Failure] = field(default_factory=list)
    raw: str = ""
    oracle: str = ""
    total: int = 0
    n_passed: int = 0


#: Per-oracle "hello world" that a working toolchain MUST verify. Deliberately minimal: the
#: probe has to fail only when the toolchain is broken, never because the fixture was
#: ambitious. An oracle with no entry is assumed healthy and says so, because inventing a
#: health verdict is the error this whole mechanism exists to prevent.
_TOOLCHAIN_SMOKE: dict[str, dict[str, str]] = {
    "python": {
        "solution.py": "def add(a, b):\n    return a + b\n",
        "test_smoke.py": "from solution import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
    },
    "rust": {
        "Cargo.toml": '[package]\nname = "smoke"\nversion = "0.1.0"\nedition = "2021"\n',
        "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n",
    },
    "go": {"go.mod": "module smoke\n\ngo 1.21\n",
           "main.go": "package main\n\nfunc main() { _ = 1 }\n"},
    "typescript": {
        "tsconfig.json": '{"compilerOptions":{"noEmit":true,"target":"ES2020"},"include":["*.ts"]}',
        "index.ts": "export const x: number = 1;\n",
    },
    "c": {"main.c": "int main(void) { return 0; }\n"},
    "cpp": {"main.cpp": "int main() { return 0; }\n"},
    "swift": {
        "Package.swift": '// swift-tools-version:5.7\nimport PackageDescription\n'
                         'let package = Package(name: "smoke", targets: [.target(name: "smoke")])\n',
        "Sources/smoke/main.swift": "public func add(_ a: Int, _ b: Int) -> Int { a + b }\n",
    },
    "dotnet": {
        "p.csproj": '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                    "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
        "Program.cs": "public class P { public static int Add(int a, int b) => a + b; }\n",
    },
    "ruby": {"lib.rb": "def add(a, b)\n  a + b\nend\n"},
    "php": {"lib.php": "<?php\nfunction add($a, $b) { return $a + $b; }\n"},
}

#: Process-lifetime cache of toolchain health. A toolchain cannot repair itself mid-run, and
#: some of these probes cost ten seconds.
_TOOLCHAIN_HEALTH: dict[str, tuple[bool, str]] = {}


@dataclass
class Oracle:
    """A deterministic ground-truth surface for one language/domain."""

    name: str
    languages: tuple[str, ...]
    probe: tuple[str, ...]  # ANY of these on PATH proves the toolchain
    install_hint: str  # how to get the toolchain
    verify_fn: Callable[[Path], OracleResult]

    def available(self) -> bool:
        # Available if ANY probed tool is present. The JVM oracle, e.g., can
        # drive gradle OR maven OR plain javac — having any one is enough.
        #
        # NOTE this asks only whether the binary EXISTS. Whether it WORKS is a different
        # question, answered by `toolchain_healthy()` -- see the note there for why the
        # distinction is load-bearing.
        return any(shutil.which(p) is not None for p in self.probe)

    def toolchain_healthy(self) -> tuple[bool, str]:
        """(healthy, detail) — can this toolchain verify a known-good trivial program?

        WHY THIS EXISTS. `available()` checks PATH. On 2026-08-02 this machine had
        `swift.exe` on PATH and a broken Swift-on-Windows SDK: every build died with
        `error: could not build C module 'SwiftOverlayShims'`, which has nothing to do with
        the code under test. The oracle dutifully reported the USER'S program as failing.
        A broken toolchain accusing the user's code is the same shape as the timeout that
        reported "collection or environment error" -- our problem, described as theirs.

        The probe is a minimal program the toolchain must accept. If it cannot compile hello
        world, nothing it says about the user's code is evidence.

        Cached per process: the answer cannot change mid-run, and some of these builds cost
        ten seconds. Only consulted when a verification FAILS, so the happy path never pays.
        """
        if self.name in _TOOLCHAIN_HEALTH:
            return _TOOLCHAIN_HEALTH[self.name]
        smoke = _TOOLCHAIN_SMOKE.get(self.name)
        if smoke is None:
            # No probe defined: say so rather than claiming health we did not establish.
            _TOOLCHAIN_HEALTH[self.name] = (True, "no smoke test defined for this oracle")
            return _TOOLCHAIN_HEALTH[self.name]
        import tempfile

        ws = Path(tempfile.mkdtemp(prefix="dtx_smoke_"))
        for rel, body in smoke.items():
            p = ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        try:
            res = self.verify_fn(ws)
            out = (True, "") if res.passed else (
                False,
                f"the {self.name} toolchain could not verify a trivial known-good program; "
                f"{(res.raw or '').strip()[-300:]}",
            )
        except Exception as e:  # a toolchain that raises on hello world is not usable
            out = (False, f"{type(e).__name__}: {str(e)[:200]}")
        _TOOLCHAIN_HEALTH[self.name] = out
        return out

    def verify(self, workdir: Path, *, approved: bool = False) -> OracleResult:
        """Verify `workdir`, refusing to start a job whose cost the caller has not accepted.

        The gate exists because `repair_diagnose` on a real repository blocked a UI for ten
        minutes with no output and then reported a fabricated defect. Both halves of that
        are fixed by asking first: estimate the work, and if it exceeds the caller's budget
        raise `OracleNeedsApproval` carrying the estimate, so a frontend can say "this will
        take about N minutes -- run it?" instead of freezing or guessing.

        `approved=True` (or DETERMINEX_ORACLE_APPROVED=1) is the caller saying yes. It skips
        the gate, never the verification.
        """
        if not self.available():
            raise OracleUnavailable(
                f"oracle '{self.name}' needs one of {self.probe}. {self.install_hint}"
            )
        if not (approved or os.environ.get("DETERMINEX_ORACLE_APPROVED") == "1"):
            budget = _oracle_budget_s()
            pf = preflight(self.name, workdir)
            estimate = (
                (pf.estimate_s, pf.summary()) if pf is not None
                else estimate_work(self.name, workdir)
            )
            if estimate is not None and estimate[0] > budget:
                secs, detail = estimate
                extra = ""
                if pf is not None and pf.broken_paths:
                    # Say the cheap finding OUT LOUD at the moment of asking. A user deciding
                    # whether to spend 44 minutes should know we already found files that do
                    # not import -- that is often the answer they came for.
                    first = ", ".join(path for path, _ in pf.broken_paths[:3])
                    extra = (f" Already found without running anything: "
                             f"{len(pf.broken_paths)} path(s) do not import ({first}).")
                raise OracleNeedsApproval(
                    f"verifying this workspace with the '{self.name}' oracle is estimated at "
                    f"~{secs / 60:.0f} min ({detail}), over the {budget}s budget.{extra} "
                    f"Approve to run it (approved=True / DETERMINEX_ORACLE_APPROVED=1), "
                    f"narrow it (DETERMINEX_PYTEST_SCOPE), or raise "
                    f"DETERMINEX_ORACLE_BUDGET_S.",
                    estimate_s=secs,
                    detail=detail,
                )
        result = self.verify_fn(workdir)
        if not result.passed:
            # Before blaming the code, check that the toolchain can verify anything at all.
            # Measured 2026-08-02: `swift.exe` was on PATH with a broken Windows SDK, so
            # every build died on `could not build C module 'SwiftOverlayShims'` and the
            # oracle reported the USER'S program as failing. A toolchain that cannot compile
            # hello world produces no evidence about anyone's code.
            healthy, detail = self.toolchain_healthy()
            if not healthy:
                raise OracleUnavailable(
                    f"oracle '{self.name}' is installed but not working, so its verdict is "
                    f"not evidence about this code. {detail} {self.install_hint}"
                )
        return result


# ---------------------------------------------------------------------------
# Cost estimation — know what a job costs BEFORE starting it
# ---------------------------------------------------------------------------
#: Seconds of verification a caller gets without being asked. Deliberately short: the point
#: is that anything longer becomes a decision the operator makes knowingly, not a UI freeze.
_DEFAULT_ORACLE_BUDGET_S = 120

#: Seconds per collected pytest test. Derived from this repository's own suite, which is the
#: largest one on hand: 5,670 tests in 2,608s = 0.46 s/test. A rate is far more honest than a
#: fixed guess -- it scales with the repo instead of pretending every project is the same
#: size -- and it only has to be right to within a factor of two to answer "minutes or
#: seconds?", which is the question the operator is actually being asked.
_SECONDS_PER_PYTEST_TEST = 0.46


def _oracle_budget_s() -> int:
    try:
        return max(1, int(os.environ.get("DETERMINEX_ORACLE_BUDGET_S", "")
                          or _DEFAULT_ORACLE_BUDGET_S))
    except ValueError:
        return _DEFAULT_ORACLE_BUDGET_S


#: Directory names that are somebody else's code or a build artifact. Collecting them means
#: verifying dependencies instead of the project, and it is the single biggest reason a
#: "quick check" turns into a 40-minute run. pytest's default `norecursedirs` catches `.*`,
#: `build`, `dist` and `venv` -- it does NOT catch node_modules, vendor, third_party,
#: site-packages reached by a symlink, or a corpus of vendored upstream checkouts.
_NOISE_DIRS = (
    "node_modules", "site-packages", "vendor", "third_party", "thirdparty",
)
#: Pruned from the walk but NOT reported. pytest never collects from these anyway, so
#: listing them is output the reader has to skip past -- this repo produced 40 lines of
#: `__pycache__` under a heading that said "vendored/generated path(s) excluded", which
#: buries the one line that mattered.
_PRUNE_ONLY_DIRS = ("__pycache__", ".tox", ".eggs", ".mypy_cache", ".pytest_cache")
# DELIBERATELY NOT HERE: target, out, bin, obj.
#
# The first version included them and the result was 38 hits of `.../source/bin` on this
# repo -- Rust's `src/bin` is REAL SOURCE, and excluding it would have hidden exactly the
# code a user asked us to check. "It is probably a build directory" is not good enough for a
# list whose job is to decide what does not get verified; every name here has to be one that
# is never hand-written source. A false positive in this list is worse than a false negative,
# because a slow check is annoying and an unverified file is a lie.


@dataclass
class Preflight:
    """What a cheap look at a workspace establishes before anything expensive runs.

    Ryan, 2026-08-02: "our onboard runtimes should tell us what compiles what doesn't from
    the jump, we should filter what doesn't work. or what paths are clunky for looking at.
    it's about finding the patterns, fixing and correcting."

    The cost gate that preceded this was honest but blunt -- it priced the whole job and
    asked permission to spend 44 minutes. The better answer is usually that 44 minutes was
    never the right job: part of that tree does not import at all (which is a finding, and a
    cheap one), and part of it is vendored code that was never ours to verify.
    """

    oracle: str
    collectible: int = 0
    #: (path, first line of the error) for files that could not even be imported. These are
    #: real findings available in seconds -- "what compiles and what doesn't, from the jump".
    broken_paths: list[tuple[str, str]] = field(default_factory=list)
    #: Vendored / generated directories present in the tree that should not be verified.
    noise_paths: list[str] = field(default_factory=list)
    estimate_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        """True when the cheap pass already found something worth showing a human."""
        return bool(self.broken_paths or self.noise_paths)

    def summary(self) -> str:
        bits = [f"{self.collectible} tests collectible (~{self.estimate_s / 60:.0f} min)"]
        if self.broken_paths:
            bits.append(f"{len(self.broken_paths)} path(s) do not import")
        if self.noise_paths:
            bits.append(f"{len(self.noise_paths)} vendored/generated path(s) excluded")
        return "; ".join(bits)


def find_noise_paths(
    workdir: Path,
    limit: int = 40,
    max_dirs: int = 20000,
    max_depth: int = 6,
    budget_s: float = 5.0,
) -> list[str]:
    """Vendored or generated directories under `workdir`, as workspace-relative paths.

    Walked rather than globbed so a nested `node_modules` deep in a monorepo is found, and
    pruned as it goes so it does not descend INTO the trees it is reporting.

    BOUNDED, because the first version was not. This runs inside a "cheap look before the
    expensive run", and on this repository -- which vendors ~155,000 files under `corpus/`,
    a directory that is legitimately NOT in the noise list -- an unbounded walk took
    `repair_diagnose` from 20s to 64s. A pre-flight that costs a minute is not a pre-flight.

    Both bounds are deliberate rather than defensive: vendored trees live near the top of a
    project (`node_modules`, `vendor`, `target`), so depth 6 finds them in any realistic
    monorepo, and 20,000 directories is far more than any hand-written source tree while
    being a small fraction of a vendored one. Hitting a bound is reported in the returned
    list's absence, not concealed -- see `Preflight.notes` via `preflight_python`.
    """
    found: list[str] = []
    base_depth = len(workdir.parts)
    visited = 0
    deadline = time.monotonic() + budget_s
    for root, dirs, _files in os.walk(workdir):
        visited += 1
        # A WALL-CLOCK budget, because "cheap" is a statement about seconds and no count of
        # directories predicts them. Measured on this repo: a 20,000-directory cap still let
        # the walk run 50s once dot-directories were pruned, because it then descended into
        # corpus/programbench/per_tool_overrides -- 142,750 files, ~420 of which are ours.
        if visited > max_dirs or time.monotonic() > deadline:
            break
        if len(Path(root).parts) - base_depth >= max_depth:
            dirs.clear()  # stop descending; do not walk a deep vendored tree looking for one
            continue
        # Never descend into a dot-directory. pytest's own `norecursedirs` default already
        # excludes `.*`, so they cannot contribute collectible tests and reporting them as
        # "excluded" tells the user nothing. It is also where the time went: this repo keeps
        # a multi-gigabyte `.determinex_staging` tree of vendored checkouts, and walking it
        # took the pre-flight to 192 SECONDS -- three times longer than the run it was
        # supposed to be cheaper than.
        for d in [x for x in dirs if x.startswith(".") or x in _PRUNE_ONLY_DIRS]:
            dirs.remove(d)
        pruned = []
        for d in list(dirs):
            if d in _NOISE_DIRS:
                rel = os.path.relpath(os.path.join(root, d), workdir).replace("\\", "/")
                if len(found) < limit:
                    found.append(rel)
                pruned.append(d)
        for d in pruned:
            dirs.remove(d)  # do not descend into it
        if len(found) >= limit:
            break
    return sorted(found)


def preflight_python(workdir: Path) -> Preflight:
    """Collect-only pass: what runs, what does not import, what is not ours."""
    pf = Preflight(oracle="python")
    pf.noise_paths = find_noise_paths(workdir)
    est = estimate_python_work(workdir, _collected=pf)
    if est is not None:
        pf.estimate_s = est[0]
    return pf


def estimate_python_work(
    workdir: Path, _collected: Preflight | None = None
) -> tuple[float, str] | None:
    """(estimated seconds, human detail) for a pytest run, or None if unknowable.

    Uses pytest's own collection, which is cheap relative to running the tests and is the
    only source that knows how many there actually are. Collection is itself capped, and a
    collection that blows the cap is reported as "too large to estimate" rather than as an
    estimate of zero -- an unmeasurable job is exactly the one worth asking about.
    """
    from intake.hardened_runner import run as _hrun

    # Exclude vendored/generated trees from the COLLECTION too, not just from the report.
    # Counting somebody else's test suite and then quoting the operator a number based on it
    # is a wrong estimate, not merely a noisy one.
    ignores: list[str] = []
    for rel in (_collected.noise_paths if _collected is not None else find_noise_paths(workdir)):
        ignores += ["--ignore", rel]

    try:
        res = _hrun(
            [_repo_python(workdir), "-m", "pytest", "--collect-only", "-q",
             "-p", "no:cacheprovider", *ignores],
            workspace=workdir, cwd=workdir, timeout=90,
            allow_network=False, output_limit=None,
        )
    except Exception:
        return None
    if res.timed_out:
        if _collected is not None:
            _collected.notes.append("collection alone exceeded 90s; the tree is very large")
        return (float("inf"), "test collection alone exceeded 90s; the suite is very large")
    text = (res.stdout or "") + (res.stderr or "")

    # WHAT DOES NOT IMPORT, reported from the cheap pass. pytest names each uncollectable
    # file; those are real findings available in seconds, and before this they were invisible
    # until (or unless) the full run finished.
    if _collected is not None:
        seen: set[str] = set()
        for m in re.finditer(r"ERROR\s+(?:collecting\s+)?(\S+\.py)", text):
            path = m.group(1).replace("\\", "/")
            if path in seen:
                continue
            seen.add(path)
            after = text[m.end(): m.end() + 400]
            reason = next(
                (ln.strip() for ln in after.splitlines()
                 if ln.strip() and not ln.strip().startswith(("_", "="))),
                "",
            )
            _collected.broken_paths.append((path, reason[:160]))

    m = re.search(r"(\d+)\s+tests?\s+collected", text)
    if not m:
        m = re.search(r"collected\s+(\d+)\s+items?", text)
    if not m:
        return None
    n = int(m.group(1))
    if _collected is not None:
        _collected.collectible = n
    return (n * _SECONDS_PER_PYTEST_TEST, f"{n} tests collected")


#: Per-oracle cost estimators. An oracle with no entry is NOT gated -- an absent estimate
#: must never become a fabricated one, and gating on a number nobody measured would block
#: work for a reason the system cannot defend. Python is measured; the rest are honest
#: blanks until someone measures them.
_WORK_ESTIMATORS: dict[str, Callable[[Path], tuple[float, str] | None]] = {
    "python": estimate_python_work,
}


def estimate_work(oracle_name: str, workdir: Path) -> tuple[float, str] | None:
    fn = _WORK_ESTIMATORS.get(oracle_name)
    if fn is None:
        return None
    try:
        return fn(workdir)
    except Exception:
        return None  # an estimator that fails must not block the real work


#: Per-oracle cheap triage. Same rule as the estimators: no entry means no triage, never an
#: invented one.
_PREFLIGHTS: dict[str, Callable[[Path], Preflight]] = {
    "python": preflight_python,
}


def preflight(oracle_name: str, workdir: Path) -> Preflight | None:
    """Cheap look before an expensive run: what runs, what will not import, what is vendored.

    Separated from `estimate_work` because the two answer different questions and only one
    of them is about time. The estimate says "this costs 44 minutes"; the pre-flight says
    "and 40 of those minutes are node_modules, and two of your files do not import" -- which
    is usually the more useful sentence and is available just as cheaply.
    """
    fn = _PREFLIGHTS.get(oracle_name)
    if fn is None:
        return None
    try:
        return fn(workdir)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers shared by concrete oracles
# ---------------------------------------------------------------------------
def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    # Route through the hardened runner: cwd is workspace-bounded and the child
    # env is secret-scrubbed. allow_network=True because oracle BUILDS legitimately
    # fetch dependencies (cargo/go/npm/gradle) — the operator's own toolchain is
    # trusted-by-design; what we harden here is path-bounding + secret hygiene.
    # Returns a CompletedProcess so every verify_fn caller stays unchanged.
    from intake.hardened_runner import run as _hrun

    res = _hrun(cmd, workspace=cwd, cwd=cwd, timeout=timeout, allow_network=True, output_limit=None)
    if res.timed_out:
        # RAISE, do not hand back a non-zero CompletedProcess.
        #
        # This flag used to be dropped on the floor here. Every verify_fn then saw a
        # non-zero exit with no parsed test failures and reported it as a collection or
        # environment error -- i.e. as a defect in the user's repository. There are 24 call
        # sites in 19 verify functions and all of them had that bug, because none of them
        # could see the one fact that distinguishes "your code is broken" from "we stopped
        # waiting". Fixing it at the choke point fixes it everywhere at once.
        raise OracleTimedOut(
            f"verification exceeded its {timeout}s budget running {' '.join(cmd[:4])}...; "
            f"this is a Determinex time limit, NOT a finding about the code. "
            f"Narrow the run (DETERMINEX_PYTEST_SCOPE) or raise the budget "
            f"(DETERMINEX_ORACLE_BUDGET_S).",
            seconds=timeout,
        )
    return subprocess.CompletedProcess(
        args=cmd, returncode=res.exit_code, stdout=res.stdout, stderr=res.stderr
    )


def _junit_failures(xml_path: Path) -> list[Failure]:
    """Parse a JUnit XML into normalized Failure records (jest/pytest/gradle/go all
    emit JUnit). Kept dependency-free with ElementTree."""
    import xml.etree.ElementTree as ET

    out: list[Failure] = []
    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:
        return out
    for tc in root.iter("testcase"):
        cls = tc.get("classname", "")
        name = tc.get("name", "")
        tid = f"{cls}.{name}" if cls else name
        fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        skip = tc.find("skipped")
        if fail is not None:
            out.append(
                Failure(
                    test_id=tid,
                    name=name,
                    text=(fail.get("message", "") + "\n" + (fail.text or "")),
                    status="failure",
                )
            )
        elif skip is not None:
            out.append(
                Failure(
                    test_id=tid,
                    name=name,
                    text=skip.get("message", "") or (skip.text or ""),
                    status="skipped",
                )
            )
    return out


def _junit_counts(xml_path: Path) -> tuple[int, int]:
    """Parse a JUnit XML into (total, n_passed) testcase counts.

    Every OracleResult below previously left `total`/`n_passed` at the
    dataclass default of 0 -- pass/fail itself was always correct (verified
    live 2026-07-02), but the counters were silently dead across every
    JUnit-backed oracle (python/jvm/swift/dotnet/ruby/php/typescript), which
    matters because determinex_oracle_env's OpenEnv observation contract
    exposes these exact fields to external RL consumers. A skipped testcase
    counts toward total but not n_passed (it neither passed nor failed)."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:
        return (0, 0)
    total = 0
    n_passed = 0
    for tc in root.iter("testcase"):
        total += 1
        fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        skip = tc.find("skipped")
        if fail is None and skip is None:
            n_passed += 1
    return (total, n_passed)


def _uses_vitest(workdir: Path) -> bool:
    """vitest vs jest -- checked, not assumed. A vitest.config.* file is the
    clearest signal; falls back to checking package.json's own dependency
    lists (covers a vitest project configured inline in package.json's
    "test" script with no separate config file)."""
    for cfg in (
        "vitest.config.ts",
        "vitest.config.js",
        "vitest.config.mjs",
        "vitest.config.cjs",
        "vite.config.ts",
        "vite.config.js",
    ):
        if (workdir / cfg).exists():
            # vite.config.* only counts if it actually configures a `test`
            # block -- a plain Vite app with no vitest set up shouldn't
            # falsely route here.
            if cfg.startswith("vitest.config"):
                return True
            try:
                if "test" in (workdir / cfg).read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                pass
    pkg = workdir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "vitest" in deps:
                return True
        except (OSError, json.JSONDecodeError):
            pass
    return False


def _has_test_framework(workdir: Path) -> bool:
    """Does this subproject actually have a JS/TS test framework configured
    at all? A package.json with no jest/vitest dependency and no "test"
    script (e.g. a thin CLI-wrapper extension whose only scripts are
    compile/package) has nothing for _verify_typescript's test-run step to
    invoke -- that's "nothing to verify", not "0 tests ran"."""
    if _uses_vitest(workdir):
        return True
    pkg = workdir / "package.json"
    if not pkg.exists():
        return False
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    if "jest" in deps:
        return True
    test_script = data.get("scripts", {}).get("test", "")
    # npm's own default placeholder for `npm init` scaffolds -- explicitly
    # NOT a real test command.
    return bool(test_script) and "Error: no test specified" not in test_script


# ---------------------------------------------------------------------------
# Concrete oracle: TypeScript / JavaScript (tsc + jest/vitest)
# This is the surface Determinex's OWN products live in -- highest day-one priority.
# ---------------------------------------------------------------------------
def _verify_typescript(workdir: Path) -> OracleResult:
    # Found live 2026-07-22: this whole function computed `passed = len(failures)
    # == 0` -- if tsc/jest failed to even LAUNCH (missing binary, bad --
    # no-install resolution, config error) with a nonzero exit that didn't
    # happen to contain a parseable "error TSxxxx"/JUnit failure line,
    # `failures` stayed empty and the oracle silently reported PASSED without
    # ever actually verifying anything. Ryan: "it should be fixed to where it
    # all compiles and reports one way or the other" -- a tool that couldn't
    # run is not the same claim as "nothing's wrong", and must never be
    # reported identically.
    raw = []
    failures: list[Failure] = []
    ran_typecheck = False
    # 1) type check -- tsc is itself a compiler oracle (no tests required)
    if (workdir / "tsconfig.json").exists():
        ran_typecheck = True
        cp = _run(["npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"], workdir)
        out = cp.stdout + cp.stderr
        raw.append(out)
        ts_failures = [
            Failure(
                test_id=line.split("(")[0].strip(),
                name=line.split("(")[0].strip(),
                text=line,
                status="failure",
            )
            for line in out.splitlines()
            if "): error TS" in line
        ]
        failures.extend(ts_failures)
        if cp.returncode != 0 and not ts_failures:
            # tsc itself failed to produce a real type-check verdict (missing
            # binary, npx resolution failure, OOM, etc.) -- not "0 errors".
            tail = out.strip()[-1500:]
            failures.append(
                Failure(
                    test_id="tsc",
                    name="typecheck",
                    text=f"tsc exited {cp.returncode} with no parsed TS error lines "
                    f"(likely failed to run at all, not '0 errors'):\n{tail}",
                    status="failure",
                )
            )
    # 2) run the test suite if one exists, emitting JUnit. vitest OR jest --
    # found live 2026-07-22: this always ran jest unconditionally, so any
    # vitest-based project (this repo's OWN frontend among them -- "test":
    # "vitest run" in package.json, no jest anywhere) got an npx prompt to
    # auto-install jest, which _run's --no-install correctly refuses, and
    # that refusal read as a real test failure. Detect which one this
    # project actually uses instead of assuming.
    junit = workdir / "junit.xml"
    total, n_passed = 0, 0
    ran_tests = False
    # Found live 2026-07-22: a package.json with NO test framework configured
    # at all (this repo's own vscode-extension: no jest/vitest dependency,
    # no "test" script -- it's a thin CLI wrapper with its own compile-only
    # scripts) still unconditionally tried to run jest, which npx correctly
    # refused to auto-install, and that refusal read as a real test failure.
    # No test framework configured is "nothing to verify" (vacuous pass,
    # same principle as pytest's "no tests collected"), not "broken".
    if (workdir / "package.json").exists() and _has_test_framework(workdir):
        ran_tests = True
        if _uses_vitest(workdir):
            cp = _run(
                [
                    "npx",
                    "--no-install",
                    "vitest",
                    "run",
                    "--reporter=junit",
                    f"--outputFile={junit}",
                ],
                workdir,
            )
            runner_name = "vitest"
        else:
            cp = _run(["npx", "--no-install", "jest", "--ci", "--reporters=jest-junit"], workdir)
            runner_name = "jest"
        out = cp.stdout + cp.stderr
        raw.append(out)
        if junit.exists():
            junit_failures = _junit_failures(junit)
            failures.extend(junit_failures)
            total, n_passed = _junit_counts(junit)
        elif cp.returncode != 0 and "No tests found" not in out:
            # No JUnit report AND a real nonzero exit that isn't the test
            # runner's own well-known "there simply are no tests here"
            # message -- it failed to run at all (missing binary, config
            # error, crash), not "0 test failures".
            tail = out.strip()[-1500:]
            failures.append(
                Failure(
                    test_id=runner_name,
                    name="test-run",
                    text=f"{runner_name} exited {cp.returncode} with no JUnit report and no "
                    f"'No tests found' message (likely failed to run at all):\n{tail}",
                    status="failure",
                )
            )
    # Nothing to verify is NOT a pass. This branch used to set passed=len(failures)==0, which is
    # True when neither the type check nor the tests ran -- so an empty workspace, or a workspace
    # holding `const a: number = "not a number";` with no tsconfig, returned passed=True with
    # total=0. The explanation went into `raw`, which no caller reads.
    #
    # This is the Python `compileall`-over-zero-files bug relocated into the universal registry,
    # and every other oracle in this file already refuses an empty tree (jvm, swift, dotnet,
    # ruby, php, ...). It matters more here than it looks: verified_search turns a generation
    # exception into the candidate string "__generation_error__: ..." and verifies it like any
    # other, so against a lenient oracle that string is reported solved with a proof line.
    if not (ran_typecheck or ran_tests):
        failures.append(
            Failure(
                test_id="typescript",
                name="verify",
                text="no tsconfig.json and no package.json test script -- nothing was verified, so "
                "this cannot be reported as a pass",
                status="failure",
            )
        )
    passed = len(failures) == 0
    return OracleResult(
        passed=passed,
        failures=failures,
        raw="\n".join(raw),
        oracle="typescript",
        total=total,
        n_passed=n_passed,
    )


# ---------------------------------------------------------------------------
# Concrete oracle: Python (pytest -> JUnit) -- already PB's main surface
# ---------------------------------------------------------------------------
def _repo_python(workdir: Path) -> str:
    """The interpreter that can actually import this project.

    Bare "python" is whatever is on PATH -- for us, Determinex's own venv, which does not
    have the target project's dependencies. Measured 2026-08-01 against a real seaborn
    checkout: pytest exited 4 with "ImportError while loading conftest ... No module named
    'matplotlib'", and because that is not a parsed test failure it was reported as a single
    failure with test_id="pytest", name="collection/run".

    The Adjudicator then classified that as CODE. It is ENVIRONMENT -- the most consequential
    misclassification this oracle can make, because it sends a repair loop off to rewrite
    working source. Prefer the project's own venv when it ships one.
    """
    for c in (
        workdir / ".venv/Scripts/python.exe",
        workdir / ".venv/bin/python",
        workdir / "venv/Scripts/python.exe",
        workdir / "venv/bin/python",
    ):
        if c.exists():
            return str(c)
    return "python"


def _verify_python(workdir: Path) -> OracleResult:
    junit = workdir / "_determinex_junit.xml"
    # SCOPE (DETERMINEX_PYTEST_SCOPE, space-separated pytest node ids). Running a whole
    # suite is the wrong question for repair: a real project carries breakage unrelated to
    # the bug in hand. Measured on a 2022 seaborn checkout under modern pytest -- the full
    # run reports a collection error in tests/test_core.py (a positional @pytest.fixture arg
    # newer pytest rejects), which has nothing to do with the failure being repaired and
    # would make any fix look unsuccessful. A developer says "this test fails", not "my repo
    # is broken"; unset, behaviour is unchanged.
    scope = [s for s in os.environ.get("DETERMINEX_PYTEST_SCOPE", "").split() if s]
    cp = _run(
        [
            _repo_python(workdir),
            "-m",
            "pytest",
            "-q",
            f"--junitxml={junit}",
            "-p",
            "no:cacheprovider",
            *scope,
        ],
        workdir,
    )
    failures = _junit_failures(junit) if junit.exists() else []
    total, n_passed = _junit_counts(junit) if junit.exists() else (0, 0)
    # Found live 2026-07-22: `passed=(len(failures)==0 and returncode==0)` reported
    # a bare, unexplained "not passed" (0 failures, no notes -- nothing to look
    # at) for ANY nonzero pytest exit that wasn't a parsed test failure. The
    # most common real case: exit code 5 = "no tests were collected" for a
    # small package with no local tests (its coverage lives in the root
    # tests/ tree) -- that is NOT the same claim as "this package is broken",
    # and reporting it identically was exactly the un-actionable "fails with
    # no reason" this project's whole philosophy forbids. Ryan: "it should be
    # fixed to where it all compiles and reports one way or the other."
    if cp.returncode == 5 and not failures:
        return OracleResult(
            passed=True,
            failures=[],
            raw=cp.stdout + cp.stderr,
            oracle="python",
            total=0,
            n_passed=0,
        )
    if cp.returncode != 0 and not failures:
        # Some other non-test-failure exit (import/collection error, crash,
        # etc.) -- a REAL problem, but the JUnit file never got a chance to
        # record it as a normal test failure. Surface it explicitly instead
        # of silently reporting "0 failures" alongside passed=False.
        tail = (cp.stdout + cp.stderr).strip()
        tail = tail[-2000:] if len(tail) > 2000 else tail
        failures = [
            Failure(
                test_id="pytest",
                name="collection/run",
                text=f"pytest exited {cp.returncode} with no parsed test "
                f"failures (collection or environment error):\n{tail}",
                status="failure",
            )
        ]
    return OracleResult(
        passed=(len(failures) == 0 and cp.returncode == 0),
        failures=failures,
        raw=cp.stdout + cp.stderr,
        oracle="python",
        total=total,
        n_passed=n_passed,
    )


# ---------------------------------------------------------------------------
# Concrete oracle: Go (go build ./... -> compile errors are ground truth)
# ---------------------------------------------------------------------------
def _verify_go(workdir: Path) -> OracleResult:
    cp = _run(["go", "build", "./..."], workdir)
    out = cp.stdout + cp.stderr
    failures: list[Failure] = []
    for line in out.splitlines():
        # go errors: path:line:col: message
        m = re.match(r"(\S+\.go):(\d+):\d*:?\s*(.+)", line)
        if m:
            failures.append(
                Failure(
                    test_id=f"{m.group(1)}:{m.group(2)}",
                    name=m.group(1),
                    text=line,
                    status="failure",
                )
            )
    passed = cp.returncode == 0
    return OracleResult(
        passed=passed,
        failures=failures
        or ([] if passed else [Failure("go", "build", out[:600], status="failure")]),
        raw=out,
        oracle="go",
    )


# ---------------------------------------------------------------------------
# Concrete oracle: Rust (cargo build --message-format short)
# ---------------------------------------------------------------------------
def _verify_rust(workdir: Path) -> OracleResult:
    cp = _run(["cargo", "build", "--message-format", "short"], workdir)
    out = cp.stdout + cp.stderr
    failures: list[Failure] = []
    for line in out.splitlines():
        # rustc short: path:line:col: error[Exxxx]: message
        m = re.match(r"(\S+\.rs):(\d+):\d*:?\s*(error.*)", line)
        if m:
            failures.append(
                Failure(
                    test_id=f"{m.group(1)}:{m.group(2)}",
                    name=m.group(1),
                    text=line,
                    status="failure",
                )
            )
    passed = cp.returncode == 0
    return OracleResult(
        passed=passed,
        failures=failures
        or ([] if passed else [Failure("rust", "build", out[:600], status="failure")]),
        raw=out,
        oracle="rust",
    )


# ---------------------------------------------------------------------------
# Concrete oracle: JVM (Gradle / Maven / plain javac) -> JUnit XML
# ---------------------------------------------------------------------------
def _verify_jvm(workdir: Path) -> OracleResult:
    if (workdir / "build.gradle").exists() or (workdir / "build.gradle.kts").exists():
        gradle = "./gradlew" if (workdir / "gradlew").exists() else "gradle"
        cp = _run([gradle, "test", "--console=plain", "--no-daemon"], workdir, timeout=1800)
        results = list(workdir.glob("**/build/test-results/**/*.xml"))
    elif (workdir / "pom.xml").exists():
        mvn = "./mvnw" if (workdir / "mvnw").exists() else "mvn"
        cp = _run([mvn, "-q", "test"], workdir, timeout=1800)
        results = list(workdir.glob("**/target/surefire-reports/*.xml"))
    else:
        # plain javac compile = ground truth (no build system shipped)
        srcs = [str(p) for p in workdir.glob("**/*.java")]
        if not srcs:
            return OracleResult(
                passed=False,
                oracle="jvm",
                failures=[Failure("jvm", "build", "no gradle/maven/.java found", status="failure")],
            )
        cp = _run(["javac", "-d", "_determinex_out", *srcs], workdir, timeout=900)
        results = []
    failures: list[Failure] = []
    total, n_passed = 0, 0
    for x in results:
        failures.extend(_junit_failures(x))
        t, p = _junit_counts(x)
        total += t
        n_passed += p
    hard = [f for f in failures if f.status == "failure"]
    passed = cp.returncode == 0 and not hard
    if not passed and not failures:
        failures = [Failure("jvm", "build", (cp.stdout + cp.stderr)[:600], status="failure")]
    return OracleResult(
        passed=passed,
        failures=failures,
        raw=cp.stdout + cp.stderr,
        oracle="jvm",
        total=total,
        n_passed=n_passed,
    )


# ---------------------------------------------------------------------------
# Concrete oracle: Swift (swift test --xunit-output -> JUnit-shaped XML)
# ---------------------------------------------------------------------------
def _verify_swift(workdir: Path) -> OracleResult:
    xml = workdir / "_determinex_swift.xml"
    cp = _run(["swift", "test", "--xunit-output", str(xml)], workdir, timeout=1800)
    failures = _junit_failures(xml) if xml.exists() else []
    total, n_passed = _junit_counts(xml) if xml.exists() else (0, 0)
    hard = [f for f in failures if f.status == "failure"]
    passed = cp.returncode == 0 and not hard
    if not passed and not failures:
        failures = [Failure("swift", "test", (cp.stdout + cp.stderr)[:600], status="failure")]
    return OracleResult(
        passed=passed,
        failures=failures,
        raw=cp.stdout + cp.stderr,
        oracle="swift",
        total=total,
        n_passed=n_passed,
    )


# ---------------------------------------------------------------------------
# Concrete oracle: C# / .NET (dotnet test, JUnit logger -> XML)
# ---------------------------------------------------------------------------
def _verify_dotnet(workdir: Path) -> OracleResult:
    """BUILD first, then test. Measured 2026-08-02: this oracle certified code that does
    not compile.

    It ran only `dotnet test`. On a project that is not a test project, that restores and
    exits 0 without building -- the captured output was literally two lines, "Determining
    projects to restore..." and "Restored ...". No JUnit file, so `total=0`, no failures, and
    `passed = cp.returncode == 0 and not hard` evaluated True. A class whose body was
    `a + oops` came back VERIFIED, under a comment reading "never silent-pass".

    `dotnet build` is the missing half: it fails on the undefined name regardless of whether
    any tests exist, which is the property that makes this an oracle rather than a formality.
    And when neither a build nor a test actually verified anything, this now refuses to
    report a pass -- the same honesty `_verify_typescript` already applies when it finds no
    tsconfig and no test script.
    """
    build = _run(["dotnet", "build", "--nologo"], workdir, timeout=1800)
    if build.returncode != 0:
        return OracleResult(
            passed=False,
            failures=[Failure("dotnet", "build", (build.stdout + build.stderr)[-2000:],
                              status="failure")],
            raw=build.stdout + build.stderr,
            oracle="dotnet",
        )

    xml = workdir / "_determinex_dotnet.xml"
    cp = _run(["dotnet", "test", "--no-build", "--logger", f"junit;LogFilePath={xml}"],
              workdir, timeout=1800)
    failures = _junit_failures(xml) if xml.exists() else []
    total, n_passed = _junit_counts(xml) if xml.exists() else (0, 0)
    hard = [f for f in failures if f.status == "failure"]

    if hard or (cp.returncode != 0 and failures):
        return OracleResult(passed=False, failures=failures, raw=cp.stdout + cp.stderr,
                            oracle="dotnet", total=total, n_passed=n_passed)

    # A clean build with no tests is a REAL result -- the code compiles -- so it passes, but
    # it passes on the strength of the build, which actually ran. What must never happen is
    # the previous behaviour: passing when nothing ran at all.
    if cp.returncode != 0 and not failures and total == 0:
        combined = (cp.stdout + cp.stderr).lower()
        if "no test" not in combined and "not a test project" not in combined:
            return OracleResult(
                passed=False,
                failures=[Failure("dotnet", "test", (cp.stdout + cp.stderr)[-2000:],
                                  status="failure")],
                raw=cp.stdout + cp.stderr, oracle="dotnet", total=total, n_passed=n_passed,
            )
    return OracleResult(
        passed=True,
        failures=failures,
        raw=build.stdout + cp.stdout + cp.stderr,
        oracle="dotnet",
        total=total,
        n_passed=n_passed,
    )


# ---------------------------------------------------------------------------
# Concrete oracle: Ruby (rspec JUnit if a suite ships, else `ruby -c` per file)
# ---------------------------------------------------------------------------
def _verify_ruby(workdir: Path) -> OracleResult:
    if (workdir / "spec").is_dir() or (workdir / ".rspec").exists():
        xml = workdir / "_determinex_rspec.xml"
        cp = _run(
            ["rspec", "--format", "RspecJunitFormatter", "--out", str(xml)], workdir, timeout=1800
        )
        failures = _junit_failures(xml) if xml.exists() else []
        total, n_passed = _junit_counts(xml) if xml.exists() else (0, 0)
        hard = [f for f in failures if f.status == "failure"]
        passed = cp.returncode == 0 and not hard
        if not passed and not failures:
            failures = [Failure("ruby", "test", (cp.stdout + cp.stderr)[:600], status="failure")]
        return OracleResult(
            passed=passed,
            failures=failures,
            raw=cp.stdout + cp.stderr,
            oracle="ruby",
            total=total,
            n_passed=n_passed,
        )
    # No suite shipped: syntax compile of every .rb is the ground truth.
    srcs = list(workdir.glob("**/*.rb"))
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="ruby",
            failures=[Failure("ruby", "build", "no .rb found", status="failure")],
        )
    fails: list[Failure] = []
    raw = ""
    for s in srcs:
        cp = _run(["ruby", "-c", str(s)], workdir, timeout=120)
        raw += cp.stdout + cp.stderr
        if cp.returncode != 0:
            fails.append(Failure("ruby", s.name, (cp.stdout + cp.stderr)[:400], status="failure"))
    return OracleResult(
        passed=not fails,
        failures=fails,
        raw=raw[:4000],
        oracle="ruby",
        total=len(srcs),
        n_passed=len(srcs) - len(fails),
    )


# ---------------------------------------------------------------------------
# Concrete oracle: PHP (phpunit JUnit if configured, else `php -l` per file)
# ---------------------------------------------------------------------------
def _verify_php(workdir: Path) -> OracleResult:
    if (workdir / "phpunit.xml").exists() or (workdir / "phpunit.xml.dist").exists():
        xml = workdir / "_determinex_phpunit.xml"
        cp = _run(["phpunit", "--log-junit", str(xml)], workdir, timeout=1800)
        failures = _junit_failures(xml) if xml.exists() else []
        total, n_passed = _junit_counts(xml) if xml.exists() else (0, 0)
        hard = [f for f in failures if f.status == "failure"]
        passed = cp.returncode == 0 and not hard
        if not passed and not failures:
            failures = [Failure("php", "test", (cp.stdout + cp.stderr)[:600], status="failure")]
        return OracleResult(
            passed=passed,
            failures=failures,
            raw=cp.stdout + cp.stderr,
            oracle="php",
            total=total,
            n_passed=n_passed,
        )
    # No suite shipped: `php -l` lint of every .php is the ground truth.
    srcs = list(workdir.glob("**/*.php"))
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="php",
            failures=[Failure("php", "build", "no .php found", status="failure")],
        )
    fails: list[Failure] = []
    raw = ""
    for s in srcs:
        cp = _run(["php", "-l", str(s)], workdir, timeout=120)
        raw += cp.stdout + cp.stderr
        if cp.returncode != 0:
            fails.append(Failure("php", s.name, (cp.stdout + cp.stderr)[:400], status="failure"))
    return OracleResult(
        passed=not fails,
        failures=fails,
        raw=raw[:4000],
        oracle="php",
        total=len(srcs),
        n_passed=len(srcs) - len(fails),
    )


# ---------------------------------------------------------------------------
# Concrete oracle: C / C++ (cmake / make / autotools build, else compiler
# syntax-check per file -- same "compile is ground truth" shape as go/rust).
# ---------------------------------------------------------------------------
_C_FAMILY_ERROR_RE = re.compile(r"(\S+\.(?:c|cc|cpp|cxx|h|hpp)):(\d+):\d*:?\s*(error.*)")


def _verify_c_family(workdir: Path, cc: str, lang: str, ext: str) -> OracleResult:
    if (workdir / "CMakeLists.txt").exists():
        build_dir = workdir / "_determinex_cbuild"
        build_dir.mkdir(exist_ok=True)
        cfg = _run(["cmake", "-S", str(workdir), "-B", str(build_dir)], workdir, timeout=300)
        cp = (
            cfg
            if cfg.returncode != 0
            else _run(["cmake", "--build", str(build_dir)], workdir, timeout=900)
        )
    elif (workdir / "Makefile").exists() or (workdir / "makefile").exists():
        cp = _run(["make"], workdir, timeout=900)
    elif (workdir / "configure").exists():
        cfg = _run(["./configure"], workdir, timeout=300)
        cp = cfg if cfg.returncode != 0 else _run(["make"], workdir, timeout=900)
    else:
        # No build system shipped: per-file syntax-only compile is ground
        # truth, same posture as _verify_ruby/_verify_php's lint fallback.
        srcs = [str(p) for p in workdir.glob(f"**/{ext}")]
        if not srcs:
            return OracleResult(
                passed=False,
                oracle=lang,
                failures=[Failure(lang, "build", f"no {ext} found", status="failure")],
            )
        cp = _run([cc, "-fsyntax-only", *srcs], workdir, timeout=300)

    out = cp.stdout + cp.stderr
    failures: list[Failure] = []
    for line in out.splitlines():
        m = _C_FAMILY_ERROR_RE.match(line)
        if m:
            failures.append(
                Failure(
                    test_id=f"{m.group(1)}:{m.group(2)}",
                    name=m.group(1),
                    text=line,
                    status="failure",
                )
            )
    passed = cp.returncode == 0
    if not passed and not failures:
        # Compiler/build-system failed to even launch (missing toolchain
        # component, configure error, ...) with no parseable error line --
        # must surface as an explained failure, never a silent 0/0 pass.
        failures = [Failure(lang, "build", out[:600], status="failure")]
    return OracleResult(passed=passed, failures=failures, raw=out, oracle=lang)


def _verify_c(workdir: Path) -> OracleResult:
    return _verify_c_family(workdir, cc="gcc", lang="c", ext="*.c")


def _verify_cpp(workdir: Path) -> OracleResult:
    return _verify_c_family(workdir, cc="g++", lang="cpp", ext="*.cpp")


# ---------------------------------------------------------------------------
# Concrete oracle: COBOL (legacy) -- GnuCOBOL `cobc -c` compile-only per file.
# ---------------------------------------------------------------------------
def _verify_cobol(workdir: Path) -> OracleResult:
    srcs = [p for p in list(workdir.glob("**/*.cob")) + list(workdir.glob("**/*.cbl"))]
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="cobol",
            failures=[Failure("cobol", "build", "no .cob/.cbl found", status="failure")],
        )
    fails: list[Failure] = []
    raw = ""
    for s in srcs:
        cp = _run(["cobc", "-c", str(s)], workdir, timeout=120)
        raw += cp.stdout + cp.stderr
        if cp.returncode != 0:
            fails.append(Failure("cobol", s.name, (cp.stdout + cp.stderr)[:400], status="failure"))
    return OracleResult(
        passed=not fails,
        failures=fails,
        raw=raw[:4000],
        oracle="cobol",
        total=len(srcs),
        n_passed=len(srcs) - len(fails),
    )


# ---------------------------------------------------------------------------
# Concrete oracle: BASIC (legacy) -- FreeBASIC `fbc -c` compile-only per file.
# ---------------------------------------------------------------------------
def _verify_basic(workdir: Path) -> OracleResult:
    srcs = list(workdir.glob("**/*.bas"))
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="basic",
            failures=[Failure("basic", "build", "no .bas found", status="failure")],
        )
    fails: list[Failure] = []
    raw = ""
    for s in srcs:
        cp = _run(["fbc", "-c", str(s)], workdir, timeout=120)
        raw += cp.stdout + cp.stderr
        if cp.returncode != 0:
            fails.append(Failure("basic", s.name, (cp.stdout + cp.stderr)[:400], status="failure"))
    return OracleResult(
        passed=not fails,
        failures=fails,
        raw=raw[:4000],
        oracle="basic",
        total=len(srcs),
        n_passed=len(srcs) - len(fails),
    )


# ---------------------------------------------------------------------------
# Concrete oracle: Tauri (composite) -- the Rust backend (src-tauri/) AND the
# TS/JS frontend verified together as ONE unit. A Tauri app is only actually
# correct when both halves compile; a passing `cargo check` next to a broken
# frontend build (or vice versa) is not a real pass. Reuses the existing
# _verify_rust / _verify_typescript oracles rather than reimplementing either
# half -- this is composition, not a third compiler frontend.
# ---------------------------------------------------------------------------
def _verify_tauri(workdir: Path) -> OracleResult:
    src_tauri = workdir / "src-tauri"
    if not src_tauri.exists():
        if (workdir / "Cargo.toml").exists() and (workdir / "tauri.conf.json").exists():
            # workdir passed in as the src-tauri dir itself
            src_tauri = workdir
            workdir = workdir.parent
        else:
            return OracleResult(
                passed=False,
                oracle="tauri",
                failures=[
                    Failure(
                        "tauri",
                        "layout",
                        "no src-tauri/ (or Cargo.toml+tauri.conf.json) found -- "
                        "not a Tauri project layout",
                        status="failure",
                    )
                ],
            )

    backend = _verify_rust(src_tauri)
    failures = list(backend.failures)
    raw = f"--- backend (cargo, {src_tauri}) ---\n{backend.raw}\n"
    total = backend.total
    n_passed = backend.n_passed
    passed = backend.passed

    if (workdir / "package.json").exists():
        frontend = _verify_typescript(workdir)
        failures.extend(frontend.failures)
        raw += f"--- frontend (tsc/tests, {workdir}) ---\n{frontend.raw}\n"
        total += frontend.total
        n_passed += frontend.n_passed
        passed = passed and frontend.passed

    if not passed and not failures:
        failures = [Failure("tauri", "build", raw[:600], status="failure")]
    return OracleResult(
        passed=passed,
        failures=failures,
        raw=raw[:6000],
        oracle="tauri",
        total=total,
        n_passed=n_passed,
    )


# ---------------------------------------------------------------------------
# Concrete oracle: RISC-V / ET-SoC1 silicon kernels (Docker toolchain + sys-emu)
# Built 2026-07-10 during the AIFoundry CORE-ET hackathon. workdir must be a
# checkout of aifoundry-org/hf-hackathon (or a git worktree of it) with the
# candidate kernel already written into ported_models/yolo/src/. Requires
# Docker Desktop + a one-time toolchain/SDK build under DETERMINEX_ET_WORK
# (default <repo-parent>/et-soc1-work) -- see docs/architecture (or ask this session)
# for the exact bootstrap; probe below only checks Docker itself is present,
# matching the "available() = a toolchain COULD run" contract other oracles use.
#
# Two-tier verification, same shape as every other domain oracle here:
#   tier 1 (this function, seconds): compiles the candidate with the REAL
#     riscv64-unknown-elf-gcc via the shared toolchain container -- catches
#     syntax/type/link errors exactly like tsc/cargo/go build do elsewhere in
#     this file. This is the fast, always-run gate.
#   tier 2 (opt-in, 30-90+ min per test image on this hardware -- NOT run by
#     default, pass env DETERMINEX_ET_SYSEMU_VERIFY=1 to enable): runs one
#     sys-emu image through the actual launcher and checks it produces a
#     non-empty dump without crashing. This is a REAL accuracy signal but too
#     slow to gate every candidate; use it selectively on tier-1 survivors.
# ---------------------------------------------------------------------------
def _et_soc1_work_root() -> Path:
    import os

    return Path(
        os.environ.get(
            "DETERMINEX_ET_WORK",
            str(Path(__file__).resolve().parent.parent.parent / "et-soc1-work"),
        )
    )


def _docker(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        # Found live 2026-07-23: _wait_for_container_ready's readiness-probe
        # loop calls this with a short per-attempt timeout (10s) specifically
        # so a hung probe doesn't block the whole poll -- but subprocess.run
        # RAISES on timeout rather than returning a nonzero-exit
        # CompletedProcess, so an unhandled TimeoutExpired crashed the entire
        # oracle call instead of just failing that one poll attempt (every
        # _docker() caller's existing `cp.returncode != 0` handling expects a
        # CompletedProcess, never an exception). 124 matches the conventional
        # `timeout` shell command's exit code for "the command timed out".
        stdout = (
            (e.stdout or b"").decode("utf-8", "replace")
            if isinstance(e.stdout, bytes)
            else (e.stdout or "")
        )
        stderr = (
            (e.stderr or b"").decode("utf-8", "replace")
            if isinstance(e.stderr, bytes)
            else (e.stderr or "")
        )
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=124,
            stdout=stdout,
            stderr=stderr + f"\n[determinex] docker command timed out after {timeout}s: {cmd}",
        )


def _verify_riscv_et_soc1(workdir: Path) -> OracleResult:
    et_work = _et_soc1_work_root()
    if (
        not (et_work / "et" / "bin" / "riscv64-unknown-elf-gcc").exists()
        and not (et_work / "build").exists()
    ):
        raise OracleUnavailable(
            "riscv-et-soc1 oracle needs a one-time toolchain+SDK build under "
            f"{et_work} (Docker-based, ~30-60 min, fully self-serve, no board "
            "credentials needed -- see docs/security/OPENENV_SUBMISSION.md-adjacent "
            "notes or corpus/programbench/build_knowledge.json "
            "'local_verification_boundary' for the exact bootstrap steps)."
        )

    container = "determinex-et-oracle"
    # Reuse a running container ONLY if it's already mounted at THIS exact
    # workdir -- a container reused across a DIFFERENT workdir silently tests
    # stale code from whichever worktree originally created it (found
    # 2026-07-10: a leaked container from an earlier apt-get timeout stayed
    # mounted to one worktree for 25+ minutes while later verify_fn calls for
    # OTHER worktrees reused it under started_here=False, none of them ever
    # cleaning it up). Mount identity, not "does a container exist", is the
    # correctness condition for reuse.
    mount_check = _docker(
        ["docker", "inspect", container, "--format", "{{range .Mounts}}{{.Source}}|{{end}}"]
    )
    workdir_str = str(workdir)
    mount_matches = mount_check.returncode == 0 and workdir_str in mount_check.stdout
    started_here = False
    if not mount_matches:
        _docker(["docker", "rm", "-f", container])
        run = _docker(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "-v",
                f"{workdir}:/repo",
                "-v",
                f"{et_work}:/etwork",
                "-w",
                "/repo",
                "ubuntu:24.04",
                "sleep",
                "1800",
            ],
            timeout=60,
        )
        if run.returncode != 0:
            return OracleResult(
                passed=False,
                oracle="riscv-et-soc1",
                failures=[
                    Failure("riscv-et-soc1", "docker-start", run.stderr[:2000], status="failure")
                ],
            )
        started_here = True

    try:
        if started_here:
            # Inside try/finally now: an apt-get timeout no longer leaks an
            # un-cleaned, stale-mounted container for subsequent calls to
            # silently inherit.
            _docker(
                [
                    "docker",
                    "exec",
                    container,
                    "bash",
                    "-c",
                    "apt-get update -qq && apt-get install -y -qq python3 libmpc-dev "
                    "libmpfr-dev libgmp-dev 2>&1 | tail -5",
                ],
                timeout=180,
            )
        env_args = [
            "-e",
            "WORK_ROOT=/etwork",
            "-e",
            "ET_INSTALL=/etwork/et",
            "-e",
            "BUILD_ROOT=/etwork/build",
            "-e",
            "BENCHMARK_ARTIFACT_ROOT=/repo/local-artifacts/model-port-benchmarks",
        ]
        cp = _docker(
            [
                "docker",
                "exec",
                *env_args,
                container,
                "bash",
                "-c",
                "bash .github/ci/scripts/prepare_benchmark_inputs.sh yolo 2>&1 && "
                "bash .github/ci/scripts/build_leaderboard_elf.sh yolo 2>&1",
            ],
            timeout=300,
        )
        raw = cp.stdout + cp.stderr
        elf_check = _docker(
            [
                "docker",
                "exec",
                container,
                "bash",
                "-c",
                "test -s /repo/local-artifacts/model-port-benchmarks/"
                "yolo-bench/yolo_m30.elf && echo ELF_OK",
            ],
            timeout=30,
        )
        passed = cp.returncode == 0 and "ELF_OK" in elf_check.stdout
        failures: list[Failure] = []
        if not passed:
            failures.append(Failure("riscv-et-soc1", "compile", raw[-4000:], status="failure"))
        return OracleResult(
            passed=passed,
            failures=failures,
            raw=raw[-4000:],
            oracle="riscv-et-soc1",
            total=1,
            n_passed=1 if passed else 0,
        )
    finally:
        if started_here:
            _docker(["docker", "rm", "-f", container])


# ---------------------------------------------------------------------------
# Concrete oracle: DuckDB (embedded -- no server, no Docker). Runs every
# *.sql file in workdir through the real duckdb CLI against an in-memory
# database. Installed live 2026-07-22 via `winget install --id DuckDB.cli
# --location T:/determinex-tools/duckdb` (kept off C: per Ryan: "put what
# you need on T to save for now on space").
# ---------------------------------------------------------------------------
_SQL_ERROR_RE = re.compile(r"^Error:.*", re.IGNORECASE)


def _verify_duckdb(workdir: Path) -> OracleResult:
    srcs = list(workdir.glob("**/*.sql"))
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="duckdb",
            failures=[Failure("duckdb", "build", "no .sql found", status="failure")],
        )
    fails: list[Failure] = []
    raw = ""
    for s in srcs:
        # ".bail on" is load-bearing: without it the CLI (sqlite3-style)
        # keeps going after a failed statement and exits 0 even though a
        # query inside the script errored -- would be a silent pass.
        # DuckDB's dot-command tokenizer treats backslash as an escape char
        # (sqlite3-style), so a raw Windows path in ".read C:\Users\..."
        # silently eats the backslashes -- found live 2026-07-22. Forward
        # slashes are accepted by Windows paths and aren't special to the
        # tokenizer.
        cp = _run(
            ["duckdb", ":memory:", "-c", ".bail on", "-c", f".read {s.as_posix()}"],
            workdir,
            timeout=120,
        )
        out = cp.stdout + cp.stderr
        raw += out
        errors = [line for line in out.splitlines() if _SQL_ERROR_RE.match(line)]
        if cp.returncode != 0 or errors:
            text = "\n".join(errors) or out[:400]
            fails.append(Failure("duckdb", s.name, text[:400], status="failure"))
    return OracleResult(
        passed=not fails,
        failures=fails,
        raw=raw[:4000],
        oracle="duckdb",
        total=len(srcs),
        n_passed=len(srcs) - len(fails),
    )


# ---------------------------------------------------------------------------
# Concrete oracle: MariaDB (Docker-backed, ephemeral). A native Windows
# MSI service install was tried live 2026-07-22 (`winget install --id
# MariaDB.Server`) and failed with a generic 1603, rolling back cleanly with
# no files left on disk -- exactly the fragile, elevation-hungry, host-
# service-registering path an EPHEMERAL verification sandbox shouldn't
# depend on. Every *.sql file in workdir is run against a real, disposable
# mariadb server instead -- same "spin up -> verify -> tear down" Docker
# shape already proven by the riscv-et-soc1 oracle above.
# ---------------------------------------------------------------------------
def _wait_for_container_ready(container: str, probe_cmd: list[str], timeout: int = 150) -> bool:
    # 90s was measured live 2026-07-23 to be uncomfortably close to the real
    # boundary -- mariadb:11's first-time container init (mariadb-install-db
    # + the temp-server bootstrap/restart cycle) consistently took 94-99s on
    # this box, one run exceeded 90s outright. 150s gives real margin without
    # meaningfully slowing down the common case (the loop returns as soon as
    # the probe succeeds, it doesn't wait out the full budget).
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        cp = _docker(["docker", "exec", container, *probe_cmd], timeout=10)
        if cp.returncode == 0:
            return True
        time.sleep(2)
    return False


# Found live 2026-07-23: the official mariadb image's entrypoint runs a
# TEMPORARY bootstrap mysqld first (binds the port, answers "ready for
# connections" and responds to a ping/ident probe) purely to apply
# MARIADB_ROOT_PASSWORD, then stops it and starts the REAL server ~10-15s
# later -- confirmed via `docker logs`: two separate "ready for
# connections" lines with a "Temporary server stopped" in between. A probe
# landing in that temporary-server window reports ready, but the actual
# root password grant isn't durably in place yet, so the first real exec
# right after can get a genuine `ERROR 1045 Access denied` with the
# CORRECT password -- not a bad credential, a startup race. Retrying the
# exact same exec a few times (not a separate readiness probe, which
# raced identically) is what actually closes the window.
_TRANSIENT_AUTH_SIGNATURES = ("Access denied for user", "Can't connect to")


def _run_with_transient_retry(
    cmd: list[str], timeout: int, attempts: int = 5, delay: float = 3.0
) -> subprocess.CompletedProcess:
    import time

    cp = _docker(cmd, timeout=timeout)
    for _ in range(attempts - 1):
        out = cp.stdout + cp.stderr
        if cp.returncode == 0 or not any(sig in out for sig in _TRANSIENT_AUTH_SIGNATURES):
            break
        time.sleep(delay)
        cp = _docker(cmd, timeout=timeout)
    return cp


def _verify_mariadb(workdir: Path) -> OracleResult:
    srcs = list(workdir.glob("**/*.sql"))
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="mariadb",
            failures=[Failure("mariadb", "build", "no .sql found", status="failure")],
        )
    container = "determinex-mariadb-oracle"
    _docker(["docker", "rm", "-f", container])
    run = _docker(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "-e",
            "MARIADB_ROOT_PASSWORD=determinex",
            "-v",
            f"{workdir}:/sql:ro",
            "mariadb:11",
        ],
        timeout=120,
    )
    if run.returncode != 0:
        return OracleResult(
            passed=False,
            oracle="mariadb",
            failures=[Failure("mariadb", "docker-start", run.stderr[:2000], status="failure")],
        )
    try:
        if not _wait_for_container_ready(
            container, ["mariadb-admin", "ping", "-uroot", "-pdeterminex"]
        ):
            return OracleResult(
                passed=False,
                oracle="mariadb",
                failures=[
                    Failure(
                        "mariadb",
                        "startup",
                        "mariadb server never became ready within 90s",
                        status="failure",
                    )
                ],
            )
        fails: list[Failure] = []
        raw = ""
        for s in srcs:
            rel = f"/sql/{s.relative_to(workdir).as_posix()}"
            cp = _run_with_transient_retry(
                ["docker", "exec", container, "sh", "-c", f"mariadb -uroot -pdeterminex < {rel}"],
                timeout=60,
            )
            out = cp.stdout + cp.stderr
            raw += out
            if cp.returncode != 0:
                fails.append(Failure("mariadb", s.name, out[:400], status="failure"))
        return OracleResult(
            passed=not fails,
            failures=fails,
            raw=raw[:4000],
            oracle="mariadb",
            total=len(srcs),
            n_passed=len(srcs) - len(fails),
        )
    finally:
        _docker(["docker", "rm", "-f", container])


# ---------------------------------------------------------------------------
# Concrete oracle: MongoDB (Docker-backed, ephemeral) -- same shape as
# MariaDB above. Every *.js file in workdir is run as a mongosh script
# against a real, disposable mongod instance.
# ---------------------------------------------------------------------------
def _verify_mongodb(workdir: Path) -> OracleResult:
    srcs = list(workdir.glob("**/*.js"))
    if not srcs:
        return OracleResult(
            passed=False,
            oracle="mongodb",
            failures=[Failure("mongodb", "build", "no .js found", status="failure")],
        )
    container = "determinex-mongodb-oracle"
    _docker(["docker", "rm", "-f", container])
    run = _docker(
        ["docker", "run", "-d", "--name", container, "-v", f"{workdir}:/scripts:ro", "mongo:7"],
        timeout=120,
    )
    if run.returncode != 0:
        return OracleResult(
            passed=False,
            oracle="mongodb",
            failures=[Failure("mongodb", "docker-start", run.stderr[:2000], status="failure")],
        )
    try:
        if not _wait_for_container_ready(
            container, ["mongosh", "--quiet", "--eval", "db.runCommand({ping:1})"]
        ):
            return OracleResult(
                passed=False,
                oracle="mongodb",
                failures=[
                    Failure(
                        "mongodb",
                        "startup",
                        "mongod never became ready within 90s",
                        status="failure",
                    )
                ],
            )
        fails: list[Failure] = []
        raw = ""
        for s in srcs:
            rel = f"/scripts/{s.relative_to(workdir).as_posix()}"
            cp = _docker(["docker", "exec", container, "mongosh", "--quiet", rel], timeout=60)
            out = cp.stdout + cp.stderr
            raw += out
            if cp.returncode != 0:
                fails.append(Failure("mongodb", s.name, out[:400], status="failure"))
        return OracleResult(
            passed=not fails,
            failures=fails,
            raw=raw[:4000],
            oracle="mongodb",
            total=len(srcs),
            n_passed=len(srcs) - len(fails),
        )
    finally:
        _docker(["docker", "rm", "-f", container])


# ---------------------------------------------------------------------------
# Stubs for surfaces still on the roadmap. Each declares the EXACT command it
# will run; raising OracleUnavailable (never silently passing) until wired.
# ---------------------------------------------------------------------------
def _stub(name: str, cmd: str) -> Callable[[Path], OracleResult]:
    def _fn(workdir: Path) -> OracleResult:
        raise OracleUnavailable(f"oracle '{name}' not yet wired; planned command: {cmd}")

    return _fn


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_ORACLES: dict[str, Oracle] = {}


def register(o: Oracle) -> None:
    for lang in o.languages:
        _ORACLES[lang.lower()] = o


def get_oracle(language: str) -> Oracle:
    key = language.lower()
    if key not in _ORACLES:
        raise KeyError(f"no oracle registered for language '{language}'. Known: {sorted(_ORACLES)}")
    return _ORACLES[key]


def available_oracles() -> dict[str, bool]:
    return {lang: o.available() for lang, o in sorted(_ORACLES.items())}


register(
    Oracle(
        "typescript",
        ("typescript", "ts", "javascript", "js", "tsx", "node"),
        ("npx",),
        "npm i -D typescript jest jest-junit",
        _verify_typescript,
    )
)
register(
    Oracle("python", ("python", "py"), ("python",), "python 3.11+ with pytest", _verify_python)
)
register(
    Oracle(
        "jvm",
        ("kotlin", "kt", "java", "jvm"),
        ("gradle", "mvn", "javac"),
        "install Gradle/Maven (JVM); gradle/maven emit JUnit XML, or plain javac "
        "compile is used as ground truth when no build file ships",
        _verify_jvm,
    )
)
register(Oracle("rust", ("rust", "rs"), ("cargo",), "rustup toolchain", _verify_rust))
register(Oracle("go", ("go", "golang"), ("go",), "go toolchain", _verify_go))
register(
    Oracle(
        "swift",
        ("swift",),
        ("swift",),
        "Swift toolchain (swift test --xunit-output)",
        _verify_swift,
    )
)
register(
    Oracle(
        "csharp",
        ("csharp", "cs", "dotnet"),
        ("dotnet",),
        ".NET SDK + JUnitXml.TestLogger (dotnet add package JunitXml.TestLogger)",
        _verify_dotnet,
    )
)
register(
    Oracle(
        "ruby",
        ("ruby", "rb"),
        ("ruby",),
        "Ruby (rspec + rspec_junit_formatter for tests; else `ruby -c` syntax)",
        _verify_ruby,
    )
)
register(
    Oracle(
        "php",
        ("php",),
        ("php",),
        "PHP (phpunit --log-junit for tests; else `php -l` lint)",
        _verify_php,
    )
)
register(
    Oracle(
        "c",
        ("c",),
        ("gcc", "clang", "cc"),
        "a C compiler (gcc/clang); cmake/make/autotools build used if shipped, "
        "else `gcc -fsyntax-only` per file",
        _verify_c,
    )
)
register(
    Oracle(
        "cpp",
        ("cpp", "c++", "cxx"),
        ("g++", "clang++"),
        "a C++ compiler (g++/clang++); cmake/make/autotools build used if shipped, "
        "else `g++ -fsyntax-only` per file",
        _verify_cpp,
    )
)
register(
    Oracle(
        "cobol",
        ("cobol", "cob", "cbl"),
        ("cobc",),
        "GnuCOBOL (`cobc -c` compile-only per .cob/.cbl file)",
        _verify_cobol,
    )
)
register(
    Oracle(
        "basic",
        ("basic", "bas", "freebasic"),
        ("fbc",),
        "FreeBASIC (`fbc -c` compile-only per .bas file)",
        _verify_basic,
    )
)
register(
    Oracle(
        "tauri",
        ("tauri",),
        ("cargo", "npx"),
        "Rust toolchain (cargo) + Node/npm -- composite: verifies src-tauri/ "
        "(cargo) AND the TS/JS frontend (tsc/tests) together as one Tauri app",
        _verify_tauri,
    )
)
register(
    Oracle(
        "duckdb",
        ("duckdb",),
        ("duckdb",),
        "DuckDB CLI (embedded, no server) -- runs *.sql files with .bail on",
        _verify_duckdb,
    )
)
register(
    Oracle(
        "mariadb",
        ("mariadb", "mysql"),
        ("docker",),
        "Docker Desktop -- spins an ephemeral mariadb:11 container, "
        "runs *.sql files against it, tears down",
        _verify_mariadb,
    )
)
register(
    Oracle(
        "mongodb",
        ("mongodb", "mongo"),
        ("docker",),
        "Docker Desktop -- spins an ephemeral mongo:7 container, "
        "runs *.js (mongosh) scripts against it, tears down",
        _verify_mongodb,
    )
)
register(
    Oracle(
        "riscv-et-soc1",
        ("riscv-et-soc1", "et-soc1", "erbium"),
        ("docker",),
        "Docker Desktop + one-time toolchain/SDK build under "
        "DETERMINEX_ET_WORK (default <repo-parent>/et-soc1-work); see "
        "corpus/programbench/build_knowledge.json 'local_verification_boundary'",
        _verify_riscv_et_soc1,
    )
)


# ===========================================================================
# Ground-Truth Synthesizer -- "make the tests for the ones it doesn't have"
# ===========================================================================
@dataclass
class SynthesizedOracle:
    """An executable specification derived for a task that shipped no tests.
    The synthesizer captures the CURRENT observable behavior (characterization)
    and/or derives invariants from a spec, so the solve loop has ground truth to
    iterate against even in greenfield / unbenchmarked domains."""

    kind: str  # characterization | property | golden | contract
    language: str
    artifact_path: Path  # where the generated test/spec was written
    rationale: str


_SYNTH_TEMPLATES = {
    # characterization: pin the program's current output so refactors are safe
    "characterization": (
        "Run the target on a representative input corpus, capture stdout/stderr/rc "
        "as golden files, and emit a test that re-runs and diffs. Locks behavior "
        "before any change -- the classic 'tests for legacy code with no tests'."
    ),
    # property: derive invariants from the spec (idempotence, round-trip, ordering)
    "property": (
        "From the spec, derive invariants (round-trip encode/decode == identity, "
        "sort is idempotent, output schema validates) and emit property tests that "
        "fuzz inputs against them. Ground truth without a reference binary."
    ),
    # golden: when a reference implementation exists, diff against it
    "golden": (
        "Run a trusted reference implementation alongside the candidate over a "
        "shared input corpus; any divergence is a failure. The PB pattern, applied "
        "to a domain PB never benchmarked."
    ),
    # contract: types/schemas/API contracts as the oracle
    "contract": (
        "Treat the type checker / schema validator / OpenAPI contract as the oracle. "
        "No example tests needed -- the contract IS ground truth (tsc, mypy, jsonschema)."
    ),
}


def synthesize_oracle(
    workdir: Path, language: str, spec: str = "", kind: str = "characterization"
) -> SynthesizedOracle:
    """Generate ground truth where none was shipped.

    This is the bridge from "PB has a test suite for this" to "the IDE can fix
    ANYTHING": for an unbenchmarked task the system first manufactures a
    deterministic oracle, then runs the identical closed loop against it.

    The returned SynthesizedOracle points at a generated artifact (a test file or
    golden corpus). Generation of the artifact body is delegated to the builder
    model under the relevant `get_oracle(language)` so the SAME compiler/test
    surface validates the synthesized tests themselves (tests must compile/run).
    """
    if kind not in _SYNTH_TEMPLATES:
        raise ValueError(f"unknown synthesis kind '{kind}'. Choose: {sorted(_SYNTH_TEMPLATES)}")
    out_dir = workdir / "_determinex_synth"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / f"oracle_{kind}.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": kind,
                "language": language,
                "strategy": _SYNTH_TEMPLATES[kind],
                "spec_excerpt": spec[:2000],
                "status": "manifest_only",
                "note": (
                    "Builder model fills the test/golden body next, then the "
                    "language oracle runs it to confirm the synthesized oracle is "
                    "itself executable before it gates any fix."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return SynthesizedOracle(
        kind=kind, language=language, artifact_path=manifest, rationale=_SYNTH_TEMPLATES[kind]
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Universal Ground-Truth Oracle")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show registered oracles and toolchain availability")
    v = sub.add_parser("verify", help="run an oracle against a workdir")
    v.add_argument("language")
    v.add_argument("workdir", type=Path)
    s = sub.add_parser("synthesize", help="manufacture ground truth where none exists")
    s.add_argument("language")
    s.add_argument("workdir", type=Path)
    s.add_argument("--kind", default="characterization", choices=sorted(_SYNTH_TEMPLATES))
    args = ap.parse_args()

    if args.cmd == "status":
        print("Registered oracles (language -> toolchain present?):")
        for lang, ok in available_oracles().items():
            o = _ORACLES[lang]
            mark = "OK " if ok else "-- "
            print(f"  {mark} {lang:12} via {o.probe[0]:8} | {'' if ok else o.install_hint}")
        return 0
    if args.cmd == "verify":
        o = get_oracle(args.language)
        res = o.verify(args.workdir)
        print(f"oracle={res.oracle} passed={res.passed} failures={len(res.failures)}")
        for f in res.failures[:20]:
            print(f"  [{f.status}] {f.name}: {f.text[:80]}")
        return 0 if res.passed else 1
    if args.cmd == "synthesize":
        so = synthesize_oracle(args.workdir, args.language, kind=args.kind)
        print(f"synthesized {so.kind} oracle -> {so.artifact_path}")
        print(f"  rationale: {so.rationale}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
