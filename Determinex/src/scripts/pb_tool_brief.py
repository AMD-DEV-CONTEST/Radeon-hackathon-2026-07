#!/usr/bin/env python3
"""Generate a one-page artifact-first ProgramBench tool brief."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BEST_INDEX = ROOT / "corpus" / "programbench" / "best_known_state.json"
PATTERNS = ROOT / "corpus" / "programbench" / "cross_tool_patterns.md"
HANDBACK = ROOT / "docs" / "campaign" / "CODEX_HANDBACK.md"
VERDICT_CORPUS = ROOT / "corpus" / "programbench" / "training_corpus" / "pb_verdict_corpus.jsonl"
LOCKED = ROOT / "corpus" / "programbench" / "locked"


def load_index(path: Path = BEST_INDEX) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{path} does not exist; run scripts/pb_best_state_index.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_tool(name: str, index: dict[str, Any]) -> str:
    tools = index.get("tools", {})
    if name in tools:
        return name
    needle = name.lower()
    matches = []
    for slug, row in tools.items():
        candidates = [slug] + list(row.get("aliases") or [])
        candidates.extend([c.split(".")[0] for c in candidates])
        if any(needle == c.lower() or needle in c.lower() for c in candidates):
            matches.append(slug)
    if not matches:
        raise SystemExit(f"tool not found in best_known_state: {name}")
    matches.sort(key=lambda s: (len(s), s))
    return matches[0]


def read_text(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit and len(text) > limit:
        return text[-limit:]
    return text


def matching_sections(text: str, needles: list[str], *, max_sections: int = 4) -> list[str]:
    if not text:
        return []
    sections = re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)
    hits = []
    for section in sections:
        low = section.lower()
        if any(n.lower() in low for n in needles if n):
            hits.append(section.strip())
        if len(hits) >= max_sections:
            break
    return hits


def tail_matching_lines(
    path: Path, needles: list[str], *, max_lines: int = 8, bytes_to_read: int = 3_000_000
) -> list[str]:
    if not path.exists():
        return []
    with path.open("rb") as f:
        try:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - bytes_to_read))
        except OSError:
            pass
        text = f.read().decode("utf-8", errors="replace")
    hits = []
    for line in text.splitlines():
        low = line.lower()
        if any(n.lower() in low for n in needles if n):
            hits.append(line[:500])
        if len(hits) >= max_lines:
            break
    return hits


def infer_language(paths: list[str]) -> str:
    markers_from_dirs: list[str] = []
    for raw in paths:
        path = ROOT / raw if not Path(raw).is_absolute() else Path(raw)
        if path.is_dir():
            for child in list(path.rglob("*"))[:400]:
                if child.is_file():
                    try:
                        markers_from_dirs.append(child.name)
                    except OSError:
                        pass
        elif path.exists():
            markers_from_dirs.append(path.name)
    joined = " ".join(paths + markers_from_dirs).lower()
    suffix_map = [
        ("rust", [".rs", "cargo.toml"]),
        ("go", [".go", "go.mod"]),
        ("python", [".py", "setup.py", "pyproject.toml"]),
        ("c-cpp", [".c", ".cc", ".cpp", "makefile", "cmakelists.txt"]),
        ("javascript", [".js", ".ts", "package.json"]),
    ]
    for lang, markers in suffix_map:
        if any(m in joined for m in markers):
            return lang
    return "unknown"


def collect_path_hints(row: dict[str, Any]) -> list[str]:
    paths = []
    for key in ("best_report", "best_tarball", "best_overrides"):
        if row.get(key):
            paths.append(str(row[key]))
    for state in row.get("state_lineage") or []:
        if state.get("path"):
            paths.append(str(state["path"]))
    return paths


def nearest_locked(
    tool: str, row: dict[str, Any], index: dict[str, Any], limit: int = 3
) -> list[dict[str, Any]]:
    lang = infer_language(collect_path_hints(row))
    candidates = []
    for slug, other in index.get("tools", {}).items():
        if slug == tool or other.get("eval_index_status") != "strict_lock":
            continue
        other_lang = infer_language(collect_path_hints(other))
        score = 0
        if lang != "unknown" and other_lang == lang:
            score += 3
        if other.get("best_overrides"):
            score += 1
        if other.get("best_tarball"):
            score += 1
        if score == 0:
            continue
        locked_dir = LOCKED / slug
        candidates.append(
            {
                "tool": slug,
                "language": other_lang,
                "score": score,
                "locked_dir": str(locked_dir.relative_to(ROOT)) if locked_dir.exists() else None,
                "best_report": other.get("best_report"),
                "best_overrides": other.get("best_overrides"),
                "best_tarball": other.get("best_tarball"),
            }
        )
    candidates.sort(key=lambda r: (-r["score"], r["tool"]))
    return candidates[:limit]


def brief(tool: str, index: dict[str, Any]) -> str:
    slug = resolve_tool(tool, index)
    row = index["tools"][slug]
    failure_ids = row.get("failing_test_ids") or []
    needles = [slug, slug.split(".")[0], str(row.get("best_report") or "")]
    for state in row.get("state_lineage") or []:
        if state.get("failure_class"):
            needles.append(str(state["failure_class"]))
        for sig in state.get("pattern_signatures") or []:
            needles.append(str(sig))

    patterns = matching_sections(read_text(PATTERNS), needles)
    handback_hits = tail_matching_lines(HANDBACK, needles, max_lines=10)
    verdict_hits = tail_matching_lines(VERDICT_CORPUS, needles, max_lines=6)
    nearby = nearest_locked(slug, row, index)

    lines = [
        f"# ProgramBench Tool Brief - {slug}",
        "",
        "## Seed State",
        "",
        f"- best_report: `{row.get('best_report')}`",
        f"- best_tarball: `{row.get('best_tarball')}`",
        f"- best_overrides: `{row.get('best_overrides')}`",
        f"- score: `{row.get('passed')}/{row.get('total')}`",
        f"- delta_to_lock: `{row.get('delta_to_lock')}`",
        f"- failed/errors/skipped/not_run: `{row.get('failed')}/{row.get('errors')}/{row.get('skipped')}/{row.get('not_run')}`",
        "",
        "## Delta To Work",
        "",
    ]
    for test_id in failure_ids[:20]:
        lines.append(f"- `{test_id}`")
    if len(failure_ids) > 20:
        lines.append(
            f"- ... {len(failure_ids) - 20} more failing/nonpassing ids in best_known_state"
        )
    if not failure_ids:
        lines.append("- none listed")

    lines.extend(["", "## Matching Patterns", ""])
    if patterns:
        for section in patterns[:3]:
            title = section.splitlines()[0]
            lines.append(f"- {title}")
    else:
        lines.append("- no direct pattern section hit")

    lines.extend(["", "## Prior Diagnoses", ""])
    if handback_hits:
        for hit in handback_hits[:8]:
            lines.append(f"- {hit}")
    else:
        lines.append("- no recent handback hit")

    lines.extend(["", "## Verdict Corpus Hints", ""])
    if verdict_hits:
        for hit in verdict_hits[:6]:
            lines.append(f"- {hit}")
    else:
        lines.append("- no bounded corpus-tail hit")

    lines.extend(["", "## Nearest Locked Recipes", ""])
    if nearby:
        for item in nearby:
            lines.append(
                f"- `{item['tool']}` lang `{item['language']}` report `{item['best_report']}` overrides `{item['best_overrides']}`"
            )
    else:
        lines.append("- no nearby locked recipe found from current index")

    lines.extend(
        [
            "",
            "## Required Next Action",
            "",
            "- Restore the best-known tarball/overrides above before any eval.",
            "- Work only the listed delta; if a pattern applies, fix the pattern once and rerun all matching tools.",
            "- New reports go through `scripts/pb_eval_conveyor.py`; count changes still require Section 5 guards.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool")
    parser.add_argument("--index", default=str(BEST_INDEX))
    parser.add_argument("--out", help="Write markdown brief to this path instead of stdout.")
    args = parser.parse_args()

    text = brief(args.tool, load_index(Path(args.index)))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(out)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
