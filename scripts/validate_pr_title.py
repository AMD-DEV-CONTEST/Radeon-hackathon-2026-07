#!/usr/bin/env python3
"""Validate the fixed official submission identity in PR titles."""

from __future__ import annotations

import argparse
import sys


OFFICIAL_PR_TITLE = "Track 2, PLASMA, ProjectPack Office Agent"


def validate_title(title: str) -> str | None:
    """Return an error message, or ``None`` when *title* is valid."""
    if "\n" in title or "\r" in title:
        return "title must be a single line"
    if title != OFFICIAL_PR_TITLE:
        return (
            f"expected exactly: '{OFFICIAL_PR_TITLE}'"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="pull-request title to validate")
    args = parser.parse_args(argv)

    error = validate_title(args.title)
    if error:
        print(f"ERROR: invalid pull-request title: {error}", file=sys.stderr)
        return 1

    print("PR title is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
