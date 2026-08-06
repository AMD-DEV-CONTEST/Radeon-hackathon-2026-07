"""Parameterized load test: concurrency capacity boundary probing for the Insurance RAG Agent.

References the four-round controlled-variable method of lesson 25 integrated_agent_service/load_test.py:
- Baseline round: small request volume to verify the main path
- Concurrency round: gradually raise client concurrency, observe the latency inflection point
- Timeout round: gradually shrink the timeout, observe 503 rejection behavior
- Capacity round: adjust the Agently scheduler concurrency, observe throughput changes

The five parameter groups fall into three categories (change only one variable type at a time):
| Parameter group  | Parameter          | Meaning                                    |
|------------------|--------------------|--------------------------------------------|
| Client pressure  | --requests         | total number of requests to submit         |
| Client pressure  | --concurrency      | how many clients submit concurrently       |
| Service capacity | --timeout          | per-request timeout seconds (controls the Agent concurrency window) |
| Service capacity | --max-concurrency  | Agently scheduler max concurrency (overrides agent.toml) |
| Task duration    | --question-mode    | preset question mode (affects RAG pipeline runtime) |

Three question modes (simulate different business-flow lengths):
| Mode          | Question                                        | LLM Calls | Expected Latency |
|---------------|-------------------------------------------------|-----------|------------------|
| simple        | What is the coverage of employer liability insurance? | 3-4   | 15-25s   |
| comparison    | Compare the coverage of employer liability and group accident insurance; what are the main differences? | 5-7 | 25-45s |
| multistep     | Compare the coverage of Plan A and Plan B critical illness insurance, and judge whether a case pays out | 6-8 | 30-60s |

Three invariants (checked first in every round):
1. accepted + rejected_503 + failed = request_count
2. sse_completed <= accepted
3. observed_peak_concurrency <= concurrency

Usage::

    # Baseline round (simple question, 60s timeout)
    python scripts/load_test.py --question-mode simple --requests 10 --concurrency 2

    # Multi-step comparison scenario baseline (longer business flow, 120s timeout)
    python scripts/load_test.py --question-mode comparison --requests 10 --concurrency 2 --timeout 120

    # Concurrency round
    python scripts/load_test.py --question-mode comparison --requests 40 --concurrency 20 --timeout 120

    # Overload round
    python scripts/load_test.py --question-mode simple --requests 80 --concurrency 40 --timeout 15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════════════
# Preset question modes
# ═══════════════════════════════════════════════════════════════════════

QUESTION_PRESETS: dict[str, dict[str, Any]] = {
    "simple": {
        "question": "What is the coverage of employer liability insurance?",
        "description": "single-document retrieval + direct answer",
        "expected_llm_calls": "3-4",
        "expected_latency_s": "15-25",
        "recommended_timeout": 60,
    },
    "comparison": {
        "question": "Compare the coverage of employer liability insurance and group accident insurance; what are the main differences?",
        "description": "two-document retrieval + comparative reasoning (F3 multi-step task)",
        "expected_llm_calls": "5-7",
        "expected_latency_s": "25-45",
        "recommended_timeout": 120,
    },
    "multistep": {
        "question": (
            "Compare the coverage of employer liability insurance and group accident insurance. "
            "If an employee is injured during an accident while on overtime and becomes disabled, "
            "can each of the two insurance policies pay out? What is the difference in payout conditions and amounts?"
        ),
        "description": "two-document retrieval + comparative reasoning + case judgment (longest business flow)",
        "expected_llm_calls": "6-8",
        "expected_latency_s": "30-60",
        "recommended_timeout": 180,
    },
}


@dataclass(frozen=True)
class Scenario:
    """Parameters for a single load-test round."""

    name: str
    request_count: int
    client_concurrency: int
    timeout_seconds: float
    base_url: str
    question: str
    question_mode: str


@dataclass
class RequestResult:
    """Result of a single request."""

    index: int
    status: str  # "success" | "rejected_503" | "failed" | "timeout"
    latency_ms: float
    answer_length: int = 0
    has_citations: bool = False
    error: str = ""


@dataclass
class ScenarioReport:
    """Report for a single load-test round."""

    scenario: Scenario
    results: list[RequestResult] = field(default_factory=list)
    peak_active: int = 0

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.results if r.status == "success")

    @property
    def rejected_503(self) -> int:
        return sum(1 for r in self.results if r.status == "rejected_503")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status in ("failed", "timeout"))

    @property
    def latencies_ms(self) -> list[float]:
        return [r.latency_ms for r in self.results if r.status == "success"]


def _percentile(values: list[float], ratio: float) -> float:
    """Compute a percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * ratio))
    return ordered[index]


