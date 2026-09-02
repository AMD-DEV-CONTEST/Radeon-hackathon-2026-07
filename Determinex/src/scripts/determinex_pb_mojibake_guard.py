#!/usr/bin/env python3
"""
determinex_pb_mojibake_guard.py -- reject CRLF / BOM / mojibake / encoding corruption (Windows issues)
===================================================================================================
The CRLF lesson: `set -e\r` killed dash before any build and "compile_failed" lied for hours.
This makes that whole class IMPOSSIBLE to commit. Rejects, in tracked text files:
  * CRLF line endings in shell/script files (dash-breaking)
  * UTF-8 BOM at file start
  * U+FFFD replacement char (decode corruption)
  * classic mojibake sequences (UTF-8 mis-decoded as Latin-1: Ã©, â€™, â€œ, Ã¢, ...)
Run as a pre-commit hook over staged files, or `--all` to scan the tree.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT_EXT = (".sh", ".bash", ".zsh")
# Line endings these may legitimately keep -- never flag CRLF here.
_CRLF_OK_EXT = (".bat", ".cmd", ".ps1", ".sln", ".vcxproj")
_TEXT_EXT = (
    ".sh",
    ".bash",
    ".py",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".js",
    ".ts",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".txt",
)
_MOJIBAKE = ("Ã©", "â€™", "â€œ", "â€", "Ã¨", "Ã ", "Ã¼", "Â ", "â€“")


def _git_eol_rows(paths: list[str] | None = None) -> list[tuple[str, str, str, str]]:
    """(index_eol, worktree_eol, attr, path) for tracked files. Empty if not a git repo.

    `paths` is passed THROUGH to git as a pathspec rather than used to filter the result.
    That distinction is the whole fix: `git ls-files --eol` with no pathspec enumerates every
    tracked file, which here means the entire vendored corpus and takes over three minutes.
    Filtering afterwards costs exactly the same as not filtering at all -- the first attempt
    at this scoped the output and was still timing out at ten minutes.
    """
    cmd = ["git", "ls-files", "--eol"]
    if paths:
        cmd += ["--", *paths]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout
    except Exception:
        return []
    rows = []
    for ln in out.splitlines():
        # format: "i/lf    w/crlf  attr/text=auto   \tpath"
        head, _, path = ln.partition("\t")
        parts = head.split()
        if len(parts) >= 2 and path:
            attr = parts[2] if len(parts) >= 3 else ""
            rows.append((parts[0], parts[1], attr, path.strip()))
    return rows


def committed_crlf_violations(only: set[str] | None = None) -> list[str]:
    """Files whose INDEX (committed bytes) is CRLF but whose policy is LF. This is the real bug
    class -- worktree CRLF from autocrlf checkout is i/lf and is correctly never flagged.

    `only` restricts the result to a given set of repo-relative paths. `git ls-files --eol`
    enumerates every tracked file, which on this repo means walking the whole vendored corpus:
    measured at over 180 seconds. Running that on EVERY invocation made a single-file
    pre-commit check take three minutes, so a commit touching two files took ten -- which is
    the practical reason these hooks went unrun for so long. The full sweep still happens in
    --all / --crlf-report mode, where the cost is expected and paid once in CI.
    """
    bad = []
    for i_eol, _w, attr, path in _git_eol_rows(sorted(only) if only else None):
        if "crlf" not in i_eol and "mixed" not in i_eol:
            continue
        if path.lower().endswith(_CRLF_OK_EXT):
            continue
        if "-text" in attr:  # binary / explicitly un-normalized (sbom hashes etc.)
            continue
        bad.append(path)
    return bad


def crlf_report() -> int:
    """The massive corpus CRLF census: every committed-CRLF file, grouped by extension."""
    rows = _git_eol_rows()
    if not rows:
        print("crlf-report: not a git repo / git unavailable")
        return 0
    viol = committed_crlf_violations()
    wt_crlf = sum(1 for i, w, _a, _p in rows if "crlf" in w)
    print(f"CRLF census over {len(rows)} tracked files:")
    print(f"  committed (index) CRLF that should be LF : {len(viol)}   <- the real risk")
    print(f"  worktree CRLF (autocrlf checkout, i/lf)  : {wt_crlf}   (normal on Windows, harmless)")
    if viol:
        from collections import Counter

        by_ext = Counter(
            p[p.rfind(".") :] if "." in p.rsplit("/", 1)[-1] else "(noext)" for p in viol
        )
        print("  committed-CRLF violations by type:")
        for e, c in by_ext.most_common():
            print(f"     {e:10} {c}")
        for p in viol[:40]:
            print(f"     CRLF  {p}")
    else:
        print("  -> 0 committed-CRLF violations: corpus is clean (.gitattributes is holding).")
    return 1 if viol else 0


def fix_crlf() -> int:
    """Eradicate committed CRLF: re-apply .gitattributes normalization to the whole tree."""
    root = Path(__file__).resolve().parent.parent
    before = committed_crlf_violations()
    print(f"before: {len(before)} committed-CRLF violations")
    subprocess.run(["git", "add", "--renormalize", "."], cwd=root, check=False)
    after = committed_crlf_violations()
    print(f"after `git add --renormalize .`: {len(after)} remaining")
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True
    ).stdout.split()
    print(f"renormalized (staged) files: {len(staged)}")
    for f in staged[:40]:
        print(f"   staged  {f}")
    return 0


def check_file(p: Path) -> list[str]:
    try:
        raw = p.read_bytes()
    except Exception:
        return []
    issues = []
    if p.suffix in _SCRIPT_EXT and b"\r\n" in raw:
        issues.append("CRLF in shell script (dash breaks on `set -e\r`)")
    if raw[:3] == b"\xef\xbb\xbf":
        issues.append("UTF-8 BOM at file start")
    try:
        txt = raw.decode("utf-8")
        if "�" in txt:
            issues.append("U+FFFD replacement char (decode corruption)")
        for m in _MOJIBAKE:
            if m in txt:
                issues.append(f"mojibake sequence {m!r} (UTF-8 mis-decoded as Latin-1)")
                break
    except UnicodeDecodeError:
        issues.append("not valid UTF-8 (encoding corruption)")
    return issues


# ML/model artifacts have legitimate byte-level tokens that LOOK like mojibake; skip them.
_SKIP = (
    "fine_tuning",
    "outputs",
    "checkpoint",
    "tokenizer",
    "vocab",
    "merges",
    "node_modules",
    ".venv",
    "__pycache__",
    "/models/",
    "rosetta",
    "mojibake",
    "fix_mojibake",
    "/units/",
    "fixtures",
    "test_resources",
    "action_sheets",
    "/results/",
    ".d/",
    "input.",
    "expected.",
    "/golden",
)


def _skip(p):
    s = str(p).replace("\\", "/").lower()
    return any(k in s for k in _SKIP)


def main() -> int:
    if "--crlf-report" in sys.argv:
        return crlf_report()
    if "--fix-crlf" in sys.argv:
        return fix_crlf()
    args = [a for a in sys.argv[1:] if a != "--all" and not a.startswith("--")]
    scan_all = "--all" in sys.argv or not args
    if scan_all:
        files = [p for p in Path("scripts").rglob("*") if p.suffix in _TEXT_EXT and not _skip(p)]
        # tool-level Determinex-authored .sh only (compile.sh/reimpl_compile.sh/build*.sh) --
        # NOT nested vendor trees (source/, t/ test suites have legit non-UTF-8/CRLF fixtures).
        files += [
            p for p in Path("corpus/programbench/per_tool_overrides").glob("*/*.sh") if not _skip(p)
        ]
    else:
        files = [Path(a) for a in args if Path(a).suffix in _TEXT_EXT and not _skip(Path(a))]
    bad = {}
    for p in files:
        iss = check_file(p)
        if iss:
            bad[str(p)] = iss
    # committed-CRLF check is git-aware and independent of the per-file content scan. Scoped
    # to the given files when files were given, corpus-wide only in --all mode.
    scope = None if scan_all else {Path(a).as_posix() for a in args}
    for path in committed_crlf_violations(scope):
        bad.setdefault(path, []).append("committed CRLF (index) in an LF-policy file")
    if bad:
        print(f"MOJIBAKE/CRLF GUARD FAILED: {len(bad)} file(s) with encoding/line-ending issues:")
        for f, iss in list(bad.items())[:25]:
            print(f"  {f}: {'; '.join(iss)}")
        return 1
    print("mojibake/CRLF guard: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
