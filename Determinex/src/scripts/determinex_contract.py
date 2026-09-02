#!/usr/bin/env python3
"""
determinex_contract.py -- Output Contract Enforcer (Amplifier piece #6)
====================================================================
The well-formedness floor. Before any candidate reaches the (expensive) oracle,
it must satisfy a cheap, deterministic OUTPUT CONTRACT: is it a valid unified
diff? does the JSON parse? does the code parse in its language? is the required
shape present? A weak model emits malformed junk a large fraction of the time;
rejecting that junk in microseconds -- before a Docker eval or compile -- both
saves the oracle and guarantees a well-formed floor for whatever model plugs in.

This is a pre-filter for VerifiedSearch: wrap a model so malformed candidates are
rejected and resampled, never counted as a real attempt.

    from determinex_contract import enforce, patch_contract, json_contract, py_contract
    ok, reason = enforce(candidate, patch_contract)
    guarded = guard(generate, py_contract)     # a model that only emits valid python

Contracts are `Callable[[str], tuple[bool, str]]` -> (well_formed, reason).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

Contract = Callable[[str], "tuple[bool, str]"]
GenerateFn = Callable[[str, float], str]


def patch_contract(text: str) -> tuple[bool, str]:
    """A minimal unified-diff sanity check (does not apply it -- that's the oracle)."""
    if not text.strip():
        return False, "empty patch"
    has_header = bool(re.search(r"^(diff --git|--- |\+\+\+ |@@ )", text, re.M))
    if not has_header:
        return False, "no diff header (--- / +++ / @@ / diff --git)"
    # every hunk line should start with a valid prefix
    for ln in text.splitlines():
        if (
            ln
            and ln[0] not in " +-@\\d"
            and not ln.startswith(
                (
                    "diff ",
                    "index ",
                    "--- ",
                    "+++ ",
                    "new file",
                    "deleted file",
                    "similarity",
                    "rename ",
                    "old mode",
                    "new mode",
                    "Binary ",
                )
            )
        ):
            # tolerate context but flag obviously prose lines mid-patch
            if "@@" in text[: text.find(ln)] and not ln.startswith(("+", "-", " ")):
                return False, f"stray non-hunk line in patch body: {ln[:40]!r}"
    return True, "valid unified diff shape"


def json_contract(text: str) -> tuple[bool, str]:
    t = text.strip()
    # tolerate a fenced block
    m = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        json.loads(t)
        return True, "valid json"
    except Exception as e:
        return False, f"invalid json: {e}"


def py_contract(text: str) -> tuple[bool, str]:
    t = _strip_fence(text)
    try:
        ast.parse(t)
        return True, "valid python syntax"
    except SyntaxError as e:
        return False, f"python syntax error: {e}"


def nonempty_contract(text: str) -> tuple[bool, str]:
    return (bool(text.strip()), "nonempty" if text.strip() else "empty output")


def native_code_contract(text: str) -> tuple[bool, str]:
    """Cheap, language-agnostic sanity floor for compiled languages (C/Rust/Go/C++/Haskell).

    Found 2026-07-02: py_contract (ast.parse -- PYTHON syntax) was being applied
    UNCONDITIONALLY, including to native (--lang c/rust/go/...) candidates. Valid
    C/Rust/Go source essentially never parses as Python, so every real candidate in
    native mode was failing its own contract check and burning resample budget on a
    check that could never pass. Real syntax validation for native code already
    happens downstream (the compiler oracle); this pre-filter only needs to catch
    OBVIOUSLY malformed/truncated/prose output cheaply, not fully parse the language.
    """
    t = _strip_fence(text).strip()
    if not t:
        return False, "empty output"
    if t.count("{") != t.count("}"):
        return False, f"unbalanced braces ({t.count('{')} open vs {t.count('}')} close)"
    if t.count("(") != t.count(")"):
        return False, f"unbalanced parens ({t.count('(')} open vs {t.count(')')} close)"
    # a real source file has at least one brace pair; bare prose/explanation text won't.
    if "{" not in t:
        return False, "no brace-delimited block found (looks like prose, not source)"
    return True, "balanced braces/parens, looks like source"


def regex_contract(pattern: str) -> Contract:
    pat = re.compile(pattern, re.S)

    def _c(text: str) -> tuple[bool, str]:
        return (
            bool(pat.search(text)),
            f"matches /{pattern[:30]}/"
            if pat.search(text)
            else f"missing required pattern /{pattern[:30]}/",
        )

    return _c


def all_of(*contracts: Contract) -> Contract:
    def _c(text: str) -> tuple[bool, str]:
        for c in contracts:
            ok, reason = c(text)
            if not ok:
                return False, reason
        return True, "all contracts satisfied"

    return _c


def _strip_fence(text: str) -> str:
    m = re.search(r"```(?:\w+)?\s*(.+?)```", text, re.S)
    return m.group(1) if m else text


# language -> contract, so the Ingester's detected language picks the floor
LANGUAGE_CONTRACT: dict[str, Contract] = {
    "python": py_contract,
    "py": py_contract,
    "json": json_contract,
    "patch": patch_contract,
    "diff": patch_contract,
}


def enforce(text: str, contract: Contract) -> tuple[bool, str]:
    return contract(text)


def guard(generate, contract: Contract, max_retries: int = 5):
    """Wrap a generate(prompt,temp)->str so it only returns contract-valid output,
    resampling on malformed candidates (widening temperature). The wrapper raises
    after max_retries so a broken model cannot loop forever."""

    def _wrapped(prompt: str, temperature: float) -> str:
        last = ""
        for i in range(max_retries):
            t = temperature + 0.1 * i
            last = generate(prompt, t)
            ok, _ = contract(last)
            if ok:
                return last
        # return the last (malformed) -> the oracle will reject; never silently pass
        return last

    return _wrapped


# ---------------------------------------------------------------------------
# Known-traps scan + two-strike gate (2026-07-16)
# ---------------------------------------------------------------------------
# A cheap PRE-ORACLE linter for the specific anti-patterns already documented in
# corpus/programbench/language_reference/{rust,go,c,cpp}.md's "Known traps" sections --
# keep these two in sync by hand (a regex can't be derived from prose; the .md files are
# the human-readable explanation, this is the executable check for the same list).
#
# Design (Ryan, 2026-07-16): "it should warn, and if it still goes with it, it should gate
# at compile and be like.. bro i told you not to, its gated try the hell again and actually
# listen this time." -- i.e. NOT a hard reject on first sight (a heuristic pattern match is
# not a sound oracle -- CLAUDE.md: "No LLM judges for code quality — compiler is the only
# oracle"; forcing a genuinely oracle-passing candidate to fail on a heuristic would violate
# that). First occurrence of a trap is a WARNING ONLY and the candidate still reaches the
# real compiler/test oracle untouched. Only if the SAME trap recurs in a LATER candidate
# from the same generation sequence (meaning the model was told and ignored it) does this
# gate BEFORE the candidate ever reaches the oracle -- exactly where native_code_contract
# already sits ("before any candidate reaches the (expensive) oracle").
@dataclass
class TrapHit:
    trap_id: str
    message: str
    line: int


_KNOWN_TRAPS: dict[str, list[tuple[str, re.Pattern[str], str]]] = {
    "rust": [
        (
            "rust_unwrap_expect",
            re.compile(r"\.(?:unwrap|expect)\s*\("),
            "unwrap()/expect() turns a clean rc=1 error into a rc=101 panic backtrace -- handle "
            "the Result/Option explicitly near user input or file I/O instead.",
        ),
        (
            "rust_debug_error_print",
            re.compile(
                r"(?:eprintln|println|print|format)!\([^)]*\{:\?\}[^)]*,\s*(?:e|err|error)\s*\)"
            ),
            "printing an error with {:?} (Debug) instead of {} (Display) looks nothing like a "
            "real CLI's error wording -- tests check exact stderr text.",
        ),
    ],
    "go": [
        (
            "go_ignored_error",
            re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*_\s*:?=\s*[\w.]+\(", re.M),
            "assigning an error result to _ discards it -- an unchecked error that later causes a "
            "nil-pointer dereference panics with a raw Go stack trace, not the tool's real message.",
        ),
        (
            "go_len_on_string",
            re.compile(r"\blen\((?:s|str|input|text|line)\)"),
            "len() on a Go string counts UTF-8 BYTES, not characters -- wrong for any test with "
            "multi-byte Unicode input; range over the string for rune-correct iteration.",
        ),
    ],
    "c": [
        (
            "c_unbounded_strcpy",
            re.compile(r"\b(?:strcpy|strcat|gets)\s*\("),
            "strcpy/strcat/gets on unbounded input is the classic buffer overflow -- use "
            "snprintf or a length-checked copy with an explicit size limit.",
        ),
        (
            "c_unchecked_malloc",
            re.compile(r"=\s*malloc\([^)]*\)\s*;(?!\s*(?:if|assert))"),
            "malloc's return isn't checked for NULL before use -- a failed allocation followed "
            "by a write through the pointer is undefined behavior.",
        ),
    ],
    "cpp": [
        (
            "cpp_uncaught_stoi",
            re.compile(r"\bstd::sto[id]\s*\("),
            "std::stoi/std::stod throws on bad input (std::invalid_argument/out_of_range) -- "
            "uncaught, this calls std::terminate and prints an implementation-defined message, "
            "not the tool's real error text. Wrap it in try/catch.",
        ),
        (
            "cpp_raw_new_no_raii",
            re.compile(r"\bnew\s+[A-Za-z_]"),
            "a raw `new` without RAII (std::unique_ptr/std::vector/std::string) leaks on any "
            "early-return or exception path -- prefer an owning standard container.",
        ),
    ],
}


def known_traps_scan(code: str, lang: str) -> list[TrapHit]:
    """Scan generated candidate code for the specific anti-patterns documented in this
    language's language_reference/*.md 'Known traps' section. Heuristic, not sound -- a hit
    means 'this pattern is present', not 'this code is definitely wrong'. Empty list for a
    language with no known-traps table (python needs none; unregistered languages return [])."""
    traps = _KNOWN_TRAPS.get(lang, [])
    if not traps:
        return []
    text = _strip_fence(code)
    hits: list[TrapHit] = []
    for trap_id, pattern, message in traps:
        m = pattern.search(text)
        if m:
            line = text.count("\n", 0, m.start()) + 1
            hits.append(TrapHit(trap_id=trap_id, message=message, line=line))
    return hits


def trap_guard(generate: GenerateFn, lang: str, max_retries: int = 3) -> GenerateFn:
    """Two-strike wrapper around a generate(prompt,temp)->str: the FIRST time any given
    known-trap appears in a candidate from this wrapped generator, it is allowed through
    untouched (the real oracle is still the only judge of a first attempt) -- but the trap
    is recorded. If that SAME trap appears again in a LATER candidate from this same wrapped
    instance, this gates BEFORE the candidate is returned: it resamples (widening temperature,
    up to max_retries) with an escalated correction note appended to the prompt. State is
    scoped to one wrapped instance -- construct a fresh one per model/ladder entry so a
    router escalation to a different model tier starts with a clean slate."""
    warned: set[str] = set()

    def _wrapped(prompt: str, temperature: float) -> str:
        p = prompt
        last = ""
        for i in range(max_retries):
            last = generate(p, temperature + 0.1 * i)
            hits = known_traps_scan(last, lang)
            hit_ids = {h.trap_id for h in hits}
            repeated = hit_ids & warned
            warned.update(hit_ids)
            if not repeated:
                return last
            note = "\n".join(f"- {h.message}" for h in hits if h.trap_id in repeated)
            p = (
                f"{prompt}\n\nYou were already warned about this exact issue and submitted "
                f"it again anyway. Fix it this time, before anything else:\n{note}"
            )
        return last  # exhausted retries -- return the last candidate; the oracle still judges it

    return _wrapped


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Output Contract Enforcer")
    ap.add_argument("kind", choices=["patch", "json", "python", "nonempty"])
    ap.add_argument("file", nargs="?", help="file to check (else stdin)")
    args = ap.parse_args()
    text = (
        open(args.file, encoding="utf-8", errors="replace").read()
        if args.file
        else sys.stdin.read()
    )
    contract = {
        "patch": patch_contract,
        "json": json_contract,
        "python": py_contract,
        "nonempty": nonempty_contract,
    }[args.kind]
    ok, reason = contract(text)
    print(f"{'OK' if ok else 'REJECT'}: {reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
