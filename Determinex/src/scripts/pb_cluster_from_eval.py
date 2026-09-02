#!/usr/bin/env python3
"""Cluster ProgramBench failures from an official eval JSON.

Generic across tools. Reads `<slug>.eval.json`, partitions failures by
failure SIGNATURE (returncode + stderr fingerprint + assertion shape),
labels each cluster with a likely category, and writes:

    <out-dir>/<slug>.official_cluster_report.json
    <out-dir>/<slug>.official_cluster_report.md

The category labels are the worker-facing taxonomy from
`docs/PROGRAMBENCH_FACTORY_ARCHITECTURE.md` Section 9:

    argparse/help, version, missing-arg, unknown-flag, file-io,
    output-format, golden-output, tty/tmux, algorithm, timeout,
    runtime, unknown

The script is read-only: it never edits the eval JSON, never touches
overrides or locked archives, and never runs an eval. Use
`scripts/pb_candidate_gate.py` to run eval; use this script to consume
its JSON output.

Usage:
    python scripts/pb_cluster_from_eval.py <slug> <eval_json_path> \
        --out-dir logs/programbench_failure_inventory
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

# ----------------------------- categorization -------------------------------


def _extract_completed_process(msg: str) -> dict[str, Any]:
    """Best-effort parse of pytest's CompletedProcess repr in a failure message."""
    out: dict[str, Any] = {}
    cp = re.search(
        r"CompletedProcess\(\s*args=(\[[^\]]*\])\s*,\s*returncode=(\-?\d+)"
        r"(?:\s*,\s*stdout=(b?(?:[\"'][^\"']*[\"']|None)))?"
        r"(?:\s*,\s*stderr=(b?(?:[\"'][^\"']*[\"']|None)))?\s*\)",
        msg,
        re.DOTALL,
    )
    if cp:
        out["args"] = cp.group(1)[:300]
        out["returncode"] = int(cp.group(2))
        if cp.group(3):
            out["stdout"] = cp.group(3)
        if cp.group(4):
            out["stderr"] = cp.group(4)
    return out


# Category taxonomy. Order matters: earlier patterns win on tie.
#
# Each rule is (category, predicate). Predicate receives (test_name_lower,
# msg, cp_dict) and returns True/False.
def _classify(test_name: str, msg: str, cp: dict[str, Any]) -> str:
    n = test_name.lower()
    m = msg.lower()

    # --- timeout / runtime infra failures (eval harness flagged them) ---
    if "timeout" in m and ("timeoutexpired" in m or "exceeded" in m):
        return "timeout"
    if "subprocess.calledprocesserror" in m and "tmux" in m:
        return "tty/tmux"
    if "tmux" in m and "send-keys" in m:
        return "tty/tmux"
    if "no such file or directory" in m and "tmux" in m:
        return "tty/tmux"

    # --- version-specific tests ---
    if "test_version" in n or "version_flag" in n:
        return "version"
    if (" 1." in msg or "v1." in msg or "v0." in msg) and "version" in n:
        return "version"

    # --- argparse / help ---
    if any(
        k in n
        for k in (
            "test_help",
            "help_flag",
            "help_text",
            "help_output",
            "help_long",
            "help_short",
            "help_command",
        )
    ):
        return "argparse/help"
    if "usage:" in m and (" == " in m or "assert " in m):
        return "argparse/help"

    # --- missing-arg / missing-required ---
    if "the following required arguments were not provided" in m:
        return "missing-arg"
    if "missing required" in n or "missing_required" in n:
        return "missing-arg"
    if "no_args" in n and ("required" in m or "missing" in m):
        return "missing-arg"

    # --- unknown-flag ---
    if "unexpected argument" in m or "unrecognized argument" in m:
        return "unknown-flag"
    if "no such option" in m or "unrecognized option" in m:
        return "unknown-flag"
    if "unknown_flag" in n or "unknown_option" in n or "unknown_arg" in n:
        return "unknown-flag"
    if "invalid value" in m and "for '--" in m:
        return "argparse/help"

    # --- TTY / TUI rendering (pty/tmux harness behavior) ---
    if "tui" in n or "test_tui" in n:
        return "tty/tmux"
    if "pty" in m or "ttyiocontrol" in m:
        return "tty/tmux"

    # --- file-io / not-found ---
    if "no such file" in m or "filenotfounderror" in m:
        return "file-io"
    if "permission denied" in m or "permissionerror" in m:
        return "file-io"
    if "isdirectoryerror" in m or "isadirectoryerror" in m:
        return "file-io"

    # --- golden-output (test compares against a fixture file) ---
    if ".golden" in msg or ".golden" in n:
        return "golden-output"
    if "fixture" in m and ("expected" in m or "golden" in m):
        return "golden-output"
    if "test_resources" in m or "expected_output" in m:
        return "golden-output"
    if "snapshot" in n or "snapshot" in m:
        return "golden-output"

    # --- output-format (==/in on stdout/stderr text) ---
    if "stdout ==" in m or "stderr ==" in m:
        return "output-format"
    if "in result.stdout" in m or "in result.stderr" in m or "in stdout" in m or "in stderr" in m:
        return "output-format"
    if " == " in m and (cp.get("stdout") or cp.get("stderr")):
        return "output-format"

    # --- runtime crash (Python traceback or non-shell rc != 0/1/2) ---
    if "traceback" in m or "exception" in m[:200]:
        return "runtime"
    if cp.get("returncode") is not None and cp["returncode"] not in (0, 1, 2):
        return "runtime"

    # --- algorithm (returncode mismatch where it's the assertion target) ---
    if "returncode" in m and " == " in m:
        return "algorithm"
    if "assert " in m and cp.get("returncode") is not None:
        return "algorithm"

    return "unknown"


