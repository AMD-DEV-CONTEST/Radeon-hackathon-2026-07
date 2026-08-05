#!/usr/bin/env python3
"""programbench_inspect_tool.py - read a tool's tests and tell us exactly
what the scaffold needs to satisfy them, BEFORE we throw a generic scaffold
at it and burn 25 minutes waiting for a timeout.

Outputs per-tool requirements JSON with:
  - subprocess invocation patterns (args used by tests)
  - flag taxonomy (which flags appear as boolean vs taking values)
  - assertion classes (golden_file, substring, regex, returncode_only,
    structural, exact_bytes)
  - fixture types (mkfifo, threading, tmux/pty, network, tempfile, subprocess.Popen)
  - test count breakdown
  - feasibility verdict + recommended scaffold subtype

Usage:
  python scripts/programbench_inspect_tool.py <instance_id>
  python scripts/programbench_inspect_tool.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from collections import Counter
from pathlib import Path

HF_SNAPSHOT_ROOT = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "hub"
    / "datasets--programbench--ProgramBench-Tests"
    / "snapshots"
)

# Patterns that signal scaffold feature requirements
FIXTURE_PATTERNS = {
    "mkfifo": re.compile(r"\bos\.mkfifo\b|mkfifo\("),
    "threading": re.compile(r"\bthreading\.Thread\b|\bThread\(target"),
    "multiprocess": re.compile(r"\bmultiprocessing\.|\bProcess\(target"),
    "tmux": re.compile(r"\btmux\b|tui2cli"),
    "pty": re.compile(r"\bpty\.|\bptyprocess\b|\bspawn\("),
    "network_server": re.compile(r"socket\.\w*[lL]isten|HTTPServer|TCPServer|socket\.bind"),
    "fork": re.compile(r"\bos\.fork\b"),
    "popen_pipe": re.compile(r"subprocess\.Popen\b"),
    "subprocess_run": re.compile(r"subprocess\.run\b"),
    "tempfile": re.compile(r"\btempfile\b|tmp_path"),
    "git_init": re.compile(r"git\s+init|gitpython|Repo\(\.init"),
}

ASSERTION_PATTERNS = {
    "golden_file": re.compile(r"\.golden|read_text\(\)\s*(?:==|in)|(?:==|in)\s*\w+\.read_text\(\)"),
    "exact_stdout": re.compile(r"assert\s+result\.stdout\s*==\s*[bB]?[\"']"),
    "substring_in": re.compile(r"assert\s+[bB]?[\"'][^\"']+[\"']\s+in\s+\w*\.std"),
    "returncode_only": re.compile(r"assert\s+\w*\.returncode\s*==\s*\d+(?!\s*[,\)])"),
    "regex_match": re.compile(r"re\.(search|match|fullmatch)|assertRegex"),
    "json_parse": re.compile(r"json\.loads\(.*std|loads\(result"),
    "csv_parse": re.compile(r"csv\.reader|csv\.DictReader"),
    "structural": re.compile(r"len\(\w*\.\w*\)\s*==|len\(lines\)|cols\[\d+\]|fields\[\d+\]"),
    "long_compare": re.compile(r"== b?[\"'][^\"']{200,}[\"']"),
}

ARGV_INVOCATION_PATTERNS = [
    # Common ways tests invoke the executable
    re.compile(r"run\w*\s*\(\s*\[\s*([\"'][^\"']*[\"'](?:\s*,\s*[\"'][^\"']*[\"'])*)"),
    re.compile(r"subprocess\.\w+\(\s*\[\s*[\"'][^\"']*executable[^\"']*[\"']\s*,\s*([^\]]+)\]"),
    re.compile(r"run_executable\s*\(\s*([^)]+)\)"),
    re.compile(r"run_ag?\w*\s*\(\s*\[\s*([^\]]+)\]"),
]


def find_branch_tarballs(instance_id: str) -> list[Path]:
    snapshots = sorted(HF_SNAPSHOT_ROOT.iterdir()) if HF_SNAPSHOT_ROOT.is_dir() else []
    if not snapshots:
        return []
    tool_dir = snapshots[0] / instance_id / "tests"
    if not tool_dir.is_dir():
        return []
    return sorted(tool_dir.glob("*.tar.gz"))


def inspect_branch(tarball: Path) -> dict:
    """Return dict of {fixture: count, assertion: count, file_count: N, sample_invocations: [...]}."""
    fix = Counter()
    assertions = Counter()
    invocations = []
    test_count = 0
    files_scanned = 0
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            for m in tf.getmembers():
                if not m.isreg():
                    continue
                # Only inspect test files + run.sh + conftest
                if not (m.name.endswith(".py") or m.name.endswith("run.sh")):
                    continue
                if "test_resources" in m.name or m.name.endswith(".pyc"):
                    continue
                try:
                    fobj = tf.extractfile(m)
                    if fobj is None:
                        continue
                    data = fobj.read().decode("utf-8", errors="ignore")
                except Exception:
                    continue
                files_scanned += 1
                if "/test_" in m.name or m.name.endswith("/conftest.py"):
                    test_count += sum(
                        1 for _ in re.finditer(r"^\s*def\s+test_", data, re.MULTILINE)
                    )
                for name, regex in FIXTURE_PATTERNS.items():
                    if regex.search(data):
                        fix[name] += 1
                for name, regex in ASSERTION_PATTERNS.items():
                    n = len(regex.findall(data))
                    if n:
                        assertions[name] += n
                # Capture a few invocation samples
                for regex in ARGV_INVOCATION_PATTERNS:
                    for mm in regex.finditer(data):
                        sample = mm.group(1)[:200].replace("\n", " ").strip()
                        if sample and len(invocations) < 15:
                            invocations.append(sample)
    except Exception as e:
        return {"error": str(e)}
    return {
        "tarball": tarball.name,
        "files_scanned": files_scanned,
        "test_count": test_count,
        "fixtures": dict(fix),
        "assertions": dict(assertions),
        "invocations_sample": invocations[:10],
    }


def feasibility_verdict(branches: list[dict]) -> dict:
    """Aggregate across branches and produce a verdict."""
    total_fix = Counter()
    total_assert = Counter()
    total_tests = 0
    for b in branches:
        if "fixtures" in b:
            total_fix.update(b["fixtures"])
        if "assertions" in b:
            total_assert.update(b["assertions"])
        total_tests += b.get("test_count", 0)

    # High-risk fixtures that imply the generic scaffold won't satisfy
    risk_fixtures = [
        ("tmux", "TUI: tests drive the executable through tmux"),
        ("pty", "TUI: tests require pseudo-terminal interaction"),
        ("network_server", "Networking: tests bind sockets that scaffold can't fake"),
        ("multiprocess", "Multiprocess fixture: hard to replicate without real impl"),
    ]
    risks = [r for f, r in risk_fixtures if total_fix.get(f, 0) > 0]

    # Recommended scaffold path
    scaffold_hint = "generic_family"
    if total_assert.get("golden_file", 0) > total_tests * 0.3:
        scaffold_hint = "golden_file_heavy (need byte-exact reproduction)"
    elif total_assert.get("long_compare", 0) > 10:
        scaffold_hint = "golden_file_heavy"
    elif total_assert.get("json_parse", 0) > 0:
        scaffold_hint = "structured_output (json output mode)"
    elif total_assert.get("csv_parse", 0) > 0:
        scaffold_hint = "structured_output (csv output mode)"
    elif total_fix.get("git_init", 0) > 0:
        scaffold_hint = "git_wrappers subtype"
    elif total_fix.get("mkfifo", 0) > 0:
        scaffold_hint = "search_grep with walk_files FIFO fix (already shipped)"

    verdict = "feasible_with_generic"
    if risks:
        verdict = "needs_specific_subtype"
    if total_assert.get("golden_file", 0) > total_tests * 0.5:
        verdict = "golden_file_ceiling (per-tool byte-exact impl needed)"

    return {
        "test_count_total": total_tests,
        "fixtures_total": dict(total_fix),
        "assertions_total": dict(total_assert),
        "risks": risks,
        "scaffold_hint": scaffold_hint,
        "verdict": verdict,
    }


def inspect_tool(instance_id: str) -> dict:
    tarballs = find_branch_tarballs(instance_id)
    if not tarballs:
        return {"instance_id": instance_id, "error": "no test tarballs found"}
    # Inspect first 3 branches to keep cost bounded (or all if <= 3)
    branch_reports = [inspect_branch(t) for t in tarballs[:3]]
    verdict = feasibility_verdict(branch_reports)
    return {
        "instance_id": instance_id,
        "branches_inspected": len(branch_reports),
        "branches_available": len(tarballs),
        "per_branch": branch_reports,
        **verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("instances", nargs="*", help="instance IDs (default: a single tool)")
    ap.add_argument("--all", action="store_true", help="inspect all tools in mass_run_v2_base")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "logs"
        / "mass_run_v2"
        / "inspection_report.json",
        help="write per-tool reports to this JSON",
    )
    args = ap.parse_args()

    targets: list[str] = []
    if args.all:
        base = Path("T:/determinex-programbench/mass_run_v2_base")
        targets = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name != "_TASKS.txt")
    targets += args.instances

    reports = {}
    for inst in targets:
        rep = inspect_tool(inst)
        reports[inst] = rep
        v = rep.get("verdict", "?")
        hint = rep.get("scaffold_hint", "?")
        nt = rep.get("test_count_total", 0)
        risks = ",".join(rep.get("risks", []))
        print(f"{inst:<55} tests={nt:>4} verdict={v:<35} hint={hint}")
        if risks:
            print(f"  ! risks: {risks}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print()
    print(f"=== {len(reports)} reports written: {args.out} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
