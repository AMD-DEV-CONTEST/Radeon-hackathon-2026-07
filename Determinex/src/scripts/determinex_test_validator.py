#!/usr/bin/env python3
"""
determinex_test_validator.py -- The Test Validator (Adjudicator component D)
=========================================================================
"...and the actual test be correct, not slop."

The Compiler Oracle answers "does the code pass the test?" This module answers
the harder question the user demanded: "is the TEST itself correct?" -- without
ever letting an LLM judge it. Determinex's founding rule holds: the only verdicts
allowed are DETERMINISTIC PROOFS. A test is called slop ONLY when one of four
checks produces evidence; otherwise the test is presumed correct and the CODE is
wrong (back to the solve loop). No vibes, no "this looks off."

The four deterministic checks
-----------------------------
1. CONTRADICTION   -- two tests share an identical observable context
                      (same nodeid/argv/env) but demand different ground truth.
                      A single binary cannot satisfy both => at least one test is
                      wrong. PROOF: the two conflicting test ids + their goldens.
2. ENVIRONMENT-BAKED -- the golden encodes an environment the eval cannot
                      reproduce (a TTY-rendered screen, host locale, AVX2 output).
                      The assertion tests the test-generation machine, not the
                      program. PROOF: the environment signature in the golden.
3. TAUTOLOGY       -- the test asserts nothing falsifiable (`assert True`,
                      `assert x or not x`, no assertion at all, `assert rc in
                      <every value>`). It can never fail => it certifies nothing.
                      PROOF: the trivial assertion text.
4. REFERENCE-FAIL  -- the real upstream binary, run against the test, FAILS it.
                      If the reference implementation can't pass it, the test does
                      not describe correct behavior. PROOF: reference rc/stdout vs
                      golden. (This is the manual "build the upstream binary"
                      technique, mechanized. Requires a reference binary.)

Anything not matched by 1-4 returns CORRECT (the code is the thing to fix).

    from determinex_test_validator import validate_eval_report
    verdicts = validate_eval_report(Path("eval.json"), test_sources={...})
    slop = [v for v in verdicts if v.verdict == TestVerdict.SLOP]

CLI
---
    python scripts/determinex_test_validator.py check <eval_report.json> [--tests-dir DIR]
    python scripts/determinex_test_validator.py reference \
        --binary ./ov --cmd "--plain -n test.txt" --golden-rc 0 --golden-out-file g.txt
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from determinex_adjudicator import (  # noqa: E402
    Failure,
    _base_nodeid,
    _extract_golden,
    _failures_from_eval_report,
)


class TestVerdict(str, Enum):
    __test__ = False  # not a pytest test class despite the name
    CORRECT = "CORRECT"  # no slop signature -> fix the code, not the test
    SLOP = "SLOP"  # proven wrong test -> do not chase it
    UNKNOWN = "UNKNOWN"  # needs a reference binary to decide


@dataclass
class Judgement:
    test_id: str
    verdict: TestVerdict
    check: str  # which of the 4 checks fired
    proof: str  # the deterministic evidence
    recommended_action: str = ""
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Check 2 -- environment-baked golden signatures (the test tests the machine)
# ---------------------------------------------------------------------------
_ENV_BAKED = [
    (
        "tty-rendered",
        re.compile(
            r"line numbers|caption|--force-screen|screen render|columns?=\d+|"
            r"len\(result\.stdout\)\s*[<>]\s*\d",
            re.I,
        ),
    ),
    (
        "locale-baked",
        re.compile(r"invalid_?utf-?8|LC_ALL|locale-specific|0x[0-9a-f]{2}.*decode", re.I),
    ),
    (
        "simd-baked",
        re.compile(r"AVX2|SIMD|symbols_output|character (art|map)|render.*symbol", re.I),
    ),
    ("host-path-baked", re.compile(r"/home/\w+/|/Users/\w+/|C:\\\\Users", re.I)),
    ("timestamp-baked", re.compile(r"\b20\d\d-\d\d-\d\d\b|\b\d{10}\b.*epoch", re.I)),
]

# ---------------------------------------------------------------------------
# Check 3 -- tautology / triviality signatures in the test SOURCE
# ---------------------------------------------------------------------------
_TAUTOLOGY = [
    ("assert-true", re.compile(r"assert\s+True\b")),
    ("assert-constant", re.compile(r"assert\s+\d+\s*(==|!=)\s*\d+")),
    ("assert-or-not", re.compile(r"assert\s+(\w+)\s+or\s+not\s+\1\b")),
    (
        "rc-in-everything",
        re.compile(r"returncode\s+in\s+[\[(][^)\]]{0,4}0[^)\]]*1[^)\]]*2[^)\]]*[\])]"),
    ),
    ("always-in", re.compile(r"assert\s+(''|b''|\"\")\s+in\s+")),
]


def _detect_env_baked(text: str) -> tuple[str, str] | None:
    for name, pat in _ENV_BAKED:
        m = pat.search(text)
        if m:
            return name, m.group(0)[:80]
    return None


def _detect_tautology(test_src: str) -> tuple[str, str] | None:
    for name, pat in _TAUTOLOGY:
        m = pat.search(test_src)
        if m:
            return name, m.group(0)[:80]
    return None


def _find_contradictions(failures: list[Failure]) -> dict[str, str]:
    """Return {test_id -> proof} for tests that conflict with a peer under an
    identical discriminating context (same base nodeid, different golden)."""
    by_base: dict[str, list[Failure]] = {}
    for f in failures:
        by_base.setdefault(_base_nodeid(f.test_id), []).append(f)
    out: dict[str, str] = {}
    for base, group in by_base.items():
        goldens = {}
        for f in group:
            exp, _ = _extract_golden(f.text or "")
            if exp:
                goldens.setdefault(exp, []).append(f.test_id)
        if len(goldens) > 1:
            # same base nodeid, >1 distinct golden -> contradiction
            proof = " | ".join(f"{ids[0]} expects {g[:40]!r}" for g, ids in goldens.items())
            for ids in goldens.values():
                for tid in ids:
                    out[tid] = f"identical context '{base}' demands conflicting goldens: {proof}"
    return out


# ---------------------------------------------------------------------------
# Check 4 -- reference cross-check (deterministic; needs a reference binary)
# ---------------------------------------------------------------------------
@dataclass
class ReferenceCheck:
    binary: Path
    argv: list[str]
    golden_rc: int | None = None
    golden_stdout: str | None = None
    timeout: int = 20


def reference_cross_check(rc: ReferenceCheck) -> Judgement:
    """Run the REAL upstream binary against a test's invocation. If the reference
    fails the golden, the TEST is slop (it does not describe correct behavior)."""
    if not rc.binary.exists():
        return Judgement(
            "reference",
            TestVerdict.UNKNOWN,
            "reference-fail",
            f"reference binary {rc.binary} not present",
        )
    try:
        cp = subprocess.run(
            [str(rc.binary), *rc.argv],
            capture_output=True,
            text=True,
            timeout=rc.timeout,
            errors="replace",
        )
    except Exception as e:
        return Judgement(
            "reference", TestVerdict.UNKNOWN, "reference-fail", f"reference run error: {e}"
        )
    mismatches = []
    if rc.golden_rc is not None and cp.returncode != rc.golden_rc:
        mismatches.append(f"rc {cp.returncode} != golden {rc.golden_rc}")
    if rc.golden_stdout is not None and cp.stdout != rc.golden_stdout:
        mismatches.append(f"stdout {cp.stdout[:40]!r} != golden {rc.golden_stdout[:40]!r}")
    if mismatches:
        return Judgement(
            "reference",
            TestVerdict.SLOP,
            "reference-fail",
            "REFERENCE BINARY ALSO FAILS THIS TEST -> the test is wrong: " + "; ".join(mismatches),
            recommended_action="Do not chase this test. It does not describe the "
            "reference implementation's actual behavior. Flag the "
            "fixture as provably broken (ceiling with proof).",
        )
    return Judgement(
        "reference",
        TestVerdict.CORRECT,
        "reference-fail",
        "reference binary passes -> test is correct; fix the code.",
    )


# ---------------------------------------------------------------------------
# Check 4 (AUTOMATED) -- build a clean reference from canonical source, recover each
# failing test's invocation from its traceback, run it, and call SLOP only when a
# CORRECT build also fails. This mechanizes the manual "build the upstream binary and
# run it" proof Determinex mandates -- deterministic, no LLM. (It is what caught lua: the
# real lua prints no banner for non-tty stdin, so a banner assertion is slop.)
# ---------------------------------------------------------------------------
_ARGV_RE = re.compile(r"(?:args=|Command\s*'?)(\[[^\]]{0,500}?\])")
_IN_RE = re.compile(r"assert\s+b?(['\"])(.+?)\1\s+in\s+[\w.]*\b(stdout|stderr)")
_RC_RE = re.compile(r"assert\s+[\w.()]*returncode\s*==\s*(-?\d+)")
_BIN_SUFFIX = ("executable", "_ref", "/lua", "/ov")


def extract_invocation(text: str) -> dict | None:
    """Recover (argv, stdin, expectation) from a pytest failure traceback (best-effort)."""
    m = _ARGV_RE.search(text or "")
    if not m:
        return None
    try:
        argv = [str(x) for x in ast.literal_eval(m.group(1))]
    except Exception:
        return None
    if not argv:
        return None
    stdin = "" if re.search(r"(?:stdin|input)\s*=\s*(['\"])\1", text) else None
    expect = None
    im = _IN_RE.search(text)
    if im:
        expect = ("in", im.group(2), im.group(3))
    else:
        rm = _RC_RE.search(text)
        if rm:
            expect = ("rc", int(rm.group(1)), None)
    return {"argv": argv, "stdin": stdin, "expect": expect}


# PB wrapper script + TUI/test helpers shipped alongside the tool -- NEVER the tool itself. Picking
# one of these is the #1 false-slop risk (it caught us on nnn: tui2cli != nnn -> bogus "30 slop").
_HELPER_NAMES = {"executable", "tui2cli", "tui2", "pty", "ptyhelper", "conftest", "setup", "run"}


def _find_executable(root: Path, prefer: str = "") -> Path | None:
    if not root.exists():
        return None
    bad = (".d", ".rlib", ".o", ".so", ".a", ".sh", ".py", ".c", ".h", ".toml", ".lock", ".md")
    cands = []
    for p in root.rglob("*"):
        sp = str(p).replace("\\", "/")
        if (
            p.is_file()
            and os.access(p, os.X_OK)
            and p.suffix not in bad
            and p.name not in _HELPER_NAMES
            and not p.name.startswith(".")
            and "helper" not in p.name
            and "plugin" not in p.name
            and "/deps/" not in sp
            and "/build/" not in sp
            and "/.fingerprint/" not in sp
        ):
            cands.append(p)
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if prefer:  # the real tool binary is named after the tool
        exact = [c for c in cands if c.name == prefer]
        if exact:
            return exact[0]
        partial = [c for c in cands if prefer in c.name or c.name in prefer]
        if partial:
            return partial[0]
        return None  # a tool-named binary was expected but none found -> don't trust a stray exe
    return cands[0]


def build_reference(tool_dir: Path, timeout: int = 900) -> Path | None:
    """Build the tool from its canonical source -> a clean reference binary (or None when we
    cannot build it here -> defer, never a false slop). Rust/Go/C(flat)/Make covered."""
    d = Path(tool_dir).resolve()  # absolute: gcc -o / cargo target paths must not depend on cwd
    name = d.name.split("__")[-1].split(".")[
        0
    ]  # tool binary is named after the tool (jarun__nnn -> nnn)
    try:
        if (d / "Cargo.toml").exists():
            r = subprocess.run(
                ["cargo", "build", "--release", "--offline"],
                cwd=str(d),
                capture_output=True,
                timeout=timeout,
            )
            if r.returncode != 0:
                subprocess.run(
                    ["cargo", "build", "--release"],
                    cwd=str(d),
                    capture_output=True,
                    timeout=timeout,
                )
            return _find_executable(d / "target" / "release", prefer=name)
        if (d / "go.mod").exists():
            out = d / "_determinex_ref"
            subprocess.run(
                ["go", "build", "-o", str(out), "."],
                cwd=str(d),
                capture_output=True,
                timeout=timeout,
            )
            return out if out.exists() else _find_executable(d, prefer=name)
        # Makefile = the tool's OWN build (general C/C++). Try it BEFORE the lua-specific flat-C path.
        if (d / "Makefile").exists() or (d / "makefile").exists():
            subprocess.run(["make"], cwd=str(d), capture_output=True, timeout=timeout)
            ref = _find_executable(d, prefer=name)
            if ref:
                return ref
        cfiles = [p.name for p in d.glob("*.c")]  # flat single-dir C (lua-like), no Makefile
        if cfiles:
            out = d / "_determinex_ref"
            srcs = [c for c in cfiles if c not in ("onelua.c", "luac.c")]
            for flags, libs in (
                (["-DLUA_USE_LINUX"], ["-lm", "-lreadline", "-ldl"]),
                (["-DLUA_USE_POSIX"], ["-lm", "-ldl"]),
                ([], ["-lm"]),
            ):
                r = subprocess.run(
                    ["gcc", "-O2", *flags, "-o", str(out), *srcs, *libs],
                    cwd=str(d),
                    capture_output=True,
                    timeout=timeout,
                )
                if r.returncode == 0 and out.exists():
                    return out
    except Exception:
        return None
    return None


def _smoke_ok(binary: Path) -> bool:
    """A reference we TRUST must answer a standard help/version probe with SOME output. A binary that
    prints nothing for ALL of them is broken or a stub/helper -> never trust its 'failures' as slop.
    This is the guard that unmasks false positives (the nnn tui2cli / .nnn-plugin-helper case)."""
    for probe in (["--help"], ["--version"], ["-h"], ["-V"], ["--usage"]):
        try:
            cp = subprocess.run(
                [str(binary), *probe], input="", capture_output=True, text=True, timeout=8
            )
        except Exception:
            continue
        if cp.stdout.strip() or cp.stderr.strip():
            return True
    return False


def auto_reference_check(
    tool_dir: Path, eval_report: Path, reuse_binary: Path | None = None
) -> list[Judgement]:
    """Build a clean reference (or reuse one) + run each failing test's recovered invocation against
    it. SLOP when a correct binary ALSO fails the assertion. The reference must pass a functional
    smoke test first -- a broken/wrong binary must NEVER manufacture false slop (soundness)."""
    ref = reuse_binary or build_reference(tool_dir)
    out: list[Judgement] = []
    if ref is None or not Path(ref).exists() or not _smoke_ok(ref):
        return out
    seen: set[str] = set()
    for f in _failures_from_eval_report(eval_report):
        if f.status == "skipped":
            continue
        base = _base_nodeid(f.test_id)
        if base in seen:
            continue
        seen.add(base)
        inv = extract_invocation(f.text or "")
        if not inv or not inv.get("expect"):
            continue
        argv = [str(ref) if a.endswith(_BIN_SUFFIX) else a for a in inv["argv"]]
        # Skip invocations that reference files gone since the eval (test temp dirs like /tmp/tmpXXX):
        # re-running feeds the binary a MISSING path, not the real input -> a meaningless verdict. This
        # is what inflated masscan/tig 'CORRECT' (masscan returns rc=0 for a missing --readscan file).
        # Only run when every path argument still exists.
        if any("/" in a and a != str(ref) and not os.path.exists(a) for a in argv[1:]):
            continue
        try:
            cp = subprocess.run(
                argv,
                input=inv["stdin"],
                capture_output=True,
                text=True,
                timeout=20,
                errors="replace",
            )
        except Exception:
            continue
        kind = inv["expect"][0]
        ref_fails, detail = False, ""
        if kind == "in":
            needle, stream_name = inv["expect"][1], inv["expect"][2]
            stream = cp.stdout if stream_name == "stdout" else cp.stderr
            ref_fails = needle not in stream
            detail = "reference %s=%r lacks %r" % (stream_name, stream[:50], needle)
        elif kind == "rc":
            ref_fails = cp.returncode != inv["expect"][1]
            detail = "reference rc=%d != golden %d" % (cp.returncode, inv["expect"][1])
        if ref_fails:
            out.append(
                Judgement(
                    base,
                    TestVerdict.SLOP,
                    "reference-fail",
                    "CLEAN REFERENCE BUILD ALSO FAILS -> " + detail,
                    recommended_action="Proven slop/ceiling: a correct binary fails "
                    "this test too. Do not chase the code; flag the fixture as broken.",
                    extra={"reference": str(ref)},
                )
            )
        else:
            out.append(
                Judgement(
                    base,
                    TestVerdict.CORRECT,
                    "reference-pass",
                    "clean reference PASSES -> the code/build is what to fix: " + detail,
                    extra={"reference": str(ref)},
                )
            )
    return out


# ---------------------------------------------------------------------------
# Top-level: validate every non-passing test in an eval report
# ---------------------------------------------------------------------------
def validate_eval_report(
    eval_report: Path, test_sources: dict[str, str] | None = None
) -> list[Judgement]:
    failures = _failures_from_eval_report(eval_report)
    contradictions = _find_contradictions(failures)
    test_sources = test_sources or {}
    out: list[Judgement] = []
    for f in failures:
        if f.status == "skipped":
            continue  # skips are the Adjudicator's domain, not slop
        # Check 1 -- contradiction
        if f.test_id in contradictions:
            out.append(
                Judgement(
                    f.test_id,
                    TestVerdict.SLOP,
                    "contradiction",
                    contradictions[f.test_id],
                    recommended_action="Genuine ceiling WITH PROOF. Report "
                    "the conflicting fixtures; do not chase either.",
                )
            )
            continue
        # Check 2 -- environment-baked golden
        eb = _detect_env_baked(f.text or "")
        if eb:
            out.append(
                Judgement(
                    f.test_id,
                    TestVerdict.SLOP,
                    "environment-baked",
                    f"golden encodes {eb[0]}: {eb[1]}",
                    recommended_action="Either match the environment "
                    "(see Adjudicator MATCH) or, if unreproducible, flag "
                    "the fixture as env-baked with proof.",
                )
            )
            continue
        # Check 3 -- tautology (needs test source)
        src = _lookup_source(f, test_sources)
        if src:
            ta = _detect_tautology(src)
            if ta:
                out.append(
                    Judgement(
                        f.test_id,
                        TestVerdict.SLOP,
                        "tautology",
                        f"non-falsifiable assertion ({ta[0]}): {ta[1]}",
                        recommended_action="Test certifies nothing; ignore for scoring purposes.",
                    )
                )
                continue
        # Check 4 deferred to explicit reference run -> default CORRECT
        out.append(
            Judgement(
                f.test_id,
                TestVerdict.CORRECT,
                "no-slop-signature",
                "no contradiction/env-baking/tautology found",
                recommended_action="Fix the code (run reference-cross-check to be certain).",
            )
        )
    return out


def _lookup_source(f: Failure, sources: dict[str, str]) -> str:
    # try to map a nodeid like 'tests.test_x.test_name' to a source blob
    parts = _base_nodeid(f.test_id).split(".")
    for key, src in sources.items():
        if any(p and p in key for p in parts[:-1]):
            return src
    return ""


def _summarize(eval_report: Path, judgements: list[Judgement]) -> int:
    from collections import Counter

    seen: dict[str, Judgement] = {}
    for j in judgements:
        seen.setdefault(_base_nodeid(j.test_id), j)
    uniq = list(seen.values())
    c = Counter(j.verdict.value for j in uniq)
    print(f"=== TEST VALIDATION: {eval_report.name} ===")
    print(f"unique non-passing tests judged: {len(uniq)}  -> {dict(c)}")
    slop = [j for j in uniq if j.verdict == TestVerdict.SLOP]
    if slop:
        by_check = Counter(j.check for j in slop)
        print(f"\n  PROVEN SLOP ({len(slop)} unique):")
        for chk, n in by_check.most_common():
            ex = next(j for j in slop if j.check == chk)
            print(f"    {n:3}x  [{chk}]  e.g. {ex.test_id[:55]}")
            print(f"          proof: {ex.proof[:90]}")
    correct = c.get("CORRECT", 0)
    if correct:
        print(f"\n  {correct} tests are CORRECT -> the CODE is what needs fixing.")
    if not slop:
        print("\n  No slop proven. Every failing test is legitimate -- fix the code.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex Test Validator (is the test slop?)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate the tests behind an eval report")
    c.add_argument("eval_report", type=Path)
    c.add_argument(
        "--tests-dir",
        type=Path,
        default=None,
        help="dir of test_*.py sources for tautology detection",
    )
    r = sub.add_parser("reference", help="reference cross-check one invocation")
    r.add_argument("--binary", type=Path, required=True)
    r.add_argument("--cmd", required=True, help="space-separated argv")
    r.add_argument("--golden-rc", type=int, default=None)
    r.add_argument("--golden-out-file", type=Path, default=None)
    ra = sub.add_parser(
        "reference-auto", help="build a clean reference + auto-check ALL failures for slop"
    )
    ra.add_argument("tool_dir", type=Path, help="dir with the tool's canonical source + build")
    ra.add_argument("eval_report", type=Path)
    args = ap.parse_args()

    if args.cmd == "check":
        sources = {}
        if args.tests_dir and args.tests_dir.is_dir():
            for p in args.tests_dir.rglob("test_*.py"):
                sources[p.stem] = p.read_text(encoding="utf-8", errors="replace")
        js = validate_eval_report(args.eval_report, sources)
        return _summarize(args.eval_report, js)

    if args.cmd == "reference":
        golden_out = (
            args.golden_out_file.read_text(encoding="utf-8", errors="replace")
            if args.golden_out_file
            else None
        )
        j = reference_cross_check(
            ReferenceCheck(
                binary=args.binary,
                argv=args.cmd.split(),
                golden_rc=args.golden_rc,
                golden_stdout=golden_out,
            )
        )
        print(f"[{j.verdict.value}] {j.check}: {j.proof}")
        if j.recommended_action:
            print(f"  -> {j.recommended_action}")
        return 0 if j.verdict != TestVerdict.SLOP else 2

    if args.cmd == "reference-auto":
        from collections import Counter

        js = auto_reference_check(args.tool_dir, args.eval_report)
        c = Counter(j.verdict.value for j in js)
        print(f"=== AUTO REFERENCE-FAIL: {args.tool_dir.name} ===")
        print(f"checked {len(js)} failing tests against a clean reference build -> {dict(c)}")
        for j in js:
            print(f"  [{j.verdict.value}] {j.test_id[:55]} -- {j.proof[:85]}")
        slop = sum(1 for j in js if j.verdict == TestVerdict.SLOP)
        return 2 if slop else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
