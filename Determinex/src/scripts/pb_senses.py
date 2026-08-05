#!/usr/bin/env python3
"""pb_senses.py — artifact-only not_run classifier for ProgramBench.

Classifies every non-passing test in an eval_report.json into one of:
  upstream-skip    skip/skipif marker in test source OR skip reason in report
  collection-gap   in tests.json but absent from JUnit XML (import/collection error)
  pty-gap          TTY/tmux/isatty/ioctl/terminal-size signatures in test source or failure
  image-plumbing   ENOENT on harness paths, /workspace/executable refs, hash_executable_failed
  real-fail        collected, ran, assertion mismatch
  unclassified     driver must adjudicate manually

Boundary: classification uses artifacts and test source ONLY.
Confirming upstream-skip (reference binary vs same tests) is the separate,
heavier reference-diff step — this script proposes, driver confirms.
NEVER uses static-RE on reference binaries. pb_senses_guard.py enforces.

Usage:
  python scripts/pb_senses.py --eval <eval_report.json>
                               [--tests <tests.json>]
                               [--junit <results.xml>]
                               [--test-src <dir-with-test-py-files>]
                               [--out <senses_report.json>]
                               [--summary]

Output: senses_report.json at --out path (default: <eval_report_dir>/senses_report.json)
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Classification keyword patterns ────────────────────────────────────────────

_PTY_PATTERNS = re.compile(
    # Terminal API names (case-insensitive — these rarely appear in non-PTY contexts)
    r"\b(tmux|pexpect|isatty|ioctl|terminal[-_]size|curses|ncurses"
    r"|tigetstr|setupterm|blessed|asciimatics|termios|getwinsize|TIOCGWINSZ)\b"
    # Device paths and pty module (anchored to avoid matching in prose)
    r"|/dev/(?:tty|pty)\b"
    r"|\bpty\b",
    re.IGNORECASE,
)

_IMAGE_PLUMBING_PATTERNS = re.compile(
    r"(hash_executable_failed"
    r"|/workspace/executable"
    r"|No such file or directory.*executable"
    r"|executable.*No such file or directory"
    r"|ENOENT.*executable"
    r"|executable.*ENOENT"
    r"|/usr/local/bin/[a-z_\-]+ not found"
    r"|rc=127"
    r"|exit status 127"
    r"|command not found.*executable)",
    re.IGNORECASE,
)

_SKIP_PATTERNS = re.compile(
    r"(pytest\.mark\.skip|skipif|@pytest\.mark\.skip"
    r"|unittest\.skip|@skip\b"
    r"|Skip\(\"|skip\(\"|SkipTest"
    r"|too slow|Too slow|manually disabled|requires root"
    r"|requires network|no network|platform.system|sys\.platform)",
    re.IGNORECASE,
)

_COLLECTION_ERROR_PATTERNS = re.compile(
    r"(ImportError|ModuleNotFoundError|SyntaxError|NameError.*collect"
    r"|ERROR collecting|collection error|import.*failed"
    r"|cannot import|No module named)",
    re.IGNORECASE,
)

_REAL_FAIL_INDICATORS = re.compile(
    r"(AssertionError|assert |FAILED|FAIL\b|Expected.*got|got.*expected"
    r"|mismatch|differs?|!=|wrong output|test_.*failed)",
    re.IGNORECASE,
)


def load_eval_report(path: Path) -> dict:
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def load_tests_json(path: Path) -> dict[str, list[str]]:
    """Returns mapping: test_id -> list of branch hashes it belongs to."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = json.load(f)
    result: dict[str, list[str]] = {}
    branches = raw.get("branches", {})
    for branch_hash, branch_data in branches.items():
        tests = branch_data.get("tests", [])
        for t in tests:
            tid = t if isinstance(t, str) else t.get("id", "")
            if tid:
                result.setdefault(tid, []).append(branch_hash)
    return result


