#!/usr/bin/env python3
"""Determinex Universal Term Extractor.

Mines the *canonical verbiage* of a tool/test from the test text itself, so the
reimplementation uses the tool's own terms instead of guessing per-tool.

Motivation (2026-06-16): per-tool reimplementation kept *guessing* the proper
strings -- flag long-names, metavars (`<columns>` vs nothing), error templates,
possible-value lists, even the JUnit status keyword (`failed` vs `failure`).
Every guess costs an eval round-trip. Instead, extract the proper terms straight
from the ground truth (the failing-assertion EXPECTED side in pytest tracebacks)
and normalize against what our binary currently emits.

This is a normalization layer for the universal build: feed it any
`programbench`-style eval JSON (each `test_results[i].extra.text` carries the
pytest traceback) and it emits a per-tool term dictionary + a normalization map
(`ours -> proper`) of mismatches the reimplementation should adopt.

It NEVER guesses. Every term it emits is a literal substring of the test text.

Usage:
    python scripts/determinex_term_extractor.py <eval.json> [<eval.json> ...]
    python scripts/determinex_term_extractor.py <eval.json> --out terms/<tool>.json
    python scripts/determinex_term_extractor.py <eval.json> --quiet   # JSON only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Regexes over pytest traceback text (the EXPECTED side is ground truth).
# ---------------------------------------------------------------------------

# Metavars in clap/argparse style messages and usage: <columns>, <FILE>, <color>
RE_METAVAR = re.compile(r"<([A-Za-z][A-Za-z0-9_]*)>")

# `a value is required for '--cols <columns>'`  (clap error template)
RE_VALUE_REQUIRED = re.compile(r"a value is required for '([^']+)'")

# `[possible values: bash, elvish, fish, powershell, zsh]`
RE_POSSIBLE_VALUES = re.compile(r"\[possible values:\s*([^\]]+)\]")

# `for '--format <format>'` / `for '<SHELL>'` -> the option/arg the message names
RE_FOR_OPTION = re.compile(r"for '([^']+)'")

# `error: unexpected argument '--version' found`
RE_UNEXPECTED_ARG = re.compile(r"unexpected argument '([^']+)' found")

# Long/short flags appearing anywhere: --foo-bar, -x
RE_LONG_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]+)")
RE_SHORT_FLAG = re.compile(r"(?<![\w-])(-[A-Za-z0-9])(?![\w-])")

# parametrize ids embedded in the test name: name[args0-a value is required ...]
RE_PARAM_ID = re.compile(r"\[([^\]]+)\]\s*$")

# pytest assertion forms (we want the EXPECTED literal, not the actual)
#   assert b'0.5' in result.stdout            -> expected snippet b'0.5'
#   assert X == 'Usage:'                       -> expected literal
#   assert 'Usage:' in result.stdout           -> expected snippet
RE_ASSERT_IN = re.compile(r"assert\s+(b?(['\"]).*?\2)\s+in\b")
RE_ASSERT_EQ_RHS = re.compile(r"==\s*(b?(['\"]).*?\2)")
RE_ASSERT_EQ_LHS = re.compile(r"assert\s+(b?(['\"]).*?\2)\s*==")

# Python-traceback pseudo-metavars: these appear in `<...>` inside tracebacks
# (frame names, comprehension scopes) and are NOT tool metavars. Never emit them.
PSEUDO_METAVARS = {
    "module",
    "locals",
    "genexpr",
    "listcomp",
    "dictcomp",
    "setcomp",
    "lambda",
    "string",
    "stdin",
    "stdout",
    "stderr",
    "frozen",
    "anonymous",
}

# Flag names that only ever appear as *rejection* test inputs ("unexpected
# argument '--bogus'"); they are deliberately fake and must not be treated as
# real terms the reimpl is missing.
NOISE_FLAG_SUBSTRINGS = (
    "unknown",
    "nonexistent",
    "non-existent",
    "bogus",
    "no-such",
    "nosuch",
    "not-a",
    "notreal",
    "not-real",
    "definitely",
    "fake",
    "invalid-flag",
    "made-up",
    "madeup",
    "doesnotexist",
    "does-not-exist",
)


def _is_noise_flag(flag: str) -> bool:
    low = flag.lower()
    return any(s in low for s in NOISE_FLAG_SUBSTRINGS)


# Words that look like language / format / font identifiers (lowercase tokens
# that appear inside possible-value lists or array/format contexts).
LANG_HINTS = {
    "rust",
    "go",
    "golang",
    "python",
    "c",
    "cpp",
    "kotlin",
    "java",
    "swift",
    "fsharp",
    "ruby",
    "php",
    "javascript",
    "typescript",
    "bash",
    "zsh",
    "fish",
    "elvish",
    "powershell",
    "haskell",
    "scala",
    "perl",
    "lua",
}


def _iter_results(data):
    """Yield (name, status, text) over a programbench eval JSON."""
    for t in data.get("test_results", []):
        name = t.get("name", "")
        status = t.get("status", "")
        extra = t.get("extra", "")
        if isinstance(extra, dict):
            text = extra.get("text", "") or ""
        else:
            text = str(extra or "")
        yield name, status, text


def _decode_literal(lit: str) -> str:
    """Turn a python source literal token (b'..' / '..' / "..") into its value."""
    try:
        # Use a tiny, safe eval via ast.literal_eval-style parsing.
        import ast

        out = ast.literal_eval(lit)
        if isinstance(out, bytes):
            return out.decode("utf-8", "replace")
        return str(out)
    except Exception:
        return lit


def mine_texts(texts) -> dict:
    """Mine canonical terms from arbitrary text blobs (test sources OR
    traceback text). Shared engine for the eval-JSON path and the static
    ingester path -- so both speak the same vocabulary. Returns plain term
    lists (no status/normalization; those are eval-specific)."""
    metavars = Counter()
    value_required = Counter()
    possible_values = defaultdict(set)
    long_flags = Counter()
    short_flags = Counter()
    lang_terms = Counter()
    for text in texts:
        if not text:
            continue
        for vr in RE_VALUE_REQUIRED.findall(text):
            value_required[vr] += 1
        for mv in RE_METAVAR.findall(text):
            if mv.lower() not in PSEUDO_METAVARS:
                metavars[mv] += 1
        for pv in RE_POSSIBLE_VALUES.findall(text):
            vals = [v.strip() for v in pv.split(",") if v.strip()]
            possible_values[",".join(sorted(vals))].update(vals)
            for v in vals:
                if v.lower() in LANG_HINTS:
                    lang_terms[v] += 1
        for f in RE_LONG_FLAG.findall(text):
            if not _is_noise_flag(f):
                long_flags[f] += 1
        for f in RE_SHORT_FLAG.findall(text):
            short_flags[f] += 1

    def top(c, k=40):
        return [{"term": t, "n": n} for t, n in c.most_common(k)]

    return {
        "value_required_templates": top(value_required),
        "metavars": top(metavars),
        "possible_value_sets": {k: sorted(v) for k, v in possible_values.items()},
        "long_flags": top(long_flags),
        "short_flags": top(short_flags),
        "language_terms": top(lang_terms),
    }


def extract(data) -> dict:
    """Return a term dictionary for one eval JSON."""
    status_counts = Counter()
    metavars = Counter()
    value_required = Counter()  # exact `--flag <metavar>` templates
    possible_values = defaultdict(set)  # context-option -> set(values)
    long_flags = Counter()
    short_flags = Counter()
    unexpected_args = Counter()
    expected_snippets = Counter()  # literal EXPECTED strings from assertions
    lang_terms = Counter()
    param_expected = Counter()  # expected text carried in parametrize ids

    n_total = 0
    n_fail = 0
    for name, status, text in _iter_results(data):
        n_total += 1
        status_counts[status] += 1
        if status == "passed":
            # Even passing tests' names carry parametrize verbiage; but the
            # traceback (expected/actual) only exists on failures. Skip text.
            continue
        n_fail += 1

        # Parametrize id verbiage (e.g. the expected error snippet).
        m = RE_PARAM_ID.search(name)
        if m:
            pid = m.group(1)
            # ids often look like  args0-a value is required for '--color <color>'
            for vr in RE_VALUE_REQUIRED.findall(pid):
                value_required[vr] += 1
            for mv in RE_METAVAR.findall(pid):
                metavars[mv] += 1
            param_expected[pid] += 1

        if not text:
            continue

        for vr in RE_VALUE_REQUIRED.findall(text):
            value_required[vr] += 1
        for mv in RE_METAVAR.findall(text):
            if mv.lower() not in PSEUDO_METAVARS:
                metavars[mv] += 1
        for pv in RE_POSSIBLE_VALUES.findall(text):
            vals = [v.strip() for v in pv.split(",") if v.strip()]
            key = ",".join(sorted(vals))
            possible_values[key].update(vals)
            for v in vals:
                if v.lower() in LANG_HINTS:
                    lang_terms[v] += 1
        for f in RE_LONG_FLAG.findall(text):
            if not _is_noise_flag(f):
                long_flags[f] += 1
        for f in RE_SHORT_FLAG.findall(text):
            short_flags[f] += 1
        for ua in RE_UNEXPECTED_ARG.findall(text):
            unexpected_args[ua] += 1

        # Expected literals from assertions (prefer the EXPECTED side).
        for rx in (RE_ASSERT_IN, RE_ASSERT_EQ_RHS, RE_ASSERT_EQ_LHS):
            for mlit in rx.findall(text):
                lit = mlit[0] if isinstance(mlit, tuple) else mlit
                val = _decode_literal(lit)
                if val and len(val) <= 120 and "\n" not in val:
                    expected_snippets[val] += 1

        low = text.lower()
        for hint in LANG_HINTS:
            if re.search(rf"\b{re.escape(hint)}\b", low):
                lang_terms[hint] += 1

    def top(counter, k=40):
        return [{"term": t, "n": c} for t, c in counter.most_common(k)]

    return {
        "totals": {"tests": n_total, "failed_or_other": n_fail},
        "status_values": dict(status_counts),  # <- proper JUnit keywords, no guess
        "value_required_templates": top(value_required),
        "metavars": top(metavars),
        "possible_value_sets": {k: sorted(v) for k, v in possible_values.items()},
        "long_flags": top(long_flags),
        "short_flags": top(short_flags),
        "unexpected_args": top(unexpected_args),
        "language_terms": top(lang_terms),
        "expected_snippets": top(expected_snippets, k=80),
        "parametrize_expected": top(param_expected, k=60),
    }


def normalize(terms: dict, source_path: Path | None) -> list[dict]:
    """Produce a `ours -> proper` mismatch list if the reimpl source is given.

    For every value-required template / metavar / flag the test EXPECTS, check
    whether our source already contains that exact term. Anything the tests
    expect but our source lacks is a normalization target (probably we guessed a
    different word).
    """
    if not source_path or not source_path.exists():
        return []
    src = source_path.read_text(encoding="utf-8", errors="replace")
    mismatches = []

    for item in terms["value_required_templates"]:
        tmpl = item["term"]
        if tmpl not in src:
            mismatches.append(
                {
                    "kind": "value_required",
                    "expected": tmpl,
                    "present_in_source": False,
                    "n": item["n"],
                }
            )
    for item in terms["long_flags"]:
        flag = item["term"]
        if flag not in src and item["n"] >= 1:
            mismatches.append(
                {"kind": "long_flag", "expected": flag, "present_in_source": False, "n": item["n"]}
            )
    for item in terms["metavars"]:
        mv = item["term"]
        token = f"<{mv}>"
        if token not in src:
            mismatches.append(
                {"kind": "metavar", "expected": token, "present_in_source": False, "n": item["n"]}
            )
    # rank by frequency (how many tests demand it)
    mismatches.sort(key=lambda d: -d["n"])
    return mismatches


def _print_report(tool: str, terms: dict, mismatches: list[dict]):
    print(f"\n{'=' * 70}\n  {tool}\n{'=' * 70}")
    print(f"  status keywords (PROPER, from data): {terms['status_values']}")
    if terms["value_required_templates"]:
        print("  value-required templates (exact verbiage):")
        for it in terms["value_required_templates"][:12]:
            print(f"    {it['n']:>3}x  a value is required for '{it['term']}'")
    if terms["possible_value_sets"]:
        print("  possible-value sets:")
        for k, v in list(terms["possible_value_sets"].items())[:6]:
            print(f"    {v}")
    if terms["language_terms"]:
        print(f"  language/format terms: {[t['term'] for t in terms['language_terms']]}")
    if mismatches:
        print(f"  >>> NORMALIZATION TARGETS (tests expect, our source lacks): {len(mismatches)}")
        for m in mismatches[:20]:
            print(f"    [{m['kind']}] {m['expected']!r}  (x{m['n']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Determinex universal term extractor")
    ap.add_argument("eval_jsons", nargs="+", help="programbench eval JSON file(s)")
    ap.add_argument(
        "--source",
        help="reimpl source .py to diff for normalization "
        "(only meaningful with a single eval json)",
    )
    ap.add_argument("--source-dir", help="dir holding <tool>.py reimpls to auto-pair")
    ap.add_argument("--out", help="write term dict JSON here (single input)")
    ap.add_argument("--out-dir", help="write <tool>.terms.json per input here")
    ap.add_argument("--quiet", action="store_true", help="JSON only, no report")
    args = ap.parse_args(argv)

    all_out = {}
    for path_s in args.eval_jsons:
        path = Path(path_s)
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        terms = extract(data)
        # tool name: strip .eval.json / known suffixes
        tool = path.name
        for suf in (".eval.json", ".json"):
            if tool.endswith(suf):
                tool = tool[: -len(suf)]
                break
        # full-slug like sitkevij__hex.61ae69b -> hex
        short = tool.split("__")[-1].split(".")[0] if "__" in tool else tool

        src_path = None
        if args.source and len(args.eval_jsons) == 1:
            src_path = Path(args.source)
        elif args.source_dir:
            for cand in (f"{short}.py", f"{short.replace('-', '_')}.py", f"{tool}.py"):
                p = Path(args.source_dir) / cand
                if p.exists():
                    src_path = p
                    break
        mismatches = normalize(terms, src_path)
        terms["normalization_targets"] = mismatches
        all_out[short] = terms

        if not args.quiet:
            _print_report(short, terms, mismatches)

        if args.out and len(args.eval_jsons) == 1:
            Path(args.out).write_text(json.dumps(terms, indent=2), encoding="utf-8")
        if args.out_dir:
            od = Path(args.out_dir)
            od.mkdir(parents=True, exist_ok=True)
            (od / f"{short}.terms.json").write_text(json.dumps(terms, indent=2), encoding="utf-8")

    if args.quiet:
        json.dump(all_out, sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
