#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from policyseal.agent.classification_graph import SemanticClassificationGraph
from policyseal.agent.llm_client import CompletionClient, LocalVllmClient
from policyseal.agent.schemas import LocalCompletion, SemanticRegionInput
from policyseal.domain.enums import ContentCategory, FileKind
from policyseal.domain.models import DocumentRegion
from policyseal.evals.assets import load_eval_assets


@dataclass(slots=True)
class RecordingClient(CompletionClient):
    client: CompletionClient
    completions: list[LocalCompletion] = field(default_factory=list)

    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion:
        completion = self.client.complete(regions)
        self.completions.append(completion)
        return completion


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _macro_f1(
    expected: tuple[ContentCategory, ...],
    predicted: tuple[ContentCategory | None, ...],
) -> float:
    scores: list[float] = []
    for label in sorted(set(expected), key=lambda item: item.value):
        true_positive = sum(
            expected_item is label and predicted_item is label
            for expected_item, predicted_item in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            expected_item is not label and predicted_item is label
            for expected_item, predicted_item in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            expected_item is label and predicted_item is not label
            for expected_item, predicted_item in zip(expected, predicted, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0 if denominator == 0 else 2 * true_positive / denominator)
    return sum(scores) / len(scores)


def _file_kind(scenario: str) -> FileKind:
    return {"xlsx": FileKind.XLSX, "docx": FileKind.DOCX, "pdf": FileKind.PDF}[scenario]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate local PolicySeal semantic inference")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--consistency-passes", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--minimum-macro-f1", type=float, default=0.9)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    assets = load_eval_assets()
    regions = tuple(
        DocumentRegion(
            id=snippet.id,
            file_kind=_file_kind(snippet.scenario),
            location=f"eval:{snippet.scenario}:{snippet.id}",
            order=index,
            text=snippet.text,
        )
        for index, snippet in enumerate(assets.semantic_snippets)
    )
    recording = RecordingClient(
        LocalVllmClient(
            args.base_url,
            args.model,
            timeout_seconds=args.timeout_seconds,
            max_tokens=args.max_tokens,
        )
    )
    graph = SemanticClassificationGraph(
        recording,
        batch_size=args.batch_size,
        consistency_passes=args.consistency_passes,
    )
    started = time.perf_counter()
    run = graph.run(regions)
    wall_seconds = time.perf_counter() - started
    expected = tuple(snippet.expected_category for snippet in assets.semantic_snippets)
    predicted = tuple(outcome.category for outcome in run.outcomes)
    macro_f1 = _macro_f1(expected, predicted)
    exact_matches = sum(
        expected_item is predicted_item
        for expected_item, predicted_item in zip(expected, predicted, strict=True)
    )
    latencies = [completion.latency_ms for completion in recording.completions]
    result = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "endpoint_scope": "localhost",
        "sample_count": len(expected),
        "model_region_count": len(regions),
        "batch_size": args.batch_size,
        "consistency_passes": args.consistency_passes,
        "request_count": len(recording.completions),
        "macro_f1": round(macro_f1, 6),
        "accuracy": round(exact_matches / len(expected), 6),
        "review_count": sum(outcome.requires_human_review for outcome in run.outcomes),
        "wall_seconds": round(wall_seconds, 6),
        "regions_per_second": round(len(regions) / wall_seconds, 6),
        "request_latency_ms_p50": round(_percentile(latencies, 0.5), 6),
        "request_latency_ms_p95": round(_percentile(latencies, 0.95), 6),
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "outcomes": [
            {
                "id": snippet.id,
                "expected": snippet.expected_category.value,
                "predicted": outcome.category.value if outcome.category is not None else None,
                "requires_human_review": outcome.requires_human_review,
                "reason_code": outcome.reason_code,
                "evidence_ids": outcome.evidence_ids,
            }
            for snippet, outcome in zip(assets.semantic_snippets, run.outcomes, strict=True)
        ],
    }
    encoded = json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True)
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{encoded}\n", encoding="utf-8")
    return 0 if macro_f1 >= args.minimum_macro_f1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
