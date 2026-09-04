#!/usr/bin/env python3
"""Measure shared-prefix reuse with the same case and two distinct questions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.amd.common import run_request, write_gpu_csv  # noqa: E402
from experiments.memory.gpu import AmdGpuSampler  # noqa: E402
from experiments.memory.streaming import model_name  # noqa: E402


QUESTIONS = [
    "分析违法行为、原因力、事故责任假设、关键权益期限和人工审批状态",
    "基于同一案件，仅列出关键证据缺口、法定期限、低风险下一步和审批状态",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=["baseline", "optimized"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-csv", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=350)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    with AmdGpuSampler(interval_seconds=0.25) as sampler:
        runs = [
            {"question_index": index + 1, **run_request(payload, max_tokens=args.max_tokens, question=question)}
            for index, question in enumerate(QUESTIONS)
        ]
    first = runs[0].get("ttft_seconds")
    second = runs[1].get("ttft_seconds")
    result = {
        "schema_version": 1,
        "condition": args.condition,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model_name(),
        "input": str(args.input),
        "questions": QUESTIONS,
        "runs": runs,
        "second_vs_first_ttft_change_ratio": round(
            float(second) / max(0.000001, float(first)) - 1, 6
        )
        if first is not None and second is not None
        else None,
        "gpu": sampler.summary(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_gpu_csv(args.gpu_csv, sampler.samples, label=f"prefix-{args.condition}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(item.get("success") for item in runs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
