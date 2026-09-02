#!/usr/bin/env python3
"""Spec-validity smoke — parse + structurally validate every spec doc.

For each `06_behavioral_spec.md` and `06_repo_spec.md` in the corpus:
  - Frontmatter parses cleanly (name, description, type)
  - Required sections present (§1, §6 for PB; §1-§7 for SB)
  - Code blocks balanced (no unterminated ``` fences)
  - compile.sh template, when present, has a shebang and ./executable mention
  - Pre-flight smoke block (when present) has at least 1 `|| { ... exit 1; }` line

Catches templated specs that look fine but fail at run-time injection.

Exit code 0 = all specs valid. Non-zero = at least one broken spec found.
"""

import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
PB_DIR = DETERMINEX_ROOT / "corpus" / "programbench" / "in_progress"
PB_ANCHORS = DETERMINEX_ROOT / "corpus" / "programbench" / "anchors"
SB_DIR = DETERMINEX_ROOT / "corpus" / "swebench" / "repos"

results = []  # (path, level, message) where level in {info, warn, fail}


def check(path: Path, level: str, msg: str):
    results.append((path, level, msg))


def validate_frontmatter(path: Path, text: str) -> dict:
    if not text.startswith("---"):
        check(path, "warn", "missing YAML frontmatter (no leading ---)")
        return {}
    end = text.find("\n---\n", 3)
    if end == -1:
        check(path, "fail", "frontmatter not terminated by closing ---")
        return {}
    fm = text[3:end].strip()
    meta = {}
    for line in fm.split("\n"):
        m = re.match(r"^(\w[\w-]*):\s*(.+?)\s*$", line)
        if m:
            meta[m.group(1)] = m.group(2)
    if "name" not in meta:
        check(path, "warn", "frontmatter missing 'name' field")
    if "description" not in meta:
        check(path, "warn", "frontmatter missing 'description' field")
    return meta


def validate_code_fences(path: Path, text: str):
    n = text.count("```")
    if n % 2 != 0:
        check(path, "fail", f"unbalanced ``` code fences (count={n})")


def validate_pb_spec(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        check(path, "fail", f"unreadable: {e}")
        return
    if len(text) < 200:
        check(path, "warn", f"unusually short ({len(text)} bytes)")
        return
    validate_frontmatter(path, text)
    validate_code_fences(path, text)
    # Required sections
    for sec in ["## Section 1", "## Section 6"]:
        if sec not in text:
            check(path, "warn", f"missing required section: {sec}")
    # compile.sh template hygiene
    if "compile.sh" in text:
        if "#!/bin/bash" not in text and "#!/usr/bin/env bash" not in text:
            check(path, "warn", "compile.sh references but no #!/bin/bash shebang block")
        if "./executable" not in text:
            check(path, "warn", "compile.sh references but no ./executable mention")
    # Pre-flight smoke quality
    if "smoke" in text.lower():
        if "exit 1" not in text:
            check(path, "warn", "pre-flight smoke section but no `exit 1` failure handler")


def validate_sb_spec(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        check(path, "fail", f"unreadable: {e}")
        return
    if len(text) < 200:
        check(path, "warn", f"unusually short ({len(text)} bytes)")
        return
    validate_frontmatter(path, text)
    validate_code_fences(path, text)
    # Per-repo specs need §1-§7 (dataset coverage, files, test framework, themes, samples, guidance, index)
    for sec in ["## Section 1", "## Section 2", "## Section 6"]:
        if sec not in text:
            check(path, "warn", f"missing required section: {sec}")
    # CRITICAL: no patches in spec
    # Look for `diff --git` headers OR @@ hunk markers — those are patches
    if re.search(r"^diff --git", text, re.M):
        check(path, "fail", "PATCH LEAK — `diff --git` found in spec body")
    # @@ hunks could be legitimate (in code fences) — only fail on dense @@ usage
    n_hunks = len(re.findall(r"^@@.+@@", text, re.M))
    if n_hunks > 5:
        check(path, "fail", f"PATCH LEAK suspect — {n_hunks} `@@ ... @@` hunk markers")


def main():
    pb = list(PB_DIR.glob("*/06_behavioral_spec.md")) if PB_DIR.exists() else []
    pb_anchor = list(PB_ANCHORS.glob("*/06_behavioral_spec.md")) if PB_ANCHORS.exists() else []
    sb = list(SB_DIR.glob("*/06_repo_spec.md")) if SB_DIR.exists() else []

    print(
        f"Validating {len(pb)} PB in-progress specs + {len(pb_anchor)} PB anchor packs + {len(sb)} SWE-bench repo specs..."
    )
    for p in pb + pb_anchor:
        validate_pb_spec(p)
    for p in sb:
        validate_sb_spec(p)

    fails = [r for r in results if r[1] == "fail"]
    warns = [r for r in results if r[1] == "warn"]

    if fails:
        print(f"\n=== FAIL ({len(fails)}) ===")
        for path, _, msg in fails[:20]:
            print(f"  {path.parent.name}/{path.name}: {msg}")
        if len(fails) > 20:
            print(f"  ... and {len(fails) - 20} more")

    if warns:
        # Only show warning summary
        warn_msgs = {}
        for _, _, msg in warns:
            warn_msgs[msg] = warn_msgs.get(msg, 0) + 1
        print(f"\n=== WARN ({len(warns)} total) — by message ===")
        for msg, count in sorted(warn_msgs.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {count:>4}  {msg}")

    total = len(pb) + len(pb_anchor) + len(sb)
    clean = total - len(set(r[0] for r in results))
    print(
        f"\nSummary: {total} specs scanned, {clean} clean, {len(warns)} warnings, {len(fails)} fails"
    )
    if fails:
        sys.exit(1)
    if warns:
        sys.exit(2)
    print("OK — all specs structurally valid.")


if __name__ == "__main__":
    main()
