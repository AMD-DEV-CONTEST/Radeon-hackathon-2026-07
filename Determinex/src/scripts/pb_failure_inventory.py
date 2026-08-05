#!/usr/bin/env python3
"""Build a ProgramBench local failure inventory for one tool.

The output is designed to be handed to another coding model or used directly
for hand-test iteration: exact failing node, source snippet, failure text, and
a simple cluster label.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


OVERRIDES_DIR = ROOT / "corpus/programbench/per_tool_overrides"
OUT_DIR = ROOT / "logs/programbench_failure_inventory"
PYTEST_TIMEOUT_S = 180
EXTRACTED_TESTS_ROOT = Path("T:/determinex-programbench/_extracted_tests")
_EXE_VAR_NAMES = (
    "EXECUTABLE",
    "EXE",
    "BINARY",
    "EXEC",
    "EXEPATH",
    "EXECUTABLE_PATH",
    "BIN",
    "CLI",
    "CLI_PATH",
    "PROGRAM",
)


def base_slug(slug: str) -> str:
    parts = slug.split(".")
    if len(parts) >= 2 and len(parts[-1]) in (7, 8, 12):
        return ".".join(parts[:-1])
    return slug


def find_override(slug: str) -> Path | None:
    direct = OVERRIDES_DIR / slug / "main.py"
    if direct.is_file():
        return direct
    base = base_slug(slug).lower()
    for path in OVERRIDES_DIR.iterdir():
        if path.is_dir() and base_slug(path.name).lower() == base:
            main = path / "main.py"
            if main.is_file():
                return main
    return None


def find_extracted_branches(slug: str) -> list[Path]:
    """Find extracted test branches for a ProgramBench slug."""
    base = slug.split(".")[0] if "." in slug else slug
    direct = EXTRACTED_TESTS_ROOT / slug
    if direct.is_dir():
        return [b for b in direct.iterdir() if b.is_dir() and (b / "eval/tests").is_dir()]
    if not EXTRACTED_TESTS_ROOT.is_dir():
        return []
    for path in EXTRACTED_TESTS_ROOT.iterdir():
        if path.is_dir() and path.name.startswith(base + "."):
            return [b for b in path.iterdir() if b.is_dir() and (b / "eval/tests").is_dir()]
    return []


def _patch_runner(path: Path, candidate: Path) -> str | None:
    """Patch common ProgramBench test runner variables to invoke candidate."""
    if not path.is_file():
        return None
    orig = path.read_text(encoding="utf-8", errors="replace")
    patched = orig
    if "import sys" not in patched[:300]:
        patched = "import sys\n" + patched
    if "from pathlib import Path" not in patched[:600]:
        patched = "from pathlib import Path as _DeterminexPath\n" + patched
        path_cls = "_DeterminexPath"
    else:
        path_cls = "Path"

    candidate_str = candidate.as_posix()
    sys_exe_str = Path(sys.executable).as_posix()
    for var_name in _EXE_VAR_NAMES:
        pattern = rf"^{var_name}\s*=\s*[^\n]+$"
        repl = f'{var_name} = {path_cls}(r"{candidate_str}")'
        patched = re.sub(pattern, lambda _m: repl, patched, count=1, flags=re.M)
        patched = re.sub(
            rf"subprocess\.run\(\s*\[\s*{var_name}\b",
            lambda _m, v=var_name: f"subprocess.run([sys.executable, str({v})",
            patched,
        )
        patched = re.sub(
            rf"subprocess\.run\(\s*\[\s*str\(\s*{var_name}\s*\)",
            lambda _m, v=var_name: f"subprocess.run([sys.executable, str({v})",
            patched,
        )
        patched = re.sub(
            rf"=\s*\[\s*str\(\s*{var_name}\s*\)\s*,",
            lambda _m, v=var_name: f"= [sys.executable, str({v}),",
            patched,
        )
        patched = re.sub(
            rf"=\s*\[\s*{var_name}\s*,",
            lambda _m, v=var_name: f"= [sys.executable, str({v}),",
            patched,
        )

    patched = patched.replace('["./executable",', f'[sys.executable, r"{candidate_str}",')
    patched = patched.replace("['./executable',", f"[sys.executable, r'{candidate_str}',")
    patched = patched.replace('"./executable ', f'"{sys_exe_str} {candidate_str} ')
    if patched == orig:
        return None
    path.write_text(patched, encoding="utf-8", newline="\n")
    return orig


def patch_test_tree(tests_dir: Path, candidate: Path) -> list[tuple[Path, str]]:
    patch_targets = [tests_dir / "utils.py", tests_dir / "conftest.py"]
    patch_targets.extend(sorted(tests_dir.glob("test_*.py")))
    originals: list[tuple[Path, str]] = []
    for patch_target in patch_targets:
        original = _patch_runner(patch_target, candidate)
        if original is not None:
            originals.append((patch_target, original))
    return originals


def restore(originals: list[tuple[Path, str]]) -> None:
    for path, original in originals:
        path.write_text(original, encoding="utf-8", newline="\n")


def write_exe_shim(eval_dir: Path, candidate: Path) -> tuple[Path, bool]:
    exe_shim = eval_dir / "executable"
    had_exe = exe_shim.exists()
    if not had_exe:
        exe_shim.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    return exe_shim, had_exe


def cleanup_exe_shim(exe_shim: Path, had_exe: bool) -> None:
    if not had_exe and exe_shim.exists():
        try:
            exe_shim.unlink()
        except Exception:
            pass


def parse_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0}
    for key, pattern in (
        ("passed", r"(\d+) passed"),
        ("failed", r"(\d+) failed"),
        ("error", r"(\d+) error"),
        ("skipped", r"(\d+) skipped"),
    ):
        if match := re.search(pattern, output):
            counts[key] = int(match.group(1))
    counts["total"] = counts["passed"] + counts["failed"] + counts["error"] + counts["skipped"]
    return counts


def classify_failure(node: str, text: str) -> str:
    hay = f"{node}\n{text}".lower()
    if "help" in hay or "usage" in hay or "golden" in hay:
        return "help-golden"
    if "version" in hay:
        return "version"
    if "unknown" in hay or "unexpected argument" in hay:
        return "unknown-flag"
    if "missing" in hay or "required" in hay or "at least one" in hay:
        return "missing-arg"
    if "color" in hay:
        return "color"
    if "json" in hay:
        return "json-output"
    if "stdout" in hay or "stderr" in hay or "string" in hay or "assert" in hay:
        return "output-mismatch"
    if "returncode" in hay or "exit" in hay:
        return "rc-mismatch"
    return "other"


def extract_failure_blocks(output: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    seen: set[str] = set()
    lines = output.splitlines()
    for idx, line in enumerate(lines):
        match = re.match(r"FAILED\s+(.+?)\s+-\s+(.+)", line)
        if not match:
            continue
        node = match.group(1)
        seen.add(node)
        message = match.group(2)
        context = "\n".join(lines[max(0, idx - 8) : min(len(lines), idx + 8)])
        failures.append(
            {
                "node": node,
                "message": message,
                "context": context,
                "cluster": classify_failure(node, f"{message}\n{context}"),
            }
        )
    for idx, line in enumerate(lines):
        match = re.match(r"FAILED\s+(\S+)\s*$", line)
        if not match:
            continue
        node = match.group(1)
        if node in seen:
            continue
        context = "\n".join(lines[max(0, idx - 8) : min(len(lines), idx + 8)])
        failures.append(
            {
                "node": node,
                "message": "",
                "context": context,
                "cluster": classify_failure(node, context),
            }
        )
    return failures


def locate_test_source(tests_dir: Path, node: str) -> str:
    file_part = node.split("::", 1)[0]
    fn_name = node.split("::")[-1].split("[", 1)[0]
    path = tests_dir / file_part
    if not path.is_file():
        matches = list(tests_dir.glob(f"**/{file_part}"))
        path = matches[0] if matches else path
    if not path.is_file():
        return ""
    source = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"def {re.escape(fn_name)}\b.*?(?=\ndef |\nclass |\Z)", source, re.S)
    return (match.group(0) if match else source)[:4000]


def inventory_tool(slug: str, candidate: Path, branch_limit: int) -> dict[str, Any]:
    branches = find_extracted_branches(slug)
    if branch_limit > 0:
        branches = branches[:branch_limit]
    out: dict[str, Any] = {
        "slug": slug,
        "candidate": str(candidate),
        "branches": [],
        "summary": {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0},
        "failures": [],
    }
    for branch in branches:
        eval_dir = branch / "eval"
        tests_dir = eval_dir / "tests"
        if not tests_dir.is_dir():
            continue
        originals = patch_test_tree(tests_dir, candidate)
        exe_shim, had_exe = write_exe_shim(eval_dir, candidate)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(tests_dir),
                    "-q",
                    "--tb=short",
                    "--no-header",
                    "-p",
                    "no:cacheprovider",
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=PYTEST_TIMEOUT_S,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            counts = parse_counts(output)
            for key in ("passed", "failed", "error", "skipped", "total"):
                out["summary"][key] += counts[key]
            branch_failures = extract_failure_blocks(output)
            for failure in branch_failures:
                failure["branch"] = branch.name
                failure["source"] = locate_test_source(tests_dir, failure["node"])
            out["branches"].append(
                {
                    "branch": branch.name,
                    "returncode": proc.returncode,
                    "counts": counts,
                    "patched_files": [str(path) for path, _ in originals],
                    "failure_count": len(branch_failures),
                }
            )
            out["failures"].extend(branch_failures)
        finally:
            restore(originals)
            cleanup_exe_shim(exe_shim, had_exe)
    clusters: dict[str, int] = {}
    for failure in out["failures"]:
        clusters[failure["cluster"]] = clusters.get(failure["cluster"], 0) + 1
    out["clusters"] = dict(sorted(clusters.items(), key=lambda kv: (-kv[1], kv[0])))
    return out


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"# Failure Inventory: {report['slug']}",
        "",
        f"Candidate: `{report['candidate']}`",
        "",
        "## Summary",
        "",
        "```text",
        json.dumps(report["summary"], indent=2),
        "```",
        "",
        "## Clusters",
        "",
    ]
    for cluster, count in report["clusters"].items():
        lines.append(f"- `{cluster}`: {count}")
    lines.extend(["", "## Failures", ""])
    for idx, failure in enumerate(report["failures"], 1):
        lines.extend(
            [
                f"### {idx}. `{failure['node']}`",
                "",
                f"- branch: `{failure['branch']}`",
                f"- cluster: `{failure['cluster']}`",
                f"- message: `{failure['message']}`",
                "",
                "Test source:",
                "```python",
                failure.get("source", ""),
                "```",
                "",
                "Failure context:",
                "```text",
                failure.get("context", ""),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--branch-limit", type=int, default=3, help="0 means all branches")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    candidate = args.candidate or find_override(args.slug)
    if candidate is None:
        print(f"no candidate/override found for {args.slug}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = inventory_tool(args.slug, candidate, args.branch_limit)
    json_path = args.out_dir / f"{args.slug}.inventory.json"
    md_path = args.out_dir / f"{args.slug}.inventory.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    summary = report["summary"]
    print(
        f"{args.slug}: {summary['passed']}/{summary['total']} passed; "
        f"{len(report['failures'])} failed nodes; clusters={report['clusters']}"
    )
    print(f"json: {json_path}")
    print(f"md:   {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
