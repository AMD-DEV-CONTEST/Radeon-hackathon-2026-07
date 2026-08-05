#!/usr/bin/env python3
"""
ProgramBench Behavioral Similarity Router (Layer 2).

Given a target tool slug and optional failing test categories, returns the N most
behaviorally similar locked tools from the corpus.

Similarity scoring:
  Same language:                     +3 points
  Overlapping behavioral_tags:       +2 per shared tag
  Overlapping test_category_prefixes:+1 per match
  Same build_system:                 +1 point

Usage:
  python scripts/pb_corpus_router.py --tool trdsql --top 3
  python scripts/pb_corpus_router.py --tool grex --failing-categories "test_regex,test_output"
  python scripts/pb_corpus_router.py --tool xcp --top 5 --json
"""

import argparse
import json
import sys
from pathlib import Path

SIG_DIR = Path("corpus/programbench/behavior_signatures")
LOCKED_DIR = Path("corpus/programbench/locked")
BOARD_PATH = Path("logs/programbench_lock_board.json")

# Slug-based tag hints for unknown tools — maps keywords in slug to behavioral tags
SLUG_TAG_HINTS: list[tuple[list[str], list[str]]] = [
    (["sql", "trdsql", "q "], ["json-processor", "data-viewer"]),
    (["json", "jq", "fx", "jless"], ["json-processor"]),
    (["yaml", "yq"], ["yaml-processor"]),
    (["xml", "xq", "htmlq", "html"], ["xml-processor", "html-processor"]),
    (["grep", "rg", "ripgrep", "regex", "grex", "ag", "ack"], ["regex-engine", "file-searcher"]),
    (["csv", "xsv", "tsv", "dsq", "csview"], ["data-viewer"]),
    (["git", "delta", "diff"], ["git-tool"]),
    (["http", "curl", "wget", "muffet"], ["http-client", "network-tool"]),
    (["log", "journal", "tail"], ["log-analyzer"]),
    (["zip", "zstd", "lz4", "compress"], ["compression"]),
    (["hash", "sha", "md5", "blake"], ["hash-tool"]),
    (["fmt", "format", "prettier", "lint", "check"], ["code-formatter", "code-linter"]),
    (["term", "tui", "tmux", "cmatrix"], ["terminal-utility"]),
    (["bench", "perf", "hyperfine"], ["benchmark-tool"]),
    (["image", "img", "ascii-image", "svg", "png"], ["image-processor"]),
    (["doc", "doxygen", "pandoc", "markdown"], ["document-converter"]),
    (["secret", "scan", "audit"], ["secret-scanner"]),
    (["shell", "bash", "sh", "zsh", "fish", "entr", "zoxide"], ["shell-tool"]),
    (["count", "loc", "cloc", "tokei", "scc"], ["code-counter"]),
]


def infer_tags_from_slug(slug: str) -> list[str]:
    slug_lower = slug.lower()
    tags: list[str] = []
    for keywords, tag_list in SLUG_TAG_HINTS:
        if any(kw in slug_lower for kw in keywords):
            tags.extend(tag_list)
    return sorted(set(tags))


def load_signatures() -> list[dict]:
    if not SIG_DIR.exists():
        return []
    sigs = []
    for p in sorted(SIG_DIR.glob("*.json")):
        try:
            sigs.append(json.loads(p.read_text()))
        except Exception:
            pass
    return sigs


def category_prefix(cat: str) -> str:
    """Return the semantic prefix of a test category name.

    E.g. 'test_output_format' → 'output'
         'test_flags_basic'   → 'flags'
         'test_sql_query'     → 'sql'
    """
    stripped = cat.removeprefix("test_")
    return stripped.split("_")[0] if "_" in stripped else stripped


def score_similarity(target: dict, candidate: dict) -> int:
    score = 0
    if target.get("language") and target["language"] == candidate.get("language"):
        score += 3
    if target.get("build_system") and target["build_system"] == candidate.get("build_system"):
        score += 1
    t_tags = set(target.get("behavioral_tags", []))
    c_tags = set(candidate.get("behavioral_tags", []))
    score += len(t_tags & c_tags) * 2
    t_prefixes = {category_prefix(cat) for cat in target.get("test_categories", [])}
    c_prefixes = {category_prefix(cat) for cat in candidate.get("test_categories", [])}
    score += len(t_prefixes & c_prefixes)
    return score


