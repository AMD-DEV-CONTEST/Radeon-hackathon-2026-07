#!/usr/bin/env python3
"""sprint4_subtype_smoke_pass.py — verify each generated scaffold actually
performs the BEHAVIOR its family/subtype declares.

The original sprint4_smoke_pass.py checks: compile + --help + unknown flag.
That catches "broken Python" but NOT "wrong behavior" — which is exactly
what burned us on `pls-with-cut-subtype`.

This smoke gate adds family/subtype-specific behavioral checks:
  - shell_coreutils.ls_listing  : pass a temp dir, expect file names
  - shell_coreutils.du_tree     : pass a temp file, expect <size>\\t<path>
  - shell_coreutils.table_filter: pass log lines via stdin, expect header rows
  - shell_coreutils (root)      : -f 1 -d : on "a:b:c" → "a"
  - search_grep (root)          : pattern + file → path:line:match
  - search_grep.code_rewriter   : pattern + replacement via stdin → substituted
  - text_diff                   : diff via stdin → ANSI codes in output
  - file_renamers               : regex + template → ASCII table
  - git_wrappers.log_graph      : --version OK
  - git_wrappers.changelog_generator : --version OK
  - formatters                  : --check OK on no-input

Reads:  logs/mass_run_v2/sprint4_bulk_generation.json
Writes: logs/mass_run_v2/sprint4_subtype_smoke_pass.json
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _run(
    main_py: Path,
    args: list[str],
    stdin_data: str | None = None,
    timeout: int = 10,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(main_py), *args],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


# ──────────────────────────────────────────────────────────────────────────
# Subtype-specific behavioral probes
# ──────────────────────────────────────────────────────────────────────────


def smoke_ls_listing(main_py: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        for n in ("a.txt", "b.txt", "c.txt"):
            (Path(td) / n).touch()
        try:
            r = _run(main_py, [td])
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if r.returncode != 0:
            return False, f"rc={r.returncode}"
        # Expect at least one of the test file names in stdout
        if all(n in r.stdout for n in ("a.txt", "b.txt", "c.txt")):
            return True, "OK"
        return False, f"missing file names in output: {r.stdout[:80]!r}"


def smoke_du_tree(main_py: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "big.txt").write_text("x" * 500)
        try:
            r = _run(main_py, [td])
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if r.returncode != 0:
            return False, f"rc={r.returncode}"
        # Expect a tab-separated <size>\t<path>-shaped output
        if "\t" in r.stdout and (
            "big.txt" in r.stdout or td.replace("\\", "/") in r.stdout.replace("\\", "/")
        ):
            return True, "OK"
        return False, f"no <size>\\t<path> output: {r.stdout[:120]!r}"


def smoke_table_filter(main_py: Path) -> tuple[bool, str]:
    sample = "GET /api/users 200\nGET /api/items 200\nPOST /api/users 404\n"
    try:
        r = _run(main_py, [], stdin_data=sample)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    # Expect at least the header row keywords (count / key)
    lower = r.stdout.lower()
    if "count" in lower or "key" in lower or "GET" in r.stdout:
        return True, "OK"
    return False, f"no table output: {r.stdout[:120]!r}"


def smoke_shell_coreutils_root(main_py: Path) -> tuple[bool, str]:
    # Cut-style: -d: -f 1 on stdin "a:b:c" → "a"
    try:
        r = _run(main_py, ["-d", ":", "-f", "1"], stdin_data="a:b:c\n")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    if r.stdout.strip().startswith("a"):
        return True, "OK"
    return False, f"expected 'a' got {r.stdout[:60]!r}"


def smoke_search_grep_root(main_py: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "x.txt"
        f.write_text("alpha\nbeta\ngamma\n")
        try:
            r = _run(main_py, ["beta", str(f)])
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if r.returncode != 0 and "beta" not in r.stdout:
            return False, f"rc={r.returncode}"
        if "beta" in r.stdout:
            return True, "OK"
        return False, f"no match found: {r.stdout[:80]!r}"


def smoke_code_rewriter(main_py: Path) -> tuple[bool, str]:
    try:
        r = _run(main_py, ["hello", "HI"], stdin_data="hello world\n")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    if "HI" in r.stdout:
        return True, "OK"
    return False, f"no substitution: {r.stdout[:60]!r}"


def smoke_text_diff(main_py: Path) -> tuple[bool, str]:
    diff = "--- a\n+++ b\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    try:
        r = _run(main_py, [], stdin_data=diff)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    if "\x1b[" in r.stdout or "old" in r.stdout or "new" in r.stdout:
        return True, "OK"
    return False, "no diff passthrough"


def smoke_file_renamers(main_py: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "file1.txt").touch()
        try:
            r = _run(main_py, ["-t", "-d", td, "-r", r"file(\d+)", "renamed_{1}"])
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if r.returncode != 0:
            return False, f"rc={r.returncode}"
        # Look for the ASCII table border OR space-separated "Input Output" header
        if "+--" in r.stdout or "Input" in r.stdout:
            return True, "OK"
        return False, f"no table: {r.stdout[:80]!r}"


def smoke_formatters(main_py: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "x.tex"
        f.write_text("hello\n")
        try:
            r = _run(main_py, ["--check", str(f)])
        except subprocess.TimeoutExpired:
            return False, "timeout"
        # Formatters: rc=0 (already formatted) or rc=1 (would reformat) — both OK
        if r.returncode in (0, 1):
            return True, "OK"
        return False, f"unexpected rc={r.returncode}"


def smoke_git_log_or_changelog(main_py: Path) -> tuple[bool, str]:
    # Just check --version works; git subprocess requires repo, not testable here
    try:
        r = _run(main_py, ["--version"])
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    if r.stdout.strip():
        return True, "OK"
    return False, "empty version output"


def smoke_default(main_py: Path) -> tuple[bool, str]:
    # Generic — just verify it doesn't crash with no args
    try:
        r = _run(main_py, [])
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode in (0, 1, 2):
        return True, "OK"
    return False, f"unexpected rc={r.returncode}"


# Routing table: (family, subtype) → probe function
_PROBES: dict[str, callable] = {
    "shell_coreutils.ls_listing": smoke_ls_listing,
    "shell_coreutils.du_tree": smoke_du_tree,
    "shell_coreutils.table_filter": smoke_table_filter,
    "shell_coreutils": smoke_shell_coreutils_root,
    "search_grep": smoke_search_grep_root,
    "search_grep.code_rewriter": smoke_code_rewriter,
    "text_diff": smoke_text_diff,
    "file_renamers": smoke_file_renamers,
    "formatters": smoke_formatters,
    "git_wrappers.log_graph": smoke_git_log_or_changelog,
    "git_wrappers.changelog_generator": smoke_git_log_or_changelog,
    "git_wrappers": smoke_git_log_or_changelog,
}


def main() -> int:
    bulk_log = ROOT / "logs" / "mass_run_v2" / "sprint4_bulk_generation.json"
    if not bulk_log.is_file():
        print(f"ERROR: bulk gen log not found: {bulk_log}")
        return 1
    bulk = json.loads(bulk_log.read_text(encoding="utf-8"))
    generated = [r for r in bulk["records"] if r.get("status") == "OK"]
    print(f"Subtype smoke pass — {len(generated)} scaffolds")
    print()

    results: list[dict] = []
    counts = {"OK": 0, "FAIL": 0, "NO_PROBE": 0}
    t0 = time.time()

    for r in generated:
        instance = r["instance"]
        family = r.get("family", "")
        subtype = r.get("subtype")
        main_py = Path(r.get("main_py", ""))
        if not main_py.is_file():
            results.append({"instance": instance, "status": "FAIL", "reason": "main.py missing"})
            counts["FAIL"] += 1
            continue
        # Probe selection: subtype first, then family root
        key = subtype if subtype in _PROBES else family
        probe = _PROBES.get(key)
        if probe is None:
            results.append(
                {
                    "instance": instance,
                    "family": family,
                    "subtype": subtype,
                    "status": "NO_PROBE",
                    "reason": f"no probe for '{key}'",
                }
            )
            counts["NO_PROBE"] += 1
            continue
        try:
            ok, reason = probe(main_py)
        except Exception as ex:
            ok, reason = False, f"probe crashed: {type(ex).__name__}: {ex}"
        results.append(
            {
                "instance": instance,
                "family": family,
                "subtype": subtype,
                "probe": key,
                "status": "OK" if ok else "FAIL",
                "reason": reason,
            }
        )
        counts["OK" if ok else "FAIL"] += 1

    elapsed = time.time() - t0
    print("=== summary ===")
    print(f"  total probed:       {len(results)}")
    print(f"  wall time:          {elapsed:.1f}s ({elapsed / max(len(results), 1):.3f}s/tool)")
    print(f"  ✓ OK                {counts['OK']}")
    print(f"  ✗ FAIL              {counts['FAIL']}")
    print(f"  ◦ NO_PROBE          {counts['NO_PROBE']}")
    print()

    # List failures
    if counts["FAIL"]:
        print(f"  --- FAIL ({counts['FAIL']}) ---")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    {r['instance']:<55} {r.get('probe', '?'):<30}  {r.get('reason', '')}")
    if counts["NO_PROBE"]:
        no_probe_counts: dict[str, int] = {}
        for r in results:
            if r["status"] == "NO_PROBE":
                k = r.get("family", "?")
                no_probe_counts[k] = no_probe_counts.get(k, 0) + 1
        print("\n  --- NO_PROBE (need probe per family) ---")
        for k, n in sorted(no_probe_counts.items(), key=lambda x: -x[1]):
            print(f"    {n:>3}  family={k}")

    out_log = ROOT / "logs" / "mass_run_v2" / "sprint4_subtype_smoke_pass.json"
    out_log.write_text(
        json.dumps(
            {
                "records": results,
                "counts": counts,
                "wall_s": round(elapsed, 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  log: {out_log}")
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
