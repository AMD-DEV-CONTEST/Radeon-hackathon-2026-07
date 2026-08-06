#!/usr/bin/env python3
"""Public-release gate: secret scan plus local-path / real-endpoint scan.

Scans every regular file under the given roots and fails when any file matches
a secret pattern or contains a private local path or a real operational
endpoint. Run from the package root: scripts/python.sh scripts/scan_tree.py .
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SECRET_PATTERNS = [
    ("private_key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)),
    ("openai_style_key", re.compile(rb"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b")),
    ("bearer_token", re.compile(rb"\bBearer\s+[A-Za-z0-9._~+/\-]{12,}={0,2}\b", re.IGNORECASE)),
    (
        "credential_assignment",
        re.compile(
            rb"[\"']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
            rb"[\"']?\s*[:=]\s*[\"']?[^\s\"',}\]]{4,}",
            re.IGNORECASE,
        ),
    ),
]

# Strings that must never appear in a public example package.
FORBIDDEN_LITERALS = [
    ("local_user_path", b"/Users/"),
    ("local_home_path", b"/home/"),
    ("real_ssh_endpoint", b"uchat.ccwu.cc"),
    ("real_train_host", b"u-7701-"),
]

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def iter_files(root: Path):
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(directory) / name
            if not path.is_symlink() and path.is_file():
                yield path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--allow-file", action="append", default=[],
                        help="Relative path allowed to mention forbidden literals (e.g. this scanner)")
    args = parser.parse_args()

    allow = {str(Path(p)) for p in args.allow_file}
    findings: list[dict] = []
    files = 0
    total_bytes = 0
    for root in (Path(r) for r in args.roots):
        for path in iter_files(root):
            rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
            body = path.read_bytes()
            files += 1
            total_bytes += len(body)
            if rel in allow:
                continue
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(body):
                    findings.append({"path": rel, "rule": name})
            for name, literal in FORBIDDEN_LITERALS:
                if literal in body:
                    findings.append({"path": rel, "rule": name})

    report = {
        "schema_version": "magicbox_example_scan_report.v1",
        "clean": not findings,
        "files": files,
        "bytes": total_bytes,
        "findings": findings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