def _topic_signature(test_name: str, msg: str) -> str:
    """Add a coarse semantic topic so huge generic assert buckets split.

    The base signature is intentionally mechanical, but real ProgramBench
    failures often collapse into `rc=? | assert_other`. A topic keeps packets
    worker-sized without making tool-specific claims.
    """
    n = test_name.lower()
    m = msg.lower()
    checks = [
        ("tty/tmux", ("tmux", "send-keys", "tui", "pty")),
        ("help", ("help", "usage:", "--help", "-h")),
        ("type-list", ("type_list", "type-list", "type list")),
        ("editor", ("editor", "custom-command", "custom_command")),
        ("unknown-flag", ("unknown_flag", "unknown option", "unexpected argument", "unrecognized")),
        ("missing-arg", ("missing", "required arguments", "no_args")),
        ("file-io", ("no such file", "filenotfound", "nonexistent")),
        ("config", ("config", "ripgrep_config")),
        ("table-format", ("table", "markdown", "valid timestamps", "new version")),
        ("json", ("json", "unmarshal", "unexpected eof")),
        ("timestamp", ("timestamp", "parsing time")),
        ("version", ("version_flag", "--version", "test_version")),
        ("transform", ("transform", "fixture", "golden", "stdout ==")),
        ("search-output", ("search", "match", "stdout", "screen")),
        ("returncode", ("returncode",)),
    ]
    joined = n + "\n" + m[:1200]
    for topic, needles in checks:
        if any(k in joined for k in needles):
            return topic
    return "general"


def _signature(test_name: str, msg: str, cp: dict[str, Any]) -> str:
    """Compact signature for clustering: rc + stderr fingerprint + assertion shape."""
    rc = cp.get("returncode")
    rc_part = f"rc={rc}" if rc is not None else "rc=?"

    stderr_raw = cp.get("stderr") or ""
    stderr_clean = stderr_raw.strip("b'\"").strip()
    if "Traceback" in stderr_clean:
        lines = [l for l in stderr_clean.split("\\n") if l.strip()]
        stderr_clean = lines[-1] if lines else stderr_clean
    stderr_sig = re.split(r"[.\\n]", stderr_clean, maxsplit=1)[0][:80].strip()

    m = msg.lower()
    if "in stdout" in m:
        shape = "in_stdout"
    elif "in stderr" in m:
        shape = "in_stderr"
    elif re.search(r"returncode\s*==", m):
        shape = "returncode_eq"
    elif "stdout ==" in m:
        shape = "stdout_eq"
    elif "stderr ==" in m:
        shape = "stderr_eq"
    elif "assert " in m:
        shape = "assert_other"
    else:
        shape = "no_assert"

    topic = _topic_signature(test_name, msg)

    if stderr_sig:
        return f"{rc_part} | {shape} | topic={topic} | stderr='{stderr_sig}'"
    return f"{rc_part} | {shape} | topic={topic}"


