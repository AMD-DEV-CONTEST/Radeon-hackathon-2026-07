#!/usr/bin/env python3
"""determinex_pb_strip_conftest_mirror.py -- remove the DOUBLE-bidir conftest mirror.

WHY (corpus): bidir is supposed to be the /opt/determinex_bidir pytest11 pip-plugin ONLY
(build_knowledge.modules.bidir_plugin). A legacy CONFTEST MIRROR (_bidir_inject_classnames +
the `# --- determinex bidir JUnit mirror ---` block) was left in 212 tools' compile.sh when bidir
moved to the pip plugin -> DOUBLE bidir -> fabricated failing testcases -> LOCAL evals diverge
from Hetzner (melody: local gap129 vs Hetzner gap1, SAME binary). See
build_knowledge.conftest_bidir_mirror_inflation_2026_06_23.

This strips ONLY the conftest-embedded mirror blocks (keeps collect_ignore_glob, modifyitems,
and the /opt/determinex_bidir pip plugin). Does not touch committed eval_report.json (those are
Hetzner-generated and correct). Makes future LOCAL re-evals accurate.

Usage:
  python scripts/determinex_pb_strip_conftest_mirror.py            # strip all affected tools
  python scripts/determinex_pb_strip_conftest_mirror.py --dry-run  # list only
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OV = ROOT / "corpus" / "programbench" / "per_tool_overrides"

# Block 1: the atexit _bidir_inject_classnames mirror (legacy, pre-pip-plugin)
_B1 = re.compile(
    r"\nimport atexit, re as _re\ndef _bidir_inject_classnames\(\):.*?"
    r"atexit\.register\(_bidir_inject_classnames\)\n",
    re.DOTALL,
)
# Block 2: the "determinex bidir JUnit mirror (restored)" ET-based mirror
_B2 = re.compile(
    r"\n# --- determinex bidir JUnit mirror \(restored\).*?# --- end determinex bidir mirror[^\n]*\n",
    re.DOTALL,
)


def strip_mirror(text: str) -> tuple[str, bool]:
    new, n1 = _B1.subn("\n", text)
    new, n2 = _B2.subn("\n", new)
    return new, bool(n1 or n2)


def main() -> int:
    dry = "--dry-run" in sys.argv
    changed = []
    for cs in sorted(OV.glob("*/compile.sh")):
        txt = cs.read_text(encoding="utf-8", errors="replace")
        if "_bidir_inject_classnames" not in txt and "determinex bidir JUnit mirror" not in txt:
            continue
        new, ch = strip_mirror(txt)
        if ch:
            changed.append(cs.parent.name)
            if not dry:
                # keep the pip plugin -- sanity check it's still present
                cs.write_text(new, encoding="utf-8", newline="\n")
    print(f"{'WOULD strip' if dry else 'stripped'} conftest bidir-mirror from {len(changed)} tools")
    for c in changed[:12]:
        print(f"  {c}")
    if len(changed) > 12:
        print(f"  ... +{len(changed) - 12} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
