#!/usr/bin/env python3
"""determinex_pb_go_toolchain_sweep.py -- corpus-flagged go_x_toolchain sweep.

WHY (corpus go_toolchain_bogus_future_version): a tool's go.mod pins a FUTURE/unreleased go
version (e.g. `go 1.26`). GOTOOLCHAIN=auto (default) then tries to DOWNLOAD that toolchain; the
eval sandbox blocks network -> `go build` fails -> binary missing -> EVERY test exits 127.
"the single biggest sweep this session" (overlaps.go_x_toolchain = 17 tools).

FIX (proven, from the factory_v1 winners): `export GOTOOLCHAIN=local` (use the installed go,
never download) + sed any future `go 1.2[5-9]` in go.mod down to the installed 1.24. Safe for
ALL go-build tools (local toolchain already present in the image).

Usage:
  python scripts/determinex_pb_go_toolchain_sweep.py [--dry-run]
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OV = ROOT / "corpus" / "programbench" / "per_tool_overrides"

_MARK = "# [determinex-go-toolchain]"
_BLOCK = (
    f"\n{_MARK} corpus go_x_toolchain: use local go, never download a pinned future toolchain\n"
    "export GOTOOLCHAIN=local\n"
    'for _gm in go.mod */go.mod ./*/go.mod; do [ -f "$_gm" ] && '
    'sed -i -E "s/^go 1[.]2[5-9].*/go 1.24/" "$_gm" 2>/dev/null; done\n'
)


def is_go_build(text: str) -> bool:
    return any(k in text for k in ("go build", "go install", "go test ", "/go/bin", "golang"))


def main() -> int:
    dry = "--dry-run" in sys.argv
    changed = []
    for cs in sorted(OV.glob("*/compile.sh")):
        txt = cs.read_text(encoding="utf-8", errors="replace")
        if not is_go_build(txt):
            continue
        if _MARK in txt or "GOTOOLCHAIN=local" in txt:
            continue
        # insert the block right after the shebang line
        lines = txt.splitlines(keepends=True)
        at = 1 if lines and lines[0].startswith("#!") else 0
        lines.insert(at, _BLOCK)
        changed.append(cs.parent.name)
        if not dry:
            cs.write_text("".join(lines), encoding="utf-8", newline="\n")
    print(f"{'WOULD add' if dry else 'added'} GOTOOLCHAIN=local to {len(changed)} go-build tools")
    for c in changed[:15]:
        print(f"  {c.split('__')[-1]}")
    if len(changed) > 15:
        print(f"  ... +{len(changed) - 15} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
