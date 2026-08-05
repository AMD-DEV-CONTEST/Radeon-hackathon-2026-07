#!/usr/bin/env python3
"""
ProgramBench Behavioral Signature Extractor (Layer 1).

Analyzes locked tools to extract behavioral signatures for corpus-aware repair routing.
Signatures are stored at corpus/programbench/behavior_signatures/{slug}.json.

Usage:
  python scripts/pb_corpus_behavior.py --all
  python scripts/pb_corpus_behavior.py --tool jq
  python scripts/pb_corpus_behavior.py --all --force   # re-extract even if signature exists
"""

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

LOCKED_DIR = Path("corpus/programbench/locked")
SIG_DIR = Path("corpus/programbench/behavior_signatures")
BOARD_PATH = Path("logs/programbench_lock_board.json")

# Language detection: patterns in compile.sh that identify the language
LANG_PATTERNS: list[tuple[str, str]] = [
    (r"cargo\s+build", "rust"),
    (r"go\s+build|go\s+install|GOPATH", "go"),
    (r"g\+\+\s+-|clang\+\+\s+-|cmake|CMakeLists", "cpp"),
    (r"\bgcc\s+-o\b|\bclang\s+-o\b", "c"),
    (r"mvn\s+|gradlew|\.java\b", "java"),
    (r"python3?\s+setup\.py|pip\s+install\s+\.", "python"),
    (r"npm\s+run\s+build|yarn\s+build|tsc\s+", "typescript"),
    (r"gem\s+build|bundle\s+exec", "ruby"),
    (r"crystal\s+build", "crystal"),
    (r"stack\s+build|cabal\s+build", "haskell"),
    (r"zig\s+build", "zig"),
    (r"make\b", "c"),  # generic make fallback — typically C/C++
]

BUILD_PATTERNS: list[tuple[str, str]] = [
    (r"cargo\s+build", "cargo"),
    (r"\bgo\s+build\b|\bgo\s+install\b", "go"),
    (r"cmake", "cmake"),
    (r"mvn\b|\.mvnw\b", "maven"),
    (r"gradlew?\b", "gradle"),
    (r"make\b", "make"),
    (r"pip\s+install\s+\.", "pip"),
    (r"npm\s+run\s+build|yarn\s+build", "npm"),
    (r"gcc\b|g\+\+\b|clang\b", "cc"),
]

WRAPPER_PATTERNS: list[tuple[str, str]] = [
    (r"exec\s+-a\s+.+\$0", "exec-a"),
    (r"exec\s+/usr/local/bin", "direct"),
    (r"argv0|argv\[0\]|\$0\b.*argv", "argv-capture"),
    (r"python3?\s+-c|python3?\s+.*\.py", "python-wrapper"),
]

BEHAVIORAL_TAGS_MAP: list[tuple[str, list[str]]] = [
    # Tag -> keywords that suggest it (in slug, binary name, or test names)
    ("json-processor", ["json", "jq", "yq", "xq", "fx", "jless", "htmlq"]),
    ("yaml-processor", ["yaml", "yq"]),
    ("xml-processor", ["xml", "xq", "htmlq"]),
    ("html-processor", ["html", "htmlq"]),
    (
        "text-transform",
        ["sed", "awk", "tr", "transform", "replace", "rename", "nomino", "srgn", "rumdl"],
    ),
    ("regex-engine", ["regex", "grex", "grep", "rg", "ripgrep"]),
    ("file-searcher", ["find", "fd", "ripgrep", "rg", "search", "glob"]),
    (
        "code-linter",
        ["lint", "check", "format", "fmt", "shellharden", "deadnix", "rumdl", "markuplint"],
    ),
    ("code-formatter", ["format", "fmt", "prettier", "tex-fmt", "black"]),
    ("http-client", ["http", "curl", "wget", "muffet", "curlie", "oha", "rewrk"]),
    ("compression", ["zip", "zstd", "lz4", "gz", "tar", "compress"]),
    ("hash-tool", ["hash", "md5", "sha", "blake", "ripsecrets"]),
    ("terminal-utility", ["terminal", "tui", "cmatrix", "genact", "term", "pager", "tmux"]),
    ("git-tool", ["git", "delta", "gitui", "lazygit", "ghq"]),
    ("build-tool", ["build", "make", "cargo", "gradle", "cmake"]),
    ("document-converter", ["doc", "convert", "doxygen", "pandoc", "html2md", "markdown"]),
    ("image-processor", ["image", "ascii-image", "img", "png", "jpg", "svg"]),
    ("data-viewer", ["csv", "tsv", "table", "csview", "xsv", "vd", "viewer"]),
    ("file-manager", ["ranger", "walk", "broot", "fm", "file-manager"]),
    ("network-tool", ["net", "ping", "pingu", "gping", "network", "ip", "dns"]),
    ("log-analyzer", ["log", "angle-grinder", "ag", "lnav", "tailspin"]),
    ("benchmark-tool", ["bench", "hyperfine", "oha", "rewrk", "perf"]),
    ("code-counter", ["count", "lines", "wc", "scc", "cloc", "tokei"]),
    ("shell-tool", ["shell", "bash", "sh", "zsh", "fish", "entr", "zoxide"]),
    ("version-manager", ["version", "semver", "bump"]),
    ("secret-scanner", ["secret", "ripsecrets", "trufflehog", "gitleaks"]),
]


def detect_language(compile_sh: str) -> str:
    for pattern, lang in LANG_PATTERNS:
        if re.search(pattern, compile_sh, re.IGNORECASE):
            return lang
    return "unknown"


def detect_build_system(compile_sh: str) -> str:
    for pattern, build in BUILD_PATTERNS:
        if re.search(pattern, compile_sh, re.IGNORECASE):
            return build
    return "unknown"


