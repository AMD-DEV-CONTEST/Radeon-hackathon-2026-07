#!/usr/bin/env python3
"""
governance/overclaim_guard.py -- live no-overclaim CI/pre-commit guard
======================================================================
Deterministically fails if any tracked board/config/doc literally asserts an
authority anchor TRUE (e.g. '"release_ready": true', 'release_supported = yes',
'universal_support: granted'). The replacement for the 1,175 generated lane
guard tests -- one scan, same protection.

    python scripts/governance/overclaim_guard.py            # scan tracked json/md/yaml
    python scripts/governance/overclaim_guard.py --verbose

Exit 1 on any anchor asserted true. Designed to slot into .pre-commit-config.yaml
alongside pb_doc_count_check.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent.parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import json  # noqa: E402

from governance.authority import (  # noqa: E402
    AUTHORITY_FALSE,
    json_anchor_violations,
    scan_text_for_anchor_true,
)

REPO = Path(__file__).resolve().parent.parent.parent
_SCAN_EXT = {".json", ".md", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
# never scan history/audit/evidence docs that legitimately quote the anchors or
# reuse the names as per-cell fields (a 'release_supported' cell != the global
# release_supported authority anchor). JSON files are checked STRUCTURALLY
# (top-level / authority block only), so they need no skipping.
_SKIP = (
    "archive/",
    "docs/audits/",
    "scripts/status/",
    "scripts/proof/",
    "tests/status/",
    "tests/proof/",
    "node_modules/",
    "corpus/",
)
# text (non-JSON) scanning is the blunt instrument -> restrict it to evidence-free
# canonical surfaces; evidence trees use the anchor NAMES as rule descriptions.
_TEXT_SKIP = ("assurance/", "locks/", "docs/ide-frontend/")


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=str(REPO), capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return []
    files = []
    for rel in out.splitlines():
        if any(rel.startswith(s) or f"/{s}" in rel for s in _SKIP):
            continue
        p = REPO / rel
        if p.suffix.lower() in _SCAN_EXT and p.is_file():
            files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex no-overclaim guard")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    violations: list[tuple[str, list[str]]] = []
    files = _tracked_files()
    for p in files:
        rel = str(p.relative_to(REPO))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if p.suffix.lower() == ".json":
            # structure-aware: only top-level / authority-block anchors set true
            try:
                hits = json_anchor_violations(json.loads(text))
            except Exception:
                hits = []
        else:
            # blunt text scan -> only on canonical (evidence-free) surfaces
            if any(
                rel.replace("\\", "/").startswith(s) or f"/{s}" in rel.replace("\\", "/")
                for s in _TEXT_SKIP
            ):
                continue
            hits = scan_text_for_anchor_true(text)
        if hits:
            violations.append((rel, hits))

    print(
        f"governance overclaim guard: scanned {len(files)} files, {len(AUTHORITY_FALSE)} anchors."
    )
    if violations:
        print(f"\nFAIL: {len(violations)} file(s) assert an authority anchor TRUE without proof:")
        for path, hits in violations:
            print(f"  {path}: {', '.join(hits)}")
        print(
            "\nAn anchor may only be True when genuinely earned + proven. "
            "If this is real, update governance/authority.py deliberately."
        )
        return 1
    print("OK: no authority anchor is asserted true. No-overclaim invariant holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
