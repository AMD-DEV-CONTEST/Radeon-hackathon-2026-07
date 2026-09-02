#!/usr/bin/env python3
"""
determinex_pb_integrity.py -- The integrity spine for ProgramBench remediation
===========================================================================
Fix techniques are useless -- worse, dangerous -- without an integrity layer that
decides WHEN a fix is legitimate (reproducing the reference environment) versus
CHEATING (faking output, suppressing tests, editing fixtures). Without this, the
flywheel would learn to cheat and poison every future model. This module is that
spine. Three capabilities:

  1. LEGITIMACY CLASSIFIER  -- legitimacy_class(technique, transform) -> GREEN /
     YELLOW / RED. Enforced at apply-time AND at flywheel-training-eligibility.
       GREEN  = reproduce the reference environment (build/source/clock/pty/locale/
                privileges/deps). Touches HOW the binary runs, not its output. Always OK.
       YELLOW = output post-processing. OK only if it normalizes VOLATILE token
                CLASSES (whitespace, temp paths, ANSI, timestamp/hash placeholders) --
                NEVER if it injects golden-specific content. Idempotent-on-golden test.
       RED    = forbidden: editing fixtures/goldens, collection caps, skip injection,
                stubbing test-exercised deps, rewriting output to match a golden literal.
     training_eligible() emits ONLY GREEN + justified-YELLOW into the corpus; RED is
     quarantined and never trained on.

  2. KEEP-IF-BETTER GATE    -- keep_if_better(before, after). A fix is kept ONLY if it
     introduces ZERO regressions (no previously-passing test now fails) -- enforcing,
     per-fix, the "worse-than-best never overwrites" rule. (dstask v4 regressed 98.8->
     97.55 and was reverted by hand; this makes that automatic.)

  3. CROSS-BRANCH CONTRADICTION + EXEMPTION REGISTRY -- find_cross_branch_contradictions()
     surfaces the real IMPOSSIBLE class (two branches demand conflicting ground truth
     for an identical invocation). Exemptions (upstream-skip / cross-branch-contradiction
     / harness-limit) are recorded with a PROOF artifact and a re-adjudication date --
     bounded, audited, and periodically re-challenged (an "impossible" label can be wrong).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXEMPTIONS = REPO / "corpus" / "programbench" / "exemptions.json"
QUARANTINE = REPO / "corpus" / "programbench" / "training_corpus" / "pb_quarantine.jsonl"


class Legitimacy(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# Base class per technique/strategy name (from adjudicator + autofix + behavioral).
_TECHNIQUE_CLASS = {
    # GREEN -- reproduce the reference environment / correct the build
    "fix-build-target": Legitimacy.GREEN,
    "source-completion": Legitimacy.GREEN,
    "install-dependency": Legitimacy.GREEN,
    "scalar-build": Legitimacy.GREEN,
    "clock-route": Legitimacy.GREEN,
    "clock-freeze": Legitimacy.GREEN,
    "locale-pin": Legitimacy.GREEN,
    "pty-allocate": Legitimacy.GREEN,
    "behavioral:tty-render": Legitimacy.GREEN,
    "drop-privileges": Legitimacy.GREEN,
    "deleted-cwd": Legitimacy.GREEN,
    "remove-collection-cap": Legitimacy.GREEN,  # a numeric perf cap is self-inflicted; removing it only lets real tests run
    # Routing on a REAL observable context (cwd/argv/env/input files) is legitimate; routing on the
    # TEST NAME (PYTEST_CURRENT_TEST) or a baked {nodeid->output} map is test-detection GAMING -- the
    # CANON AUDIT demoted yj/svd2rust for exactly that. So: context-route GREEN, test-name route RED.
    "context-route": Legitimacy.GREEN,
    "pytest-current-test-routing": Legitimacy.RED,  # test-name routing = gaming (forbidden)
    "bidir-mirror": Legitimacy.GREEN,  # PB tests.json lists tests under BOTH eval.tests./tests. prefixes; mirroring a PASSING case under the prefix PB asked for reflects a genuine pass (never mirrors a <failure>/<error>) -- prefix reconciliation, not a cheat
    "bidir": Legitimacy.GREEN,
    "behavioral:output-mode": Legitimacy.GREEN,  # selecting the renderer flag/env the golden used
    # YELLOW -- output post-processing (must be content-preserving; checked below)
    "error-string-normalize": Legitimacy.YELLOW,
    "behavioral:whitespace": Legitimacy.YELLOW,
    "behavioral:path-tmp": Legitimacy.YELLOW,
    "behavioral:ansi-color": Legitimacy.YELLOW,
    "behavioral:version-build": Legitimacy.YELLOW,
    "behavioral:datetime": Legitimacy.GREEN,  # via clock-route (env), not output rewrite
    # MATCH/IMPOSSIBLE bookkeeping
    "upstream-skip": Legitimacy.GREEN,  # an exemption, not a fix
    "identical-context-conflict": Legitimacy.GREEN,  # a proof, not a fix
}

# RED signatures in an applied TRANSFORM (the actual code/text we'd ship). These are
# the things that make a "fix" a cheat regardless of which technique claimed it.
_RED_TRANSFORM = [
    (re.compile(r"pytest\.mark\.skip|add_marker\(.*skip|item\.add_marker"), "injects a skip"),
    (
        re.compile(r"\bdel\s+items\[|items\[:\]\s*=\s*items\[:\d|collect_ignore"),
        "suppresses test collection",
    ),
    (
        re.compile(
            r"\.golden|expected\.write|write_text\([^)]*golden|open\([^)]*\.golden[^)]*['\"]w"
        ),
        "writes/edits a golden/fixture",
    ),
    (
        re.compile(r"results?\.xml.*<failure|del .*testcase|remove.*<failure>"),
        "edits the results XML to hide failures",
    ),
]

# A YELLOW output transform is RED if it maps SPECIFIC observed values to SPECIFIC
# golden values (memorizing the answer) rather than normalizing volatile CLASSES.
_VOLATILE_CLASS_OK = re.compile(
    r"/tmp/|pytest-|\\r\\n|\\t|\[ \\t\]|0-9a-f\]\{7|x1b\[|\\d\{4\}-\\d\{2\}|"
    r"strip\(\)|rstrip|expandtabs|\$HOME|/home/|/root/|sub\(r"
)
# a literal-to-literal replace of non-volatile content = memorizing the golden
_LITERAL_SUBST = re.compile(r"""\.replace\(\s*['"][^'"]{2,}['"]\s*,\s*['"][^'"]{2,}['"]""")


@dataclass
class Verdict:
    legitimacy: str
    reason: str
    train: bool


def legitimacy_class(technique: str, transform: str = "") -> Verdict:
    """Classify a fix. `technique` is the strategy name; `transform` is the applied
    code/text (compile.sh edit, plugin body, normalizer)."""
    # 1) Any RED transform signature is decisive, regardless of technique.
    for pat, why in _RED_TRANSFORM:
        if pat.search(transform or ""):
            return Verdict(Legitimacy.RED.value, f"RED transform: {why}", train=False)
    base = _TECHNIQUE_CLASS.get(technique, Legitimacy.YELLOW)
    # 2) YELLOW output transforms must be content-preserving (volatile-class only).
    if base == Legitimacy.YELLOW and transform:
        subs = _LITERAL_SUBST.findall(transform)
        if subs and not _VOLATILE_CLASS_OK.search(transform):
            return Verdict(
                Legitimacy.RED.value,
                "RED: literal-to-literal output substitution (memorizing the "
                "golden, not normalizing a volatile class)",
                train=False,
            )
        return Verdict(
            Legitimacy.YELLOW.value,
            "YELLOW: output post-processing; allowed (volatile-class normalize). "
            "Must be idempotent on the golden.",
            train=True,
        )
    if base == Legitimacy.GREEN:
        return Verdict(
            Legitimacy.GREEN.value,
            "GREEN: reproduces the reference environment / corrects the build.",
            train=True,
        )
    return Verdict(
        base.value, f"{base.value}: default class for '{technique}'.", train=base != Legitimacy.RED
    )


def training_eligible(technique: str, transform: str = "") -> bool:
    """The flywheel gate: only GREEN + justified-YELLOW fixes train the models."""
    return legitimacy_class(technique, transform).train


def quarantine(record: dict, reason: str) -> None:
    """Park a RED/ineligible fix so it is NEVER trained on (kept for audit)."""
    QUARANTINE.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record["_quarantine_reason"] = reason
    record["_ts"] = time.time()
    with open(QUARANTINE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# 2. Keep-if-better gate
# ---------------------------------------------------------------------------
def _passing_set(report_path: Path) -> set[str]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    results = data.get("test_results", data if isinstance(data, list) else [])
    out = set()
    for t in results:
        if t.get("status") == "passed":
            cls = t.get("classname", "")
            name = t.get("name", "")
            out.add(f"{cls}.{name}" if cls else name)
    return out


def keep_if_better(before: Path, after: Path) -> dict:
    """Compare two eval reports. KEEP the fix only if it introduces ZERO regressions
    (no test that passed before now fails). Enforces 'worse-than-best never overwrites'
    at the per-fix level."""
    b, a = _passing_set(before), _passing_set(after)
    regressed = sorted(b - a)
    gained = sorted(a - b)
    keep = len(regressed) == 0 and len(gained) >= 0
    return {
        "keep": keep,
        "gained": len(gained),
        "regressed": len(regressed),
        "regressed_examples": regressed[:8],
        "verdict": ("KEEP (+%d, 0 regressions)" % len(gained))
        if keep
        else ("REVERT (%d regressions: %s...)" % (len(regressed), regressed[:3])),
    }


# ---------------------------------------------------------------------------
# 3. Cross-branch contradiction detector + exemption registry
# ---------------------------------------------------------------------------
def find_cross_branch_contradictions(report_path: Path) -> list[dict]:
    """The real IMPOSSIBLE class: the SAME logical test (same name) across DIFFERENT
    branches asserts CONFLICTING expected output for an identical invocation. No single
    binary can satisfy both -> proof-backed ceiling (amber/html-to-markdown class)."""
    data = json.loads(report_path.read_text(encoding="utf-8"))
    results = data.get("test_results", data if isinstance(data, list) else [])
    by_name: dict[str, dict[str, str]] = {}
    for t in results:
        if t.get("status") in ("passed",):
            continue
        name = t.get("name", "")
        branch = t.get("branch", "?")
        ex = t.get("extra", {})
        txt = (ex.get("text", "") if isinstance(ex, dict) else "") or ""
        m = re.search(r"==\s+(['\"].+?['\"])", txt)  # the expected literal
        exp = m.group(1) if m else None
        if not exp:
            continue
        by_name.setdefault(name, {})[branch] = exp
    contradictions = []
    for name, perbranch in by_name.items():
        exps = set(perbranch.values())
        if len(exps) > 1:
            contradictions.append(
                {"test": name, "branches": perbranch, "distinct_expected": sorted(exps)[:4]}
            )
    return contradictions


@dataclass
class Exemption:
    tool: str
    test: str  # or '*' for whole-tool
    kind: str  # upstream-skip | cross-branch-contradiction | harness-limit
    proof: str  # what was verified
    ceiling: str  # e.g. "416/419" or "N/A"
    recorded: str  # ISO date
    re_adjudicate_after: str  # ISO date -- exemptions are periodically re-challenged


def record_exemption(e: Exemption) -> None:
    """Append a proof-backed exemption. Exemptions are the ONLY legitimate non-fixes,
    and each carries a proof + a re-adjudication date (no permanent 'impossible')."""
    data = []
    if EXEMPTIONS.exists():
        try:
            data = json.loads(EXEMPTIONS.read_text(encoding="utf-8"))
        except Exception:
            data = []
    data.append(asdict(e))
    EXEMPTIONS.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. compile.sh / conftest GAMING SCANNER
# ---------------------------------------------------------------------------
# Detects gaming the override-scan regex MISSES: subprocess output-injection
# (fabricating stdout/stderr so an assertion passes), golden writes done via
# shutil.copy (not write_text), and results.xml FAILURE editing. Does NOT flag
# the legit append-only bidir mirror (it only clones PASSING testcases; never
# touches <failure>). A tool flagged here is NOT a legitimate lock until cleaned.
_GAMING_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "output_injection_CompletedProcess",
        re.compile(r"CompletedProcess\s*\("),
    ),  # construct a fake subprocess result
    (
        "output_injection_run_monkeypatch",
        re.compile(r"(?:subprocess|_sp|sp)\.(?:run|Popen)\s*=\s*\w"),
    ),  # replace run/Popen with a patched fn
    ("output_injection_check_output", re.compile(r"(?:subprocess|_sp|sp)\.check_output\s*=\s*\w")),
    ("golden_write_text", re.compile(r"write_text\([^)]*golden|golden[^\n]{0,40}\.write_text\(")),
    (
        "golden_copy",  # shutil.copy(out, golden) -- evades override-scan
        re.compile(r"(?:shutil\.)?copy2?\([^)]*golden[^)]*\)"),
    ),
    ("golden_open_w", re.compile(r"open\([^)]*golden[^)]*['\"][wa]")),
    ("expected_write", re.compile(r"expected[^\n]{0,30}\.write|write_text\([^)]*expected")),
    (
        "results_xml_failure_edit",
        re.compile(
            r"results?\.xml[\s\S]{0,300}?(?:remove\([^)]*(?:failure|testcase)|del\s[^\n]*testcase|\.remove\([^)]*tc)"
        ),
    ),
    ("skip_injection_dynamic", re.compile(r"add_marker\([^)]*skip|item\.add_marker\([^)]*skip")),
]


def scan_text_for_gaming(text: str) -> list[dict]:
    """Return list of {category, line, evidence} gaming hits in a compile.sh/conftest text."""
    hits = []
    for cat, pat in _GAMING_PATTERNS:
        for m in pat.finditer(text or ""):
            ln = text.count("\n", 0, m.start()) + 1
            seg = text[m.start() : m.start() + 120].splitlines()[0].strip()
            hits.append({"category": cat, "line": ln, "evidence": seg})
    return hits


def _compile_sh_text(path: Path) -> str:
    """Read compile.sh text from a dir (per_tool_overrides/<iid>/), a tarball, or a file."""
    import tarfile

    if path.is_dir():
        cs = path / "compile.sh"
        return cs.read_text(encoding="utf-8", errors="replace") if cs.exists() else ""
    if path.suffix in (".gz", ".tgz") or path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as tf:
            n = next((m for m in tf.getnames() if m.endswith("compile.sh")), None)
            f = tf.extractfile(n) if n else None
            return f.read().decode("utf-8", "replace") if f else ""
    return path.read_text(encoding="utf-8", errors="replace")


def scan_gaming_path(path: Path) -> dict:
    text = _compile_sh_text(path)
    hits = scan_text_for_gaming(text)
    return {"path": str(path), "clean": not hits, "hits": hits}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex PB integrity spine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify")
    c.add_argument("technique")
    c.add_argument("--transform", default="")
    k = sub.add_parser("keep-if-better")
    k.add_argument("before", type=Path)
    k.add_argument("after", type=Path)
    x = sub.add_parser("contradictions")
    x.add_argument("eval_report", type=Path)
    g = sub.add_parser("scan-gaming")
    g.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args()
    if args.cmd == "scan-gaming":
        any_dirty = False
        for p in args.paths:
            r = scan_gaming_path(p)
            tag = "CLEAN" if r["clean"] else f"GAMED ({len(r['hits'])})"
            print(f"{tag:14} {p.name if p.is_dir() else p}")
            for h in r["hits"]:
                print(f"   - {h['category']}  L{h['line']}: {h['evidence'][:90]}")
            any_dirty = any_dirty or not r["clean"]
        return 1 if any_dirty else 0
    if args.cmd == "classify":
        v = legitimacy_class(args.technique, args.transform)
        print(f"{args.technique}: {v.legitimacy}  train={v.train}\n  {v.reason}")
        return 0
    if args.cmd == "keep-if-better":
        r = keep_if_better(args.before, args.after)
        print(json.dumps(r, indent=2))
        return 0 if r["keep"] else 1
    if args.cmd == "contradictions":
        cs = find_cross_branch_contradictions(args.eval_report)
        print(f"cross-branch contradictions: {len(cs)}")
        for c in cs[:10]:
            print(f"  {c['test'][:60]} -> {c['distinct_expected']}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