def detect_binary_name(compile_sh: str, slug: str) -> str:
    # Look for "cp .../binary /usr/local/bin/NAME"
    m = re.search(r"cp\s+[^\s]+\s+/usr/local/bin/([^\s\n]+)", compile_sh)
    if m:
        return m.group(1).strip()
    # Look for "chmod +x /usr/local/bin/NAME"
    m = re.search(r"chmod\s+\+x\s+/usr/local/bin/([^\s\n]+)", compile_sh)
    if m:
        return m.group(1).strip()
    # Fall back to slug's tool portion
    return slug.split("__")[-1] if "__" in slug else slug


def detect_wrapper_pattern(compile_sh: str) -> str:
    # Look specifically at the executable block
    exec_block_m = re.search(r"cat\s*>\s*\S*executable.*?EXEC_EOF", compile_sh, re.DOTALL)
    exec_block = exec_block_m.group(0) if exec_block_m else compile_sh
    for pattern, name in WRAPPER_PATTERNS:
        if re.search(pattern, exec_block, re.IGNORECASE):
            return name
    return "direct"


def extract_executable_block(compile_sh: str) -> str:
    m = re.search(r"(cat\s*>\s*\S*executable\s*<<'EXEC_EOF'.*?EXEC_EOF)", compile_sh, re.DOTALL)
    if m:
        return m.group(1)
    return ""


def extract_test_categories(eval_report: dict) -> list[str]:
    results = eval_report.get("test_results", [])
    modules: set[str] = set()
    for r in results:
        test_id = r.get("test", "")
        if not test_id:
            continue
        # test_id like "eval.tests.test_output_format.test_basic" → "test_output_format"
        parts = test_id.split(".")
        for part in parts:
            if part.startswith("test_") and not part.startswith("test_"):
                pass
            if re.match(r"test_[a-z]", part) and "_" in part:
                modules.add(part)
                break
    return sorted(modules)


def infer_behavioral_tags(slug: str, binary_name: str, test_categories: list[str]) -> list[str]:
    combined = (slug + " " + binary_name + " " + " ".join(test_categories)).lower()
    tags: list[str] = []
    for tag, keywords in BEHAVIORAL_TAGS_MAP:
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return sorted(set(tags))


def build_signature(tool_dir: Path, board_entry: dict) -> dict[str, Any]:
    slug = board_entry["base_slug"]

    # Read compile.sh from tarball
    compile_sh = ""
    tf_path = tool_dir / "submission.tar.gz"
    if tf_path.exists():
        try:
            with tarfile.open(tf_path, "r:gz") as tf:
                names = tf.getnames()
                sh_name = next((n for n in names if n.endswith("compile.sh")), None)
                if sh_name:
                    compile_sh = tf.extractfile(sh_name).read().decode("utf-8", errors="replace")
        except Exception as e:
            compile_sh = f"# ERROR: {e}"

    # Read eval_report
    eval_report: dict = {}
    rpt_path = tool_dir / "eval_report.json"
    if rpt_path.exists():
        try:
            eval_report = json.loads(rpt_path.read_bytes().decode("utf-8", errors="replace"))
        except Exception:
            pass

    language = detect_language(compile_sh)
    build_system = detect_build_system(compile_sh)
    binary_name = detect_binary_name(compile_sh, slug)
    wrapper_pattern = detect_wrapper_pattern(compile_sh)
    executable_block = extract_executable_block(compile_sh)
    test_categories = extract_test_categories(eval_report)
    behavioral_tags = infer_behavioral_tags(slug, binary_name, test_categories)

    results = eval_report.get("test_results", [])
    passing = sum(1 for r in results if r.get("status") == "passed")
    total = len(results)

    return {
        "slug": slug,
        "tool_name": binary_name,
        "language": language,
        "build_system": build_system,
        "binary_name": binary_name,
        "wrapper_pattern": wrapper_pattern,
        "executable_block": executable_block,
        "test_categories": test_categories,
        "behavioral_tags": behavioral_tags,
        "passing_tests": passing,
        "total_tests": total,
        "locked": board_entry.get("locked_archive", False),
        "official_full_suite_resolved": board_entry.get("official_full_suite_resolved", False),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract behavioral signatures for locked PB tools"
    )
    parser.add_argument("--all", action="store_true", help="Process all locked tools")
    parser.add_argument("--tool", type=str, help="Process a specific tool by short name")
    parser.add_argument("--force", action="store_true", help="Re-extract even if signature exists")
    args = parser.parse_args()

    SIG_DIR.mkdir(parents=True, exist_ok=True)

    board = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    locked = [e for e in board if e.get("locked_archive")]

    if args.tool:
        locked = [e for e in locked if args.tool in e["base_slug"]]
        if not locked:
            print(f"No locked tool matching '{args.tool}'")
            sys.exit(1)

    if not args.all and not args.tool:
        parser.print_help()
        sys.exit(1)

    produced = 0
    for entry in locked:
        slug = entry["base_slug"]
        out_path = SIG_DIR / f"{slug}.json"
        if out_path.exists() and not args.force:
            print(f"  SKIP {slug} (signature exists, use --force to re-extract)")
            continue

        tool_name = slug.split("__")[-1] if "__" in slug else slug
        tool_dir = LOCKED_DIR / tool_name
        if not tool_dir.exists():
            print(f"  MISSING locked dir: {tool_dir}")
            continue

        sig = build_signature(tool_dir, entry)
        out_path.write_text(json.dumps(sig, indent=2))
        produced += 1
        print(
            f"  OK {slug}: lang={sig['language']} build={sig['build_system']} tags={sig['behavioral_tags'][:3]}..."
        )

    print(f"\nProduced {produced} signatures in {SIG_DIR}/")


if __name__ == "__main__":
    main()
