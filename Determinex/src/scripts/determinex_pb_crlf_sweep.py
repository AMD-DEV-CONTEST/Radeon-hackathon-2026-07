#!/usr/bin/env python3
"""determinex_pb_crlf_sweep.py -- find the full blast radius of the CRLF build wall.

build_knowledge.crlf_configure_wall_2026_06_23: a build script with Windows CRLF (\\r\\n)
makes sh/bash choke ("$'\\r': command not found") -> configure never generates config.* ->
no binary -> every test fails 'No such file'. Proven on tinycc (52->4116). This sweeps EVERY
tool's submission.tar.gz for CRLF in its build scripts (configure/autogen.sh/bootstrap/*.sh/
Makefile*) so we know exactly which tools the class can crash through.

Usage:
  python scripts/determinex_pb_crlf_sweep.py            # scan all, print affected tools
  python scripts/determinex_pb_crlf_sweep.py --json     # machine-readable
"""

from __future__ import annotations

import json
import pathlib
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OV = ROOT / "corpus" / "programbench" / "per_tool_overrides"

# build scripts whose CRLF actually breaks the build (executed by a shell)
_SCRIPT_HINTS = (
    "configure",
    "autogen.sh",
    "bootstrap",
    "config.guess",
    "config.sub",
    "configure.ac",
    "makefile",
    "build.sh",
    "compile",
    ".m4",
)


def _is_build_script(name: str) -> bool:
    base = name.rsplit("/", 1)[-1].lower()
    if base in ("configure", "autogen.sh", "bootstrap", "config.guess", "config.sub"):
        return True
    if base.startswith("makefile"):
        return True
    if base.endswith(".sh") and base not in ("compile.sh",):  # compile.sh is OURS (LF already)
        return True
    return False


def scan_tool(slug: str) -> dict | None:
    tb = OV / slug / "submission.tar.gz"
    if not tb.exists():
        return None
    hits: dict[str, int] = {}
    try:
        with tarfile.open(tb, "r:gz") as t:
            for m in t.getmembers():
                if not m.isfile() or m.size > 5_000_000:
                    continue
                if not _is_build_script(m.name):
                    continue
                f = t.extractfile(m)
                if f is None:
                    continue
                # count CR bytes that precede LF (CRLF lines) in the first chunk
                chunk = f.read(600_000)
                crlf = chunk.count(b"\r\n")
                if crlf > 0:
                    hits[m.name.rsplit("/", 1)[-1]] = crlf
    except Exception:
        return None
    if not hits:
        return None
    return {"slug": slug, "scripts": hits, "total_crlf": sum(hits.values())}


def main() -> int:
    slugs = sorted(
        p.name for p in OV.iterdir() if p.is_dir() and (p / "submission.tar.gz").exists()
    )
    affected = []
    for s in slugs:
        r = scan_tool(s)
        if r:
            affected.append(r)
    affected.sort(key=lambda r: -r["total_crlf"])
    if "--json" in sys.argv:
        print(json.dumps(affected, indent=1))
        return 0
    print(f"=== CRLF build-script sweep: {len(affected)}/{len(slugs)} tools affected ===")
    for r in affected:
        sc = ", ".join(f"{k}:{v}" for k, v in sorted(r["scripts"].items(), key=lambda x: -x[1])[:4])
        print(f"  {r['slug'].split('__')[-1].split('.')[0]:24s} CRLF={r['total_crlf']:6d}  [{sc}]")
    print(f"\n  {len(affected)} tools have CRLF in a build script -- candidates for the class fix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