async def preflight_check(base_url: str, timeout: float = 10) -> dict[str, Any]:
    """Preflight check before the load test: confirm the service is available, measure single-request latency.

    Returns:
        dict with "ok", "latency_ms", "detail"
    """
    print("\n[Preflight] Verifying service availability...")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout, trust_env=False) as client:
            # 1. Health check
            t0 = time.perf_counter()
            resp = await client.get("/api/health")
            health_ms = (time.perf_counter() - t0) * 1000

            if resp.status_code != 200:
                print(f"  [FAIL] /api/health returned {resp.status_code}")
                return {"ok": False, "reason": f"health check failed: HTTP {resp.status_code}"}

            health = resp.json()
            print(f"  /api/health: {health_ms:.0f}ms, status={health.get('status')}")
            print(f"  RAG ready: {health.get('rag_ready', 'unknown')}")
            print(f"  Model: {health.get('model_info', {})}")

            if not health.get("rag_ready"):
                print(f"  [WARN] RAG is not ready, will run in pure LLM mode")

            return {
                "ok": True,
                "health_latency_ms": round(health_ms, 0),
                "rag_ready": health.get("rag_ready", False),
                "model_info": health.get("model_info", {}),
            }
    except httpx.ConnectError:
        print(f"  [FAIL] cannot connect to {base_url}")
        print(f"  Please confirm the Web service is running: python scripts/start_server.py")
        return {"ok": False, "reason": f"connection refused: {base_url}"}
    except Exception as e:
        print(f"  [FAIL] preflight exception: {type(e).__name__}: {e}")
        return {"ok": False, "reason": str(e)[:200]}