def load_junit_xml(path: Path) -> dict[str, dict]:
    """Returns mapping: test_id -> {status, message, text}."""
    result: dict[str, dict] = {}
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return result
    suites = [root] if root.tag in ("testsuite", "testsuites") else []
    if root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
    for suite in suites:
        for tc in suite.findall(".//testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            tid = f"{classname}.{name}" if classname else name
            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")
            if failure is not None:
                result[tid] = {
                    "status": "failure",
                    "message": failure.get("message", ""),
                    "text": failure.text or "",
                }
            elif error is not None:
                result[tid] = {
                    "status": "error",
                    "message": error.get("message", ""),
                    "text": error.text or "",
                }
            elif skipped is not None:
                result[tid] = {
                    "status": "skipped",
                    "message": skipped.get("message", ""),
                    "text": skipped.text or "",
                }
            else:
                result[tid] = {"status": "passed", "message": "", "text": ""}
    return result


def load_test_sources(test_src_dir: Path) -> dict[str, str]:
    """Returns mapping: filename_stem -> file content."""
    result: dict[str, str] = {}
    if not test_src_dir.exists():
        return result
    for py_file in test_src_dir.rglob("test_*.py"):
        try:
            result[py_file.stem] = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return result


def find_test_source(test_id: str, sources: dict[str, str]) -> str | None:
    """Try to find the source file content for a given test_id."""
    # test_id format: eval.tests.test_foo.TestClass::test_method or similar
    parts = test_id.replace("::", ".").split(".")
    # Look for a file whose stem matches any part of the test id
    for part in parts:
        if part.startswith("test_"):
            if part in sources:
                return sources[part]
    # Fall back: look for any source that contains the test function name
    func_name = parts[-1] if parts else ""
    if func_name:
        for content in sources.values():
            if f"def {func_name}" in content:
                return content
    return None


def classify_test(
    result: str,
    reason: str | None,
    junit_entry: dict | None,
    source_content: str | None,
) -> tuple[str, str]:
    """Returns (classification, evidence_line)."""

    reason_text = (reason or "").strip()
    junit_msg = ""
    junit_text = ""
    if junit_entry:
        junit_msg = junit_entry.get("message", "")
        junit_text = junit_entry.get("text", "")

    combined_failure_text = f"{reason_text} {junit_msg} {junit_text}"

    # ── skipped ──────────────────────────────────────────────────────────────
    if result == "skipped":
        m = _SKIP_PATTERNS.search(combined_failure_text)
        if m:
            return "upstream-skip", f"skip marker in report: '{m.group(0)}'"
        if source_content:
            m = _SKIP_PATTERNS.search(source_content)
            if m:
                return "upstream-skip", f"skip marker in test source: '{m.group(0)}'"
        return "unclassified", f"skipped but no skip marker found; reason='{reason_text[:120]}'"

    # ── not_run ──────────────────────────────────────────────────────────────
    if result == "not_run":
        # Check image-plumbing first (rc=127, ENOENT on executable)
        m = _IMAGE_PLUMBING_PATTERNS.search(combined_failure_text)
        if m:
            return "image-plumbing", f"harness path error: '{m.group(0)[:100]}'"

        # Not in JUnit XML at all → collection-gap
        if junit_entry is None:
            # Check test source for PTY signatures → pty-gap
            if source_content:
                m = _PTY_PATTERNS.search(source_content)
                if m:
                    return "pty-gap", f"PTY signature in test source: '{m.group(0)}'"
            # Check failure text for collection errors
            m = _COLLECTION_ERROR_PATTERNS.search(combined_failure_text)
            if m:
                return "collection-gap", f"collection error: '{m.group(0)[:100]}'"
            # No JUnit entry = absent from XML = collection-gap by definition
            return "collection-gap", "absent from JUnit XML (not collected)"

        # In JUnit but not_run → check context
        if source_content:
            m = _PTY_PATTERNS.search(source_content)
            if m:
                return "pty-gap", f"PTY signature in test source: '{m.group(0)}'"
        m = _PTY_PATTERNS.search(combined_failure_text)
        if m:
            return "pty-gap", f"PTY signature in failure text: '{m.group(0)}'"

        return "unclassified", f"not_run but in JUnit; reason='{reason_text[:120]}'"

    # ── failure ───────────────────────────────────────────────────────────────
    if result in ("failure", "error"):
        # Image-plumbing: ENOENT / missing executable
        m = _IMAGE_PLUMBING_PATTERNS.search(combined_failure_text)
        if m:
            return "image-plumbing", f"harness path error: '{m.group(0)[:100]}'"

        # PTY gap
        m = _PTY_PATTERNS.search(combined_failure_text)
        if m:
            return "pty-gap", f"PTY keyword in failure text: '{m.group(0)}'"
        if source_content:
            m = _PTY_PATTERNS.search(source_content)
            if m:
                return "pty-gap", f"PTY signature in test source: '{m.group(0)}'"

        # Upstream skip expressed as failure
        m = _SKIP_PATTERNS.search(combined_failure_text)
        if m:
            return "upstream-skip", f"skip marker in failure text: '{m.group(0)}'"

        # Real assertion failure
        if _REAL_FAIL_INDICATORS.search(combined_failure_text):
            snippet = combined_failure_text[:150].replace("\n", " ")
            return "real-fail", f"assertion failure: '{snippet}'"

        # Fallback real-fail
        snippet = combined_failure_text[:150].replace("\n", " ")
        return "real-fail", f"failure with text: '{snippet}'"

    return "unclassified", f"result='{result}' unhandled; reason='{reason_text[:80]}'"


def normalize_entry(entry: dict) -> tuple[str, str, str]:
    """Normalize eval_report entry to (test_id, result, reason).

    Handles two known formats:
    - Format A (old): {test_id, result, reason}
    - Format B (PB current): {name, status, branch, extra:{message, text, error_code}}
    """
    # Format B detection: 'name' + 'status' present
    if "name" in entry and "status" in entry:
        test_id = entry["name"]
        result = entry["status"]
        extra = entry.get("extra") or {}
        # Combine error_code + message + text into reason
        parts = []
        if extra.get("error_code"):
            parts.append(extra["error_code"])
        if extra.get("message"):
            parts.append(extra["message"])
        if extra.get("text"):
            parts.append(extra["text"])
        reason = " ".join(parts)
        return test_id, result, reason
    # Format A fallback
    test_id = entry.get("test_id", "")
    result = entry.get("result", "unknown")
    reason = entry.get("reason") or entry.get("message") or ""
    return test_id, result, reason


def run_senses(
    eval_path: Path,
    tests_path: Path | None,
    junit_path: Path | None,
    test_src_dir: Path | None,
    out_path: Path | None,
    summary_only: bool = False,
) -> dict:
    eval_data = load_eval_report(eval_path)
    test_results = eval_data.get("test_results", [])

    tests_map: dict[str, list[str]] = {}
    if tests_path and tests_path.exists():
        tests_map = load_tests_json(tests_path)

    junit_map: dict[str, dict] = {}
    if junit_path and junit_path.exists():
        junit_map = load_junit_xml(junit_path)

    sources: dict[str, str] = {}
    if test_src_dir and test_src_dir.exists():
        sources = load_test_sources(test_src_dir)

    # Build per-test classification
    classified: list[dict] = []
    histogram: dict[str, int] = {
        "upstream-skip": 0,
        "collection-gap": 0,
        "pty-gap": 0,
        "image-plumbing": 0,
        "real-fail": 0,
        "unclassified": 0,
        "passed": 0,
    }

    for entry in test_results:
        test_id, result, reason = normalize_entry(entry)

        if result == "passed":
            histogram["passed"] += 1
            continue

        # Look up JUnit entry (try multiple classname formats)
        junit_entry = junit_map.get(test_id)
        if junit_entry is None:
            # Try stripping eval. prefix
            alt_id = test_id.replace("eval.tests.", "tests.", 1)
            junit_entry = junit_map.get(alt_id)

        source_content = find_test_source(test_id, sources) if sources else None

        classification, evidence = classify_test(result, reason, junit_entry, source_content)

        histogram[classification] = histogram.get(classification, 0) + 1
        classified.append(
            {
                "test_id": test_id,
                "result": result,
                "classification": classification,
                "evidence": evidence,
                "branches": tests_map.get(test_id, []),
            }
        )

    total_non_passing = sum(v for k, v in histogram.items() if k != "passed")

    report = {
        "_schema": "senses_report_v1",
        "_source_eval": str(eval_path),
        "_generated_by": "pb_senses.py",
        "summary": {
            "total_tests": len(test_results),
            "passed": histogram["passed"],
            "non_passing": total_non_passing,
            "histogram": {k: v for k, v in histogram.items() if k != "passed"},
        },
        "classified": classified,
        "_note": (
            "upstream-skip: proposed only — reference-diff step required to confirm. "
            "unclassified rows: driver must adjudicate manually. "
            "Script proposes; never edits fixtures or reference binaries."
        ),
    }

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Wrote senses report to {out_path}")

    if summary_only:
        print(f"\n=== Senses Summary: {eval_path.name} ===")
        print(f"  Total tests: {len(test_results)}")
        print(f"  Passed: {histogram['passed']}")
        print(f"  Non-passing: {total_non_passing}")
        for cls, count in sorted(histogram.items()):
            if cls != "passed" and count > 0:
                print(f"    {cls}: {count}")
        unclassified = [r for r in classified if r["classification"] == "unclassified"]
        if unclassified:
            print("\n  UNCLASSIFIED (driver must adjudicate):")
            for r in unclassified[:10]:
                print(f"    {r['test_id'][:80]} — {r['evidence'][:80]}")
            if len(unclassified) > 10:
                print(f"    ... and {len(unclassified) - 10} more")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Artifact-only not_run classifier for ProgramBench."
    )
    parser.add_argument("--eval", required=True, help="Path to eval_report.json")
    parser.add_argument("--tests", help="Path to tests.json (optional)")
    parser.add_argument("--junit", help="Path to JUnit XML results file (optional)")
    parser.add_argument("--test-src", help="Directory containing test_*.py source files (optional)")
    parser.add_argument(
        "--out", help="Output path for senses_report.json (default: next to eval_report.json)"
    )
    parser.add_argument("--summary", action="store_true", help="Print summary to stdout")
    args = parser.parse_args()

    eval_path = Path(args.eval)
    if not eval_path.exists():
        print(f"ERROR: eval_report.json not found: {eval_path}", file=sys.stderr)
        sys.exit(1)

    tests_path = Path(args.tests) if args.tests else None
    junit_path = Path(args.junit) if args.junit else None
    test_src_dir = Path(args.test_src) if args.test_src else None

    if args.out:
        out_path = Path(args.out)
    else:
        out_path = eval_path.parent / "senses_report.json"

    run_senses(
        eval_path=eval_path,
        tests_path=tests_path,
        junit_path=junit_path,
        test_src_dir=test_src_dir,
        out_path=out_path,
        summary_only=args.summary or True,
    )


if __name__ == "__main__":
    main()
