#!/usr/bin/env python3
"""Generate lock-gap guidance for paused high-value ProgramBench tools.

This is read-only infrastructure: it consumes official eval JSON artifacts and
writes a Markdown report that separates "more patching" from the rebuilds
needed to reach 100%.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Target:
    slug: str
    label: str
    eval_path: Path
    diagnosis: str
    rebuild: list[str]
    tripwires: list[str]


DEFAULT_TARGETS = [
    Target(
        slug="nachoparker__dutree.44e877d",
        label="dutree",
        eval_path=ROOT
        / ".determinex_staging/pb_dutree_iter9/nachoparker__dutree.44e877d/nachoparker__dutree.44e877d.eval.json",
        diagnosis=(
            "The failures are dominated by byte-exact directory tree output: "
            "directory totals, aggregation thresholds, depth pruning, hidden/exclude "
            "filtering, symlink accounting, LS_COLORS, and byte/KiB rendering all "
            "interact. The current implementation is close enough for shallow CLI "
            "tests but lacks an upstream-compatible filesystem accounting model."
        ),
        rebuild=[
            "Build a filesystem snapshot layer that records path type, apparent size, disk-usage size, symlink target size, hidden status, and deterministic child order before rendering.",
            "Port the aggregation model as a pure tree transform: depth cut, files-only, exclude/no-hidden filters, then small-file aggregation. Do not mix these rules into print code.",
            "Create one renderer that consumes annotated tree nodes and emits Unicode/ASCII, colorized/plain, bytes/human sizes from the same model.",
            "Add a local fixture replay harness that runs selected extracted `dutree` test resources against the override without editing tests.",
        ],
        tripwires=[
            "`-a` optional value parsing must not consume following flags.",
            "Official gate requires runnable stability; filesystem tests can become runnable/unrunnable if paths or permission behavior drift.",
            "Do not special-case single golden files; the same size model feeds most remaining failures.",
        ],
    ),
    Target(
        slug="wfxr__csview.8ac4de0",
        label="csview",
        eval_path=ROOT
        / ".determinex_staging/pb_csview_iter6/wfxr__csview.8ac4de0/wfxr__csview.8ac4de0.eval.json",
        diagnosis=(
            "The remaining failures are table byte-exactness and sniffing edge cases: "
            "style `grid`, `ascii2`, and `none`, header-only tables, wide emoji, "
            "sniff limit truncation, non-UTF8 byte offsets, and file-not-found text. "
            "The CSV parser mostly works; the ceiling is formatter parity."
        ),
        rebuild=[
            "Introduce a table-layout oracle object: parsed rows, display widths, padding policy, borders, numbering column, indentation, and style tokens.",
            "Replay every `eval/test_resources` golden for `grid`, `ascii2`, and `none` through the same renderer and diff bytes before official gates.",
            "Replace ad-hoc sniff logic with a deterministic 100-row/width sampler that keeps the same row subset the tests expect.",
            "Calculate UTF-8 parse errors from raw bytes so byte index reporting matches upstream instead of decoded string offsets.",
        ],
        tripwires=[
            "Unicode display width is not `len()`: emoji and CJK need wcwidth-style accounting.",
            "`style none` still has padding and separators; it is not raw CSV.",
            "Header-only and empty-input paths must share the renderer, not bypass it.",
        ],
    ),
    Target(
        slug="pemistahl__grex.fa3e8ed",
        label="grex",
        eval_path=ROOT
        / ".determinex_staging/pb_grex_iter12/pemistahl__grex.fa3e8ed/pemistahl__grex.fa3e8ed.eval.json",
        diagnosis=(
            "The large behavior swap is done. Remaining failures require a real regex "
            "expression tree: verbose nested repetition formatting, prefix/suffix "
            "factoring, char-class collapse, per-token colorization, stdin/file input "
            "ordering, and clap-style validation. String assembly is now the limiting "
            "factor."
        ),
        rebuild=[
            "Create AST node types: Literal, CharClass, Sequence, Alternation, Optional, Repeat, Anchor, FlagGroup, CaptureGroup.",
            "Make synthesis produce that AST first, then render normal, verbose, and colorized output from the same tree.",
            "Implement factoring passes on the AST: common prefix/suffix, single-character alternation to ranges, repeated substring detection, and optional branch collapse.",
            "Add a fixture replay command for `eval/test_resources/test_anchors_display`, `test_char_classes`, and repetition goldens before official gates.",
            "Move clap-style validation into a table-driven parser so `--with-surrogates`, zero minimums, and empty test cases share exact error text.",
        ],
        tripwires=[
            "Verbose mode indentation and color tokens must wrap syntax tokens, not whole strings.",
            "The same AST must render normal and colorized forms; separate string paths will keep diverging.",
            "Stdin/file collection order changes can pass some tests and regress many others.",
        ],
    ),
    Target(
        slug="junegunn__fzf.b56d614",
        label="fzf",
        eval_path=ROOT
        / ".determinex_staging/pb_fzf_iter3/junegunn__fzf.b56d614/junegunn__fzf.b56d614.eval.json",
        diagnosis=(
            "The accepted line is 742/1212. A later shell-integration patch "
            "would have raised passes, but it caused a pytest internal error and "
            "changed runnable tests by -151, so the gate correctly rejected it. "
            "The remaining accepted failures are mostly fuzzy/filter algorithm "
            "semantics, TUI/key rendering, and a smaller help/man/version surface."
        ),
        rebuild=[
            "Do not reapply the rejected --bash/--zsh/--fish implementation until runnable stability is understood; active source must stay at iter3.",
            "Build a pure filter-engine test harness first: parse fzf extended search syntax, OR groups, suffix/prefix anchors, quoted exact terms, nth fields, and scoring order.",
            "Separate non-interactive `-f/--filter` behavior from TUI rendering so algorithm fixes can gate without touching PTY branches.",
            "For shell integration, reproduce the pytest internal error locally and fix collection/runtime stability before attempting another official gate.",
            "Treat keybinding/border tests as a second renderer track after filter-engine gains flatten.",
        ],
        tripwires=[
            "Any patch that changes runnable total is reject-only even if passed count rises.",
            "Shell integration handlers can alter branch collection behavior; verify total/runnable before trusting pass deltas.",
            "Filter mode must return rc 0 with empty stdout for no selected lines only where upstream does; rc drift is common here.",
        ],
    ),
    Target(
        slug="sstadick__hck.b66c751",
        label="hck",
        eval_path=ROOT
        / ".determinex_staging/pb_hck_iter10d/sstadick__hck.b66c751/sstadick__hck.b66c751.eval.json",
        diagnosis=(
            "hck is now a near-lock tool at 775/856. The remaining failures are "
            "not broad recovery; they are cut-like semantics: delimiter literal "
            "handling, header/index ordering, duplicate and mixed selections, "
            "invalid field-spec errors, invalid UTF-8 byte passthrough, and a few "
            "compressed input/help exactness cases."
        ),
        rebuild=[
            "Replace remaining delimiter handling with a byte-oriented splitter that preserves leading/trailing empty fields and supports literal delimiter mode exactly.",
            "Represent selections as ordered selector nodes: field index, range, open range, header field, regex header, complement, and duplicates. Render from that list without dedup unless upstream does.",
            "Move field-spec validation before row processing so leading comma, trailing comma, double comma, zero, and inverted ranges produce exact rc/message.",
            "Keep invalid UTF-8 as bytes through selection and output; decode only for display paths that explicitly require text.",
            "Treat compression as an input adapter layer, not parser logic; xz/gzip/bzip2 errors should not corrupt normal stdin behavior.",
        ],
        tripwires=[
            "Do not normalize Unicode replacement characters on byte-mode tests.",
            "Header-field and numeric-field selection order must follow user selection order, not table order.",
            "Delimiter literal mode and regex delimiter mode need separate paths; merging them regresses comma/tab cases.",
        ],
    ),
]


def _message(test: dict[str, Any]) -> str:
    extra = test.get("extra") or {}
    return str(extra.get("message") or test.get("message") or "")


def _cluster_key(test_name: str, msg: str) -> str:
    hay = f"{test_name}\n{msg}".lower()
    if "help" in hay or "usage:" in hay:
        topic = "help/version exactness"
    elif "style_none" in hay or "style none" in hay:
        topic = "renderer/table exactness: style none"
    elif "ascii2" in hay:
        topic = "renderer/table exactness: ascii2"
    elif "grid" in hay:
        topic = "renderer/table exactness: grid"
    elif "sniff" in hay:
        topic = "sniff/windowing exactness"
    elif "utf" in hay or "byte index" in hay:
        topic = "encoding/error byte exactness"
    elif "color" in hay or "\\x1b" in msg:
        topic = "color/env exactness"
    elif "verbose" in hay or "(?x)" in msg:
        topic = "verbose renderer exactness"
    elif "repetition" in hay or "{" in msg:
        topic = "expression factoring/repetition"
    elif "fields" in hay or "aggr" in hay or "depth" in hay:
        topic = "argument/tree transform interaction"
    elif "ls_colors" in hay or "color" in hay:
        topic = "color/env exactness"
    elif "assert" in msg:
        topic = "stdout/stderr fixture exactness"
    else:
        topic = "other"
    first = re.sub(r"\s+", " ", msg.splitlines()[0] if msg else "").strip()
    return f"{topic} | {first[:100]}"


def load_eval(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def summarize_target(target: Target) -> dict[str, Any]:
    data = load_eval(target.eval_path)
    tests = data.get("test_results", [])
    passed = sum(1 for t in tests if t.get("status") == "passed")
    failed = [t for t in tests if t.get("status") == "failure"]
    skipped = sum(1 for t in tests if t.get("status") == "skipped")
    errored = sum(1 for t in tests if t.get("status") == "error")
    runnable = passed + len(failed) + errored
    clusters: Counter[str] = Counter()
    samples: dict[str, str] = {}
    by_topic: defaultdict[str, int] = defaultdict(int)
    for test in failed:
        name = str(test.get("name") or "")
        msg = _message(test)
        key = _cluster_key(name, msg)
        clusters[key] += 1
        samples.setdefault(key, name)
        by_topic[key.split(" | ", 1)[0]] += 1
    return {
        "target": target,
        "passed": passed,
        "failed": len(failed),
        "skipped": skipped,
        "errored": errored,
        "runnable": runnable,
        "total": len(tests),
        "score": (passed / runnable * 100.0) if runnable else 0.0,
        "clusters": clusters,
        "samples": samples,
        "by_topic": by_topic,
    }


def render_report(summaries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# ProgramBench Paused Tool 100% Lock Gap Report")
    lines.append("")
    lines.append(
        "Generated from official eval JSON artifacts. This report is guidance for post-lane work; it does not change scores."
    )
    lines.append("")
    lines.append("## Snapshot")
    lines.append("")
    lines.append("| Tool | Passed | Runnable | Score | Remaining Failures |")
    lines.append("|---|---:|---:|---:|---:|")
    for s in summaries:
        t: Target = s["target"]
        lines.append(
            f"| `{t.label}` | {s['passed']} | {s['runnable']} | {s['score']:.2f}% | {s['failed']} |"
        )
    lines.append("")
    lines.append("## Diagnosis")
    lines.append("")
    for s in summaries:
        t = s["target"]
        lines.append(f"### {t.label}")
        lines.append("")
        lines.append(t.diagnosis)
        lines.append("")
        lines.append("Top failure clusters:")
        lines.append("")
        for key, count in s["clusters"].most_common(10):
            sample = s["samples"][key]
            lines.append(f"- {count}x `{key}`")
            lines.append(f"  Sample: `{sample}`")
        lines.append("")
        lines.append("100% rebuild path:")
        lines.append("")
        for item in t.rebuild:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("Regression tripwires:")
        lines.append("")
        for item in t.tripwires:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## Shared Infrastructure Needed")
    lines.append("")
    lines.append(
        "- Add per-tool fixture replay commands before official Docker gates, using extracted tests under `T:/determinex-programbench/_extracted_tests/<slug>/...`."
    )
    lines.append(
        "- Keep official gate JSON as source of truth; local replay is only for fast byte-diff debugging."
    )
    lines.append(
        "- For each paused tool, replace one-off string emitters with a structured intermediate model, then render from that model."
    )
    lines.append(
        "- Before a new fzf shell-integration attempt, compare baseline and candidate `not_run`, `error`, `total`, and `runnable` counts locally; the prior rejected patch proved pass deltas can be misleading."
    )
    lines.append(
        "- For near-lock hck, keep patches narrow and byte-oriented; it is closer to 100 than the larger paused trio."
    )
    lines.append(
        "- Continue 4-lane Docker gating for remaining tools while these three get deeper hand-specialist rebuilds."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs/PROGRAMBENCH_PAUSED_TOOL_LOCK_GAP_REPORT.md"))
    args = ap.parse_args()
    summaries = [summarize_target(t) for t in DEFAULT_TARGETS]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(summaries), encoding="utf-8", newline="\n")
    print(out)
    for s in summaries:
        t = s["target"]
        print(
            f"{t.label}: {s['passed']}/{s['runnable']} = {s['score']:.2f}% ({s['failed']} failures)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