def build_target_profile(
    slug: str,
    failing_categories: list[str],
    language: str | None,
) -> dict:
    """Build a pseudo-signature for the target tool from available info."""
    board = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    entry = next((e for e in board if slug in e["base_slug"] or e["base_slug"] in slug), None)
    official_score = entry.get("official_score_pct", 0.0) if entry else 0.0
    official_not_run = entry.get("official_not_run", 0) if entry else 0

    # Check if we already have a signature (e.g. if it was recently locked)
    tool_name = slug.split("__")[-1] if "__" in slug else slug
    sig_path = SIG_DIR / f"{slug}.json"
    if not sig_path.exists():
        # Try partial match
        matches = list(SIG_DIR.glob(f"*{tool_name}*.json"))
        if matches:
            sig_path = matches[0]

    base_sig: dict = {}
    if sig_path.exists():
        base_sig = json.loads(sig_path.read_text())

    # Infer tags from slug if no base_sig available
    base_tags = base_sig.get("behavioral_tags", [])
    if not base_tags:
        base_tags = infer_tags_from_slug(slug)

    return {
        "slug": slug,
        "language": language or base_sig.get("language", "unknown"),
        "build_system": base_sig.get("build_system", "unknown"),
        "behavioral_tags": base_tags,
        "test_categories": failing_categories or base_sig.get("test_categories", []),
        "official_score_pct": official_score,
        "official_not_run": official_not_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Route repair context from similar locked tools")
    parser.add_argument("--tool", required=True, help="Target tool slug or short name")
    parser.add_argument("--top", type=int, default=3, help="Number of results to return")
    parser.add_argument(
        "--failing-categories",
        type=str,
        default="",
        help="Comma-separated failing test categories for better matching",
    )
    parser.add_argument("--language", type=str, help="Override language detection")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Output JSON")
    args = parser.parse_args()

    sigs = load_signatures()
    if not sigs:
        print("No signatures found. Run: python scripts/pb_corpus_behavior.py --all")
        sys.exit(1)

    failing_cats = [c.strip() for c in args.failing_categories.split(",") if c.strip()]
    target = build_target_profile(args.tool, failing_cats, args.language)

    # Score all candidates (exclude the target itself)
    scored = []
    for sig in sigs:
        if sig["slug"] == target["slug"]:
            continue
        s = score_similarity(target, sig)
        if s > 0:
            scored.append((s, sig))

    scored.sort(key=lambda x: -x[0])
    top = scored[: args.top]

    if args.json_out:
        out = {
            "target": target,
            "matches": [
                {
                    "score": score,
                    "slug": sig["slug"],
                    "language": sig["language"],
                    "build_system": sig["build_system"],
                    "behavioral_tags": sig["behavioral_tags"],
                    "test_categories": sig["test_categories"],
                    "wrapper_pattern": sig["wrapper_pattern"],
                    "compile_sh_path": str(LOCKED_DIR / sig["tool_name"] / "submission.tar.gz"),
                }
                for score, sig in top
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"Target: {target['slug']}")
        print(f"  Language: {target['language']}  Tags: {target['behavioral_tags']}")
        print(f"  Failing categories: {target['test_categories']}")
        print()
        print(f"Top {args.top} similar locked tools:")
        for i, (score, sig) in enumerate(top, 1):
            print(f"  {i}. [{score}pt] {sig['slug']}")
            print(f"       Language: {sig['language']}  Build: {sig['build_system']}")
            print(f"       Tags: {sig['behavioral_tags']}")
            print(f"       Categories: {sig['test_categories'][:5]}")
            print(f"       Wrapper: {sig['wrapper_pattern']}")
            compile_sh_path = LOCKED_DIR / sig["tool_name"] / "submission.tar.gz"
            print(f"       Submission: {compile_sh_path}")
            print()


if __name__ == "__main__":
    main()
