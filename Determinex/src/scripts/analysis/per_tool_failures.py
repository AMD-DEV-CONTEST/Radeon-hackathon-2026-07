#!/usr/bin/env python3
"""Per-tool failure-cluster analysis across all PB eval.jsons.

For EACH tool we have evaluated, produces:
  - top-5 failure patterns (first-line of extra.message)
  - top-5 normalized assertions
  - top-3 failing test names (most-failed cluster ID)
  - skipped count + reasons (separate from failures — PB counts these as non-passing)

Cross-tool view:
  - which failure-pattern appears across N tools (universal vs specific)

Output:
  - JSON to c:/tmp/per_tool_failures.json
  - TSV to c:/tmp/per_tool_failures.tsv for quick load
  - cluster matrix to c:/tmp/cross_tool_clusters.tsv

Run: python scripts/analysis/per_tool_failures.py
"""

from __future__ import annotations

import collections
import glob
import json
import re
from pathlib import Path

ROOT = Path("T:/determinex-programbench")
OUT_JSON = Path("c:/tmp/per_tool_failures.json")
OUT_TSV = Path("c:/tmp/per_tool_failures.tsv")
OUT_MATRIX = Path("c:/tmp/cross_tool_clusters.tsv")


def normalize_assertion(msg: str) -> str:
    m = re.match(r"AssertionError:\s*assert\s+(.+)", msg)
    if not m:
        m = re.match(r"assert\s+(.+)", msg)
    if not m:
        return msg[:80]
    body = m.group(1)
    body = re.sub(r"\b\d+\b", "N", body)
    body = re.sub(r"'[^']{20,}'", "<LONG_STR>", body)
    body = re.sub(r"b'[^']{20,}'", "<LONG_BYTES>", body)
    return f"assert {body[:80]}"


def root_cause_bucket(first_line: str) -> str:
    fl = first_line.lower()
    if "assertionerror" in fl or "assert " in fl:
        m = re.search(r"assert\s+(\d+)\s*==\s*(\d+)", fl)
        if m:
            got, want = m.group(1), m.group(2)
            return f"rc_mismatch_got{got}_want{want}"
        if re.search(r"assert\s+\d+\s*!=\s*\d+", fl):
            return "rc_unexpected_zero"
        if "assert false" in fl:
            return "boolean_false"
        if "assert none" in fl:
            return "returned_none"
        if "==" in fl and "'" in fl:
            return "string_output_mismatch"
        if "==" in fl and "b'" in fl:
            return "bytes_output_mismatch"
        return "other_assertion"
    if "jsondecodeerror" in fl:
        return "json_output_missing_or_bad"
    if "brokenpipeerror" in fl:
        return "sigpipe_unhandled"
    if "indexerror" in fl:
        return "empty_list_or_string"
    if "keyerror" in fl:
        return "missing_dict_key"
    if "typeerror" in fl:
        return "type_error"
    if "filenotfounderror" in fl:
        return "missing_file"
    if "modulenotfounderror" in fl or "importerror" in fl:
        return "missing_import"
    if "calledprocesserror" in fl:
        return "subprocess_failed"
    if "timeout" in fl:
        return "test_timeout"
    return "uncategorized"


