#!/usr/bin/env python3
"""M3: Agent quality evaluation suite.

Runs 20 test questions against a sample repository, collects responses,
and scores them using LLM-as-judge (semi-automatic).

Usage:
    python scripts/eval_agent.py --repo ./sample_repo --base-url http://127.0.0.1:8080
    python scripts/eval_agent.py --repo ./sample_repo --grade-only results.json

Output: eval_results.json with per-question scores and overall pass rate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx


@dataclass
class EvalResult:
    question_id: str
    category: str
    question: str
    expected_keywords: list[str]
    agent_response: str = ""
    score: int = -1  # -1 = not graded, 0-3 = graded
    judge_reasoning: str = ""
    elapsed_seconds: float = 0.0


async def run_question(
    client: httpx.AsyncClient,
    question: dict,
    timeout: float = 120.0,
) -> EvalResult:
    """Send a question to the agent and collect the response."""
    result = EvalResult(
        question_id=question["id"],
        category=question.get("category", "general"),
        question=question["question"],
        expected_keywords=question.get("expected_keywords", []),
    )

    payload = {"message": question["question"]}
    t0 = time.time()

    try:
        # The chat endpoint streams SSE; collect all text events
        async with client.stream(
            "POST", "/api/chat",
            json=payload,
            timeout=timeout,
        ) as resp:
            response_parts = []
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                try:
                    event = json.loads(data)
                    if event.get("type") in ("text", "done"):
                        content = event.get("content", "")
                        if content:
                            response_parts.append(content)
                except json.JSONDecodeError:
                    continue

            result.agent_response = "".join(response_parts).strip()
    except Exception as e:
        result.agent_response = f"ERROR: {e}"

    result.elapsed_seconds = time.time() - t0

    # Quick keyword check (pre-judge filtering)
    found = [kw for kw in result.expected_keywords
             if kw.lower() in result.agent_response.lower()]
    result.score = len(found)  # temporary pre-score; judge overrides

    print(f"  [{result.question_id}] {result.category}: "
          f"{'OK' if result.agent_response else 'EMPTY'} "
          f"({result.elapsed_seconds:.1f}s, keywords: {len(found)}/{len(result.expected_keywords)})")

    return result


async def grade_results(
    client: httpx.AsyncClient,
    results: list[EvalResult],
    test_cases: list[dict],
    judge_model: str = "Qwen/Qwen2.5-Coder-14B-Instruct",
) -> None:
    """Use LLM-as-judge to score each result 0-3."""
    tc_map = {tc["id"]: tc for tc in test_cases}

    for result in results:
        tc = tc_map.get(result.question_id, {})
        expected = tc.get("expected_answer", tc.get("expected_keywords", []))

        prompt = f"""You are evaluating an AI coding assistant's response. Score 0-3:

Question: {result.question}
Expected answer should mention: {expected}
Agent response: {result.agent_response[:2000]}

Scoring:
3 = Correct and complete, references specific files/lines
2 = Mostly correct, minor gaps
1 = Partially relevant, missing key info
0 = Wrong or irrelevant

Respond with ONLY a JSON object: {{"score": N, "reasoning": "brief explanation"}}"""

        try:
            payload = {
                "model": judge_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.0,
            }
            resp = await client.post("/v1/chat/completions", json=payload, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]

            # Parse JSON from response
            import re
            json_match = re.search(r'\{[^}]+\}', text)
            if json_match:
                judge = json.loads(json_match.group())
                result.score = int(judge.get("score", 0))
                result.judge_reasoning = judge.get("reasoning", "")
        except Exception as e:
            result.judge_reasoning = f"Judge error: {e}"
            result.score = 0

        print(f"  [{result.question_id}] Score: {result.score}/3")


async def main():
    parser = argparse.ArgumentParser(description="RepositoryAnalysisAgent evaluation suite")
    parser.add_argument("--app-url", default="http://127.0.0.1:8080",
                        help="RepositoryAnalysisAgent app URL")
    parser.add_argument("--judge-url", default="http://127.0.0.1:8000",
                        help="LLM server URL for judging")
    parser.add_argument("--test-cases", default="eval/test_cases.json")
    parser.add_argument("--output", default="eval_results.json")
    parser.add_argument("--grade-only", default=None,
                        help="Skip agent run, just grade existing results")
    args = parser.parse_args()

    # Load test cases
    tc_path = Path(args.test_cases)
    if not tc_path.exists():
        print(f"Test cases not found: {tc_path}")
        return

    test_cases = json.loads(tc_path.read_text())
    print(f"Loaded {len(test_cases)} test cases\n")

    results: list[EvalResult] = []

    if args.grade_only:
        # Load existing results
        existing = json.loads(Path(args.grade_only).read_text())
        results = [EvalResult(**r) for r in existing]
    else:
        # Run agent on each question
        print("=" * 60)
        print("  RUNNING AGENT ON TEST QUESTIONS")
        print("=" * 60)
        async with httpx.AsyncClient(base_url=args.app_url) as client:
            for tc in test_cases:
                result = await run_question(client, tc)
                results.append(result)

    # Grade with LLM-as-judge
    print("\n" + "=" * 60)
    print("  GRADING (LLM-as-judge)")
    print("=" * 60)
    async with httpx.AsyncClient(base_url=args.judge_url) as judge_client:
        await grade_results(judge_client, results, test_cases)

    # Compute pass rate
    pass_count = sum(1 for r in results if r.score >= 2)
    pass_rate = pass_count / len(results) * 100 if results else 0

    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    print(f"  Total questions: {len(results)}")
    print(f"  Pass (score >= 2): {pass_count}/{len(results)} ({pass_rate:.0f}%)")
    print(f"  Target: > 70%")
    print(f"  Status: {'PASS' if pass_rate >= 70 else 'BELOW TARGET'}")

    # Category breakdown
    categories: dict[str, list[int]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r.score)
    print(f"\n  By category:")
    for cat, scores in sorted(categories.items()):
        cat_pass = sum(1 for s in scores if s >= 2)
        print(f"    {cat}: {cat_pass}/{len(scores)} ({cat_pass/len(scores)*100:.0f}%)")

    # Save
    output_data = [asdict(r) for r in results]
    Path(args.output).write_text(json.dumps(output_data, indent=2, ensure_ascii=False))
    print(f"\n  Saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