def _expected_actual(msg: str, cp: dict[str, Any]) -> tuple[str, str]:
    """Best-effort extract of expected/actual fragments from a failure message."""
    expected, actual = "", ""

    # Try unified-diff `- expected` / `+ actual` form
    m = re.search(r"\n\s*-\s+(.{1,200})", msg)
    if m:
        expected = m.group(1).strip()[:200]
    m = re.search(r"\n\s*\+\s+(.{1,200})", msg)
    if m:
        actual = m.group(1).strip()[:200]

    # CompletedProcess overrides actual if present
    if cp.get("returncode") is not None:
        parts = [f"rc={cp['returncode']}"]
        if cp.get("stdout"):
            parts.append(f"stdout={cp['stdout'][:120]}")
        if cp.get("stderr"):
            parts.append(f"stderr={cp['stderr'][:200]}")
        actual = " | ".join(parts)[:400]

    # `assert <X> == <Y>` shape - first arg is the actual (LHS), second is the expected (RHS)
    if not expected:
        m = re.search(r"assert\s+['\"]([^'\"]{1,120})['\"]\s*==\s*['\"]([^'\"]{1,120})['\"]", msg)
        if m:
            actual = actual or m.group(1)[:200]
            expected = m.group(2)[:200]

    # `assert <X> in <Y>` shape - first is what's being looked for, second is the haystack
    if not expected:
        m = re.search(r"assert\s+['\"]([^'\"]{1,120})['\"]\s+in\s+", msg)
        if m:
            expected = m.group(1)[:200]

    return expected, actual


# ----------------------------- main pipeline --------------------------------


def cluster_eval(slug: str, eval_json_path: Path) -> dict[str, Any]:
    """Read an eval JSON and return a structured cluster report."""
    if not eval_json_path.is_file():
        return {
            "slug": slug,
            "eval_json": str(eval_json_path),
            "error": f"eval JSON not found: {eval_json_path}",
        }

    try:
        data = json.loads(eval_json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return {
            "slug": slug,
            "eval_json": str(eval_json_path),
            "error": f"failed to parse eval JSON: {type(e).__name__}: {e}",
        }

    test_results = data.get("test_results") or []
    counts: Counter[str] = Counter(str(t.get("status", "?")) for t in test_results)
    passed = counts.get("passed", 0)
    failed = counts.get("failure", 0) + counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    not_run = counts.get("not_run", 0)
    errored = counts.get("error", 0)
    runnable = passed + failed + errored

    failures = [t for t in test_results if str(t.get("status", "")) in ("failure", "failed")]

    # Per-failure normalized record
    enriched: list[dict[str, Any]] = []
    for t in failures:
        name = str(t.get("name", "") or "")
        branch = str(t.get("branch", "") or "")
        extra = t.get("extra") or {}
        msg = str(extra.get("message", "") or "")
        cp = _extract_completed_process(msg)
        expected, actual = _expected_actual(msg, cp)
        signature = _signature(name, msg, cp)
        category = _classify(name, msg, cp)
        enriched.append(
            {
                "name": name,
                "branch": branch,
                "status": "failure",
                "category": category,
                "signature": signature,
                "expected": expected,
                "actual": actual,
                "message_head": msg[:300],
                "returncode": cp.get("returncode"),
            }
        )

    # Cluster by (category, signature) tuple - preserves signature granularity inside category.
    cluster_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for f in enriched:
        key = (f["category"], f["signature"])
        cluster_map.setdefault(key, []).append(f)

    clusters: list[dict[str, Any]] = []
    for (category, signature), items in cluster_map.items():
        clusters.append(
            {
                "category": category,
                "signature": signature,
                "count": len(items),
                "branches": sorted({i["branch"] for i in items if i["branch"]}),
                "sample_tests": [
                    {
                        "name": i["name"],
                        "branch": i["branch"],
                        "message_head": i["message_head"][:240],
                        "expected": i["expected"],
                        "actual": i["actual"],
                    }
                    for i in items[:6]
                ],
                "all_test_names": [i["name"] for i in items],
            }
        )
    clusters.sort(key=lambda c: (-c["count"], c["category"]))

    # Category totals
    cat_totals: Counter[str] = Counter(f["category"] for f in enriched)
    by_category = [{"category": cat, "count": n} for cat, n in cat_totals.most_common()]

    branches = sorted({f["branch"] for f in enriched if f["branch"]})

    return {
        "slug": slug,
        "eval_json": str(eval_json_path),
        "executable_hash": (data.get("executable_hash") or "")[:64],
        "solution_branch": data.get("solution_branch"),
        "test_branches": data.get("test_branches"),
        "counts": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "not_run": not_run,
            "errored": errored,
            "runnable": runnable,
            "total": len(test_results),
        },
        "by_category": by_category,
        "branches_with_failures": branches,
        "clusters": clusters,
        "failures": enriched,
    }


