#!/usr/bin/env python3
"""Fail when a relative Markdown link points to a missing local file."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    missing: list[str] = []
    for markdown in sorted(root.rglob("*.md")):
        if ".git" in markdown.parts:
            continue
        text = markdown.read_text(encoding="utf-8")
        for raw in LINK.findall(text):
            target = raw.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text = unquote(target.split("#", 1)[0])
            if path_text and not (markdown.parent / path_text).resolve().exists():
                missing.append(f"{markdown.relative_to(root)} -> {target}")
    if missing:
        raise SystemExit("Missing local Markdown links:\n" + "\n".join(missing))
    print("MARKDOWN_LINKS_OK")


if __name__ == "__main__":
    main()
