#!/usr/bin/env python3
"""Corpus Knowledge Extractor — pulls reusable patterns from high-scoring
tools (locked + ≥70%) into a tagged snippet library that future scaffold
generation can draw from.

Self-improvement loop:
  1. As tools improve (lock, near-lock), extract WHAT made them work.
  2. Tag each snippet by failure cluster it solves and language/family.
  3. Future generation looks up snippets matching predicted failure clusters.

Outputs:
  - corpus/programbench/_snippets/<bucket>.py — snippet per failure bucket
  - corpus/programbench/_snippets/registry.json — index: bucket -> [{tool, snippet_id, lang, family}]
  - corpus/programbench/_snippets/transferable_patterns.md — human-readable lookup

Inputs:
  - corpus/programbench/per_tool_overrides/<tool>/main.py — hand-tuned overrides
  - T:/determinex-programbench eval.json files for scoring
  - c:/tmp/per_tool_failures.json for buckets each tool addresses

Run: python scripts/analysis/corpus_knowledge_extractor.py
"""

from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
PER_TOOL_FAIL = Path("c:/tmp/per_tool_failures.json")
OUT_DIR = ROOT / "corpus" / "programbench" / "_snippets"
PB_TASKS = Path("c:/tmp/pb_tasks_200.tsv")


