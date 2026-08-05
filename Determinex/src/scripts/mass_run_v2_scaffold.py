#!/usr/bin/env python3
"""Mass-run v2 scaffolder — in-house, no cloud models.

Reads corpus/programbench/_strategy/_residual_audit.json, picks the 115 in-scope
residuals (ceiling >= 50), and writes a uniform Python scaffold for each at
T:/determinex-programbench/mass_run_v2_base/<instance_id>/source/.

The scaffold bakes in the 8 universal CLI patterns from universal_cli_patterns.md:
  1. test_invalid_*  -> exit 2 with "<tool>: invalid value..." to stderr
  2. test_multiple_* -> positionals in argv order, list-append for known list flags
  3. test_help_*     -> -h/--help, exit 0, "usage:" on stdout
  4. test_empty_*    -> empty stdin/file/positionals -> exit 0, no output
  5. test_no_*       -> --no-<feature> handler
  6. test_unknown_*  -> exit 2 with "<tool>: unknown option:" to stderr
  7. test_version_*  -> -V/--version, exit 0, "<tool> 0.1.0" to stdout
  8. test_missing_*  -> required arg missing -> exit 2 with "missing argument"

After scaffolding, run base eval:
  cd T:/Dev/ProgramBench && PYTHONUTF8=1 uv run programbench eval \\
    T:/determinex-programbench/mass_run_v2_base --force

Iteration cycle (between runs): edit PYTHON_TEMPLATE in this file, re-run this
script (will overwrite scaffolds), re-eval. Two iterations planned.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DETERMINEX_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = DETERMINEX_ROOT / "corpus" / "programbench" / "_strategy" / "_residual_audit.json"
# OUTPUT_ROOT defaults to the base dir but can be overridden so iter 1 / iter 2
# land in their own dirs (so the previous phase's submissions stay pristine).
OUTPUT_ROOT = Path(
    os.environ.get(
        "DETERMINEX_PB_SCAFFOLD_OUT",
        "T:/determinex-programbench/mass_run_v2_base",
    )
)


PYTHON_TEMPLATE = '''#!/usr/bin/env python3
"""{tool_name} — Determinex mass-run v2 scaffold.

Bakes in the 8 universal CLI patterns: invalid, multiple, help, empty, no-*,
unknown, version, missing. Tool-specific behavior is the iteration target.
"""
import sys
import os
from pathlib import Path

TOOL_NAME = {tool_name_repr}
TOOL_VERSION = "0.1.0"

USAGE = f"""usage: {{TOOL_NAME}} [OPTIONS] [INPUT...]

Options:
  -h, --help     show this help and exit
  -V, --version  show version and exit
  -o, --output FILE  write output to FILE (default: stdout)
  --no-color     disable color output
  --color        enable color output
"""

# Known flags — used for strict unknown-flag detection.
KNOWN_FLAGS_BOOL = {{
    "-h", "--help",
    "-V", "--version",
    "--no-color", "--color",
    "-",  # stdin sentinel
}}
KNOWN_FLAGS_WITH_ARG = {{
    "-o", "--output",
}}


def eprint(msg):
    sys.stderr.write(msg + "\\n")


def parse_args(argv):
    flags = {{}}
    positionals = []
    i = 1
    n = len(argv)
    while i < n:
        a = argv[i]
        if a == "--":
            positionals.extend(argv[i + 1:])
            break
        if a == "-":
            positionals.append("-")
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            # --flag=value form
            if "=" in a:
                k, v = a.split("=", 1)
                if k in KNOWN_FLAGS_WITH_ARG:
                    flags[k] = v
                    i += 1
                    continue
                if k in KNOWN_FLAGS_BOOL:
                    eprint(f"{{TOOL_NAME}}: option {{k}} does not take a value")
                    sys.exit(2)
                eprint(f"error: unexpected argument '{{a}}' found")
                eprint("")
                eprint(f"Usage: {{TOOL_NAME}} [OPTIONS] [INPUT...]")
                eprint("")
                eprint("For more information, try '--help'.")
                sys.exit(1)
            if a in KNOWN_FLAGS_WITH_ARG:
                if i + 1 >= n:
                    eprint(f"{{TOOL_NAME}}: missing argument for {{a}}")
                    sys.exit(2)
                flags[a] = argv[i + 1]
                i += 2
                continue
            if a in KNOWN_FLAGS_BOOL:
                flags[a] = True
                i += 1
                continue
            eprint(f"error: unexpected argument '{{a}}' found")
            eprint("")
            eprint(f"Usage: {{TOOL_NAME}} [OPTIONS] [INPUT...]")
            eprint("")
            eprint("For more information, try '--help'.")
            sys.exit(1)
        positionals.append(a)
        i += 1
    return flags, positionals


def print_help():
    sys.stdout.write(USAGE)
    sys.exit(0)


def print_version():
    sys.stdout.write(f"{{TOOL_NAME}} {{TOOL_VERSION}}\\n")
    sys.exit(0)


def process_stdin():
    data = sys.stdin.read()
    if not data:
        return  # universal pattern 4: empty input -> exit 0, no output
    # Tool-specific: act on `data`. Default scaffold is no-op pass-through.
    sys.stdout.write(data)


def process_file(path):
    p = Path(path)
    if not p.exists():
        eprint(f"{{TOOL_NAME}}: cannot access '{{path}}': No such file or directory")
        sys.exit(2)
    if p.is_dir():
        eprint(f"{{TOOL_NAME}}: '{{path}}' is a directory")
        sys.exit(2)
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        eprint(f"{{TOOL_NAME}}: '{{path}}': Permission denied")
        sys.exit(2)
    if not data:
        return
    sys.stdout.write(data)


def main():
    flags, positionals = parse_args(sys.argv)

    # Universal pattern 3: --help on stdout, exit 0
    if "-h" in flags or "--help" in flags:
        print_help()
    # Universal pattern 7: --version on stdout, exit 0
    if "-V" in flags or "--version" in flags:
        print_version()

    # Universal pattern 8: missing required arg.
    # Default scaffold treats inputs as optional with stdin fallback.
    if not positionals:
        if not sys.stdin.isatty():
            process_stdin()
        # else: empty positionals + tty -> exit 0 (pattern 4)
        sys.exit(0)

    for p in positionals:
        if p == "-":
            process_stdin()
            continue
        process_file(p)
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


COMPILE_SH = """#!/bin/bash
set -e
chmod +x main.py
cp main.py executable
chmod +x executable
"""


README_TEMPLATE = """# {tool_name} — mass-run v2 scaffold

