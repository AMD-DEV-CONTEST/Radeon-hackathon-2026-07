#!/usr/bin/env python3
"""
determinex_pb_conftest_fix.py -- validate + repair conftest corruption (the missing guard)
=======================================================================================
The blind spot the audit exposed: a submission's conftest can be syntactically BROKEN,
so pytest never loads -> no results.xml -> PB reports `results_read_failed` -> score 0,
with the real cause (a Python SyntaxError) hidden. The diagnosis layer only ever read
test_results (empty here), so it never SAW the broken conftest. This module is the guard.

Two corruption patterns, both from sloppy automated edits:
  A. ORPHANED CAP `if` -- cap-removal deleted the body of `if len(items) > N:` but left
     the dangling header -> IndentationError. (jq, the_silver_searcher, igrep.)
  B. STRAY LEADING COMMA -- a list edit left `, "x"` / `[ , ...` -> invalid syntax.
     (yq, cmatrix, diffr.)

`validate_conftest_text` parses it (ast). `repair_conftest_text` fixes both patterns
(the cap is forbidden anyway, so removing the orphaned header is correct). Wire
`validate_compile_conftest` as a PRE-EVAL gate so a broken conftest is SEEN + repaired,
never run blind into a mystery 0.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_CONFTEST_HEREDOC = re.compile(
    r"(cat\s*>\s*[^\n]*conftest\.py[^\n]*<<\s*'?(\w+)'?\n)(.*?)(\n\2)", re.DOTALL
)


def validate_conftest_text(body: str) -> tuple[bool, str]:
    try:
        ast.parse(body)
        return True, "ok"
    except SyntaxError as e:
        return False, f"{e.msg} @L{e.lineno}"


def repair_conftest_text(body: str) -> tuple[str, list[str]]:
    """Fix the two known corruption patterns. Returns (fixed_body, [fixes])."""
    lines = body.split("\n")
    fixes = []
    # Pattern A: orphaned `if len(items) > N:` (or any `if ...:`) with no indented body.
    out = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)if\b.*:\s*$", ln)
        if m:
            indent = len(m.group(1))
            # find next non-blank line
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            nxt_indent = len(lines[j]) - len(lines[j].lstrip()) if j < len(lines) else 0
            has_body = j < len(lines) and nxt_indent > indent
            if not has_body:
                fixes.append(f"removed orphaned `{ln.strip()}` (cap header w/o body)")
                continue  # drop the dangling if line
        out.append(ln)
    lines = out
    # Pattern B: stray leading comma in a list element line: `   , "x"` -> `   "x"`
    out = []
    for ln in lines:
        m = re.match(r"^(\s*),\s*(\S.*)$", ln)
        if m and not m.group(2).startswith("#"):
            fixes.append(f"removed stray leading comma: {ln.strip()[:40]}")
            ln = m.group(1) + m.group(2)
        out.append(ln)
    lines = out
    # also `[ ,` and `,,`
    fixed = "\n".join(lines)
    fixed2 = re.sub(r"\[\s*,", "[", fixed)
    fixed2 = re.sub(r",\s*,", ",", fixed2)
    if fixed2 != fixed:
        fixes.append("normalized list commas ([,/,,)")
    return fixed2, fixes


def validate_compile_conftest(compile_sh: Path) -> dict:
    """Validate (and optionally diagnose) every conftest heredoc in a compile.sh."""
    text = compile_sh.read_text(encoding="utf-8", errors="replace")
    results = []
    for m in _CONFTEST_HEREDOC.finditer(text):
        ok, why = validate_conftest_text(m.group(3))
        results.append({"ok": ok, "error": why})
    return {"conftests": len(results), "broken": [r for r in results if not r["ok"]]}


def repair_compile_conftest(compile_sh: Path, apply: bool = False) -> dict:
    """Repair broken conftest heredocs in a compile.sh. Returns the outcome."""
    text = compile_sh.read_text(encoding="utf-8", errors="replace")
    all_fixes = []
    changed = False

    def _sub(m):
        nonlocal changed
        body = m.group(3)
        ok, _ = validate_conftest_text(body)
        if ok:
            return m.group(0)
        fixed, fixes = repair_conftest_text(body)
        ok2, why2 = validate_conftest_text(fixed)
        if ok2 and fixed != body:
            changed = True
            all_fixes.extend(fixes)
            return m.group(1) + fixed + m.group(4)
        all_fixes.append(f"UNREPAIRED ({why2})")
        return m.group(0)

    new = _CONFTEST_HEREDOC.sub(_sub, text)
    if changed and apply:
        compile_sh.write_text(new, encoding="utf-8", newline="\n")
    return {"changed": changed, "fixes": all_fixes, "applied": bool(changed and apply)}


def repair_text(text: str) -> tuple[str, list[str]]:
    """Repair every conftest heredoc inside a compile.sh TEXT. Returns (new_text, fixes)."""
    fixes = []

    def _sub(m):
        body = m.group(3)
        ok, _ = validate_conftest_text(body)
        if ok:
            return m.group(0)
        fixed, fx = repair_conftest_text(body)
        ok2, _ = validate_conftest_text(fixed)
        if ok2 and fixed != body:
            fixes.extend(fx)
            return m.group(1) + fixed + m.group(4)
        return m.group(0)

    return _CONFTEST_HEREDOC.sub(_sub, text), fixes


def repair_submission_tarball(tar_path: Path) -> dict:
    """Repair the conftest inside a submission.tar.gz's compile.sh, in place.
    Extract members -> repair compile.sh conftest -> repack. Returns outcome."""
    import io
    import tarfile

    with tarfile.open(tar_path, "r:gz") as tin:
        members = tin.getmembers()
        data = {}
        for m in members:
            if m.isfile():
                f = tin.extractfile(m)
                data[m.name] = f.read() if f else b""
    fixes = []
    for name in list(data):
        if name.endswith("compile.sh"):
            txt = data[name].decode("utf-8", "replace")
            new, fx = repair_text(txt)
            if fx and new != txt:
                data[name] = new.encode("utf-8")
                fixes.extend(fx)
    if not fixes:
        return {"changed": False, "fixes": []}
    with tarfile.open(tar_path, "w:gz") as tout:
        for m in members:
            if m.isfile():
                m.size = len(data[m.name])
                tout.addfile(m, io.BytesIO(data[m.name]))
            else:
                tout.addfile(m)
    return {"changed": True, "fixes": fixes}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex conftest validate+repair")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")  # scan all overrides
    f = sub.add_parser("fix")
    f.add_argument("slug", nargs="?")  # fix one or all
    f.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    OV = Path(__file__).resolve().parent.parent / "corpus" / "programbench" / "per_tool_overrides"
    if args.cmd == "scan":
        broken = []
        for d in sorted(OV.iterdir()):
            cs = d / "compile.sh"
            if cs.exists():
                r = validate_compile_conftest(cs)
                if r["broken"]:
                    broken.append((d.name, r["broken"][0]["error"]))
        print(f"BROKEN conftests: {len(broken)}")
        for n, e in broken:
            print(f"  {n:44s} {e}")
        return 0
    if args.cmd == "fix":
        targets = [OV / args.slug] if args.slug else sorted(OV.iterdir())
        for d in targets:
            cs = d / "compile.sh"
            if not cs.exists():
                continue
            if validate_compile_conftest(cs)["broken"]:
                r = repair_compile_conftest(cs, apply=args.apply)
                print(f"{d.name}: {r['fixes']} applied={r['applied']}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