def write_outputs(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = report["slug"]
    out_json = out_dir / f"{slug}.official_cluster_report.json"
    out_md = out_dir / f"{slug}.official_cluster_report.md"

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown report
    md: list[str] = []
    md.append(f"# {slug} - official failure cluster report")
    md.append("")
    md.append(f"Source eval JSON: `{report['eval_json']}`")
    if report.get("error"):
        md.append("")
        md.append(f"**ERROR:** {report['error']}")
        out_md.write_text("\n".join(md), encoding="utf-8")
        return out_md, out_json

    c = report["counts"]
    md.append("")
    md.append(
        f"**Counts:** passed={c['passed']}  failed={c['failed']}  skipped={c['skipped']}  "
        f"not_run={c['not_run']}  errored={c['errored']}  runnable={c['runnable']}  total={c['total']}"
    )
    md.append(f"**Executable hash (16):** `{report.get('executable_hash', '')[:16]}`")
    if report.get("test_branches"):
        md.append(f"**Test branches:** {len(report['test_branches'])}")
    md.append("")

    md.append("## Failures by category")
    md.append("")
    md.append("| Category | Count |")
    md.append("|---|---:|")
    for row in report["by_category"]:
        md.append(f"| `{row['category']}` | {row['count']} |")
    md.append("")

    md.append("## Top failure clusters (by signature)")
    md.append("")
    md.append("| Rank | Count | Category | Signature |")
    md.append("|---:|---:|---|---|")
    for i, cl in enumerate(report["clusters"][:20], 1):
        md.append(f"| {i} | {cl['count']} | `{cl['category']}` | `{cl['signature'][:140]}` |")
    md.append("")

    md.append("## Cluster details")
    md.append("")
    for i, cl in enumerate(report["clusters"][:30], 1):
        md.append(f"### #{i}  ({cl['count']} tests, category `{cl['category']}`)")
        md.append("")
        md.append(f"**Signature:** `{cl['signature']}`")
        if cl["branches"]:
            md.append(f"**Branches:** {', '.join(b[:12] for b in cl['branches'])}")
        md.append("")
        md.append("Sample tests:")
        md.append("")
        for s in cl["sample_tests"]:
            md.append(f"- `{s['name']}` (branch `{s['branch'][:12]}`)")
            if s.get("expected"):
                md.append(f"    expected: `{s['expected'][:160]}`")
            if s.get("actual"):
                md.append(f"    actual:   `{s['actual'][:160]}`")
            md.append(f"    msg: `{s['message_head'][:200]}`")
        if cl["count"] > len(cl["sample_tests"]):
            md.append(f"  ...and {cl['count'] - len(cl['sample_tests'])} more.")
        md.append("")

    out_md.write_text("\n".join(md), encoding="utf-8")
    return out_md, out_json


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument("eval_json_path", type=Path, help="Path to the official eval JSON")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("logs/programbench_failure_inventory"),
        help="Output directory (will be created if missing)",
    )
    args = ap.parse_args()

    report = cluster_eval(args.slug, args.eval_json_path)
    out_md, out_json = write_outputs(report, args.out_dir)
    print(f"wrote {out_md}")
    print(f"wrote {out_json}")
    if report.get("error"):
        return 1
    c = report["counts"]
    print(
        f"  passed={c['passed']}  failed={c['failed']}  runnable={c['runnable']}  clusters={len(report['clusters'])}"
    )
    for row in report["by_category"][:8]:
        print(f"  - {row['category']:<20s} {row['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
