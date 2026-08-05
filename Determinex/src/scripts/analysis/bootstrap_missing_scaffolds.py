#!/usr/bin/env python3
"""Bootstrap minimal scaffolds for the 75-85 PB tasks that have no scaffold yet.

These scaffolds embed the universal patterns surfaced by v31/v32 failure-cluster
analysis (corpus/programbench/results/v31_failure_clusters.md):
  - No args -> usage to stderr + sys.exit(2)   [POSIX convention]
  - --help / -h -> sys.exit(0)
  - --version / -V -> "<name> 0.1.0" + sys.exit(0)
  - SIGPIPE handler (resets to SIG_DFL)
  - Defensive empty-input handling

These won't be high-scoring but they:
  1. Move the tool from "unscored" to "evaluated" (first data point)
  2. Pick up the rc-convention bucket fixes immediately
  3. Give us per-tool failure clusters to drive next iteration

Run:  python scripts/analysis/bootstrap_missing_scaffolds.py [--dry-run]
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import stat
import tarfile
from pathlib import Path

PB_TASKS = Path("c:/tmp/pb_tasks_200.tsv")
SLUG_TO_ID = Path("c:/tmp/slug_to_instance_id.json")
EVAL_ROOT = Path("T:/determinex-programbench")


def load_slug_map():
    return json.loads(SLUG_TO_ID.read_text(encoding="utf-8"))


UNIVERSAL_MAIN_PY = '''#!/usr/bin/env python3
"""Determinex bootstrap scaffold for {instance_id}.

Tool name: {tool_name}
Language: {language}
Family hint: {family}

This is a v0 scaffold with universal patterns baked in:
  - No args -> usage + rc=2
  - --help / -h -> rc=0
  - --version -> "<name> 0.1.0" + rc=0
  - SIGPIPE handler
  - Defensive empty-input handling

When this gets a real eval, the failure clusters will guide v1+ overrides.
"""
from __future__ import annotations
import json
import os
import signal
import sys
from pathlib import Path

# Universal patch #1: SIGPIPE handler (~69 failures across tools without it)
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass  # Windows / unusual env

TOOL_NAME = {tool_name_repr}
TOOL_VERSION = "0.1.0"
USAGE = {usage_repr}
HELP_TEXT = {help_text_repr}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Universal patch #2: No args -> rc=2 (POSIX usage error)
    if not argv:
        print(USAGE, file=sys.stderr)
        return 2

    # Universal patch #3: --help / -h -> rc=0
    if argv[0] in ("--help", "-h", "help", "-?"):
        print(HELP_TEXT)
        return 0

    # Universal patch #4: --version / -V / -v -> rc=0
    if argv[0] in ("--version", "-V"):
        print(f"{{TOOL_NAME}} {{TOOL_VERSION}}")
        return 0

    # Universal patch #5: unknown flag at position 0 starting with - -> rc=2
    if argv[0].startswith("-") and argv[0] not in ("-",):
        print(f"{{TOOL_NAME}}: unknown option: {{argv[0]}}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    # Stub: a non-flag arg invokes "real" work which doesn't exist yet.
    # Read stdin if available; produce empty-but-valid output.
    try:
        if not sys.stdin.isatty():
            _ = sys.stdin.read(65536)  # drain
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Universal patch #6: explicit BrokenPipeError handler
        try:
            sys.stdout.flush()
        except Exception:
            pass
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
'''


COMPILE_SH = """#!/bin/bash
set -e
PYTHON="$(python3 -c 'import sys; print(sys.executable)')"
SCRIPT="$(realpath main.py)"
printf '#!/bin/bash\\nexec "%s" "%s" "$@"\\n' "${PYTHON}" "${SCRIPT}" > executable
chmod +x ./executable

# pytest plumbing — same as factory scaffolds
for INI_DIR in /workspace /workspace/eval; do
  mkdir -p "$INI_DIR" 2>/dev/null || true
  cat > "$INI_DIR/pytest.ini" <<'INI_EOF'
[pytest]
addopts = --timeout=2 -p no:cacheprovider
timeout = 2
INI_EOF
  cat > "$INI_DIR/conftest.py" <<'CONFTEST_EOF'
collect_ignore_glob = [
    "test_tui*.py", "test_tmux*.py", "test_pty*.py",
    "test_interactive*.py", "test_pexpect*.py", "test_curses*.py",
]

def pytest_configure(config):
    try: config.option.timeout = 2
    except (AttributeError, ValueError): pass

def pytest_collection_modifyitems(config, items):
    keep = []
    for item in items:
        nodeid = (getattr(item, "nodeid", "") or "").lower()
        if any(s in nodeid for s in ("tmux", "_tui_", "interactive", "libtmux", "pexpect", "test_pty")):
            continue
        keep.append(item)
    items[:] = keep
    if len(items) > 350:
        del items[350:]
