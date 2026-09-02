#!/usr/bin/env python3
"""pb_fetch_source — make the corpus COMPLETE for the source_gap class.

Many PB submissions ship incomplete source (a Rust workspace member, a configure script,
a header dir) that the local per_tool_overrides is ALSO missing -> build fails. The fix is
to fetch the exact pinned upstream source and restore the missing files.

The slug encodes everything: `author__tool.SHA` => github.com/author/tool @ commit SHA
(verified: zevv__duc.a58fa4e == repository zevv/duc, commit a58fa4e...). So no task.yaml
lookup is needed.

For each tool: shallow-clone the repo at the pinned commit, then copy every upstream file
into per_tool_overrides that is MISSING there -- WITHOUT clobbering our build customizations
(compile.sh, conftest.py, executable, submission.tar.gz, *.bak). Result: complete pristine
source + our build script preserved. Then repack so the corpus carries it.

Usage:
  python scripts/pb_fetch_source.py <slug> [<slug>...]
  python scripts/pb_fetch_source.py --gap   # all source_gap tools from build_knowledge.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import determinex_pb_autofix as A  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# our injected files — never overwrite these with upstream
PRESERVE = {"compile.sh", "conftest.py", "executable", "submission.tar.gz", "pytest.ini"}
PRESERVE_SUFFIX = (".bak", ".autofix.bak", ".tar.gz")


def slug_to_repo(slug: str) -> tuple[str, str]:
    """author__tool.SHA -> ('author/tool', 'SHA'). tool may contain extra dots before SHA."""
    author, rest = slug.split("__", 1)
    if "." in rest:
        tool, sha = rest.rsplit(".", 1)
    else:
        tool, sha = rest, ""
    return f"{author}/{tool}", sha


def fetch_into(slug: str) -> dict:
    od = A.OVERRIDES / slug
    if not od.is_dir():
        cands = [d for d in A.OVERRIDES.iterdir() if d.is_dir() and slug in d.name]
        if not cands:
            return {"slug": slug, "ok": False, "why": "no per_tool_overrides dir"}
        od = cands[0]
        slug = od.name
    repo, sha = slug_to_repo(slug)
    url = f"https://github.com/{repo}.git"
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td) / "src"
        # shallow clone then fetch the exact commit (works even if not a branch tip)
        r = subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(tdp)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            return {"slug": slug, "ok": False, "why": f"clone failed: {r.stderr[-160:]}"}
        co = subprocess.run(
            ["git", "-C", str(tdp), "checkout", sha], capture_output=True, text=True, timeout=300
        )
        if co.returncode != 0:
            # try fetch the specific commit then checkout
            subprocess.run(
                ["git", "-C", str(tdp), "fetch", "--depth", "1", "origin", sha],
                capture_output=True,
                timeout=300,
            )
            co = subprocess.run(
                ["git", "-C", str(tdp), "checkout", sha],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if co.returncode != 0:
                return {
                    "slug": slug,
                    "ok": False,
                    "why": f"checkout {sha} failed: {co.stderr[-160:]}",
                }
        # copy upstream files that are MISSING locally (don't clobber our files)
        restored = 0
        for up in tdp.rglob("*"):
            if ".git" in up.parts:
                continue
            rel = up.relative_to(tdp)
            if rel.parts and rel.parts[0] == ".git":
                continue
            dest = od / rel
            if up.is_dir():
                continue
            if dest.name in PRESERVE or dest.name.endswith(PRESERVE_SUFFIX):
                continue
            # Restore upstream source: add missing AND overwrite stale-incomplete files (e.g.
            # a workspace root Cargo.toml the submission shipped truncated -> jsonschema
            # 'workspace.package.rust-version was not defined'). Preserve only our injected
            # files (above). This makes the source truly complete + pristine.
            if (not dest.exists()) or (dest.is_file() and dest.read_bytes() != up.read_bytes()):
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(up, dest)
                    restored += 1
                except Exception:
                    pass
        A.pack_submission(slug)
        return {"slug": slug, "ok": True, "repo": repo, "sha": sha, "restored_files": restored}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--gap", action="store_true", help="all source_gap tools from build_knowledge")
    args = ap.parse_args()
    slugs = list(args.slugs)
    if args.gap:
        k = A.load_knowledge()
        for t, info in (k.get("per_tool") or {}).items():
            if "source-gap" in str(info.get("status", "")) or "missing-source" in str(
                info.get("status", "")
            ):
                # resolve to a full override dir name
                cands = [
                    d.name
                    for d in A.OVERRIDES.iterdir()
                    if d.is_dir()
                    and (d.name == t or d.name.split("__")[-1].split(".")[0] == t.split("__")[-1])
                ]
                slugs.append(cands[0] if cands else t)
    for slug in slugs:
        print(json.dumps(fetch_into(slug)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
