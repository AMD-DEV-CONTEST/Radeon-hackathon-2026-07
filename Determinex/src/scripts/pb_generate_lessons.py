#!/usr/bin/env python3
"""pb_generate_lessons.py — auto-draft lessons.md for locked tools from data.

60+ locked tools ship `lessons.md.stub` (empty), so RAG over the locked corpus
returns nothing. This drafts a first-pass `lessons.md` for each stub from data we
already have:
  - source/compile.sh  -> build command, eval-entry wrapper form, inline `# vN:`
                          and `# Decision N:` post-mortem comment blocks
  - eval_report.json   -> final passed/total/score
Drafts are marked `auto_generated: true` in front-matter so a human can promote
them. By default only stubs are drafted; --force overwrites real lessons too.

Usage:
    python scripts/pb_generate_lessons.py --dry-run
    python scripts/pb_generate_lessons.py            # write drafts for stubs only
    python scripts/pb_generate_lessons.py --tool oha
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"


def detect_lang(text: str) -> str:
    if "cargo build" in text:
        return "rust"
    if "go build" in text or "GOFLAGS" in text:
        return "go"
    if re.search(r"\bg\+\+\b", text) or ".cc" in text:
        return "cpp"
    if "make" in text or "cmake" in text:
        return "c"
    return "unknown"


def wrapper_form(text: str) -> str:
    if re.search(r'exec\s+-a\s+"executable"', text):
        return "exec -a (argv0=executable, clap usage name)"
    if "exec -a" in text:
        return "exec -a (preserve argv[0] for multicall/name dispatch)"
    if "ln -sf" in text or re.search(r"cp\s+\S+\s+\./executable", text):
        return "direct binary copy (binary inspected / streaming I/O)"
    if "exec /usr/local/bin" in text:
        return "plain exec wrapper"
    return "unknown"


def extract_comment_blocks(text: str) -> list[str]:
    """Pull out multi-line `# ...` decision/version post-mortem blocks."""
    blocks: list[str] = []
    cur: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") and not s.startswith("#!"):
            body = s.lstrip("#").strip()
            if body and not set(body) <= {"-", "="}:
                cur.append(body)
        else:
            if len(cur) >= 2:
                blocks.append("\n".join(cur))
            cur = []
    if len(cur) >= 2:
        blocks.append("\n".join(cur))
    # Keep substantive blocks (those mentioning a decision/version/fix/test).
    keep = [
        b
        for b in blocks
        if re.search(r"decision|version|fix|test|branch|golden|rc=|panic|wrapper", b, re.I)
    ]
    return keep[:6]


def read_eval(d: Path) -> dict:
    ev = d / "eval_report.json"
    if not ev.is_file():
        return {}
    try:
        data = json.loads(ev.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return {
        "passed": data.get("passed"),
        "total": data.get("total"),
        "runnable_total": data.get("runnable_total") or data.get("runnable"),
        "score": data.get("score") or data.get("raw_score"),
    }


def draft(d: Path) -> str:
    cs = d / "source" / "compile.sh"
    text = cs.read_text(encoding="utf-8", errors="replace") if cs.is_file() else ""
    lang = detect_lang(text)
    wf = wrapper_form(text)
    ev = read_eval(d)
    blocks = extract_comment_blocks(text)

    score = ev.get("score")
    passed = ev.get("passed")
    rt = ev.get("runnable_total")
    headline = f"{passed}/{rt}" if passed is not None and rt else "100%"

    out = [
        "---",
        f"name: pb-locked-{d.name}-lessons",
        f"description: Auto-drafted post-mortem for {d.name} (lock {headline}). "
        f"Language: {lang}. Eval-entry: {wf}. Promote to a hand-authored lessons.md before publishing.",
        "type: lessons",
        "auto_generated: true",
        "---",
        "",
        f"# {d.name} — Lessons (auto-draft)",
        "",
        f"> Locked at **{headline}**"
        + (f" / score {score}" if score is not None else "")
        + f". Upstream language: **{lang}**. Eval entry point: **{wf}**.",
        "",
        "## Build recipe (from compile.sh)",
        "",
        "```sh",
    ]
    # Include just the build+install region (first ~25 non-conftest lines).
    body_lines = []
    for line in text.splitlines():
        if "pytest.ini" in line or "INI_DIR" in line:
            break
        body_lines.append(line)
    out += body_lines[:30]
    out += ["```", ""]

    if blocks:
        out.append("## Decisions recorded in compile.sh")
        out.append("")
        for i, b in enumerate(blocks, 1):
            first = b.splitlines()[0]
            out.append(f"### {i}. {first[:80]}")
            out.append("")
            out.append(b)
            out.append("")
    else:
        out.append("## Decisions")
        out.append("")
        out.append("_No inline decision blocks found in compile.sh; author manually._")
        out.append("")

    out += [
        "## Cluster transfer notes",
        "",
        f"- Build pattern is the canonical {lang} skeleton — see "
        "`docs/AGENTS_PROGRAMBENCH_STRATEGY.md` Section 1.",
        f"- Eval-entry form ({wf}) is reusable by same-class tools.",
        "",
        "## TODO (human)",
        "",
        "- Replace this auto-draft: add the single decision that closed the lock,",
        "  the hard discoveries, and the upstream build command used to adjudicate.",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite real lessons.md too")
    ap.add_argument("--tool", help="single tool only")
    args = ap.parse_args()

    written = 0
    skipped = 0
    for d in sorted(LOCKED.iterdir()):
        if not d.is_dir():
            continue
        if args.tool and d.name != args.tool:
            continue
        stub = d / "lessons.md.stub"
        real = d / "lessons.md"
        is_stub = stub.is_file() and not real.is_file()
        if real.is_file() and not args.force:
            skipped += 1
            continue
        if not is_stub and not args.force:
            skipped += 1
            continue
        content = draft(d)
        target = d / "lessons.md"
        if args.dry_run:
            print(f"[dry-run] would write {target} ({len(content)} chars)")
        else:
            target.write_text(content, encoding="utf-8", newline="\n")
            # Remove the stub marker now that a draft exists.
            if stub.is_file():
                stub.unlink()
            print(f"[wrote] {target}")
        written += 1

    print(f"\ndrafted: {written}, skipped (already authored): {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