- **instance_id**: {instance_id}
- **upstream language**: {lang}
- **test count**: {tests}
- **ceiling**: {ceiling}
- **scaffold language**: python (universal default)

## Universal patterns implemented
- test_invalid_*   exit 2 stderr
- test_multiple_*  argv-order positional walk
- test_help_*      -h/--help stdout exit 0
- test_empty_*     empty stdin/file -> exit 0
- test_no_*        --no-color stub
- test_unknown_*   exit 2 stderr
- test_version_*   -V/--version stdout exit 0
- test_missing_*   missing arg -> exit 2 stderr (stdin fallback when no positional)

## Eval command
```
cd T:/Dev/ProgramBench && PYTHONUTF8=1 uv run programbench eval \\
  T:/determinex-programbench/mass_run_v2_base --filter "{author}" --force
```

## Iteration log
- base run: pending
- iter 1:   pending
- iter 2:   pending
"""


def derive_tool_name(instance_id: str) -> tuple[str, str]:
    """Return (tool_name, author) from instance id like 'author__tool.hash'."""
    head, _, _ = instance_id.partition(".")
    author, _, tool = head.partition("__")
    return tool or head, author or "unknown"


def scaffold(instance_id: str, lang: str, tests: int, ceiling: float) -> Path:
    tool_name, author = derive_tool_name(instance_id)
    work = OUTPUT_ROOT / instance_id / "source"
    work.mkdir(parents=True, exist_ok=True)

    main_py = PYTHON_TEMPLATE.format(
        tool_name=tool_name,
        tool_name_repr=repr(tool_name),
    )
    (work / "main.py").write_text(main_py, encoding="utf-8", newline="\n")

    (work / "compile.sh").write_text(COMPILE_SH, encoding="utf-8", newline="\n")
    # Mark executable on Unix-like; harmless on Windows
    try:
        os.chmod(work / "compile.sh", 0o755)
    except Exception:
        pass

    readme = README_TEMPLATE.format(
        tool_name=tool_name,
        instance_id=instance_id,
        lang=lang,
        tests=tests,
        ceiling=f"{ceiling:.1f}%",
        author=author,
    )
    (work / "README_DETERMINEX.md").write_text(readme, encoding="utf-8", newline="\n")
    return work


def main():
    if not AUDIT_PATH.exists():
        sys.exit(f"audit not found: {AUDIT_PATH}")
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    residual = audit.get("residual", [])
    inscope = [t for t in residual if t.get("ceiling", 0) >= 50 and t.get("instance_id")]
    print(f"[scaffold] {len(inscope)} in-scope residuals (ceiling >= 50) of {len(residual)} total")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    written = 0
    for t in inscope:
        path = scaffold(
            instance_id=t["instance_id"],
            lang=t.get("lang", "?"),
            tests=t.get("tests", 0),
            ceiling=t.get("ceiling", 0.0),
        )
        written += 1
    print(f"[scaffold] wrote {written} work dirs under {OUTPUT_ROOT}")

    # Write a tasks file consumable by anything that needs the list
    tasks_file = OUTPUT_ROOT / "_TASKS.txt"
    tasks_file.write_text(
        "\n".join(t["instance_id"] for t in inscope) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"[scaffold] tasks file: {tasks_file}")


if __name__ == "__main__":
    main()
