#!/usr/bin/env python3
"""pb_compile_lint.py — static pre-deploy lint of a ProgramBench compile.sh.

Catches the footguns that cause the dominant `missing_executable` failure class
(10,717 test-instances across the corpus) WITHOUT spinning up a container, so a
doomed candidate is never deployed to Hetzner. Pure text, sub-second.

Checks:
  E1  `exec -a` used under a `#!/bin/sh` shebang (dash lacks exec -a → not found)
  E2  no install line to /usr/local/bin/<tool> (guarantees missing_executable)
  E3  no build command AND no bundled-binary fallback (nothing is produced)
  E4  missing `chmod +x ./executable`
  W1  conftest not written to BOTH /workspace and /workspace/eval
  E5  forbid 400-item collection cap (caps shrink official active denominator)

Exit code: 0 = clean (warnings ok), 1 = has errors (do not deploy).

Usage:
    python scripts/pb_compile_lint.py path/to/compile.sh [--tool zoxide]
    python scripts/pb_compile_lint.py corpus/programbench/per_tool_overrides/*/compile.sh
"""

from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path


def lint(path: Path, tool: str | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")

    # E1: exec -a under /bin/sh shebang (in the generated executable heredoc).
    # Look for a heredoc that sets #!/bin/sh and then uses exec -a.
    for m in re.finditer(r"<<'?EXEC_EOF'?\n(.*?)\nEXEC_EOF", text, re.DOTALL):
        body = m.group(1)
        if (
            "exec -a" in body
            and re.search(r"#!\s*/bin/sh\b", body)
            and "bash" not in body.splitlines()[0]
        ):
            errors.append(
                "E1: `exec -a` under #!/bin/sh in ./executable (dash has no exec -a; use #!/usr/bin/env bash)"
            )

    # E2: install to /usr/local/bin/<tool>
    if "/usr/local/bin/" not in text:
        errors.append("E2: no install to /usr/local/bin/<tool> (tests invoke that path)")
    elif tool and f"/usr/local/bin/{tool}" not in text:
        warns.append(f"W?: /usr/local/bin/ used but not /usr/local/bin/{tool} (verify binary name)")

    # E3: must produce something — either a build or a bundled fallback.
    has_build = any(
        k in text for k in ("cargo build", "go build", "make", "cmake", "g++", "./configure")
    )
    has_fallback = bool(re.search(r"\[ -f \./\S+ \]", text)) or "cp ./" in text
    if not has_build and not has_fallback:
        errors.append("E3: no build command and no bundled-binary fallback (nothing produced)")

    # E4: executable made runnable.
    if (
        "executable" in text
        and "chmod +x ./executable" not in text
        and "chmod +x executable" not in text
    ):
        errors.append("E4: ./executable created but never chmod +x")

    # W1: conftest to both dirs.
    if "conftest.py" in text:
        if not ("/workspace/eval" in text and "/workspace" in text):
            warns.append("W1: conftest not written to both /workspace and /workspace/eval")
    # E5: item cap.
    if "del items[400:]" in text or "items[:400]" in text:
        errors.append(
            "E5: 400-item collection cap present (removes expected_active tests from official denominator)"
        )

    return errors, warns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="compile.sh path(s) or globs")
    ap.add_argument("--tool", help="expected binary name")
    args = ap.parse_args()

    expanded: list[str] = []
    for p in args.paths:
        hits = glob.glob(p)
        expanded.extend(hits if hits else [p])

    any_error = False
    for p in expanded:
        path = Path(p)
        if not path.is_file():
            print(f"[SKIP] {p}: not a file")
            continue
        errors, warns = lint(path, args.tool)
        status = "FAIL" if errors else ("WARN" if warns else "OK")
        print(f"[{status}] {p}")
        for e in errors:
            print(f"    ERROR {e}")
        for w in warns:
            print(f"    warn  {w}")
        if errors:
            any_error = True
    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
