#!/usr/bin/env python3
"""Compatibility entrypoint for the day-one public claim scanner.

The current canonical authority scanner is `scripts/governance/overclaim_guard.py`.
This wrapper preserves the older release-runbook command shape:

    python scripts/claim_scanner/day_one_public_claim_scanner.py --root .
    python scripts/claim_scanner/day_one_public_claim_scanner.py --print

It scans tracked public claim surfaces for authority anchors asserted true
without proof. It does not grant release readiness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from governance.authority import (  # noqa: E402
    AUTHORITY_FALSE,
    json_anchor_violations,
    scan_text_for_anchor_true,
)

SCAN_EXTENSIONS = {".json", ".md", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
#: Trees that are not Determinex's claims. `node_modules/` was already here; `.vscode-test/` is the
#: same kind of thing and was missed because nothing had created one until 2026-07-31, when the
#: extension-host harness began caching a full VS Code (1,995 files, several hundred of them JSON
#: manifests the scanner then parsed). The scan went from ~5 s to over its own 90 s timeout, and
#: `test_day_one_public_claim_scanner_compat` failed as a TIMEOUT rather than a finding — which is
#: the right way to notice, but the wrong thing to be noticing.
#:
#: A downloaded toolchain cache makes no claims about Determinex. Both entries are gitignored build
#: caches; neither is ever published.
#:
#: Deliberately NOT adding `.tmp/` alongside it, though it is also large and gitignored: it holds the
#: generated `SETUP.md` that ships inside the download ZIP, which is user-facing text this scanner
#: should keep reading. `.tmp/` was already being scanned before tonight and was never the
#: bottleneck — widening the skip list past the actual cause would have quietly cost real coverage.
SKIP_PREFIXES = (
    "archive/",
    "docs/audits/",
    "scripts/status/",
    "scripts/proof/",
    "tests/status/",
    "tests/proof/",
    "node_modules/",
    "corpus/",
    ".vscode-test/",
)
TEXT_SKIP_PREFIXES = ("assurance/", "locks/", "docs/ide-frontend/")


def _tracked_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception:
        return []
    files: list[Path] = []
    for rel in result.stdout.splitlines():
        normalized = rel.replace("\\", "/")
        if any(
            normalized.startswith(prefix) or f"/{prefix}" in normalized for prefix in SKIP_PREFIXES
        ):
            continue
        path = root / rel
        if path.suffix.lower() in SCAN_EXTENSIONS and path.is_file():
            files.append(path)
    return files


def scan(root: Path) -> dict[str, object]:
    violations: list[dict[str, object]] = []
    files = _tracked_files(root)
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix.lower() == ".json":
            try:
                hits = json_anchor_violations(json.loads(text))
            except json.JSONDecodeError:
                hits = []
        else:
            if any(rel.startswith(prefix) or f"/{prefix}" in rel for prefix in TEXT_SKIP_PREFIXES):
                continue
            hits = scan_text_for_anchor_true(text)
        if hits:
            violations.append({"path": rel, "anchors": hits})
    return {
        "status": "DAY_ONE_PUBLIC_CLAIM_SCANNER_PASSED"
        if not violations
        else "DAY_ONE_PUBLIC_CLAIM_SCANNER_FAILED",
        "claim_clean": not violations,
        "current_repo_violation_count": len(violations),
        "scanner_self_test_passed": True,
        "authority_anchor_count": len(AUTHORITY_FALSE),
        "tracked_file_count": len(files),
        "violations": violations,
        "claim_boundary": (
            "This scanner checks authority-anchor overclaims. It does not prove release readiness, "
            "universal support, installer trust, or clean-host success."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--print", dest="print_json", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    payload = scan(root)
    if args.print_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['status']}: current_repo_violation_count="
            f"{payload['current_repo_violation_count']}"
        )
    return 0 if payload["claim_clean"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
