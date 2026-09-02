#!/usr/bin/env python3
"""programbench_classify_subtype.py — deterministic family + subtype router.

Where the broad classifier was: tool_name + test_modules → family.
This module adds: family + tool_name + test_modules + flag_signature → subtype.

Subtype routing is DETERMINISTIC, not heuristic. The rules:
  1. Exact tool-name match in _SUBTYPE_TOOL_NAMES → that subtype (highest priority)
  2. Required-flag signature: subtype requires a CHARACTERISTIC flag pattern
     (e.g. `--max-depth` + walking-style names → du_tree)
  3. Test-module fingerprint: subtype-specific test module names
  4. Default: family root (no subtype, use the family's default behavior)

Returns a `Classification` with confidence + reasons. Callers downstream
(bulk-gen, smoke gate) decide whether to act on weak classifications.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from programbench_classify_family import (
    _classify_by_lang as _family_by_lang,
)
from programbench_classify_family import (  # type: ignore[import-not-found]
    _classify_by_name as _family_by_name,
)
from programbench_classify_family import (
    _classify_by_tests as _family_by_tests,
)


@dataclass(frozen=True)
class Classification:
    family: str | None
    subtype: str | None  # None = use family root behavior
    confidence: str  # "strong" | "moderate" | "weak" | "default"
    reasons: tuple[str, ...] = field(default_factory=tuple)


# ──────────────────────────────────────────────────────────────────────────
# Subtype routing — TOOL NAME match (highest authority)
# ──────────────────────────────────────────────────────────────────────────

_SUBTYPE_TOOL_NAMES: dict[str, str] = {
    # shell_coreutils variants
    "pls": "shell_coreutils.ls_listing",
    "exa": "shell_coreutils.ls_listing",
    "lsd": "shell_coreutils.ls_listing",
    "broot": "shell_coreutils.ls_listing",
    "parallel-disk-usage": "shell_coreutils.du_tree",
    "dust": "shell_coreutils.du_tree",
    "dua": "shell_coreutils.du_tree",
    "gdu": "shell_coreutils.du_tree",
    "ncdu": "shell_coreutils.du_tree",
    "rhit": "shell_coreutils.table_filter",
    "lnav": "shell_coreutils.table_filter",
    # search_grep variants
    "the_silver_searcher": "search_grep",  # default behavior is ag-style
    "ag": "search_grep",
    "amber": "search_grep",
    "igrep": "search_grep",
    "ripgrep": "search_grep",
    "rg": "search_grep",
    "srgn": "search_grep.code_rewriter",
    "sd": "search_grep.code_rewriter",
    "ruplacer": "search_grep.code_rewriter",
    # git_wrappers variants
    "git-trim": "git_wrappers",  # default = branch_cleanup
    "git-branchless": "git_wrappers",
    "git-graph": "git_wrappers.log_graph",
    "git-graph-rs": "git_wrappers.log_graph",
    "gitui": "git_wrappers.log_graph",
    "clog-cli": "git_wrappers.changelog_generator",
    "git-cliff": "git_wrappers.changelog_generator",
    "git-log": "git_wrappers.log_graph",
    # formatter subtype: linter (Go linters etc.)
    "errcheck": "formatters.linter",
    "wrapcheck": "formatters.linter",
    "dupl": "formatters.linter",
    # NEW deferred-list families fleshed out (sprint-4 audit)
    "seqtk": "biosequence",
    "ascii-image-converter": "image_terminal_render",
    "jp2a": "image_terminal_render",
    "chafa": "image_terminal_render",
    "pixterm": "image_terminal_render",
    "code-minimap": "image_terminal_render",
    "mdbook": "docs_static_site",
    "html-to-markdown": "html_converter",
    "elfcat": "binary_inspector",
    "halite": "game_simulator",
    "keifu": "game_simulator",
    # NOT routed to a subtype — these are family roots
    "nomino": "file_renamers",
    "tuc": "shell_coreutils",
    "diffr": "text_diff",
    "tex-fmt": "formatters",
}


# ──────────────────────────────────────────────────────────────────────────
# Subtype routing — REQUIRED-FLAG signature (deterministic)
# ──────────────────────────────────────────────────────────────────────────

# When the failing-test flag inventory shows ALL of these flags, route to this
# subtype. Used when tool name isn't in the explicit map but flags are
# characteristic.

_SUBTYPE_FLAG_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    # (subtype, required_flag_set)
    ("shell_coreutils.ls_listing", ("--long", "--all")),
    ("shell_coreutils.du_tree", ("--max-depth", "--human-readable")),
    ("shell_coreutils.table_filter", ("--lines", "--no-headers")),
    ("git_wrappers.log_graph", ("--graph", "--oneline")),
    ("git_wrappers.changelog_generator", ("--setversion",)),
    ("search_grep.code_rewriter", ("--literal-replacement", "--in-place")),
]


# ──────────────────────────────────────────────────────────────────────────
# Subtype routing — TEST-MODULE fingerprint (medium signal)
# ──────────────────────────────────────────────────────────────────────────

_SUBTYPE_TEST_MODULE_HINTS: dict[str, str] = {
    "test_listing": "shell_coreutils.ls_listing",
    "test_long_format": "shell_coreutils.ls_listing",
    "test_tree_output": "shell_coreutils.ls_listing",
    "test_directory_listing": "shell_coreutils.ls_listing",
    "test_disk_usage": "shell_coreutils.du_tree",
    "test_size_tree": "shell_coreutils.du_tree",
    "test_walker_depth": "shell_coreutils.du_tree",
    "test_log_aggregation": "shell_coreutils.table_filter",
    "test_nginx_log": "shell_coreutils.table_filter",
    "test_access_log": "shell_coreutils.table_filter",
    "test_log_graph": "git_wrappers.log_graph",
    "test_commit_tree": "git_wrappers.log_graph",
    "test_changelog": "git_wrappers.changelog_generator",
    "test_conventional_commits": "git_wrappers.changelog_generator",
    "test_replace": "search_grep.code_rewriter",
    "test_substitute": "search_grep.code_rewriter",
    "test_rewriter": "search_grep.code_rewriter",
}


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _tool_name(instance_id: str) -> str:
    m = re.match(r"^[^_]+__([^.]+)\.[^.]+$", instance_id)
    return m.group(1) if m else instance_id


_FLAG_RX = re.compile(r"(?<![\w/])--?[A-Za-z0-9][A-Za-z0-9_.-]*")


def _flags_from_eval(eval_json: Path | None) -> set[str]:
    if eval_json is None or not eval_json.is_file():
        return set()
    try:
        d = json.loads(eval_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    flags: set[str] = set()
    for r in d.get("test_results", []) or []:
        msg = str(r.get("extra", {}).get("message", "")) or ""
        for m in _FLAG_RX.findall(msg):
            if m not in {"--", "---"}:
                flags.add(m)
    return flags


def _test_modules_from_eval(eval_json: Path | None) -> Counter:
    counts: Counter = Counter()
    if eval_json is None or not eval_json.is_file():
        return counts
    try:
        d = json.loads(eval_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return counts
    for r in d.get("test_results", []) or []:
        nm = str(r.get("name", ""))
        parts = nm.split(".")
        if len(parts) >= 3:
            mod_leaf = parts[-2]  # tests.test_<X>.<test_func> → mod_leaf is test_<X>
            counts[mod_leaf] += 1
    return counts


# ──────────────────────────────────────────────────────────────────────────
# Main classification
# ──────────────────────────────────────────────────────────────────────────


def classify(instance_id: str, eval_json: Path | None = None) -> Classification:
    tool = _tool_name(instance_id)
    reasons: list[str] = []

    # Rule 1: explicit tool-name → subtype map
    if tool in _SUBTYPE_TOOL_NAMES:
        subtype = _SUBTYPE_TOOL_NAMES[tool]
        family = subtype.split(".", 1)[0]
        reasons.append(f"tool_name '{tool}' → {subtype}")
        return Classification(
            family=family,
            subtype=subtype if "." in subtype else None,
            confidence="strong",
            reasons=tuple(reasons),
        )

    # Rule 2: flag signature match
    flags = _flags_from_eval(eval_json)
    for sub, required in _SUBTYPE_FLAG_SIGNATURES:
        if all(f in flags for f in required):
            family = sub.split(".", 1)[0]
            reasons.append(f"flag-sig {required} → {sub}")
            return Classification(
                family=family, subtype=sub, confidence="moderate", reasons=tuple(reasons)
            )

    # Rule 3: test-module fingerprint
    test_mods = _test_modules_from_eval(eval_json)
    for mod, sub in _SUBTYPE_TEST_MODULE_HINTS.items():
        if mod in test_mods and test_mods[mod] >= 3:
            family = sub.split(".", 1)[0]
            reasons.append(f"test_module '{mod}' ({test_mods[mod]} hits) → {sub}")
            return Classification(
                family=family, subtype=sub, confidence="moderate", reasons=tuple(reasons)
            )

    # Rule 4: fall back to broad-family classifier (no subtype)
    fam_by_name = _family_by_name(tool)
    fam_by_test = _family_by_tests(eval_json) if eval_json else []
    fam_by_lang = _family_by_lang(instance_id)
    family: str | None = None
    if fam_by_name:
        family = fam_by_name[0]
        reasons.append(f"broad-family tool_name → {family}")
    elif fam_by_test:
        family = fam_by_test[0][0]
        reasons.append(f"broad-family test-module → {family}")
    elif fam_by_lang:
        family = fam_by_lang
        reasons.append(f"broad-family language → {family}")
    if family:
        return Classification(
            family=family, subtype=None, confidence="default", reasons=tuple(reasons)
        )

    return Classification(
        family=None, subtype=None, confidence="weak", reasons=("no signal matched",)
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Classify a ProgramBench instance into family + subtype"
    )
    ap.add_argument("instance_id")
    ap.add_argument("--eval-json", type=Path, default=None)
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    cls = classify(args.instance_id, args.eval_json)

    if args.json:
        print(
            json.dumps(
                {
                    "instance_id": args.instance_id,
                    "family": cls.family,
                    "subtype": cls.subtype,
                    "confidence": cls.confidence,
                    "reasons": list(cls.reasons),
                },
                indent=2,
            )
        )
        return 0

    print(f"instance:    {args.instance_id}")
    print(f"tool:        {_tool_name(args.instance_id)}")
    print(f"family:      {cls.family or '(none)'}")
    print(f"subtype:     {cls.subtype or '(use family root)'}")
    print(f"confidence:  {cls.confidence}")
    print("reasons:")
    for r in cls.reasons:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
