#!/usr/bin/env python3
"""Portable, read-only recomputation of the published Base/SFT A/B result.

With ``--test``, this tool verifies the canonical frozen Test, rebuilds the
published 49-task ordered prefix, checks every raw record against that plan and
its Test reference, independently re-scores each response, and compares the
result with ``summary.json``. It deliberately ignores host-local inode, uid,
mode, and timestamp assertions from the historical recovery seals.

Without ``--test``, it preserves the original lightweight behavior and
re-aggregates the score fields already stored in the raw JSONL evidence.

No model calls, network, GPU, or third-party packages are required.

Usage (from a run directory such as runs/model-ab-heldout113-20260805-v2):
    python3 ../../recompute_ab.py \
      --test ../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl \
      arms/base.raw.jsonl arms/sft.raw.jsonl summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import summarize_ab


CAPPED_RECORDS = 170
CAPPED_TASKS = 49
CAPPED_MAX_CAPTURED_RECORDS = 171


class RecomputeError(RuntimeError):
    """The portable evidence bundle is incomplete or inconsistent."""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise RecomputeError(f"{path}: blank JSONL line {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise RecomputeError(
                    f"{path}: invalid JSON at line {line_number}: {error}"
                ) from error
            if not isinstance(record, dict):
                raise RecomputeError(f"{path}: line {line_number} is not an object")
            records.append(record)
    return records


def load_stored_score_prefix(path: Path) -> tuple[list[dict[str, Any]], int]:
    records = load_jsonl(path)
    capped = [
        record
        for record in records
        if record.get("task_index", CAPPED_TASKS) < CAPPED_TASKS
    ][:CAPPED_RECORDS]
    if len(capped) != CAPPED_RECORDS:
        raise RecomputeError(
            f"{path}: expected {CAPPED_RECORDS} capped records, found {len(capped)}"
        )
    return capped, len(records)


def expected_reference(
    rows: list[dict[str, Any]], plan_item: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = rows[plan_item["task_index"]]["messages"][plan_item["turn_index"]]
    return reference, {
        "content": reference.get("content"),
        "tool_calls": summarize_ab.normalize_tool_calls(reference.get("tool_calls") or []),
    }


def load_independently_scored_prefix(
    path: Path, label: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    records = load_jsonl(path)
    if not CAPPED_RECORDS <= len(records) <= CAPPED_MAX_CAPTURED_RECORDS:
        raise RecomputeError(
            f"{path}: expected 170 records plus at most one next-plan record, "
            f"found {len(records)}"
        )

    plan = summarize_ab.build_frozen_plan(rows, label)
    validated: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    run_ids: set[str] = set()
    for line_number, record in enumerate(records, 1):
        plan_item = plan[line_number - 1]
        for field in ("key", "task_index", "turn_index", "task_id"):
            if record.get(field) != plan_item[field]:
                raise RecomputeError(
                    f"{path}:{line_number}: frozen plan mismatch for {field}: "
                    f"{record.get(field)!r} != {plan_item[field]!r}"
                )
        if record.get("label") != label:
            raise RecomputeError(f"{path}:{line_number}: arm label mismatch")
        if record["key"] in seen_keys:
            raise RecomputeError(f"{path}:{line_number}: duplicate record key")
        seen_keys.add(record["key"])
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RecomputeError(f"{path}:{line_number}: missing run ID")
        run_ids.add(run_id)

        reference, normalized_reference = expected_reference(rows, plan_item)
        if record.get("reference") != normalized_reference:
            raise RecomputeError(f"{path}:{line_number}: frozen Test reference mismatch")

        response = record.get("response")
        response_message = response.get("message") if isinstance(response, dict) else None
        if not isinstance(response_message, dict):
            raise RecomputeError(f"{path}:{line_number}: response message is missing")
        normalized_response_calls = summarize_ab.normalize_tool_calls(
            response_message.get("tool_calls") or []
        )
        if response.get("tool_calls") != normalized_response_calls:
            raise RecomputeError(f"{path}:{line_number}: stored response drift")
        rescored = summarize_ab.independently_score(
            reference, response_message, response.get("finish_reason")
        )
        if record.get("scores") != rescored:
            raise RecomputeError(f"{path}:{line_number}: stored score drift")
        validated.append({**record, "reference": normalized_reference, "scores": rescored})

    if len(run_ids) != 1:
        raise RecomputeError(f"{path}: records contain multiple run IDs")
    selected = validated[:CAPPED_RECORDS]
    if (
        len({record["task_id"] for record in selected}) != CAPPED_TASKS
        or selected[-1]["task_index"] != CAPPED_TASKS - 1
    ):
        raise RecomputeError(f"{path}: first 170 records are not 49 complete tasks")
    if (
        len(validated) == CAPPED_MAX_CAPTURED_RECORDS
        and validated[-1]["task_index"] != CAPPED_TASKS
    ):
        raise RecomputeError(f"{path}: optional record is not the next frozen task")
    return selected, len(records)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def turn_contract_pass(record: dict[str, Any]) -> bool:
    scores = record["scores"]
    if scores["reference_kind"] == "tool_calls":
        return scores["tool_calls_exact"] is True
    return scores["final_clean"] is True


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    tool = [r for r in records if r["scores"]["reference_kind"] == "tool_calls"]
    final = [r for r in records if r["scores"]["reference_kind"] == "final"]
    tasks: dict[str, list[bool]] = {}
    for record in records:
        tasks.setdefault(record["task_id"], []).append(turn_contract_pass(record))
    latencies = [record["latency_seconds"] for record in records]

    def rate(pool: list[dict[str, Any]], key: str) -> tuple[int, int]:
        return sum(1 for record in pool if record["scores"][key] is True), len(pool)

    return {
        "models": sorted({record["response"]["model"] for record in records}),
        "structured": rate(tool, "structured"),
        "tool_names_exact": rate(tool, "tool_names_exact"),
        "tool_arguments_exact": rate(tool, "tool_arguments_exact"),
        "tool_calls_exact": rate(tool, "tool_calls_exact"),
        "tool_call_count_exact": rate(tool, "tool_call_count_exact"),
        "final_clean": rate(final, "final_clean"),
        "final_text_exact": rate(final, "final_text_exact"),
        "task_all_turns_contract": (
            sum(1 for ok in (all(values) for values in tasks.values()) if ok),
            len(tasks),
        ),
        "latency_p50": percentile(latencies, 0.50),
        "latency_p95": percentile(latencies, 0.95),
        "latency_mean": statistics.fmean(latencies),
        "completion_tokens": sum(
            record["response"]["usage"]["completion_tokens"] for record in records
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test",
        type=Path,
        help="canonical frozen Test; enables portable independent re-scoring",
    )
    parser.add_argument("base_raw", type=Path)
    parser.add_argument("sft_raw", type=Path)
    parser.add_argument("summary", type=Path)
    return parser.parse_args()


def compare_published(
    base: dict[str, Any], sft: dict[str, Any], published: dict[str, Any]
) -> list[str]:
    mismatches: list[str] = []
    for arm_name, arm in (("base", base), ("sft", sft)):
        scores = published[arm_name]["scores"]
        for key in (
            "structured",
            "tool_names_exact",
            "tool_arguments_exact",
            "tool_calls_exact",
            "tool_call_count_exact",
            "final_clean",
            "final_text_exact",
            "task_all_turns_contract",
        ):
            got, total = arm[key]
            if scores[key]["passed"] != got or scores[key]["total"] != total:
                mismatches.append(
                    f"{arm_name}.{key}: recomputed {got}/{total} != published "
                    f"{scores[key]['passed']}/{scores[key]['total']}"
                )
    return mismatches


def main() -> int:
    args = parse_args()
    try:
        if args.test is not None:
            rows = summarize_ab.load_frozen_rows(args.test)
            base_records, base_captured = load_independently_scored_prefix(
                args.base_raw, "base", rows
            )
            sft_records, sft_captured = load_independently_scored_prefix(
                args.sft_raw, "sft", rows
            )
            mode = "independent Test-based re-score"
        else:
            base_records, base_captured = load_stored_score_prefix(args.base_raw)
            sft_records, sft_captured = load_stored_score_prefix(args.sft_raw)
            mode = "stored-score aggregation"

        base, sft = aggregate(base_records), aggregate(sft_records)
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        published = summary["groups"]["all"]["all"]

        if args.test is not None:
            expected_test = {
                "sha256": summarize_ab.FROZEN_TEST_SHA256,
                "bytes": summarize_ab.FROZEN_TEST_BYTES,
            }
            if summary.get("test_sha256") != expected_test["sha256"]:
                raise RecomputeError("published summary does not bind the canonical Test")
            summary_test = (summary.get("inputs") or {}).get("frozen_test") or {}
            for field, expected in expected_test.items():
                if summary_test.get(field) != expected:
                    raise RecomputeError(
                        f"published summary frozen Test {field} mismatch: "
                        f"{summary_test.get(field)!r} != {expected!r}"
                    )

        run_ids = {record["run_id"] for record in (*base_records, *sft_records)}
        if len(run_ids) != 1 or summary.get("run_id") not in run_ids:
            raise RecomputeError("Base/SFT raw and summary run IDs do not match")
        scope = summary.get("scope") or {}
        expected_scope = {
            "selected_records_per_arm": CAPPED_RECORDS,
            "selected_tasks": CAPPED_TASKS,
            "base_captured_records": base_captured,
            "sft_captured_records": sft_captured,
        }
        for field, expected in expected_scope.items():
            if scope.get(field) != expected:
                raise RecomputeError(
                    f"summary scope mismatch for {field}: {scope.get(field)!r} != {expected!r}"
                )

        print(f"Verification mode: {mode}")
        print(
            f"Evaluated prefix: first {CAPPED_TASKS} tasks / "
            f"{CAPPED_RECORDS} assistant turns per arm"
        )
        print(
            f"Base responded by: {base['models']}  |  "
            f"SFT responded by: {sft['models']}\n"
        )
        table_rows = [
            ("Strict tool-call exact", "tool_calls_exact"),
            ("Tool-name exact", "tool_names_exact"),
            ("Tool-arguments exact", "tool_arguments_exact"),
            ("Tool-call-count exact", "tool_call_count_exact"),
            ("Clean final response", "final_clean"),
            ("All-turn task contract", "task_all_turns_contract"),
        ]
        print(f"{'Metric':<26}{'Base':>16}{'SFT':>16}{'Delta':>10}")
        for name, key in table_rows:
            (base_passed, base_total), (sft_passed, sft_total) = base[key], sft[key]
            delta = 100 * (sft_passed / sft_total - base_passed / base_total)
            base_cell = f"{base_passed}/{base_total} ({100 * base_passed / base_total:.2f}%)"
            sft_cell = f"{sft_passed}/{sft_total} ({100 * sft_passed / sft_total:.2f}%)"
            print(
                f"{name:<26}{base_cell:>16}{sft_cell:>16}{f'{delta:+.2f}pp':>10}"
            )
        base_lat = f"{base['latency_p50']:.1f} / {base['latency_p95']:.1f}"
        sft_lat = f"{sft['latency_p50']:.1f} / {sft['latency_p95']:.1f}"
        print(f"\n{'Latency p50 / p95 (s)':<26}{base_lat:>16}{sft_lat:>16}")
        print(
            f"{'Completion tokens':<26}{base['completion_tokens']:>16,}"
            f"{sft['completion_tokens']:>16,}"
        )

        mismatches = compare_published(base, sft, published)
        if args.test is not None:
            recomputed_group = summarize_ab.group_summary(base_records, sft_records)
            if recomputed_group != published:
                mismatches.append(
                    "full all-task group (aggregates, deltas, or paired outcomes) differs"
                )
        if mismatches:
            print("\nMISMATCH vs published summary.json:")
            for mismatch in mismatches:
                print(" -", mismatch)
            return 1
        if args.test is not None:
            print(
                "\nOK: canonical Test, ordered raw references, independently re-scored "
                "responses, and published summary all match"
            )
        else:
            print("\nOK: every recomputed metric matches the published summary.json")
        return 0
    except Exception as error:
        print(f"recompute failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
