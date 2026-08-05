"""scripts/determinex_pb_taxonomy.py — single source of truth for ProgramBench failure families.

Previously the same 19-family taxonomy was duplicated in three places:
  - scripts/failure_classifier.py  (FAMILY_PATTERNS)
  - scripts/run_ledger.py          (_FAMILY_RX, used in backfill)
  - scripts/mass_run_v2_aggregate.py (FAMILY_CLASSIFIERS)

Three copies of the same regex meant any drift between them would silently
make the cockpit disagree with itself: monitor showing one top family while
the aggregator reports a different one. This module is now the only place
the patterns live; every consumer imports from here.

Tier-1 patterns appear in 130+ of the 157 residual ProgramBench repos and
collectively account for ~40% of the test surface across the residual.
Tier-2 patterns appear in 60-110 repos. Infra patterns are pipeline failures,
not behavioral.

Adding a new family: append to FAMILY_PATTERNS with a unique key + regex.
The order of the list matters — earlier patterns win on conflict, so put the
most specific patterns first within their tier.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The taxonomy
# ---------------------------------------------------------------------------

# (family_name, regex_source). Compiled with re.I.
FAMILY_PATTERNS: list[tuple[str, str]] = [
    # ── Tier 1: universal CLI patterns (>=130 of 157 residual repos) ───────
    ("rc_2_missing_arg", r"missing argument|required argument"),
    ("rc_2_unknown_option", r"unknown option|unrecognized argument|unexpected argument"),
    ("help_text_mismatch", r"--help|test_help|usage:.*expected"),
    ("version_format", r"--version|test_version"),
    ("stdin_handling", r"stdin|test_stdin"),
    ("empty_input", r"empty|test_empty"),
    ("invalid_value", r"invalid|test_invalid"),
    ("file_not_found", r"no such file|cannot access|file_not_found"),
    ("multiple_inputs", r"multiple|test_multiple"),
    ("no_color_negation", r"--no-|test_no_"),
    # ── Tier 2: domain-conditional (60-110 repos) ──────────────────────────
    ("output_flag", r"--output|test_output"),
    ("config_file", r"--config|test_config"),
    ("json_io", r"--json|test_json"),
    ("format_flag", r"--format|test_format"),
    ("list_subcommand", r"test_list|--list"),
    ("filter_flag", r"--filter|test_filter|--include|--exclude"),
    ("check_mode", r"--check|test_check"),
    ("export_flag", r"test_export|--export"),
    # ── Infrastructure (pipeline failures, not behavioral) ─────────────────
    ("hash_executable_fail", r"hash_executable_failed"),
]


# Pre-compiled, in deterministic order. Public name kept short because callers
# iterate it directly.
COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pat, re.I)) for name, pat in FAMILY_PATTERNS
]

# Convenience set of known family keys + the catch-all
FAMILY_NAMES: list[str] = [name for name, _ in FAMILY_PATTERNS] + ["other"]


# ---------------------------------------------------------------------------
# Classification API
# ---------------------------------------------------------------------------


def classify_one(test_name: str, message: str) -> str:
    """Map one failing test (name + message) to its family.

    Returns 'other' if nothing matches. The blob length cap (400 chars of
    message) matches what the eval JSONs typically include in `extra.message`
    and keeps classification time bounded on long pytest tracebacks.
    """
    blob = f"{test_name}  {message[:400]}"
    for name, rx in COMPILED:
        if rx.search(blob):
            return name
    return "other"


def classify_test_results(test_results: Iterable[dict]) -> Counter:
    """Family histogram for one eval JSON's `test_results` array.

    Skips passed / skipped — only failures count. Returns a Counter so callers
    can merge histograms across runs with `Counter + Counter`.
    """
    c: Counter = Counter()
    for r in test_results:
        if r.get("status") != "failure":
            continue
        name = r.get("name", "") or ""
        msg = str((r.get("extra") or {}).get("message", ""))
        c[classify_one(name, msg)] += 1
    return c


# ---------------------------------------------------------------------------
# Tier metadata — used by the patch advisor when ranking recommendations
# ---------------------------------------------------------------------------

TIER_1: frozenset[str] = frozenset(
    {
        "rc_2_missing_arg",
        "rc_2_unknown_option",
        "help_text_mismatch",
        "version_format",
        "stdin_handling",
        "empty_input",
        "invalid_value",
        "file_not_found",
        "multiple_inputs",
        "no_color_negation",
    }
)

TIER_2: frozenset[str] = frozenset(
    {
        "output_flag",
        "config_file",
        "json_io",
        "format_flag",
        "list_subcommand",
        "filter_flag",
        "check_mode",
        "export_flag",
    }
)

INFRA: frozenset[str] = frozenset(
    {
        "hash_executable_fail",
    }
)


def tier_of(family: str) -> str:
    """Return 'tier-1' | 'tier-2' | 'infra' | 'other' for a family key."""
    if family in TIER_1:
        return "tier-1"
    if family in TIER_2:
        return "tier-2"
    if family in INFRA:
        return "infra"
    return "other"


# ===========================================================================
# SECOND AXIS: root-MECHANISM classification (CAUSE, not feature). Merged here
# 2026-06-16 so there is ONE taxonomy module, not two. FAMILY_PATTERNS above = the
# CLI-feature axis (symptom); the below = the root-mechanism axis (cause: crlf, clock,
# locale, prefix-dupe, build-fail, root-perm, ...). Callers pick the axis they need.
# ===========================================================================
# ---- the mechanism taxonomy (cause, not appearance) -------------------------------------
# Each: (name, technique it routes to, p-hint). p-hint: MECH=deterministic fix exists,
# SAMPLE=needs more samples/decompose (p>0), SOLVE=genuine content, CEILING=likely a wall.
MECHANISMS = {
    # --- environment brittleness (the hermetic-layer kills these wholesale) ---
    "crlf-lineending": ("crlf-normalize", "MECH"),
    "clock-timing": ("hermetic-clock", "MECH"),
    "locale-encoding": ("hermetic-locale", "MECH"),
    "path-assumption": ("hermetic-path-canon", "MECH"),
    "hash-seed-random": ("hermetic-seed", "MECH"),
    "ordering-nondet": ("canonical-sort-compare", "MECH"),
    "network-dep": ("hermetic-no-network", "MECH/CEILING"),
    # --- harness / contract ---
    "exit-code-mismatch": ("exit-code-route", "MECH"),
    "tty-stdin": ("pty-allocate", "MECH"),
    "signal-handling": ("signal-route", "MECH"),
    "resource-limit": ("rlimit-route", "MECH"),
    "root-perm": ("drop-privileges", "MECH"),
    "prefix-dupe": ("bidir-mirror", "MECH"),
    "build-fail": ("build-fail-routing", "MECH"),
    "ansi-color": ("ansi-normalize", "MECH"),
    "whitespace": ("whitespace-normalize", "MECH"),
    "version-build": ("version-pin", "MECH"),
    "numeric-drift": ("numeric-route", "SAMPLE"),
    # --- genuine ---
    "upstream-skip": ("ceiling-cert", "CEILING"),
    "semantic": ("solve-loop", "SOLVE"),
    "unknown": ("triage", "SAMPLE"),
}

# signature regexes against the failure text (traceback + expected/actual) and test name
_SIG = [
    ("crlf-lineending", re.compile(r"\\r\\n|carriage return|set: Illegal option|\r\n", re.I)),
    (
        "build-fail",
        re.compile(
            r"compile_failed|build failed|cannot find -l|undefined reference|"
            r"no such file.*\.(h|go|rs)|error\[E\d|cmake error|make.*\bError\b",
            re.I,
        ),
    ),
    (
        "network-dep",
        re.compile(
            r"connection refused|could not resolve|network is unreachable|"
            r"timed out.*(http|connect)|getaddrinfo|ECONNREFUSED|no route to host",
            re.I,
        ),
    ),
    (
        "root-perm",
        re.compile(
            r"permission denied|EACCES|unreadable|as_non_root|operation not permitted|"
            r"read[- ]?only file system",
            re.I,
        ),
    ),
    (
        "clock-timing",
        re.compile(
            r"\b20\d\d-\d\d-\d\d\b|\b\d\d:\d\d:\d\d\b|elapsed|duration|"
            r"timestamp|date\.today|ago\b|seconds?\b",
            re.I,
        ),
    ),
    (
        "locale-encoding",
        re.compile(
            r"UnicodeDecodeError|UnicodeEncodeError|codec can't|locale|"
            r"LC_ALL|ascii.*ordinal|utf-?8|latin-1|encoding",
            re.I,
        ),
    ),
    (
        "hash-seed-random",
        re.compile(r"PYTHONHASHSEED|set iteration|dict order|randomized|nondeterministic", re.I),
    ),
    (
        "ordering-nondet",
        re.compile(r"same.*different order|out of order|sorted\(|unordered|reorder", re.I),
    ),
    (
        "path-assumption",
        re.compile(r"/tmp/|pytest-\d|/home/|/root/|cwd|getcwd|tmpdir|tempfile|absolute path", re.I),
    ),
    (
        "ansi-color",
        re.compile(r"\\x1b\[|\\033\[|\\e\[|ansi|color code|\bSGR\b|escape sequence", re.I),
    ),
    (
        "signal-handling",
        re.compile(r"SIGINT|SIGTERM|SIGPIPE|signal \d|killed by signal|broken pipe", re.I),
    ),
    (
        "resource-limit",
        re.compile(
            r"too many open files|EMFILE|ENOMEM|out of memory|rlimit|ulimit|"
            r"resource temporarily unavailable",
            re.I,
        ),
    ),
    (
        "tty-stdin",
        re.compile(r"\btty\b|isatty|termios|pty|/dev/tty|not a terminal|stdin|raw mode", re.I),
    ),
    (
        "version-build",
        re.compile(r"version|revision|commit [0-9a-f]{7}|build date|--version", re.I),
    ),
    (
        "exit-code-mismatch",
        re.compile(r"return ?code|exit ?code|rc[ =]\d|assert \d+ ==|status \d", re.I),
    ),
    ("whitespace", re.compile(r"trailing whitespace|rstrip|expandtabs|\\t|padding|indent", re.I)),
    ("numeric-drift", re.compile(r"\b\d+ != \d+\b|count|size in bytes|\d+ bytes|off by", re.I)),
]
_NAME_SIG = [
    ("root-perm", re.compile(r"unreadable|permission|as_non_root|atomic.*swap|read_only", re.I)),
    ("tty-stdin", re.compile(r"_tty|tmux|pty|pexpect|curses|interactive|render", re.I)),
    ("network-dep", re.compile(r"http|url|server|socket|download|fetch", re.I)),
    ("version-build", re.compile(r"version|revision|build", re.I)),
]


@dataclass
class Fingerprint:
    mechanism: str
    technique: str
    p_hint: str
    evidence: str


def fingerprint_test(rec: dict, passed_idents: set[str] | None = None) -> Fingerprint:
    """Classify ONE test record by root mechanism."""
    name = rec.get("name", "")
    status = rec.get("status", "")
    text = rec.get("text") or (json.dumps(rec.get("extra")) if rec.get("extra") else "") or ""
    blob = f"{name}\n{text}"

    # not_run that is a prefix-dupe of a passing test = bidir mechanism
    if status == "not_run" and passed_idents is not None:
        ident = name.split("::")[-1] if "::" in name else name.split(".")[-1]
        if ident in passed_idents:
            return Fingerprint(
                "prefix-dupe",
                *MECHANISMS["prefix-dupe"][:2],
                evidence="not_run ident matches a passing test",
            )
    # skipped -> read the skip reason / name
    if status == "skipped":
        for mech, rx in _SIG:
            if rx.search(blob):
                return Fingerprint(mech, *MECHANISMS[mech][:2], evidence=f"skip:{mech}")
        for mech, rx in _NAME_SIG:
            if rx.search(name):
                return Fingerprint(mech, *MECHANISMS[mech][:2], evidence=f"skip-name:{mech}")
        return Fingerprint(
            "upstream-skip", *MECHANISMS["upstream-skip"][:2], evidence="skip, no mech signature"
        )
    # failed/error/not_run -> match against text then name
    for mech, rx in _SIG:
        if rx.search(blob):
            return Fingerprint(mech, *MECHANISMS[mech][:2], evidence=f"text:{mech}")
    for mech, rx in _NAME_SIG:
        if rx.search(name):
            return Fingerprint(mech, *MECHANISMS[mech][:2], evidence=f"name:{mech}")
    if status in ("failed", "error"):
        return Fingerprint(
            "semantic", *MECHANISMS["semantic"][:2], evidence="failure w/ no env signature"
        )
    return Fingerprint("unknown", *MECHANISMS["unknown"][:2], evidence=f"status={status}")