async def single_request_timing(
    base_url: str,
    question: str,
    timeout: float = 180,
) -> dict[str, Any]:
    """Send a single request to measure the real latency, used for timeout suggestions.

    Agently five-step flow (understand -> plan -> validate -> fetch -> answer)
    takes at least 3-4 LLM calls; a simple question is expected to take 15-25s.
    """
    print(f"\n[single-request timing] Measuring single-request latency (timeout={timeout}s)...")
    print(f"  question: {question[:60]}")
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=timeout, trust_env=False,
        ) as client:
            t0 = time.perf_counter()
            resp = await client.post(
                "/api/chat",
                json={"message": question, "session_id": "preflight-timing"},
            )
            elapsed = time.perf_counter() - t0

            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("answer", "")
                citations = data.get("citations", [])
                print(f"  [OK] latency: {elapsed:.1f}s")
                print(f"  answer length: {len(answer)} chars")
                print(f"  citation count: {len(citations)}")
                print(f"  status: {data.get('status', 'unknown')}")

                # Timeout suggestion
                suggested_timeout = max(60, int(elapsed * 2.5))
                print(f"\n  suggested timeout: {suggested_timeout}s (single-request latency x 2.5)")
                return {
                    "ok": True,
                    "latency_s": round(elapsed, 1),
                    "answer_length": len(answer),
                    "citation_count": len(citations),
                    "suggested_timeout": suggested_timeout,
                }
            else:
                print(f"  [FAIL] HTTP {resp.status_code}: {resp.text[:200]}")
                return {"ok": False, "reason": f"HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        print(f"  [FAIL] single request timed out ({timeout}s)")
        print(f"  vLLM may not be running or is responding very slowly")
        return {"ok": False, "reason": f"single request timeout >{timeout}s"}
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return {"ok": False, "reason": str(e)[:200]}


async def run_scenario(scenario: Scenario) -> dict[str, Any]:
    """Run one load-test scenario and return the report dictionary.

    Flow:
    1. Create client_concurrency concurrent submission coroutines
    2. Each coroutine POSTs /api/chat with an insurance question
    3. A Semaphore limits how many requests enter the HTTP entry point at once
    4. Timed-out or 503 requests are recorded as rejected/failed
    5. Successful requests record latency, answer length, and citation status
    """
    report = ScenarioReport(scenario=scenario)
    semaphore = asyncio.Semaphore(scenario.client_concurrency)
    active_counter = 0
    peak_active = 0
    counter_lock = asyncio.Lock()

    async with httpx.AsyncClient(
        base_url=scenario.base_url,
        timeout=scenario.timeout_seconds,
        trust_env=False,
        limits=httpx.Limits(
            max_connections=scenario.client_concurrency + 10,
            max_keepalive_connections=scenario.client_concurrency + 10,
        ),
    ) as client:
        async def submit(index: int) -> RequestResult:
            nonlocal active_counter, peak_active
            async with semaphore:
                async with counter_lock:
                    active_counter += 1
                    peak_active = max(peak_active, active_counter)
                try:
                    t0 = time.perf_counter()
                    response = await client.post(
                        "/api/chat",
                        json={
                            "message": scenario.question,
                            "session_id": f"load-test-{index}",
                        },
                    )
                    latency_ms = (time.perf_counter() - t0) * 1000

                    if response.status_code == 200:
                        data = response.json()
                        return RequestResult(
                            index=index,
                            status="success",
                            latency_ms=round(latency_ms, 2),
                            answer_length=len(data.get("answer", "")),
                            has_citations=bool(data.get("citations")),
                        )
                    elif response.status_code == 503:
                        return RequestResult(
                            index=index,
                            status="rejected_503",
                            latency_ms=round(latency_ms, 2),
                            error=f"503: {response.text[:100]}",
                        )
                    else:
                        return RequestResult(
                            index=index,
                            status="failed",
                            latency_ms=round(latency_ms, 2),
                            error=f"status={response.status_code}: {response.text[:100]}",
                        )
                except httpx.TimeoutException:
                    latency_ms = (time.perf_counter() - t0) * 1000
                    return RequestResult(
                        index=index,
                        status="timeout",
                        latency_ms=round(latency_ms, 2),
                        error=f"timeout>{scenario.timeout_seconds}s",
                    )
                except Exception as exc:
                    return RequestResult(
                        index=index,
                        status="failed",
                        latency_ms=0.0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                finally:
                    async with counter_lock:
                        active_counter -= 1

        tasks = [submit(i) for i in range(scenario.request_count)]
        report.results = await asyncio.gather(*tasks)
        report.peak_active = peak_active

    lats = report.latencies_ms
    return {
        "name": scenario.name,
        "request_count": scenario.request_count,
        "accepted": report.accepted,
        "rejected_503": report.rejected_503,
        "failed": report.failed,
        "observed_peak_concurrency": report.peak_active,
        "client_concurrency": scenario.client_concurrency,
        "timeout_seconds": scenario.timeout_seconds,
        "question_mode": scenario.question_mode,
        "question": scenario.question[:80],
        "latency_ms": {
            "p50": round(median(lats), 2) if lats else 0,
            "p95": round(_percentile(lats, 0.95), 2) if lats else 0,
            "max": round(max(lats), 2) if lats else 0,
        },
        "answer_avg_length": round(
            sum(r.answer_length for r in report.results if r.status == "success")
            / max(report.accepted, 1),
            0,
        ),
        "citation_rate": round(
            sum(1 for r in report.results if r.has_citations)
            / max(report.accepted, 1),
            2,
        ),
        "invariants": {
            "conservation": report.accepted + report.rejected_503 + report.failed == scenario.request_count,
            "peak_within_limit": report.peak_active <= scenario.client_concurrency,
        },
        "errors": [
            {"index": r.index, "status": r.status, "error": r.error}
            for r in report.results
            if r.status not in ("success",)
        ][:10],  # keep only the first 10 errors
    }


def parse_scenario() -> tuple[Scenario, Path, dict[str, Any]]:
    """Parse the command-line arguments into a load-test scenario."""
    parser = argparse.ArgumentParser(
        description="Insurance RAG Agent parameterized load test - four-round capacity boundary probing",
    )
    parser.add_argument("--name", default="custom-load", help="scenario name")
    parser.add_argument("--requests", type=int, default=10, help="total number of requests")
    parser.add_argument("--concurrency", type=int, default=2, help="client concurrency")
    parser.add_argument("--timeout", type=float, default=0, help="per-request timeout (seconds), 0=auto-recommended")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="Agent Web service URL",
    )

    # Question mode
    parser.add_argument(
        "--question-mode",
        choices=["simple", "comparison", "multistep"],
        default="comparison",
        help="preset question mode (default comparison)",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="custom question text (overrides --question-mode)",
    )

    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="skip the preflight check (single-request timing)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="report output path (if empty, auto-generated by mode name, e.g. load_test_simple.json)",
    )
    args = parser.parse_args()

    # Determine the question
    if args.question:
        question = args.question
        mode = "custom"
        preset = None
    else:
        preset = QUESTION_PRESETS[args.question_mode]
        question = preset["question"]
        mode = args.question_mode

    positive_values = {
        "requests": args.requests,
        "concurrency": args.concurrency,
    }
    invalid = [name for name, value in positive_values.items() if value <= 0]
    if invalid:
        parser.error(f"the following parameters must be greater than 0: {', '.join(invalid)}")

    # Timeout auto-recommendation
    timeout = args.timeout
    if timeout == 0 and preset:
        timeout = preset["recommended_timeout"]
    elif timeout == 0:
        timeout = 60  # default 60s

    # Auto-generate the output path by mode name to avoid different scenarios overwriting each other
    output_path = args.output
    if output_path is None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"docs/benchmarks/load_test_{mode}_{ts}.json")

    preflight = {
        "skip": args.skip_preflight,
        "preset": preset,
    }

    return (
        Scenario(
            name=args.name,
            request_count=args.requests,
            client_concurrency=args.concurrency,
            timeout_seconds=timeout,
            base_url=args.base_url,
            question=question,
            question_mode=mode,
        ),
        output_path,
        preflight,
    )