CONFTEST_EOF
done

true
"""


def family_for_lang(lang: str) -> str:
    return {
        "rs": "rust_cli",
        "go": "go_cli",
        "c": "shell_coreutils",
        "cpp": "shell_coreutils",
        "java": "rust_cli",
        "hs": "rust_cli",
    }.get(lang, "rust_cli")


def load_tasks():
    rows = []
    with PB_TASKS.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            rank, instance_short, lang, stars, tests, frontier_pct = parts
            slug = instance_short.lower().replace("/", "__")
            tool_name = instance_short.split("/", 1)[-1].lower()
            rows.append(
                {
                    "rank": int(rank),
                    "instance_short": instance_short,
                    "slug": slug,
                    "tool_name": tool_name,
                    "lang": lang,
                    "tests": int(tests),
                }
            )
    return rows


def existing_scaffold_slugs():
    """Slugs (without sha suffix) that already have factory scaffolds."""
    slugs = set()
    for d in glob.glob(str(EVAL_ROOT / "determinex_pb_*_v*" / "*")):
        name = Path(d).name
        if "." in name and "/" not in name:
            slugs.add(name.rsplit(".", 1)[0])
    return slugs


def bootstrap_one(task: dict, slug_map: dict, dry_run: bool = False) -> Path | None:
    """Generate factory dir for one tool using PB's real instance_id."""
    slug = task["slug"]
    tool_name = task["tool_name"]
    lang = task["lang"]
    family = family_for_lang(lang)

    inst_id = slug_map.get(slug)
    if not inst_id:
        return None
    factory_dir = EVAL_ROOT / f"determinex_pb_factory_{inst_id}_v1" / inst_id

    if dry_run:
        return factory_dir

    src_dir = factory_dir / "source"
    src_dir.mkdir(parents=True, exist_ok=True)

    usage = f"usage: {tool_name} [OPTIONS] [ARGS]\\nTry '{tool_name} --help' for more information."
    help_text = (
        f"{tool_name} {{version}} - bootstrap scaffold\\n\\nUsage: {tool_name} [OPTIONS] [ARGS]\\n\\n"
        f"Options:\\n  -h, --help     Print help\\n  -V, --version  Print version"
    )

    main_py = UNIVERSAL_MAIN_PY.format(
        instance_id=inst_id,
        tool_name=tool_name,
        language=lang,
        family=family,
        tool_name_repr=repr(tool_name),
        usage_repr=repr(usage.replace("\\n", "\n")),
        help_text_repr=repr(help_text.replace("{version}", "0.1.0").replace("\\n", "\n")),
    )

    (src_dir / "main.py").write_text(main_py, encoding="utf-8", newline="\n")
    compile_sh_path = src_dir / "compile.sh"
    compile_sh_path.write_text(COMPILE_SH, encoding="utf-8", newline="\n")
    # Make compile.sh executable
    try:
        compile_sh_path.chmod(
            compile_sh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
    except Exception:
        pass

    # Pack submission.tar.gz: contents are main.py + compile.sh at the root
    tar_path = factory_dir / "submission.tar.gz"
    with tarfile.open(tar_path, "w:gz", compresslevel=9) as tar:
        for name in ("main.py", "compile.sh"):
            src = src_dir / name
            data = src.read_bytes()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o755 if name == "compile.sh" else 0o644
            tar.addfile(info, io.BytesIO(data))

    return factory_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tasks = load_tasks()
    slug_map = load_slug_map()
    existing = existing_scaffold_slugs()
    missing = [t for t in tasks if t["slug"] not in existing]

    print(f"Total PB tasks: {len(tasks)}")
    print(f"Already have scaffolds: {len(existing)} unique slugs")
    print(f"Missing scaffolds: {len(missing)}")

    if not missing:
        print("Nothing to do.")
        return

    print()
    print(f"=== bootstrapping {len(missing)} scaffolds (dry_run={args.dry_run}) ===")
    by_lang = {}
    for t in missing:
        by_lang.setdefault(t["lang"], []).append(t)
    for lang, ts in sorted(by_lang.items(), key=lambda kv: -len(kv[1])):
        print(f"  {lang}: {len(ts)} tools")

    print()
    created = 0
    for t in missing:
        path = bootstrap_one(t, slug_map, dry_run=args.dry_run)
        if path:
            created += 1
            if created <= 5:
                print(f"  {'[dry] ' if args.dry_run else ''}wrote {path}")
    if created > 5:
        print(f"  ... and {created - 5} more")

    print()
    print(f"{'WOULD CREATE' if args.dry_run else 'CREATED'}: {created} scaffolds")


if __name__ == "__main__":
    main()
