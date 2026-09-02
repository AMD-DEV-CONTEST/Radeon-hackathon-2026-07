#!/usr/bin/env python3
"""programbench_classify_family.py — pick the right family folder for a tool.

Given an instance_id (and optionally its eval JSON), surface the matching
families from corpus/programbench/families/wave1/. Used by sprint operators
to choose which family generator to run.

Usage:
    python scripts/programbench_classify_family.py yaa110__nomino.f892499
    python scripts/programbench_classify_family.py konradsz__igrep.aa75630 \\
        --eval-json T:/determinex-programbench/mass_run_v2_base/<iid>/<iid>.eval.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Heuristics: tool-name + test-module hints → family suggestions.
# Lower-cased substrings; first match wins for primary family, additional
# matches are listed as "also consider".

_TOOL_NAME_HINTS = {
    # File-system / renamers
    "nomino": ("file_renamers",),
    "rename": ("file_renamers",),
    "fd": ("file_renamers", "search_grep"),
    # Search / grep
    "rg": ("search_grep",),
    "ripgrep": ("search_grep",),
    "igrep": ("search_grep",),
    "amber": ("search_grep",),
    "ack": ("search_grep",),
    # Diff
    "diffr": ("text_diff",),
    "delta": ("text_diff",),
    "icdiff": ("text_diff",),
    # Formatters
    "fmt": ("formatters",),
    "prettier": ("formatters",),
    "black": ("formatters",),
    "shellharden": ("formatters",),
    "tailspin": ("formatters",),
    # Coreutils
    "tuc": ("shell_coreutils",),
    "cut": ("shell_coreutils",),
    "csview": ("shell_coreutils", "csv_table"),
    "dutree": ("shell_coreutils",),
    "pls": ("shell_coreutils",),
    "rhit": ("shell_coreutils",),
    "disk-usage": ("shell_coreutils",),
    # Git wrappers
    "git-": ("git_wrappers",),
    "clog": ("git_wrappers",),
    # Wave 2
    "jq": ("json_yaml_toml",),
    "yq": ("json_yaml_toml",),
    "yj": ("json_yaml_toml",),
    "json": ("json_yaml_toml",),
    "yaml": ("json_yaml_toml",),
    "toml": ("json_yaml_toml",),
    "csv": ("csv_table",),
    "sed": ("regex_tools",),
    "sd": ("regex_tools",),
    "lz4": ("archive_compression",),
    "zstd": ("archive_compression",),
    "tar": ("archive_compression",),
    "zip": ("archive_compression",),
    "curl": ("network_http",),
    "curlie": ("network_http",),
    "httpie": ("network_http",),
    "xh": ("network_http",),
    "skeema": ("database",),
    "direnv": ("config_env",),
    "fzf": ("tui_terminal",),
    # Wave 3
    "tex": ("latex_document", "formatters"),
    "svd": ("codegen",),
    "genact": ("animation_output",),
    "hyperfine": ("benchmark_timing",),
    "cheat": ("editor_integrated",),
    "ripsecrets": ("security_scanner",),
    "trufflehog": ("security_scanner",),
    # Round 2 hints (from bulk-gen unclassified list)
    "html-to-markdown": ("json_yaml_toml",),
    "errcheck": ("formatters",),  # Go linter
    "dupl": ("security_scanner",),  # code-duplication detector
    "eva": ("rust_cli",),  # calculator
    "proj": ("rust_cli",),  # geospatial projection
    "elfcat": ("rust_cli",),  # ELF viewer
    "xcp": ("shell_coreutils",),  # cp alternative
    "ascii-image-converter": ("formatters",),
    "wrapcheck": ("formatters",),  # Go linter
    "code-minimap": ("formatters",),  # code visualization
    "halite": ("rust_cli",),  # game/util
    "keifu": ("rust_cli",),  # unknown but Rust
}

# Test-module substrings that strongly indicate a family
_TEST_MODULE_HINTS = {
    "test_placeholder": "file_renamers",
    "test_rename": "file_renamers",
    "test_tui_": "search_grep",
    "test_search": "search_grep",
    "test_type_list": "search_grep",
    "test_colors": "text_diff",
    "test_diffr": "text_diff",
    "test_line_numbers": "text_diff",
    "test_wrapping": "formatters",
    "test_indent_": "formatters",
    "test_format_subs": "formatters",
    "test_check_mode": "formatters",
    "test_fields": "shell_coreutils",
    "test_char_byte_line": "shell_coreutils",
    "test_delimiters": "shell_coreutils",
    "test_json": "json_yaml_toml",
    "test_yaml": "json_yaml_toml",
    "test_toml": "json_yaml_toml",
    "test_csv": "csv_table",
    "test_regex": "regex_tools",
    "test_compress": "archive_compression",
    "test_archive": "archive_compression",
    "test_http": "network_http",
    "test_request": "network_http",
    "test_sql": "database",
    "test_database": "database",
    "test_env_": "config_env",
    "test_module": "animation_output",  # genact-style
    "test_benchmark": "benchmark_timing",
    "test_timing": "benchmark_timing",
    "test_editor": "editor_integrated",
    "test_secret": "security_scanner",
    "test_credential": "security_scanner",
    # NOTE: removed test_harvest hint — too generic (appears in many tools'
    # test suites unrelated to git). The git-trim hint comes from the tool-name
    # match "git-" or "clog" — not from generic test_harvest signal.
}

# Language guess from tool name patterns (used only as supplemental signal)
_LANG_HINTS = {
    "_rs": "rust_cli",
    "rust": "rust_cli",
    "_go": "go_cli",
    "_py": "python_cli",
    "_js": "node_cli",
}


def _classify_by_name(tool_name: str) -> list[str]:
    name = tool_name.lower()
    out: list[str] = []
    for sub, fams in _TOOL_NAME_HINTS.items():
        if sub in name:
            for f in fams:
                if f not in out:
                    out.append(f)
    return out


def _classify_by_tests(eval_json: Path) -> list[tuple[str, int]]:
    """Returns family suggestions ranked by count of matching test-module hits."""
    counts: Counter = Counter()
    try:
        d = json.loads(Path(eval_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    for t in d.get("test_results", []) or []:
        nm = str(t.get("name", "")).lower()
        for needle, fam in _TEST_MODULE_HINTS.items():
            if needle in nm:
                counts[fam] += 1
    return counts.most_common()


def _classify_by_lang(instance_id: str) -> str | None:
    name = instance_id.lower()
    for sub, fam in _LANG_HINTS.items():
        if sub in name:
            return fam
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify a ProgramBench instance into family folders")
    ap.add_argument("instance_id", help="e.g. yaa110__nomino.f892499")
    ap.add_argument(
        "--eval-json",
        type=Path,
        default=None,
        help="optional eval JSON path for test-module-based signals",
    )
    args = ap.parse_args()

    # Derive tool name: everything after '__' up to '.'
    m = re.match(r"^[^_]+__([^.]+)\.[^.]+$", args.instance_id)
    tool = m.group(1) if m else args.instance_id

    by_name = _classify_by_name(tool)
    by_lang = _classify_by_lang(args.instance_id)
    by_test = _classify_by_tests(args.eval_json) if args.eval_json else []

    # Compose: primary = first by_name OR top by_test; supplemental = rest
    primary: str | None = None
    if by_name:
        primary = by_name[0]
    elif by_test:
        primary = by_test[0][0]
    elif by_lang:
        primary = by_lang

    seen = set()
    rec: list[str] = []
    for f in by_name + ([by_lang] if by_lang else []):
        if f and f not in seen:
            seen.add(f)
            rec.append(f)
    for f, _n in by_test:
        if f not in seen:
            seen.add(f)
            rec.append(f)

    print(f"instance_id: {args.instance_id}")
    print(f"tool_name:   {tool}")
    print()
    print(f"primary family:    {primary or '(unknown)'}")
    if rec[1:]:
        print(f"also consider:     {', '.join(rec[1:])}")
    if by_test:
        print()
        print("test-module signals:")
        for fam, n in by_test[:5]:
            print(f"  {n:>4}  {fam}")
    if not primary:
        print()
        print("No family matched. Likely a NEW family — copy _template/ to wave2/<new_family>/")
    else:
        print()
        print(f"→ Family file: corpus/programbench/families/wave1/{primary}/FAMILY.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
