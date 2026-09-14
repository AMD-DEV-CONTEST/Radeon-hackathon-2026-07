#!/usr/bin/env python3
"""A/B benchmark for Qwen3-32B-Agentic-SFT-r1-v3 on Radeon gfx1100.

One judge-facing entry command (run on the Radeon host, with the production
server stopped so the GPU is free):

    python benchmark.py --run-dir <dir>

It verifies model/adapter/test-set identity fail-closed, replays a fixed,
deterministically selected subset of the frozen held-out agent test set
(rdk-sft-v1 test.jsonl, 113 tasks) against both arms ("baseline" = the
production inference path, "optimized" = merged-LoRA + real streaming; see
runtime.py), scores every assistant turn against the frozen references with
the same exact-match rules as the existing model A/B evaluation
(model/benchmark/eval_ab.py), and writes an auto-generated results.json.

Arms run in separate subprocesses (this file with --arm) so each arm loads
the model in a clean process and VRAM is fully released in between.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent

# ---- frozen identity (must match the deployed production stack) ----------
DEFAULT_MODEL = "/workspace/qwen36-agentic-sft/models/Qwen3-32B-bnb-4bit-7f721e74"
DEFAULT_ADAPTER = (
    "/workspace/qwen36-agentic-sft/runs/qwen3-32b-agentic-sft-r1-v3-cachebounded"
    "/checkpoints/checkpoint-000119"
)
DEFAULT_TEST = "/workspace/qwen36-agentic-sft/data/rdk-sft-v1-20260803-agentic/test.jsonl"
BASE_REVISION = "7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
ADAPTER_SHA256 = "4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf"
BASE_CONFIG_SHA256 = "918fe2d123e79abf8ed4688278cc7d9c6c54d25fbea35e5f0870985f4d663000"
FROZEN_TEST_SHA256 = "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283"
MAX_TOKENS = 2048          # same generation budget as the frozen eval_ab arms
TIMEOUT_SECONDS = 900.0
WARMUP_RECORDS = 2
MEASURED_PASSES = 2
EXTRA_TASKS_PER_LARGE_CATEGORY = 4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_identity(model_path: Path, adapter_path: Path, test_path: Path) -> dict[str, str]:
    """Fail-closed: refuse to run against anything but the frozen identities."""
    checks = {
        str(model_path / "config.json"): BASE_CONFIG_SHA256,
        str(adapter_path / "adapter_model.safetensors"): ADAPTER_SHA256,
        str(test_path): FROZEN_TEST_SHA256,
    }
    verified: dict[str, str] = {}
    for raw_path, expected in checks.items():
        path = Path(raw_path)
        if not path.is_file():
            raise SystemExit(f"identity file missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise SystemExit(f"identity drift: {path}: {actual} != {expected}")
        verified[raw_path] = actual
    return verified


# ---- scoring: identical rules to model/benchmark/eval_ab.py --------------

def normalize_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_tool_calls(tool_calls: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for tool_call in tool_calls:
        function = tool_call["function"]
        normalized.append(
            {"name": function["name"], "arguments": normalize_arguments(function["arguments"])}
        )
    return normalized


def score_turn(reference: dict[str, Any], content: str, tool_calls: list[dict[str, Any]], finish_reason: str) -> dict[str, Any]:
    reference_calls = normalize_tool_calls(reference.get("tool_calls") or [])
    response_calls = normalize_tool_calls(tool_calls)
    if reference_calls:
        names_exact = [c["name"] for c in response_calls] == [c["name"] for c in reference_calls]
        arguments_exact = [c["arguments"] for c in response_calls] == [c["arguments"] for c in reference_calls]
        count_exact = len(response_calls) == len(reference_calls)
        finish_exact = finish_reason == "tool_calls"
        return {
            "reference_kind": "tool_calls",
            "tool_call_count_exact": count_exact,
            "tool_names_exact": names_exact,
            "tool_arguments_exact": arguments_exact,
            "tool_finish_reason_exact": finish_exact,
            "tool_calls_exact": count_exact and names_exact and arguments_exact and finish_exact,
        }
    clean = (content or "").strip()
    final_clean = bool(clean) and not response_calls and finish_reason == "stop"
    return {
        "reference_kind": "final",
        "final_clean": final_clean,
        "final_text_exact": final_clean and clean == (reference.get("content") or "").strip(),
    }


def to_openai(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same replay conversion as eval_ab.py (reference tool_call ids kept)."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "assistant" and message.get("tool_calls"):
            tool_calls = []
            for tool_call in message["tool_calls"]:
                function = tool_call["function"]
                arguments = function["arguments"]
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                tool_calls.append({
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {"name": function["name"], "arguments": arguments},
                })
            converted.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
        elif role == "tool":
            content = message.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            converted.append({"role": "tool", "tool_call_id": message["tool_call_id"], "content": content})
        else:
            converted.append({"role": role, "content": message.get("content")})
    return converted


# ---- deterministic task selection ----------------------------------------

def select_tasks(rows: list[dict[str, Any]], canary: bool) -> list[int]:
    """Pick a fixed, metadata-driven representative subset: the
    lexicographically first task of every category, plus the second task of
    the largest categories.  Covers both task kinds (live_diagnostic and
    controlled_actuation), single- and multi-tool-call turns, and final
    text answers.  No performance data is consulted."""
    by_category: dict[str, list[tuple[str, int]]] = {}
    for index, row in enumerate(rows):
        metadata = row.get("metadata") or {}
        by_category.setdefault(metadata.get("category") or "unknown", []).append(
            (row["task_id"], index)
        )
    for bucket in by_category.values():
        bucket.sort()
    selected: list[int] = [bucket[0][1] for _, bucket in sorted(by_category.items())]
    largest = sorted(by_category.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for category, bucket in largest[:EXTRA_TASKS_PER_LARGE_CATEGORY]:
        if len(bucket) > 1:
            selected.append(bucket[1][1])
    selected = sorted(set(selected))
    if canary:
        selected = selected[:2]
    return selected


def build_plan(rows: list[dict[str, Any]], task_indexes: list[int]) -> list[dict[str, Any]]:
    plan = []
    for task_index in task_indexes:
        row = rows[task_index]
        for turn_index, message in enumerate(row["messages"]):
            if message.get("role") != "assistant":
                continue
            plan.append({
                "task_index": task_index,
                "turn_index": turn_index,
                "task_id": row["task_id"],
                "task_kind": (row.get("metadata") or {}).get("task_kind"),
                "category": (row.get("metadata") or {}).get("category"),
            })
    return plan


# ---- arm runner (subprocess) ---------------------------------------------

def run_arm(args: argparse.Namespace) -> None:
    import torch  # deferred: orchestrator does not need torch
    from runtime import Runtime

    rows = [json.loads(line) for line in Path(args.test).open(encoding="utf-8")]
    task_indexes = select_tasks(rows, args.canary)
    plan = build_plan(rows, task_indexes)
    runtime = Runtime(args.model, args.adapter, args.arm)
    trials: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    def run_record(item: dict[str, Any], passno: int, measured: bool) -> None:
        row = rows[item["task_index"]]
        reference = row["messages"][item["turn_index"]]
        request_messages = to_openai(row["messages"][: item["turn_index"]])
        try:
            result = runtime.generate(request_messages, row.get("tools") or [], MAX_TOKENS, TIMEOUT_SECONDS)
        except Exception as error:
            failures.append({
                "key": f"{item['task_id']}:{item['turn_index']}",
                "pass": passno,
                "error": f"{type(error).__name__}: {error}"[:500],
            })
            return
        if not measured:
            return
        trials.append({
            "key": f"{item['task_id']}:{item['turn_index']}",
            "pass": passno,
            "task_kind": item["task_kind"],
            "category": item["category"],
            "metrics": result["metrics"],
            "finish_reason": result["finish_reason"],
            "response_content": result["content"],
            "response_tool_calls": normalize_tool_calls(result["tool_calls"]),
            "output_sha256": sha256_text(result["raw_text_sha256_input"]),
            "scores": score_turn(reference, result["content"], result["tool_calls"], result["finish_reason"]),
        })

    for item in plan[:WARMUP_RECORDS]:
        run_record(item, 0, measured=False)
    passes = 1 if args.canary else MEASURED_PASSES
    for passno in range(1, passes + 1):
        for item in plan:
            run_record(item, passno, measured=True)
            done = len(trials) + len(failures)
            print(f"[{args.arm}] {done}/{passes * len(plan)} trials", file=sys.stderr, flush=True)

    payload = {
        "arm": args.arm,
        "load_seconds": runtime.load_seconds,
        "merge_seconds": runtime.merge_seconds,
        "load_vram_bytes": runtime.load_vram_bytes,
        "task_indexes": task_indexes,
        "task_ids": [rows[i]["task_id"] for i in task_indexes],
        "record_count": len(plan),
        "passes": passes,
        "trials": trials,
        "failures": failures,
        "torch_version": torch.__version__,
        "device_name": torch.cuda.get_device_name(0),
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{args.arm}] wrote {args.out}", file=sys.stderr)


# ---- summaries and quality gates -----------------------------------------

def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[int(index)], 4)


def summarize_arm(arm: dict[str, Any]) -> dict[str, Any]:
    trials = arm["trials"]
    ttft = [t["metrics"]["user_visible_ttft_seconds"] for t in trials]
    first = [t["metrics"]["first_token_seconds"] for t in trials]
    e2e = [t["metrics"]["e2e_seconds"] for t in trials]
    tps = [t["metrics"]["decode_tokens_per_second"] for t in trials if t["metrics"]["decode_tokens_per_second"]]
    tool_trials = [t for t in trials if t["scores"]["reference_kind"] == "tool_calls"]
    final_trials = [t for t in trials if t["scores"]["reference_kind"] == "final"]
    return {
        "trials": len(trials),
        "failures": len(arm["failures"]),
        "user_visible_ttft_seconds_p50": percentile(ttft, 0.5),
        "user_visible_ttft_seconds_p95": percentile(ttft, 0.95),
        "internal_first_token_seconds_p50": percentile(first, 0.5),
        "e2e_seconds_p50": percentile(e2e, 0.5),
        "e2e_seconds_p95": percentile(e2e, 0.95),
        "e2e_seconds_mean": round(sum(e2e) / len(e2e), 4) if e2e else None,
        "decode_tokens_per_second_p50": percentile(tps, 0.5),
        "decode_tokens_per_second_mean": round(sum(tps) / len(tps), 4) if tps else None,
        "prompt_tokens_total": sum(t["metrics"]["prompt_tokens"] for t in trials),
        "completion_tokens_total": sum(t["metrics"]["completion_tokens"] for t in trials),
        "completion_tokens_mean": round(
            sum(t["metrics"]["completion_tokens"] for t in trials) / len(trials), 2
        ) if trials else None,
        "peak_vram_bytes": max((t["metrics"]["peak_vram_bytes"] for t in trials), default=None),
        "truncated_trials": sum(1 for t in trials if t["finish_reason"] == "length"),
        "quality": {
            "tool_turn_trials": len(tool_trials),
            "tool_calls_exact_rate": round(
                sum(t["scores"]["tool_calls_exact"] for t in tool_trials) / len(tool_trials), 4
            ) if tool_trials else None,
            "tool_names_exact_rate": round(
                sum(t["scores"]["tool_names_exact"] for t in tool_trials) / len(tool_trials), 4
            ) if tool_trials else None,
            "tool_arguments_exact_rate": round(
                sum(t["scores"]["tool_arguments_exact"] for t in tool_trials) / len(tool_trials), 4
            ) if tool_trials else None,
            "final_turn_trials": len(final_trials),
            "final_clean_rate": round(
                sum(t["scores"]["final_clean"] for t in final_trials) / len(final_trials), 4
            ) if final_trials else None,
            "final_text_exact_rate": round(
                sum(t["scores"]["final_text_exact"] for t in final_trials) / len(final_trials), 4
            ) if final_trials else None,
        },
    }


def quality_gates(base: dict[str, Any], opt: dict[str, Any]) -> dict[str, Any]:
    bq, oq = base["quality"], opt["quality"]
    gates = {
        "tool_names_exact_not_worse": (oq["tool_names_exact_rate"] or 0) >= (bq["tool_names_exact_rate"] or 0),
        "tool_arguments_exact_within_2pp": (oq["tool_arguments_exact_rate"] or 0) >= (bq["tool_arguments_exact_rate"] or 0) - 0.02,
        "tool_calls_exact_within_2pp": (oq["tool_calls_exact_rate"] or 0) >= (bq["tool_calls_exact_rate"] or 0) - 0.02,
        "no_new_truncation": opt["truncated_trials"] <= base["truncated_trials"],
        "final_answers_clean_not_worse": (oq["final_clean_rate"] or 0) >= (bq["final_clean_rate"] or 0),
        "no_failures": opt["failures"] == 0,
    }
    gates["all_passed"] = all(gates.values())
    return gates


def output_agreement(base: dict[str, Any], opt: dict[str, Any]) -> dict[str, Any]:
    base_by_key = {(t["key"], t["pass"]): t for t in base["trials"]}
    same = 0
    total = 0
    for t in opt["trials"]:
        ref = base_by_key.get((t["key"], t["pass"]))
        if ref is None:
            continue
        total += 1
        if ref["output_sha256"] == t["output_sha256"]:
            same += 1
    return {"compared": total, "identical_outputs": same,
            "identical_rate": round(same / total, 4) if total else None}


# ---- environment capture --------------------------------------------------

def capture_environment(python_bin: str) -> dict[str, Any]:
    probe = subprocess.run(
        [python_bin, "-c", (
            "import json, torch, transformers, peft, bitsandbytes, accelerate\n"
            "print(json.dumps({'torch': torch.__version__, 'hip': torch.version.hip,"
            " 'transformers': transformers.__version__, 'peft': peft.__version__,"
            " 'bitsandbytes': bitsandbytes.__version__, 'accelerate': accelerate.__version__,"
            " 'device': torch.cuda.get_device_name(0),"
            " 'gcn_arch': torch.cuda.get_device_properties(0).gcnArchName,"
            " 'total_vram_bytes': torch.cuda.get_device_properties(0).total_memory}))"
        )],
        capture_output=True, text=True, timeout=300,
    )
    versions = json.loads(probe.stdout.strip().splitlines()[-1]) if probe.returncode == 0 else {"error": probe.stderr[-400:]}
    rocm = None
    rocm_path = Path("/opt/rocm/.info/version")
    if rocm_path.is_file():
        rocm = rocm_path.read_text().strip()
    git: dict[str, Any] = {}
    try:
        head = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        if head.returncode == 0:
            git["commit"] = head.stdout.strip()
            dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain"], capture_output=True, text=True, timeout=10)
            git["dirty"] = bool(dirty.stdout.strip())
        else:
            git["commit"] = None
    except Exception:
        git["commit"] = None
    return {
        "hostname": platform.node(),
        "python": sys.version.split()[0],
        "rocm_version": rocm,
        "versions": versions,
        "git": git,
    }


# ---- orchestrator ---------------------------------------------------------

def orchestrate(args: argparse.Namespace) -> None:
    model_path, adapter_path, test_path = Path(args.model), Path(args.adapter), Path(args.test)
    identity = verify_identity(model_path, adapter_path, test_path)
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = "radeon-ab-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = utc_now()
    arm_files: dict[str, Path] = {}
    for arm in ("baseline", "optimized"):
        out = run_dir / f"arm-{arm}.json"
        arm_files[arm] = out
        command = [
            sys.executable, str(Path(__file__).resolve()), "--arm", arm,
            "--model", str(model_path), "--adapter", str(adapter_path),
            "--test", str(test_path), "--out", str(out),
        ]
        if args.canary:
            command.append("--canary")
        print(f"=== running arm: {arm} ===", flush=True)
        completed = subprocess.run(command)
        if completed.returncode != 0 or not out.is_file():
            raise SystemExit(f"arm {arm} failed with exit code {completed.returncode}")
    base = json.loads(arm_files["baseline"].read_text(encoding="utf-8"))
    opt = json.loads(arm_files["optimized"].read_text(encoding="utf-8"))
    base_summary, opt_summary = summarize_arm(base), summarize_arm(opt)
    results = {
        "schema_version": "radeon_qwen3_32b_agentic_ab.v1",
        "run_id": run_id,
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "canary": bool(args.canary),
        "model_identity": {
            "alias": "Qwen3-32B-Agentic-SFT-r1-v3",
            "base": "unsloth/Qwen3-32B-bnb-4bit",
            "base_revision": BASE_REVISION,
            "base_local_path": str(model_path),
            "adapter": "checkpoint-000119",
            "adapter_local_path": str(adapter_path),
            "adapter_model_sha256": ADAPTER_SHA256,
            "verified_files": identity,
        },
        "test_set": {
            "path": str(test_path),
            "sha256": FROZEN_TEST_SHA256,
            "selected_task_ids": base["task_ids"],
            "records_per_pass": base["record_count"],
            "measured_passes": base["passes"],
            "warmup_records": WARMUP_RECORDS,
        },
        "environment": capture_environment(sys.executable),
        "code_sha256": {
            "runtime.py": sha256_file(HERE / "runtime.py"),
            "benchmark.py": sha256_file(Path(__file__).resolve()),
        },
        "configs": {
            "common": {
                "temperature": 0, "do_sample": False, "max_tokens": MAX_TOKENS,
                "enable_thinking": False, "attn_implementation": "sdpa",
                "dtype": "bfloat16 (fp32 RMSNorm)", "quantization": "bnb NF4 double-quant",
            },
            "baseline": {
                "lora": "online (PeftModel, unmerged) — production path",
                "streaming": "buffered SSE (user-visible TTFT = e2e)",
            },
            "optimized": {
                "lora": "online (unmerged), lean bf16 execution with scaling folded into B",
                "streaming": "true token streaming (TextIteratorStreamer)",
            },
        },
        "arms": {
            "baseline": {k: base[k] for k in ("load_seconds", "merge_seconds", "load_vram_bytes", "trials", "failures")},
            "optimized": {k: opt[k] for k in ("load_seconds", "merge_seconds", "load_vram_bytes", "trials", "failures")},
        },
        "performance_summary": {"baseline": base_summary, "optimized": opt_summary},
        "speedup": {
            "e2e_p50": round(base_summary["e2e_seconds_p50"] / opt_summary["e2e_seconds_p50"], 3)
            if base_summary["e2e_seconds_p50"] and opt_summary["e2e_seconds_p50"] else None,
            "user_visible_ttft_p50": round(
                base_summary["user_visible_ttft_seconds_p50"] / opt_summary["user_visible_ttft_seconds_p50"], 3)
            if base_summary["user_visible_ttft_seconds_p50"] and opt_summary["user_visible_ttft_seconds_p50"] else None,
            "decode_tps_p50": round(
                opt_summary["decode_tokens_per_second_p50"] / base_summary["decode_tokens_per_second_p50"], 3)
            if base_summary["decode_tokens_per_second_p50"] and opt_summary["decode_tokens_per_second_p50"] else None,
        },
        "quality_gates": quality_gates(base_summary, opt_summary),
        "baseline_vs_optimized_output_agreement": output_agreement(base, opt),
        "boundaries": [
            "Single-request (batch=1) serving path only; no concurrent-load results.",
            "Lean LoRA runs the adapter matmuls in bf16 instead of fp32;"
            " canary-verified token-identical, and full-run drift is bounded"
            " by output agreement + quality gates below.",
            "Merging LoRA into the NF4 base was evaluated and rejected (delta"
            " below the NF4 quantization step; destroyed by requantization)."
            "  torch.compile+StaticCache decode was evaluated and rejected"
            " (padded static-cache attention is slower than eager at 3-6k"
            " prompt lengths on this stack).",
            "Perf figures are specific to gfx1100 + ROCm 7.2.1 + this software stack.",
            "Subset replay (not the full 113-task set); task selection is"
            " deterministic and metadata-driven, defined in select_tasks().",
        ],
    }
    out_path = run_dir / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "results": str(out_path),
        "speedup": results["speedup"],
        "quality_gates": results["quality_gates"],
        "baseline": {k: base_summary[k] for k in ("e2e_seconds_p50", "user_visible_ttft_seconds_p50", "decode_tokens_per_second_p50")},
        "optimized": {k: opt_summary[k] for k in ("e2e_seconds_p50", "user_visible_ttft_seconds_p50", "decode_tokens_per_second_p50")},
    }, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--adapter", default=DEFAULT_ADAPTER)
    parser.add_argument("--test", default=DEFAULT_TEST)
    parser.add_argument("--run-dir", default=str(HERE / "run"))
    parser.add_argument("--arm", choices=("baseline", "optimized"))
    parser.add_argument("--out")
    parser.add_argument("--canary", action="store_true", help="2 tasks, 1 pass: fast compatibility/benefit check")
    args = parser.parse_args()
    if args.arm:
        if not args.out:
            raise SystemExit("--arm requires --out")
        sys.path.insert(0, str(HERE))
        verify_identity(Path(args.model), Path(args.adapter), Path(args.test))
        run_arm(args)
    else:
        orchestrate(args)


if __name__ == "__main__":
    main()
