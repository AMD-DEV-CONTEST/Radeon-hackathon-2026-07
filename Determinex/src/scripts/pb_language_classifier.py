#!/usr/bin/env python3
"""ProgramBench language classifier.

For each tool, scans its behavioral test surface (test names + failure
messages from the best eval JSON) for signals that distinguish:

  native-required  - tool MUST be reimplemented in its source language
                     because the test suite enshrines C/Rust/Go-level
                     semantics (integer overflow, signal handling, byte-
                     level output, timing) a Python wrapper cannot fake.

  python-sufficient - tool can ship as a Python implementation. Tests
                     only check stdout/stderr text, exit codes, file
                     existence. The majority of current locks live here.

  unknown          - eval JSON missing, no test data to classify yet.

The classifier reads `logs/programbench_lock_board.json` and writes:

    logs/programbench_factory/LANGUAGE_CLASSIFICATION.json
    logs/programbench_factory/LANGUAGE_CLASSIFICATION.md

Each tool's entry records:
    base_slug, classification, evidence (matched_patterns + sample_tests),
    confidence (high|medium|low), source_language (best guess from binary)

This drives the conversion priority list: native-required tools must be
rewritten in their target language before final submission; python-
sufficient tools ship as Python.

Invocation:
    python scripts/pb_language_classifier.py           # full board
    python scripts/pb_language_classifier.py --slug X  # one tool
    python scripts/pb_language_classifier.py --summary # board breakdown
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
OUT_JSON = FACTORY_DIR / "LANGUAGE_CLASSIFICATION.json"
OUT_MD = FACTORY_DIR / "LANGUAGE_CLASSIFICATION.md"
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"


SOURCE_LANGUAGE_BY_BASE: dict[str, str] = {
    # High-priority native tools where slug heuristics are ambiguous.
    "jqlang__jq": "c",
    "lua__lua": "c",
    "tinycc__tinycc": "c",
    "sqlite__sqlite": "c",
    "nuta__nsh": "c",
    "sstadick__hck": "rust",
    "chmln__sd": "rust",
    "pemistahl__grex": "rust",
    "mookid__diffr": "rust",
    "sharkdp__hexyl": "rust",
    "sharkdp__fd": "rust",
    "burntsushi__ripgrep": "rust",
    "burntsushi__xsv": "rust",
    "bootandy__dust": "rust",
    "byron__dua-cli": "rust",
    "sharkdp__pastel": "rust",
    "kyoh86__richgo": "go",
    "tomnomnom__gron": "go",
    "konradsz__igrep": "go",
    "rs__curlie": "go",
    "dundee__gdu": "go",
    "junegunn__fzf": "go",
    "peco__peco": "go",
    "ariga__atlas": "go",
    "sibprogrammer__xq": "go",
    "sclevine__yj": "go",
    "oppiliappan__eva": "python",
    "dalance__amber": "python",
}


# Patterns that, when found in test names or failure messages, indicate
# the test enshrines language-native behavior a Python wrapper cannot fake.
# `_BS` is an underscore-aware token boundary: matches start-of-string,
# end-of-string, or any non-alphanumeric/non-underscore-EXCEPT it treats
# `_` itself as a boundary. This is crucial because pytest test names are
# snake_case (e.g. `test_or_overflow_values`) and Python's `\b` treats `_`
# as a word char, so `\boverflow\b` would miss `_overflow_`.
_BL = r"(?<![A-Za-z0-9])"  # left:  no preceding alphanumeric
_BR = r"(?![A-Za-z0-9])"  # right: no following alphanumeric


def _W(pat: str, flags: int = re.I) -> re.Pattern[str]:
    return re.compile(_BL + pat + _BR, flags)


NATIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("integer_overflow", _W(r"(?:integer[_ -]?)?overflow")),
    ("integer_overflow", _W(r"underflow")),
    ("c_atoi_semantics", _W(r"c[_ -]?atoi|atoi[_ -]?overflow|atoi_(?:max|min|range)")),
    # "buffer_size" only matches when the test name explicitly mentions
    # buffer size/overflow/underrun. Pure "test_large_input" doesn't count.
    ("buffer_size", _W(r"buffer[_ -]?(?:overflow|underrun|over[_ -]?run)")),
    ("buffer_size_arg", _W(r"buffer[_ -]?(?:size|len)")),
    (
        "signal_handling",
        re.compile(
            r"(?<![A-Za-z0-9])SIG(?:PIPE|TERM|INT|KILL|HUP|CHLD|ALRM|USR1|USR2|QUIT)(?![A-Za-z0-9])"
        ),
    ),
    ("signal_handling", _W(r"signal[_ -]?(?:handler|handling|trap|raised|caught)")),
    ("broken_pipe", _W(r"broken[_ -]?pipe|EPIPE")),
    ("byte_level", _W(r"byte[_ -]?(?:exact|level|order|sequence|count|stream|swap)")),
    ("byte_level", _W(r"raw[_ -]?bytes")),
    ("binary_output", _W(r"binary[_ -]?(?:output|format|file|safe|stream|mode|data)")),
    ("file_magic", _W(r"(?:file[_ -]?)?magic[_ -]?(?:bytes?|number|header)")),
    ("file_magic", _W(r"ELF[_ -]?(?:header|magic)?")),
    ("endianness", _W(r"(?:little|big)[_ -]?endian")),
    ("memory_layout", _W(r"memory[_ -]?(?:usage|leak|mapped|mmap|alignment|map)")),
    ("memory_layout", _W(r"malloc|calloc|realloc|free_byte|stack[_ -]?frame|heap")),
    (
        "timing_perf",
        _W(r"(?:performance|benchmark|throughput|latency|timing)[_ -]?(?:test|sensitive|critical)"),
    ),
    ("timing_perf", _W(r"nanosecond|microsecond[_ -]?(?:precision|accuracy)")),
    ("native_panic", re.compile(r"panicked at [^\s]+\.rs:\d+", re.I)),
    ("native_panic", _W(r"goroutine|go[_ -]?runtime")),
    ("native_panic", _W(r"segmentation[_ -]?fault|segfault|core[_ -]?dump")),
    (
        "size_t_off_t",
        re.compile(
            r"(?<![A-Za-z0-9])(?:off_?t|size_?t|ssize_?t|uint(?:32|64|ptr)|int(?:32|64))(?![A-Za-z0-9])"
        ),
    ),
    ("utf16_native", _W(r"utf[_ -]?16|utf[_ -]?32|surrogate[_ -]?pair")),
    ("compression_native", _W(r"compression[_ -]?(?:ratio|level|format)")),
    ("compression_native", _W(r"(?:gzip|bzip2|lz4|zstd|xz)[_ -]?(?:stream|format|magic|header)")),
    ("null_byte", _W(r"null[_ -]?(?:bytes?|terminator|delimited|delimiter)")),
    ("stdin_binary", _W(r"binary[_ -]?stdin|raw[_ -]?stdin")),
    ("file_descriptor", _W(r"file[_ -]?descriptor|fd[_ -]?leak")),
    ("file_descriptor", re.compile(r"/dev/fd/\d+")),
    ("mmap_io", _W(r"mmap|memory[_ -]?map")),
    # Tool-specific signals seen in known-native tools
    ("invalid_utf8", _W(r"invalid[_ -]?utf8|invalid[_ -]?utf[_ -]?8")),
    ("invalid_utf8", _W(r"utf8[_ -]?(?:passthrough|preservation)")),
    ("native_ints", _W(r"i32_(?:max|min)|i64_(?:max|min)|u32_max|u64_max")),
    ("native_ints", _W(r"INT_MAX|INT_MIN|UINT_MAX|LLONG_MAX")),
]

# Patterns that signal pure text I/O — used as positive evidence for
# python-sufficient (so we don't classify a tool as native-required
# from one ambiguous test name when 99% are plain text).
PYTHON_OK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(exit[_ -]?code|return[_ -]?code|status)\b", re.I),
    re.compile(r"\bstdout[_ -]?(contains|equals|matches|empty)\b", re.I),
    re.compile(r"\bstderr[_ -]?(contains|equals|matches|empty)\b", re.I),
    re.compile(r"\bhelp[_ -]?(output|text|message)\b", re.I),
    re.compile(r"\bversion[_ -]?(flag|output|string)\b", re.I),
    re.compile(r"\busage[_ -]?(line|format|message)\b", re.I),
    re.compile(r"\bfile[_ -]?(exists|created|missing)\b", re.I),
    re.compile(r"\b(invalid|missing|unknown)[_ -]?(flag|arg|option)\b", re.I),
]

# Detect raw bytes assertions in failure messages (e.g. assert b'\xff\xfe' ==
# b'\xef\xbf\xbd'). High-entropy escape sequences in expected output usually
# indicate the test asserts byte-level semantics native code reproduces but
# Python str-handling normalizes away.
BYTE_ASSERTION_RE = re.compile(r"\bb'[^']*\\x[0-9a-fA-F]{2}", re.I)
HIGH_ESCAPE_RE = re.compile(r"(?:\\x[0-9a-fA-F]{2}){3,}")  # 3+ adjacent hex escapes


def _detect_source_language(slug: str, override_dir: Path) -> str:
    """Best-effort source language detection from the override dir contents."""
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    if base in SOURCE_LANGUAGE_BY_BASE:
        return SOURCE_LANGUAGE_BY_BASE[base]
    if not override_dir.is_dir():
        return "unknown"
    if (override_dir / "main.go").is_file() or (override_dir / "go.mod").is_file():
        return "go"
    if (override_dir / "src" / "main.rs").is_file() or (override_dir / "Cargo.toml").is_file():
        return "rust"
    if (override_dir / "main.c").is_file():
        return "c"
    if (override_dir / "main.cpp").is_file() or (override_dir / "main.cc").is_file():
        return "cpp"
    # The bundled binary name often matches the tool name.
    binaries = []
    for child in override_dir.iterdir():
        if (
            child.is_file()
            and not child.suffix
            and not child.name.endswith(".sh")
            and not child.name.endswith(".py")
            and not child.name.startswith(".")
        ):
            # Could be the binary
            try:
                with open(child, "rb") as f:
                    head = f.read(8)
                if head.startswith(b"\x7fELF"):
                    binaries.append(child)
                elif head[:2] == b"MZ":
                    binaries.append(child)
            except Exception:
                pass
    main_py = override_dir / "main.py"
    if main_py.is_file():
        try:
            text = main_py.read_text(encoding="utf-8", errors="replace")[:2000].lower()
            if "language: c\n" in text or "family hint: c_" in text or "c_cli" in text:
                return "c"
            if "language: rust" in text or "family hint: rust" in text or "rust_cli" in text:
                return "rust"
            if "language: go" in text or "family hint: go" in text or "go_cli" in text:
                return "go"
            if "language: cpp" in text or "language: c++" in text:
                return "cpp"
        except Exception:
            pass
    # Guess from slug prefix patterns
    if "_rust" in slug.lower() or any(
        x in slug
        for x in (
            "burntsushi__",
            "alacritty__",
            "sharkdp__",
            "extrawurst__",
            "servo__",
            "rust-lang__",
            "ducaale__",
            "ogham__",
            "BurntSushi__",
        )
    ):
        return "rust"
    return "unknown"


def _scan_tests(eval_json_path: Path) -> dict[str, Any]:
    """Walk the eval JSON's test_results and look for native-required signals.

    Key insight: the signal that matters is whether FAILING tests bind to
    native behavior. A test named "test_overflow" that already PASSES under
    a bundled-binary or even Python wrapper is not blocking - the surface it
    enshrines is something the current wrapper handles fine. The native-
    required signal is when failing tests cannot be solved without native
    semantics (integer overflow, signal handling, byte-level output).

    Returns separate buckets for failing-only matches (signal) and all-tests
    matches (context), plus byte-level assertion hits in failure messages.
    """
    try:
        ev = json.loads(eval_json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as err:
        return {"error": str(err)}

    results = ev.get("test_results") or []
    matched_failing: dict[str, list[str]] = defaultdict(list)
    matched_passing: dict[str, list[str]] = defaultdict(list)
    byte_hits = 0
    python_ok_failing = 0
    total = len(results)
    failing = 0
    passing = 0

    for t in results:
        status = (t.get("status") or "").lower()
        is_failure = status in ("failure", "error", "failed")
        is_pass = status == "passed"
        if is_failure:
            failing += 1
        elif is_pass:
            passing += 1
        name = str(t.get("name") or "")
        msg = ""
        extra = t.get("extra") or {}
        if isinstance(extra, dict):
            m = extra.get("message")
            if isinstance(m, str):
                msg = m
        searchable = name + "\n" + msg

        for label, pat in NATIVE_PATTERNS:
            if pat.search(searchable):
                bucket = matched_failing if is_failure else matched_passing
                if len(bucket[label]) < 4:
                    bucket[label].append(name)

        # Byte-level escape sequences in FAILURE messages only (passing tests
        # don't have informative messages).
        if is_failure and msg and (BYTE_ASSERTION_RE.search(msg) or HIGH_ESCAPE_RE.search(msg)):
            byte_hits += 1
            if len(matched_failing["byte_escape_assertion"]) < 4:
                matched_failing["byte_escape_assertion"].append(name)

        # Python-sufficient signal: failing tests that are clearly text I/O
        if is_failure:
            for pat in PYTHON_OK_PATTERNS:
                if pat.search(name) or pat.search(msg):
                    python_ok_failing += 1
                    break

    return {
        "total_tests": total,
        "passing": passing,
        "failing": failing,
        "matched_patterns": {k: list(v) for k, v in matched_failing.items()},
        "matched_patterns_passing_only": {
            k: list(v) for k, v in matched_passing.items() if k not in matched_failing
        },
        "byte_escape_hits": byte_hits,
        "python_ok_failing_hits": python_ok_failing,
    }


def _classify(scan: dict[str, Any]) -> tuple[str, str, str]:
    """Return (classification, confidence, reason)."""
    if "error" in scan:
        return "unknown", "low", f"eval load failed: {scan['error']}"
    if scan["total_tests"] == 0:
        return "unknown", "low", "no test data in eval JSON"

    # Failing-test signals are the discriminator. Tests that already pass
    # under a bundled binary or wrapper don't constrain language choice -
    # they're handled. The signal we care about is "what blocks us today".
    cats = scan.get("matched_patterns") or {}
    byte_hits = scan.get("byte_escape_hits") or 0
    py_hits = scan.get("python_ok_failing_hits") or 0
    failing = scan.get("failing") or 0

    # Strong native signals when found in FAILING tests
    strong = {
        "integer_overflow",
        "c_atoi_semantics",
        "buffer_size",
        "memory_layout",
        "size_t_off_t",
        "endianness",
        "file_magic",
        "compression_native",
        "null_byte",
        "mmap_io",
        "native_ints",
        "native_panic",
    }
    strong_hit = [c for c in cats if c in strong and cats[c]]

    moderate = {
        "signal_handling",
        "broken_pipe",
        "byte_level",
        "binary_output",
        "timing_perf",
        "utf16_native",
        "byte_escape_assertion",
        "file_descriptor",
        "stdin_binary",
        "invalid_utf8",
    }
    mod_hit = [c for c in cats if c in moderate and cats[c]]

    if failing == 0:
        # No failures means we have no diagnostic surface. Fall back to
        # current score: 100% under a bundled-binary wrapper proves nothing
        # about Python, but we can't classify without failure evidence.
        if scan.get("passing") and scan.get("passing") == scan.get("total_tests"):
            return (
                "python-sufficient",
                "low",
                "no failures to diagnose; current implementation passes all runnable tests",
            )
        return "unknown", "low", "no failures and no clear pass-all evidence"

    if strong_hit:
        return "native-required", "high", f"failing tests bind native semantics: {strong_hit}"
    if len(mod_hit) >= 2 or byte_hits >= 3:
        return (
            "native-required",
            "high",
            f"multiple native signals in failures: {mod_hit} (byte_hits={byte_hits})",
        )
    if mod_hit and byte_hits >= 1:
        return (
            "native-required",
            "medium",
            f"failing-test signal + byte assertions: {mod_hit} (byte_hits={byte_hits})",
        )
    if mod_hit:
        return "native-required", "low", f"single moderate signal in failures: {mod_hit}"

    py_ratio = py_hits / failing if failing else 0
    if py_ratio >= 0.50:
        return (
            "python-sufficient",
            "high",
            f"all {failing} failures are text-I/O patterns ({py_hits} matched python-ok)",
        )
    if py_hits > 0:
        return (
            "python-sufficient",
            "medium",
            f"{py_hits}/{failing} failures match python-ok patterns; no native signals",
        )
    return (
        "python-sufficient",
        "low",
        f"no native signals in failures, but no clear python-ok matches either ({failing} fails)",
    )


def classify_one(board_entry: dict[str, Any]) -> dict[str, Any]:
    slug = board_entry.get("base_slug") or board_entry.get("slug") or ""
    full_slug = board_entry.get("slug") or board_entry.get("base_slug") or ""
    ep = board_entry.get("best_eval_path")
    has_eval = bool(ep) and isinstance(ep, str) and Path(ep).is_file()
    override_dir = OVERRIDES_DIR / (full_slug or slug)
    if not override_dir.is_dir():
        # try other naming
        for cand in OVERRIDES_DIR.glob(f"{slug}*"):
            if cand.is_dir():
                override_dir = cand
                break

    source_lang = _detect_source_language(slug, override_dir)
    scan: dict[str, Any] = {}
    if has_eval and isinstance(ep, str):
        scan = _scan_tests(Path(ep))
        classification, confidence, reason = _classify(scan)
    else:
        classification, confidence, reason = "unknown", "low", "no eval JSON"

    return {
        "base_slug": slug,
        "slug": full_slug,
        "classification": classification,
        "confidence": confidence,
        "reason": reason,
        "source_language": source_lang,
        "best_score": board_entry.get("best_score"),
        "best_passed": board_entry.get("best_passed"),
        "best_runnable_total": board_entry.get("best_runnable_total"),
        "next_action": board_entry.get("next_action"),
        "evidence": scan.get("matched_patterns", {}),
        "test_stats": {
            "total": scan.get("total_tests"),
            "passing": scan.get("passing"),
            "failing": scan.get("failing"),
            "byte_escape_hits": scan.get("byte_escape_hits"),
            "python_ok_hits": scan.get("python_ok_failing_hits"),
        },
    }


def write_markdown_report(classifications: list[dict[str, Any]], out_md: Path) -> None:
    bands = Counter(c["classification"] for c in classifications)
    confidence_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
    for c in classifications:
        confidence_breakdown[c["classification"]][c["confidence"]] += 1
    lang_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
    for c in classifications:
        lang_breakdown[c["classification"]][c["source_language"]] += 1

    lines: list[str] = []
    lines.append("# ProgramBench Language Classification\n")
    lines.append("> Generated by `scripts/pb_language_classifier.py`. ")
    lines.append("Reads behavioral test surface from each tool's `best_eval_path` ")
    lines.append("and flags tools whose tests enshrine language-native behavior ")
    lines.append("(integer overflow, signal handling, byte-level output, timing) ")
    lines.append("that a Python wrapper cannot faithfully reproduce.\n\n")

    lines.append("## Summary\n\n")
    lines.append("| classification | count |\n|---|---|\n")
    for k in ("native-required", "python-sufficient", "unknown"):
        lines.append(f"| **{k}** | {bands.get(k, 0)} |\n")
    lines.append(f"| total | {sum(bands.values())} |\n\n")

    lines.append("### By confidence\n\n")
    for cls in ("native-required", "python-sufficient", "unknown"):
        cb = confidence_breakdown.get(cls, Counter())
        lines.append(
            f"- **{cls}**: high={cb.get('high', 0)}, medium={cb.get('medium', 0)}, low={cb.get('low', 0)}\n"
        )
    lines.append("\n")

    lines.append("### By source language (best guess)\n\n")
    for cls in ("native-required", "python-sufficient"):
        lb = lang_breakdown.get(cls, Counter())
        if not lb:
            continue
        line = " ".join(f"{k}={v}" for k, v in lb.most_common())
        lines.append(f"- **{cls}**: {line}\n")
    lines.append("\n")

    # native-required priority list (highest test count first — biggest impact)
    nr = [c for c in classifications if c["classification"] == "native-required"]
    nr.sort(key=lambda c: -(c.get("best_runnable_total") or 0))
    lines.append("## Native-required priority list\n\n")
    lines.append("Tools that must be rewritten in their source language. Ordered by ")
    lines.append("test surface (largest first — biggest score impact when converted).\n\n")
    lines.append("| score | passed/runnable | source | confidence | reason | slug |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for c in nr[:80]:
        score = c.get("best_score") or 0
        score_s = f"{score:.1f}" if isinstance(score, (int, float)) else "-"
        rsn = c["reason"]
        if len(rsn) > 100:
            rsn = rsn[:100] + "..."
        lines.append(
            f"| {score_s} | {c.get('best_passed') or 0}/{c.get('best_runnable_total') or 0} | "
            f"{c.get('source_language') or '?'} | {c['confidence']} | {rsn} | `{c['base_slug']}` |\n"
        )
    if len(nr) > 80:
        lines.append(f"\n_({len(nr) - 80} more native-required tools omitted)_\n")
    lines.append("\n")

    # python-sufficient — these can ship as Python
    ps = [c for c in classifications if c["classification"] == "python-sufficient"]
    ps.sort(key=lambda c: -(c.get("best_score") or 0))
    lines.append("## Python-sufficient (top 40 by current score)\n\n")
    lines.append("| score | passed/runnable | confidence | slug |\n")
    lines.append("|---|---|---|---|\n")
    for c in ps[:40]:
        score = c.get("best_score") or 0
        score_s = f"{score:.1f}" if isinstance(score, (int, float)) else "-"
        lines.append(
            f"| {score_s} | {c.get('best_passed') or 0}/{c.get('best_runnable_total') or 0} | "
            f"{c['confidence']} | `{c['base_slug']}` |\n"
        )
    lines.append("\n")

    out_md.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="classify one tool by base_slug, print to stdout")
    ap.add_argument(
        "--summary",
        action="store_true",
        help="print board-wide breakdown to stdout after writing artifacts",
    )
    args = ap.parse_args()

    if not BOARD_JSON.is_file():
        sys.stderr.write(f"missing board JSON: {BOARD_JSON}\n")
        return 2
    board = json.loads(BOARD_JSON.read_text(encoding="utf-8"))

    if args.slug:
        for entry in board:
            if entry.get("base_slug") == args.slug:
                result = classify_one(entry)
                print(json.dumps(result, indent=2, default=str))
                return 0
        sys.stderr.write(f"slug not found in board: {args.slug}\n")
        return 3

    FACTORY_DIR.mkdir(parents=True, exist_ok=True)
    classifications = [classify_one(e) for e in board]
    OUT_JSON.write_text(json.dumps(classifications, indent=2, default=str), encoding="utf-8")
    write_markdown_report(classifications, OUT_MD)

    bands = Counter(c["classification"] for c in classifications)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print()
    print(f"native-required:   {bands.get('native-required', 0)}")
    print(f"python-sufficient: {bands.get('python-sufficient', 0)}")
    print(f"unknown:           {bands.get('unknown', 0)}")

    if args.summary:
        # Detail by confidence + source language
        confidence_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
        lang_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
        for c in classifications:
            confidence_breakdown[c["classification"]][c["confidence"]] += 1
            lang_breakdown[c["classification"]][c["source_language"]] += 1
        print()
        print("Confidence breakdown:")
        for cls, cb in confidence_breakdown.items():
            print(f"  {cls}: " + " ".join(f"{k}={v}" for k, v in cb.most_common()))
        print()
        print("Source-language breakdown (best guess):")
        for cls, lb in lang_breakdown.items():
            print(f"  {cls}: " + " ".join(f"{k}={v}" for k, v in lb.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