async def main(scenario: Scenario, output: Path, preflight: dict[str, Any]) -> None:
    """Run the load test and save the report."""
    preset = preflight.get("preset")

    print("=" * 70)
    print("Insurance RAG Agent load test")
    print("=" * 70)
    print(f"  Scenario: {scenario.name}")
    print(f"  Requests: {scenario.request_count}, concurrency: {scenario.client_concurrency}")
    print(f"  Timeout: {scenario.timeout_seconds}s, target: {scenario.base_url}")
    print(f"  Question mode: {scenario.question_mode}")
    if preset:
        print(f"  Business-flow description: {preset['description']}")
        print(f"  Expected LLM calls: {preset['expected_llm_calls']}")
        print(f"  Expected single-request latency: {preset['expected_latency_s']}s")
    print(f"  Question: {scenario.question[:80]}")
    print()

    # -- Preflight --
    if not preflight.get("skip"):
        # 1. Health check
        health = await preflight_check(scenario.base_url)
        if not health.get("ok"):
            print(f"\n[preflight failed] {health.get('reason')}")
            print("Please start the Web service first: python scripts/start_server.py")
            sys.exit(1)

        # 2. Single-request timing
        timing = await single_request_timing(
            scenario.base_url,
            scenario.question,
            timeout=max(scenario.timeout_seconds, 180),
        )

        if not timing.get("ok"):
            print(f"\n[preflight failed] the single request could not complete: {timing.get('reason')}")
            print("Possible causes:")
            print("  1. The vLLM service is not running or is responding very slowly")
            print("  2. The model is still loading; wait for vLLM to be fully ready before retrying")
            print("  3. A network or firewall block")
            print("\nDiagnostic commands:")
            print(f"  curl http://localhost:8000/v1/models  # check vLLM")
            print(f"  curl {scenario.base_url}/api/health   # check the Web service")
            sys.exit(1)

        single_latency = timing.get("latency_s", 0)
        suggested = timing.get("suggested_timeout", 60)

        # Timeout warning
        if scenario.timeout_seconds < single_latency * 1.5:
            print(f"\n  [WARNING] current timeout {scenario.timeout_seconds}s < single-request latency {single_latency}s x 1.5")
            print(f"  Latency will increase further under concurrency; recommend --timeout {suggested}")
            print(f"  Continuing anyway (may all time out)...\n")
        else:
            print(f"\n  Timeout {scenario.timeout_seconds}s is sufficient (single request {single_latency}s)\n")
    else:
        print("[preflight skipped]\n")

    # -- Load test --
    print("Running the load test...")
    start = time.perf_counter()
    report = await run_scenario(scenario)
    elapsed = time.perf_counter() - start

    report["elapsed_seconds"] = round(elapsed, 2)
    report["throughput_per_second"] = round(
        report["accepted"] / elapsed if elapsed > 0 else 0, 2,
    )

    # All-timeout diagnosis
    if report["failed"] == scenario.request_count and report["accepted"] == 0:
        print(f"\n[All failed] {report['failed']}/{scenario.request_count} requests timed out or failed")
        print("Diagnostic suggestions:")
        print(f"  1. Single-request latency: {timing.get('latency_s', '?')}s (measured in preflight)")
        print(f"  2. Current timeout: {scenario.timeout_seconds}s")
        if timing.get("suggested_timeout", 0) > scenario.timeout_seconds:
            print(f"  3. Suggested timeout: {timing['suggested_timeout']}s")
            print(f"     Re-run: python scripts/load_test.py --timeout {timing['suggested_timeout']}")
        print(f"  4. Latency may double at concurrency {scenario.client_concurrency}")
        print(f"  5. Consider --question-mode simple to shorten the business flow")

    output_path = PROJECT_ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    full_report = {
        "method": (
            "real HTTP + FastAPI /api/chat + Agently TriggerFlow five-step flow; "
            "a Semaphore limits client concurrency; timeouts and 503s are recorded as rejections"
        ),
        "question_mode": scenario.question_mode,
        "question_description": preset["description"] if preset else "custom",
        "expected_llm_calls": preset["expected_llm_calls"] if preset else "unknown",
        "preflight": timing if not preflight.get("skip") else {"skipped": True},
        "scenario": report,
    }

    output_path.write_text(
        json.dumps(full_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport saved: {output_path}")


if __name__ == "__main__":
    selected_scenario, report_path, preflight_cfg = parse_scenario()
    asyncio.run(main(selected_scenario, report_path, preflight_cfg))
