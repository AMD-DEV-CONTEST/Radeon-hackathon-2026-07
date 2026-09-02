#!/usr/bin/env python3
"""Check the lightweight specification records used by this project."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


LEVELS = {"S1", "S2", "S3"}
STATUSES = {"draft", "ready", "blocked", "implemented", "verified"}
REQUIRED = ("PRODUCT.md", "TECH.md")


def metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[:30]:
        match = re.match(r"^-\s*(Level|Status)\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if match:
            values[match.group(1).lower()] = match.group(2).lower()
    return values


def check_spec(spec_dir: Path) -> list[str]:
    errors: list[str] = []
    present = [spec_dir / name for name in (*REQUIRED, "TEST_REPORT.md")]
    if not any(path.exists() for path in present):
        return errors

    for name in REQUIRED:
        if not (spec_dir / name).is_file():
            errors.append(f"{spec_dir / name}: required file is missing")

    tech = spec_dir / "TECH.md"
    if not tech.is_file():
        return errors

    values = metadata(tech)
    level = values.get("level", "").upper()
    status = values.get("status", "")
    if level not in LEVELS:
        errors.append(f"{tech}: metadata must contain '- Level: S1', 'S2', or 'S3'")
    if status not in STATUSES:
        errors.append(f"{tech}: metadata must contain a valid '- Status:' value")
    if level in {"S2", "S3"} and status in {"implemented", "verified"}:
        report = spec_dir / "TEST_REPORT.md"
        if not report.is_file():
            errors.append(f"{report}: required for implemented or verified {level} specs")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specs-root", default="specs", type=Path)
    parser.add_argument("--strict", action="store_true", help="return non-zero for errors")
    args = parser.parse_args(argv)

    if not args.specs_root.exists():
        print("spec validation: no specs directory yet; skipping")
        return 0

    errors: list[str] = []
    for spec_dir in sorted(path for path in args.specs_root.iterdir() if path.is_dir() and not path.name.startswith("_")):
        errors.extend(check_spec(spec_dir))
    for error in errors:
        print(f"ERROR: {error}")
    print(f"spec validation: checked errors={len(errors)}")
    return 1 if args.strict and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
