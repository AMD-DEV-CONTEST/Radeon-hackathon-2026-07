from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from .agent import InvestigationService
from .llm import OpenAICompatibleClient
from .store import SessionStore

REQUIRED_TOOLS = {"get_deployments", "query_metrics", "search_logs"}


class OfflineClient:
    def choose_tool(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("local model is disabled")

    def complete(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("local model is disabled")


def benchmark_workflows(
    service_factory: Callable[[Path], InvestigationService],
    root: Path,
    incident: dict[str, Any],
    iterations: int = 10,
    warmups: int = 2,
    p95_limit_ms: float = 30_000,
) -> dict[str, Any]:
    if iterations < 1 or warmups < 0 or p95_limit_ms <= 0:
        raise ValueError("iterations must be positive, warmups non-negative, and p95 limit positive")
    root.mkdir(parents=True, exist_ok=True)
    for index in range(warmups):
        _run_workflow(service_factory(root / f"warmup-{index}"), incident, f"warmup-{index}-{uuid4().hex[:8]}")
    runs = [
        _run_workflow(service_factory(root / f"run-{index}"), incident, f"run-{index}-{uuid4().hex[:8]}")
        for index in range(iterations)
    ]
    result = summarize_runs(runs, p95_limit_ms)
    return {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "warmups": warmups,
        "iterations": iterations,
        "p95_limit_ms": p95_limit_ms,
        **result,
        "runs": runs,
    }


def _run_workflow(service: InvestigationService, incident: dict[str, Any], prefix: str) -> dict[str, Any]:
    started = perf_counter()
    try:
        investigation = service.create(f"{prefix}-create", incident)
        for step_index in range(4):
            investigation = service.next(
                investigation["id"], f"{prefix}-next-{step_index}", investigation["version"]
            )
        known_ids = {item["id"] for item in investigation["evidence"]}
        cited_ids = {
            evidence_id
            for collection in (investigation["hypotheses"], investigation["trace"], investigation["messages"])
            for item in collection
            for evidence_id in item.get("evidence_ids", [])
        }
        tools = {
            event["tool"]
            for event in investigation["trace"]
            if event.get("kind") == "tool" and event.get("status") in {"completed", "fallback"}
        }
        completed = (
            investigation["status"] in {"awaiting_approval", "completed"}
            and all(step["status"] == "completed" for step in investigation["plan"])
        )
        return {
            "completed": completed,
            "status": investigation["status"],
            "distinct_tools": sorted(tools),
            "unknown_citations": len(cited_ids - known_ids),
            "remote_core_requests": int(investigation["runtime"].get("remote_core_requests", 0)),
            "runtime_mode": investigation["runtime"].get("mode"),
            "degraded": bool(investigation["runtime"].get("degraded")),
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "completed": False,
            "status": "error",
            "distinct_tools": [],
            "unknown_citations": 0,
            "remote_core_requests": 0,
            "runtime_mode": "unknown",
            "degraded": True,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error": str(exc).replace("\n", " ")[:240],
        }


def summarize_runs(runs: list[dict[str, Any]], p95_limit_ms: float) -> dict[str, Any]:
    if not runs:
        raise ValueError("at least one measured run is required")
    latencies = [float(run["latency_ms"]) for run in runs]
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]
    completed = sum(bool(run["completed"]) for run in runs)
    three_tools = sum(set(run["distinct_tools"]) == REQUIRED_TOOLS for run in runs)
    unknown_citations = sum(int(run["unknown_citations"]) for run in runs)
    remote_requests = sum(int(run["remote_core_requests"]) for run in runs)
    failures: list[str] = []
    if completed != len(runs):
        failures.append("completion")
    if three_tools != len(runs):
        failures.append("three_tools")
    if unknown_citations:
        failures.append("unknown_citations")
    if remote_requests:
        failures.append("remote_core_requests")
    if p95 > p95_limit_ms:
        failures.append("p95_latency")
    return {
        "aggregate": {
            "completed_workflows": completed,
            "completion_rate": round(completed / len(runs), 4),
            "three_tool_workflows": three_tools,
            "three_tool_rate": round(three_tools / len(runs), 4),
            "unknown_citations": unknown_citations,
            "remote_core_requests": remote_requests,
            "latency_ms": {
                "min": round(min(latencies), 2),
                "mean": round(statistics.mean(latencies), 2),
                "p50": round(statistics.median(latencies), 2),
                "p95": round(p95, 2),
                "max": round(max(latencies), 2),
            },
        },
        "gate": {"passed": not failures, "failures": failures},
    }


def _service_factory(timeout: float) -> Callable[[Path], InvestigationService]:
    candidate = OpenAICompatibleClient(timeout=timeout)
    enabled = os.getenv("LIC_ENABLE_LLM", "0").lower() in {"1", "true", "yes"}
    if not enabled:
        return lambda root: InvestigationService(
            SessionStore(root), client=OfflineClient(), runtime={"mode": "offline-safe", "degraded": False}
        )
    hostname = urlparse(candidate.base_url).hostname
    mode = "local-unverified" if hostname in {"127.0.0.1", "localhost", "::1"} else "remote-api"
    runtime = {"mode": mode, "model": candidate.model, "base_url": candidate.base_url, "degraded": False}
    return lambda root: InvestigationService(SessionStore(root), client=candidate, runtime=runtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the complete four-step incident investigation benchmark.")
    parser.add_argument("--input", type=Path, default=Path("samples/checkout-latency.json"))
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--p95-limit-ms", type=float, default=30_000)
    parser.add_argument("--model-timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.iterations < 1 or args.warmups < 0 or args.p95_limit_ms <= 0 or args.model_timeout <= 0:
        parser.error("iterations/model timeout/P95 limit must be positive and warmups non-negative")
    incident = json.loads(args.input.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="lic-workflow-benchmark-") as directory:
        result = benchmark_workflows(
            _service_factory(args.model_timeout),
            Path(directory),
            incident,
            iterations=args.iterations,
            warmups=args.warmups,
            p95_limit_ms=args.p95_limit_ms,
        )
    result["input"] = str(args.input)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