def load_eval_scores():
    """tool_key -> pct (latest eval)."""
    latest = {}
    for p in glob.glob(str(EVAL_ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        pp = Path(p)
        tool = pp.parent.name
        mt = pp.stat().st_mtime
        if tool not in latest or mt > latest[tool][0]:
            latest[tool] = (mt, pp)
    scores = {}
    for tool, (_, ej) in latest.items():
        try:
            j = json.loads(ej.read_text(encoding="utf-8"))
            r = j.get("test_results") or []
            p = sum(1 for x in r if x.get("status") == "passed")
            t = len(r)
            if t > 0:
                scores[tool] = round(100.0 * p / t, 2)
        except Exception:
            pass
    return scores


def load_tool_failures():
    try:
        return json.loads(PER_TOOL_FAIL.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_task_meta():
    """slug -> {lang, tests, frontier_pct}."""
    meta = {}
    if not PB_TASKS.is_file():
        return meta
    with PB_TASKS.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            _, instance_short, lang, _, tests, frontier_pct = parts[:6]
            slug = instance_short.lower().replace("/", "__")
            meta[slug] = {"lang": lang, "tests": int(tests), "frontier_pct": float(frontier_pct)}
    return meta


def find_handler_blocks(main_py: str) -> dict[str, str]:
    """Heuristically extract reusable handler blocks from a main.py.

    Returns dict of pattern_name -> code block.
    Patterns we look for (regex-anchored on common shapes):
      - sigpipe_handler: `signal.signal(signal.SIGPIPE, ...)`
      - no_args_rc2:     `if not argv: ... sys.exit(2)`
      - help_rc0:        `if '--help' in argv ... sys.exit(0)`
      - version_rc0:     `if argv[0] in ("--version", "-V")...`
      - sigpipe_except:  `except BrokenPipeError:`
      - jsonout:         `print(json.dumps(...))`
      - empty_input:     `if not lst:` / `if not data:`
      - utf8_io:         `sys.stdout.reconfigure(encoding='utf-8'`
      - argparse_setup:  `parser = argparse.ArgumentParser`
      - ansi_color:      `\\x1b[` or `"colorama"` usage
    """
    found = {}
    if re.search(r"signal\.signal\(\s*signal\.SIGPIPE", main_py):
        m = re.search(r"(?ms)(\bsignal\.signal\(\s*signal\.SIGPIPE[^\n]*\n)", main_py)
        if m:
            found["sigpipe_signal"] = m.group(1).strip()
    if re.search(r"except\s+BrokenPipeError", main_py):
        m = re.search(r"(?ms)(except\s+BrokenPipeError[^\n]*:.*?(?=\n\S|\Z))", main_py)
        if m:
            found["sigpipe_except"] = m.group(1).strip()
    if re.search(r"if\s+not\s+argv\s*:[\s\S]{0,200}sys\.exit\s*\(\s*2", main_py):
        m = re.search(r"(?ms)(if\s+not\s+argv\s*:.*?sys\.exit\s*\(\s*2\s*\))", main_py)
        if m:
            found["no_args_rc2"] = m.group(1).strip()
    if re.search(r"['\"]--help['\"][\s\S]{0,150}sys\.exit\s*\(\s*0", main_py):
        m = re.search(r"(?ms)(if\s+[^\n]*--help[^\n]*\n.*?sys\.exit\s*\(\s*0\s*\))", main_py)
        if m:
            found["help_rc0"] = m.group(1).strip()
    if re.search(r"['\"]--version['\"]", main_py):
        m = re.search(r"(?ms)(if\s+[^\n]*--version[^\n]*\n.*?sys\.exit\s*\(\s*0\s*\))", main_py)
        if m:
            found["version_rc0"] = m.group(1).strip()
    if "json.dumps" in main_py:
        found["json_output"] = "print(json.dumps(result, indent=2))"
    if "argparse" in main_py:
        found["argparse_setup"] = "(uses argparse — see source)"
    if re.search(r"sys\.stdout\.reconfigure\s*\(\s*encoding\s*=", main_py):
        found["utf8_reconfigure"] = "sys.stdout.reconfigure(encoding='utf-8', errors='replace')"
    if re.search(r"\\x1b\[|colorama|ansi", main_py, re.IGNORECASE):
        found["ansi_output"] = "(produces ANSI color codes — see source)"
    return found


def primary_bucket_solved(tool: str, fails: dict) -> str:
    """If a tool has 0 or few failures in a bucket vs many in others, that bucket
    is one it 'solved' relative to peers."""
    f = fails.get(tool, {})
    bs = f.get("top_buckets", [])
    if not bs:
        return "n/a"
    # The lowest-count bucket among the top-5 is closest to "solved"
    return f"primary_remaining:{bs[0][0]}"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    scores = load_eval_scores()
    fails = load_tool_failures()
    meta = load_task_meta()

    # Snippet library: bucket -> list of source records
    library = defaultdict(list)
    # All extracted snippets — one file per bucket with provenance
    extracted_by_bucket = defaultdict(list)

    # Tier 1: per-tool overrides (these were intentionally hand-tuned)
    override_records = []
    if OVERRIDES.is_dir():
        for sub in sorted(OVERRIDES.iterdir()):
            if not sub.is_dir():
                continue
            mp = sub / "main.py"
            if not mp.is_file():
                continue
            tool = sub.name
            slug = tool.rsplit(".", 1)[0] if "." in tool else tool
            content = mp.read_text(encoding="utf-8", errors="replace")
            score = scores.get(tool, 0.0)
            tool_meta = meta.get(slug, {})
            handlers = find_handler_blocks(content)
            record = {
                "tool": tool,
                "slug": slug,
                "lang": tool_meta.get("lang", "?"),
                "tests": tool_meta.get("tests", 0),
                "our_pct": score,
                "frontier_pct": tool_meta.get("frontier_pct"),
                "handlers": list(handlers.keys()),
                "primary_failure_bucket": primary_bucket_solved(tool, fails),
                "override_lines": content.count("\n"),
            }
            override_records.append(record)
            # Each handler the tool has is "transferable knowledge" if score is good
            if score >= 30 or len(handlers) > 0:
                for hname, hsnippet in handlers.items():
                    extracted_by_bucket[hname].append(
                        {
                            "tool": tool,
                            "slug": slug,
                            "lang": record["lang"],
                            "our_pct": score,
                            "snippet": hsnippet,
                        }
                    )

    # Tier 2: high-scoring tools without overrides — also worth mining
    # (we don't have access to their full source code unless it's in a scaffold,
    # but we can record that they were "solved with default scaffold + X")
    high_scoring = []
    for tool, pct in sorted(scores.items(), key=lambda kv: -kv[1]):
        if pct >= 50:
            slug = tool.rsplit(".", 1)[0] if "." in tool else tool
            high_scoring.append(
                {
                    "tool": tool,
                    "slug": slug,
                    "our_pct": pct,
                    "lang": meta.get(slug, {}).get("lang", "?"),
                    "frontier_pct": meta.get(slug, {}).get("frontier_pct"),
                }
            )

    # Write per-bucket snippet files
    for bucket, items in extracted_by_bucket.items():
        out_path = OUT_DIR / f"{bucket}.md"
        lines = [f"# Snippet bucket: `{bucket}`", ""]
        lines.append(
            f"Extracted from {len(items)} tool override(s). Higher-scoring tools' versions are preferred for reuse."
        )
        lines.append("")
        for r in sorted(items, key=lambda x: -x["our_pct"]):
            lines.append(f"## {r['tool']}  ({r['lang']}, {r['our_pct']}%)")
            lines.append("```python")
            lines.append(r["snippet"])
            lines.append("```")
            lines.append("")
        out_path.write_text("\n".join(lines), encoding="utf-8")

    # Write registry.json
    registry = {
        "buckets": {
            b: [
                {"tool": r["tool"], "slug": r["slug"], "lang": r["lang"], "our_pct": r["our_pct"]}
                for r in items
            ]
            for b, items in extracted_by_bucket.items()
        },
        "override_records": override_records,
        "high_scoring_tools": high_scoring,
    }
    (OUT_DIR / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")

    # Write human-readable transferable_patterns.md
    md = [
        "# Transferable Patterns — Corpus Knowledge Index",
        "",
        "Auto-generated by `scripts/analysis/corpus_knowledge_extractor.py`.",
        "",
        "## Snippet buckets available",
        "",
        "| Bucket | # tools mined | Available languages |",
        "|--------|--------------:|---------------------|",
    ]
    for b, items in sorted(extracted_by_bucket.items(), key=lambda kv: -len(kv[1])):
        langs = sorted({r["lang"] for r in items})
        md.append(f"| `{b}` | {len(items)} | {', '.join(langs)} |")

    md.append("")
    md.append("## High-scoring tools (knowledge sources)")
    md.append("")
    md.append("| score | tool | lang | frontier % | gap to frontier |")
    md.append("|------:|------|------|------:|------:|")
    for r in high_scoring[:30]:
        fp = r.get("frontier_pct") or 0
        gap = r["our_pct"] - fp
        md.append(f"| {r['our_pct']} | {r['tool']} | {r['lang']} | {fp} | {gap:+.1f} |")

    md.append("")
    md.append("## Override records")
    md.append("")
    md.append("| tool | lang | our % | handlers extracted |")
    md.append("|------|------|------:|--------------------|")
    for r in sorted(override_records, key=lambda x: -x["our_pct"]):
        md.append(
            f"| {r['tool']} | {r['lang']} | {r['our_pct']} | {', '.join(r['handlers']) or '-'} |"
        )

    md.append("")
    md.append("## How to use these snippets when generating a new scaffold")
    md.append("")
    md.append(
        "1. Predict failure buckets the new tool will hit (by family + language + test count)."
    )
    md.append("2. Look up `_snippets/<bucket>.md` for prior winning snippets.")
    md.append("3. Prefer snippets from the highest-scoring same-language tool.")
    md.append("4. Compose into new scaffold's `main.py`.")
    md.append(
        "5. After eval, run `corpus_knowledge_extractor.py` again to add the new tool's contributions."
    )

    (OUT_DIR / "transferable_patterns.md").write_text("\n".join(md), encoding="utf-8")

    print(f"Wrote {OUT_DIR}/transferable_patterns.md")
    print(f"Wrote {OUT_DIR}/registry.json")
    print(f"Wrote {len(extracted_by_bucket)} per-bucket snippet files")
    print()
    print("=== summary ===")
    print(f"  Tool overrides scanned: {len(override_records)}")
    print(f"  Snippet buckets populated: {len(extracted_by_bucket)}")
    print(f"  High-scoring tools (>=50%): {len(high_scoring)}")
    print()
    print("=== buckets by tool count ===")
    for b, items in sorted(extracted_by_bucket.items(), key=lambda kv: -len(kv[1])):
        print(f"  {b:<28} {len(items):3} tools  ({', '.join(sorted({r['lang'] for r in items}))})")


if __name__ == "__main__":
    main()
