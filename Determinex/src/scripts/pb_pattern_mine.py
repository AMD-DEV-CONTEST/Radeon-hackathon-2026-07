#!/usr/bin/env python3
"""pb_pattern_mine.py — mine common compile.sh patterns across locked tools.

Reads every `corpus/programbench/locked/<tool>/source/compile.sh`, detects the
upstream language from the build command, and reports the dominant build command,
eval-entry-point (./executable) wrapper form, and conftest boilerplate presence
per language. Output drives `pb_compile_template.py` defaults and lessons drafts.

Read-only. Never edits the corpus.

Usage:
    python scripts/pb_pattern_mine.py
    python scripts/pb_pattern_mine.py --json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"


def detect_lang(text: str) -> str:
    if "cargo build" in text:
        return "rust"
    if "go build" in text or "GOFLAGS" in text:
        return "go"
    if re.search(r"\bg\+\+\b", text) or ".cc" in text or ".cpp" in text:
        return "cpp"
    if "make" in text or "cmake" in text or "./configure" in text:
        return "c"
    return "unknown"


def wrapper_form(text: str) -> str:
    # Inspect the heredoc / copy that produces ./executable.
    if re.search(r"exec\s+-a\s+\"executable\"", text):
        return "exec-a-named-executable"
    if "exec -a" in text:
        return "exec-a-argv0"
    if re.search(r"cp\s+\S+\s+\./executable", text) or "ln -sf" in text:
        return "copy-binary"
    if re.search(r"exec\s+/usr/local/bin", text):
        return "plain-exec"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    by_lang: dict[str, list[str]] = defaultdict(list)
    wrappers: dict[str, Counter] = defaultdict(Counter)
    shebangs: dict[str, Counter] = defaultdict(Counter)
    conftest_dual = 0
    cap400 = 0
    total = 0

    for d in sorted(LOCKED.iterdir()):
        cs = d / "source" / "compile.sh"
        if not cs.is_file():
            continue
        total += 1
        text = cs.read_text(encoding="utf-8", errors="replace")
        lang = detect_lang(text)
        by_lang[lang].append(d.name)
        wrappers[lang][wrapper_form(text)] += 1
        first = text.splitlines()[0] if text.splitlines() else ""
        shebangs[lang][first.strip()] += 1
        if "/workspace/eval" in text and "/workspace" in text:
            conftest_dual += 1
        if "del items[400:]" in text:
            cap400 += 1

    report = {
        "total_locked_with_compile": total,
        "by_language": {k: sorted(v) for k, v in by_lang.items()},
        "language_counts": {k: len(v) for k, v in by_lang.items()},
        "wrapper_forms_by_language": {k: dict(v) for k, v in wrappers.items()},
        "shebangs_by_language": {k: dict(v) for k, v in shebangs.items()},
        "conftest_written_to_both_dirs": conftest_dual,
        "items_capped_at_400": cap400,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Locked tools with compile.sh: {total}\n")
    for lang in sorted(report["language_counts"], key=lambda k: -report["language_counts"][k]):
        cnt = report["language_counts"][lang]
        print(f"=== {lang.upper()} ({cnt}) ===")
        print(f"  tools: {', '.join(by_lang[lang])}")
        print(f"  wrapper forms: {dict(wrappers[lang])}")
        print(f"  shebangs: {dict(shebangs[lang])}")
        print()
    print(f"conftest written to both /workspace and /workspace/eval: {conftest_dual}/{total}")
    print(f"item cap (del items[400:]) present: {cap400}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
