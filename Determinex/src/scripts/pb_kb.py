#!/usr/bin/env python3
"""
pb_kb.py — ProgramBench Knowledge Base aggregator.

Reads all corpus/programbench/locked/*/lessons.md files and builds a searchable
index of: cluster-transfer notes, hard discoveries, architecture patterns, and
known failure→fix mappings.

Usage:
    python scripts/pb_kb.py                    # rebuild index
    python scripts/pb_kb.py search <term>      # search the KB
    python scripts/pb_kb.py patterns           # list all known failure patterns
    python scripts/pb_kb.py tool <slug>        # show lessons for one tool
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
LOCKED_DIR = REPO / "corpus" / "programbench" / "locked"
KB_PATH = REPO / "logs" / "pb_kb.json"

# Known failure pattern signatures → fix recipe
PATTERN_SIGNATURES = {
    "version_string_ldflags": {
        "description": "Binary outputs 'dev'/'unknown' but golden expects pinned version string.",
        "signals": ["version dev", "GitVersion:  dev", 'version = "dev"', "GitVersion:  unknown"],
        "fix": (
            "Inject version via Go ldflags with FULL module import path (not 'main'). "
            "1. Get module from go.mod (e.g. 'github.com/Foo/bar/v2'). "
            "2. Get subdir of main package (e.g. './cli/mytool/'). "
            "3. PKG=module/subdir/path. "
            "4. go build -ldflags='-X ${PKG}.version=X.Y.Z -X ${PKG}.commit=SHA -X ${PKG}.date=DATE'. "
            "Find expected values in testdata/TestExecute/*/stdout.golden or goldens dir. "
            "WARN: -X main.version does NOT work for subdirectory main packages in modules."
        ),
        "example_tools": ["johanneskaufmann__html-to-markdown"],
    },
    "bin_name_argv0": {
        "description": "Error messages say 'executable:' but golden expects the real binary name.",
        "signals": ["executable: invalid option", "exec -a", "argv[0]", "bin_name"],
        "fix": (
            'Use exec -a "<toolname>" in the executable wrapper so argv[0] matches what '
            "the binary uses in error messages. OR if tool reads argv[0] dynamically at "
            "runtime, set it to match the upstream binary name."
        ),
        "example_tools": ["entr", "jq"],
    },
    "rc_unknown_option": {
        "description": "Tool exits rc=2 for unknown options but tests expect rc=1 (or vice versa).",
        "signals": ["returncode == 2", "exit code 2", "rc=2", "rc_2_unknown_option"],
        "fix": (
            "Check what rc the REAL upstream binary returns for unknown options. "
            "Usually clap-based Rust tools return rc=2. Do NOT change universally — "
            "probe both values across all branches before patching."
        ),
        "example_tools": ["skeema"],
    },
    "version_prefix_vN": {
        "description": "Tests expect version like '1.2.3' but binary outputs 'v1.2.3' (or vice versa).",
        "signals": ["v1.", "v2.", "assert version ==", "version strip", "lstrip('v')"],
        "fix": (
            "Strip or add 'v' prefix in the version output. Either patch the binary build "
            "or add a sed/awk filter in the executable wrapper: "
            'output=$(./binary --version); echo "${output#v}"'
        ),
        "example_tools": [],
    },
    "missing_default_wordlist": {
        "description": "Tool needs a default wordlist/data file that isn't in PATH or expected location.",
        "signals": ["No such file or directory", "wordlist", "dictionary", "data file not found"],
        "fix": (
            "Bundle the default data file in the submission tarball and copy it to the "
            "expected location in compile.sh (e.g., /usr/share/<tool>/, /etc/<tool>/)."
        ),
        "example_tools": [],
    },
    "is_a_directory_error": {
        "description": "Tool receives a directory path and prints 'Is a directory' to stderr.",
        "signals": ["Is a directory", "EISDIR"],
        "fix": (
            "Add a directory check in the executable wrapper or source. "
            "If the upstream binary would print 'Is a directory', replicate that behavior."
        ),
        "example_tools": [],
    },
    "env_bash_path_strip": {
        "description": "#!/usr/bin/env bash shebang fails because PATH is stripped in PB containers.",
        "signals": ["env: bash: No such file", "/usr/bin/env bash", "PATH-strip"],
        "fix": (
            "Use #!/bin/bash directly, OR ensure /usr/bin/env exists and bash is in PATH. "
            "In compile.sh, add: ln -sf /bin/bash /usr/local/bin/bash 2>/dev/null || true"
        ),
        "example_tools": [],
    },
    "tty_interactive_timeout": {
        "description": "Tool blocks waiting for TTY/interactive input, tests time out.",
        "signals": ["timeout", "TIMEOUT", "blocking", "stdin", "--no-interactive", "-y"],
        "fix": (
            'Detect TTY in wrapper: [ -t 0 ] && exec binary "$@" || exec binary --no-interactive -y "$@". '
            "Or pass appropriate non-interactive flags. Check if --no-interactive requires -y "
            "separately to auto-accept (amber pattern)."
        ),
        "example_tools": ["dalance__amber"],
    },
}


def load_lessons(tool_dir: Path) -> dict:
    """Parse a lessons.md file into structured sections."""
    lessons_path = tool_dir / "lessons.md"
    if not lessons_path.exists():
        return {}

    text = lessons_path.read_text(encoding="utf-8", errors="replace")
    result = {"tool": tool_dir.name, "raw": text, "sections": {}}

    current_section = "preamble"
    current_lines = []

    for line in text.splitlines():
        if line.startswith("## "):
            result["sections"][current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip().lower().replace(" ", "_")
            current_lines = []
        else:
            current_lines.append(line)

    result["sections"][current_section] = "\n".join(current_lines).strip()
    return result


def build_kb() -> dict:
    """Build the full knowledge base from all locked tool lessons.md files."""
    kb = {
        "tools": {},
        "patterns": PATTERN_SIGNATURES,
        "cluster_notes": [],
        "hard_discoveries": [],
    }

    for tool_dir in sorted(LOCKED_DIR.iterdir()):
        if not tool_dir.is_dir() or tool_dir.name == "README.md":
            continue
        lessons = load_lessons(tool_dir)
        if not lessons:
            continue

        kb["tools"][tool_dir.name] = {
            "sections": lessons.get("sections", {}),
        }

        # Extract cluster transfer notes for global aggregation
        cluster = lessons.get("sections", {}).get("cluster_transfer_notes", "")
        if cluster:
            kb["cluster_notes"].append({"tool": tool_dir.name, "notes": cluster})

        hard = lessons.get("sections", {}).get("hard_discoveries", "")
        if hard:
            kb["hard_discoveries"].append({"tool": tool_dir.name, "discoveries": hard})

    return kb


def search_kb(kb: dict, term: str) -> list[dict]:
    """Search all lessons content for a term. Returns list of hits with tool + excerpt."""
    term_lower = term.lower()
    hits = []

    for tool_name, data in kb["tools"].items():
        for section_name, content in data["sections"].items():
            if term_lower in content.lower():
                # Find the matching line(s)
                lines = content.splitlines()
                matching = [l for l in lines if term_lower in l.lower()]
                hits.append(
                    {
                        "tool": tool_name,
                        "section": section_name,
                        "matches": matching[:3],
                    }
                )

    return hits


def match_pattern(failure_text: str) -> list[dict]:
    """Given a failure traceback, return matching known patterns."""
    text_lower = failure_text.lower()
    matches = []
    for pattern_id, pattern in PATTERN_SIGNATURES.items():
        score = sum(1 for sig in pattern["signals"] if sig.lower() in text_lower)
        if score > 0:
            matches.append({"pattern": pattern_id, "score": score, **pattern})
    return sorted(matches, key=lambda x: -x["score"])


def cmd_build(_args):
    kb = build_kb()
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")
    tool_count = len(kb["tools"])
    cluster_count = len(kb["cluster_notes"])
    print(f"KB built: {tool_count} tools, {cluster_count} with cluster notes -> {KB_PATH}")


def cmd_search(args):
    if not KB_PATH.exists():
        print("KB not built yet. Run: python scripts/pb_kb.py first.")
        sys.exit(1)
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    term = " ".join(args)
    hits = search_kb(kb, term)
    if not hits:
        print(f"No results for: {term!r}")
        return
    print(f"Found {len(hits)} hit(s) for {term!r}:\n")
    for h in hits[:20]:
        print(f"  [{h['tool']}] §{h['section']}")
        for m in h["matches"]:
            print(f"    {m.strip()}")
        print()


def cmd_patterns(_args):
    for pid, p in PATTERN_SIGNATURES.items():
        print(f"\n[{pid}]")
        print(f"  {p['description']}")
        print(f"  Signals: {', '.join(p['signals'][:3])}")
        print(f"  Fix: {p['fix'][:120]}...")


def cmd_tool(args):
    if not KB_PATH.exists():
        print("KB not built yet. Run: python scripts/pb_kb.py first.")
        sys.exit(1)
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    tool = args[0] if args else ""
    # fuzzy match
    matches = [k for k in kb["tools"] if tool.lower() in k.lower()]
    if not matches:
        print(f"No tool matching {tool!r}")
        return
    for m in matches[:3]:
        print(f"\n=== {m} ===")
        for section, content in kb["tools"][m]["sections"].items():
            if content.strip():
                print(f"\n## {section}\n{content[:600]}")


def cmd_record(args):
    """Record a fix for a newly locked tool into the KB pattern index.

    Usage: python scripts/pb_kb.py record <tool_slug> <pattern_id> "<notes>"
    """
    if len(args) < 3:
        print("Usage: pb_kb.py record <tool> <pattern_id> <notes>")
        return
    tool, pattern_id, notes = args[0], args[1], " ".join(args[2:])
    if pattern_id not in PATTERN_SIGNATURES:
        print(f"Unknown pattern {pattern_id!r}. Run 'patterns' to list.")
        return
    # Write a cluster note to the tool's lessons.md if it exists
    locked_path = LOCKED_DIR / tool.split(".")[0] / "lessons.md"
    if locked_path.exists():
        existing = locked_path.read_text(encoding="utf-8")
        if "Cluster transfer notes" not in existing:
            with locked_path.open("a", encoding="utf-8") as f:
                f.write(f"\n## Cluster transfer notes\n\n- Pattern: {pattern_id}\n- {notes}\n")
            print(f"Appended cluster note to {locked_path}")
    print(f"Recorded: {tool} -> pattern={pattern_id}")
    print("Rebuild KB with: python scripts/pb_kb.py build")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "build":
        cmd_build(args[1:])
    elif args[0] == "search":
        cmd_search(args[1:])
    elif args[0] == "patterns":
        cmd_patterns(args[1:])
    elif args[0] == "tool":
        cmd_tool(args[1:])
    elif args[0] == "record":
        cmd_record(args[1:])
    else:
        print(__doc__)