def main():
    latest = {}
    for p in glob.glob(str(ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        pp = Path(p)
        tool = pp.parent.name
        mt = pp.stat().st_mtime
        if tool not in latest or mt > latest[tool][0]:
            latest[tool] = (mt, pp)

    per_tool = {}
    cross_tool_bucket = collections.defaultdict(set)

    for tool, (_, ej) in latest.items():
        try:
            j = json.loads(ej.read_text(encoding="utf-8"))
        except Exception:
            continue
        results = j.get("test_results") or []
        statuses = collections.Counter(r.get("status") for r in results)
        passed = statuses.get("passed", 0)
        failed_results = [r for r in results if r.get("status") == "failure"]
        skipped_results = [r for r in results if r.get("status") == "skipped"]
        total = len(results)
        if total == 0:
            continue

        # Skipped reasons (for triage)
        skipped_reasons = collections.Counter()
        skipped_samples = []
        for r in skipped_results:
            msg = (r.get("extra") or {}).get("message") or "<no-reason>"
            first = msg.strip().split("\n")[0][:120]
            skipped_reasons[first] += 1
            if len(skipped_samples) < 3:
                skipped_samples.append({"name": r.get("name", ""), "reason": first})

        # Failure clusters
        first_line_counter = collections.Counter()
        norm_assertion_counter = collections.Counter()
        bucket_counter = collections.Counter()
        bucket_to_test_names = collections.defaultdict(list)

        for r in failed_results:
            msg = (r.get("extra") or {}).get("message") or ""
            fl = msg.strip().split("\n")[0][:120]
            first_line_counter[fl] += 1
            norm_assertion_counter[normalize_assertion(fl)] += 1
            bucket = root_cause_bucket(fl)
            bucket_counter[bucket] += 1
            if len(bucket_to_test_names[bucket]) < 3:
                tn = r.get("name") or ""
                bucket_to_test_names[bucket].append(tn)
            cross_tool_bucket[bucket].add(tool)

        per_tool[tool] = {
            "passed": passed,
            "failed": len(failed_results),
            "skipped": len(skipped_results),
            "total": total,
            "pct": round(100.0 * passed / total, 2),
            "non_pass_count": total - passed,
            "top_first_lines": first_line_counter.most_common(5),
            "top_normalized": norm_assertion_counter.most_common(5),
            "top_buckets": bucket_counter.most_common(5),
            "bucket_samples": {
                b: bucket_to_test_names[b][:3] for b in dict(bucket_counter.most_common(5))
            },
            "skipped_reasons": skipped_reasons.most_common(5),
            "skipped_samples": skipped_samples,
        }

    OUT_JSON.write_text(json.dumps(per_tool, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON} ({len(per_tool)} tools)")

    with OUT_TSV.open("w", encoding="utf-8", newline="\n") as f:
        f.write(
            "tool\tpct\tpassed\tfailed\tskipped\ttotal\ttop_bucket\ttop_bucket_count\ttop_assertion\tassertion_count\n"
        )
        for tool, d in sorted(per_tool.items(), key=lambda kv: -kv[1]["pct"]):
            top_b, top_bc = d["top_buckets"][0] if d["top_buckets"] else ("-", 0)
            top_a, top_ac = d["top_normalized"][0] if d["top_normalized"] else ("-", 0)
            top_a = top_a.replace("\t", " ").replace("\n", " ")[:100]
            f.write(
                f"{tool}\t{d['pct']}\t{d['passed']}\t{d['failed']}\t{d['skipped']}\t{d['total']}\t{top_b}\t{top_bc}\t{top_a}\t{top_ac}\n"
            )
    print(f"wrote {OUT_TSV}")

    with OUT_MATRIX.open("w", encoding="utf-8", newline="\n") as f:
        f.write("bucket\ttool_count\ttotal_failures\tsample_tools\n")
        rows = []
        for bucket, tools in cross_tool_bucket.items():
            total_fails = sum(dict(per_tool[t]["top_buckets"]).get(bucket, 0) for t in tools)
            rows.append((bucket, len(tools), total_fails, sorted(tools)[:5]))
        rows.sort(key=lambda x: (-x[1], -x[2]))
        for bucket, tc, fc, sample in rows:
            f.write(f"{bucket}\t{tc}\t{fc}\t{','.join(sample)}\n")
    print(f"wrote {OUT_MATRIX}")

    print()
    print("=== TOP UNIVERSAL FAILURE BUCKETS ===")
    print(f"{'bucket':<40} {'#tools':>7} {'#fails':>10}")
    for bucket, tc, fc, _ in rows[:15]:
        print(f"{bucket:<40} {tc:>7} {fc:>10}")


if __name__ == "__main__":
    main()
