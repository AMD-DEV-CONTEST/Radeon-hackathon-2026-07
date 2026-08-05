#!/usr/bin/env python3
"""quality_benchmark_agent.py — Run any benchmark through the Quality Oracle retry loop.

Supported benchmarks:
  --bench humaneval       164 Python coding problems (HumanEval)
  --bench triviaqa        Factual QA from TriviaQA (requires local data)
  --bench mt_bench        MT-Bench conversational quality (requires mt_bench_questions.jsonl)
  --bench custom          Single task from --prompt / --context flags

The loop:
  1. Generate response (DeepSeek / Claude)
  2. QualityOracle.score(response) → OracleResult
  3. If not solved: inject feedback_block() into retry prompt
  4. Repeat up to --max-attempts
  5. Report: pass@1, pass@k, hallucination rate, feature improvement curves

Usage:
  python scripts/quality_benchmark_agent.py --bench humaneval --limit 20
  python scripts/quality_benchmark_agent.py --bench triviaqa --limit 50 --verify-claims
  python scripts/quality_benchmark_agent.py --bench custom \
      --prompt "Explain what a mutex is" \
      --context "A mutex is a synchronization primitive..."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from quality_oracle import OracleResult, QualityOracle
from quality_oracle.rubric_decomposer import FACTUAL_QA_RUBRIC, HUMANEVAL_RUBRIC, MT_BENCH_RUBRIC

# ── Provider setup ────────────────────────────────────────────────────────────


def _generate(
    prompt: str,
    system: str = "",
    model: str = "deepseek",
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str:
    """Generate a response from DeepSeek or Claude."""
    if model == "deepseek" or model.startswith("deepseek"):
        import openai

        client = openai.OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    else:  # Claude
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        return msg.content[0].text if msg.content else ""


# ── Task loaders ──────────────────────────────────────────────────────────────


def load_humaneval(limit: int = 20) -> list[dict]:
    """Load HumanEval problems. Downloads dataset if needed."""
    try:
        import datasets

        ds = datasets.load_dataset("openai_humaneval", split="test", trust_remote_code=True)
        tasks = []
        for i, ex in enumerate(ds):
            if i >= limit:
                break
            tasks.append(
                {
                    "id": ex["task_id"],
                    "prompt": ex["prompt"],
                    "test": ex["test"],
                    "entry_point": ex["entry_point"],
                    "canonical_solution": ex.get("canonical_solution", ""),
                    "bench": "humaneval",
                }
            )
        return tasks
    except Exception as e:
        print(f"  [humaneval] load failed: {e}")
        print("  Install: pip install datasets")
        return []


def load_triviaqa(data_path: str, limit: int = 50) -> list[dict]:
    """Load TriviaQA questions from local jsonl file."""
    tasks = []
    p = Path(data_path)
    if not p.exists():
        print(f"  [triviaqa] not found: {data_path}")
        return []
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            ex = json.loads(line)
            tasks.append(
                {
                    "id": f"triviaqa_{i}",
                    "question": ex.get("question", ""),
                    "answers": ex.get("answer", {}).get("aliases", [])
                    or [ex.get("answer", {}).get("value", "")],
                    "context": ex.get("search_results", {}).get("search_context", "")[:2000],
                    "bench": "triviaqa",
                }
            )
    return tasks


def load_mt_bench(data_path: str, limit: int = 20) -> list[dict]:
    """Load MT-Bench questions from local jsonl file."""
    tasks = []
    p = Path(data_path)
    if not p.exists():
        print(f"  [mt_bench] not found: {data_path}")
        return []
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            ex = json.loads(line)
            tasks.append(
                {
                    "id": f"mt_bench_{ex.get('question_id', i)}",
                    "question": ex.get("turns", [""])[0],
                    "category": ex.get("category", "general"),
                    "reference": ex.get("reference", ""),
                    "bench": "mt_bench",
                }
            )
    return tasks


# ── HumanEval test runner ─────────────────────────────────────────────────────


def run_humaneval_tests(code: str, test: str, entry_point: str) -> tuple[bool, str]:
    """Execute HumanEval test cases against generated code. Returns (passed, error)."""
    import subprocess
    import tempfile

    full_code = code + "\n\n" + test + f"\n\ncheck({entry_point})\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(full_code)
        fname = f.name
    try:
        result = subprocess.run([sys.executable, fname], capture_output=True, text=True, timeout=10)
        passed = result.returncode == 0
        error = (result.stderr or result.stdout or "").strip()[:500]
        return passed, error
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


# ── Task result ───────────────────────────────────────────────────────────────


@dataclass
class TaskResult:
    task_id: str
    bench: str
    attempts: int
    solved: bool
    final_score: float
    oracle_scores: list[float] = field(default_factory=list)
    hallucination_counts: list[int] = field(default_factory=list)
    wall_time_s: float = 0.0
    error: str = ""


# ── Main loop ─────────────────────────────────────────────────────────────────


def run_task(
    task: dict,
    oracle: QualityOracle,
    gen_model: str,
    max_attempts: int,
    verbose: bool,
) -> TaskResult:
    """Run a single task through the oracle retry loop."""
    t0 = time.time()
    task_id = task["id"]
    bench = task["bench"]

    system_prompt = "You are an expert assistant. Answer accurately and concisely."
    base_prompt = ""
    context = ""

    if bench == "humaneval":
        base_prompt = (
            f"Complete the following Python function. "
            f"Return ONLY the complete function implementation, no explanation.\n\n"
            f"```python\n{task['prompt']}\n```"
        )
        context = task["prompt"]

    elif bench == "triviaqa":
        context = task.get("context", "")
        q = task["question"]
        base_prompt = f"Answer this question based on the context provided.\n\nContext:\n{context}\n\nQuestion: {q}"

    elif bench == "mt_bench":
        base_prompt = task["question"]

    elif bench == "custom":
        base_prompt = task.get("prompt", "")
        context = task.get("context", "")

    oracle_scores: list[float] = []
    hall_counts: list[int] = []
    best_result: OracleResult | None = None
    current_prompt = base_prompt

    for attempt in range(1, max_attempts + 1):
        if verbose:
            print(f"\n  [{task_id}] Attempt {attempt}/{max_attempts}")

        try:
            response = _generate(
                current_prompt,
                system=system_prompt,
                model=gen_model,
                temperature=0.7 if attempt == 1 else 0.3,
            )
        except Exception as e:
            if verbose:
                print(f"  [{task_id}] generation failed: {e}")
            break

        # For HumanEval: extract code block
        if bench == "humaneval":
            import re

            code_match = re.search(r"```python\s*(.*?)\s*```", response, re.DOTALL)
            if code_match:
                response_code = code_match.group(1)
            else:
                response_code = response

        # Oracle scoring
        result, is_regression = oracle.score_with_regression_check(
            response=response if bench != "humaneval" else response_code,
            best_result=best_result,
            attempt=attempt,
            question=base_prompt[:500],
            context=context[:1000],
        )

        oracle_scores.append(result.score)
        hall_counts.append(result.hallucination_count)

        # For HumanEval: also run actual tests and override solved flag
        if bench == "humaneval":
            passed, err = run_humaneval_tests(response_code, task["test"], task["entry_point"])
            result.solved = passed
            if not passed and err:
                # Inject test failure into feedback
                result._feedback = (
                    f"## TEST FAILURE\nYour code failed the test suite:\n{err}\n\n"
                    + result._feedback
                )

        # For TriviaQA: check if answer matches any accepted answer
        if bench == "triviaqa":
            answers = [a.lower() for a in task.get("answers", [])]
            resp_lower = response.lower()
            exact_match = any(ans in resp_lower for ans in answers if ans)
            if exact_match:
                result.solved = True

        if verbose:
            print(
                f"  [{task_id}] oracle={result.score_pct}% "
                f"hallucinations={result.hallucination_count} "
                f"solved={result.solved}"
            )

        if not is_regression:
            best_result = result

        if result.solved:
            break

        # Build retry prompt from feedback
        feedback = result.feedback_block()
        current_prompt = (
            f"{base_prompt}\n\n"
            f"## PREVIOUS ATTEMPT FEEDBACK (attempt {attempt})\n"
            f"{feedback}\n\n"
            f"Revise your answer to fix the issues above. "
            f"Keep everything that was already correct."
        )

    solved = best_result.solved if best_result else False
    final_score = best_result.score if best_result else 0.0
    return TaskResult(
        task_id=task_id,
        bench=bench,
        attempts=attempt,
        solved=solved,
        final_score=final_score,
        oracle_scores=oracle_scores,
        hallucination_counts=hall_counts,
        wall_time_s=round(time.time() - t0, 1),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--bench", choices=["humaneval", "triviaqa", "mt_bench", "custom"], default="custom"
    )
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--model", default="deepseek")
    ap.add_argument("--verify-claims", action="store_true")
    ap.add_argument("--solve-threshold", type=float, default=0.80)
    ap.add_argument("--output", default="logs/quality_bench_results.jsonl")
    ap.add_argument("--verbose", action="store_true")
    # Custom bench
    ap.add_argument("--prompt", default="")
    ap.add_argument("--context", default="")
    # Data paths for offline benches
    ap.add_argument("--data", default="")
    args = ap.parse_args()

    # Build oracle
    rubric_map = {
        "humaneval": HUMANEVAL_RUBRIC,
        "triviaqa": FACTUAL_QA_RUBRIC,
        "mt_bench": MT_BENCH_RUBRIC,
        "custom": FACTUAL_QA_RUBRIC,
    }
    oracle = QualityOracle(
        rubric=rubric_map[args.bench],
        verify_claims=args.verify_claims,
        solve_threshold=args.solve_threshold,
    )

    # Load tasks
    if args.bench == "humaneval":
        tasks = load_humaneval(args.limit)
    elif args.bench == "triviaqa":
        tasks = load_triviaqa(args.data or "data/triviaqa_dev.jsonl", args.limit)
    elif args.bench == "mt_bench":
        tasks = load_mt_bench(args.data or "data/mt_bench_questions.jsonl", args.limit)
    else:
        tasks = [
            {"id": "custom_0", "prompt": args.prompt, "context": args.context, "bench": "custom"}
        ]

    if not tasks:
        print("No tasks loaded. Exiting.")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"Quality Oracle Benchmark - {args.bench.upper()}")
    print(
        f"Tasks: {len(tasks)} | Model: {args.model} | "
        f"Max attempts: {args.max_attempts} | RAG verify: {args.verify_claims}"
    )
    print(f"{'=' * 60}\n")

    results: list[TaskResult] = []
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for i, task in enumerate(tasks):
        print(f"[{i + 1}/{len(tasks)}] {task['id']}")
        try:
            r = run_task(task, oracle, args.model, args.max_attempts, args.verbose)
        except Exception as e:
            traceback.print_exc()
            r = TaskResult(
                task_id=task["id"],
                bench=args.bench,
                attempts=0,
                solved=False,
                final_score=0.0,
                error=str(e),
            )
        results.append(r)

        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(r.__dict__) + "\n")

        status = "SOLVED" if r.solved else f"score={r.final_score:.0%}"
        print(
            f"  -> {status} | {r.attempts} attempts | "
            f"hall: {r.hallucination_counts} | {r.wall_time_s}s\n"
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    n = len(results)
    solved = sum(1 for r in results if r.solved)
    pass_at_1 = (
        sum(1 for r in results if r.oracle_scores and r.oracle_scores[0] >= args.solve_threshold)
        / n
    )
    avg_hall_att1 = (
        sum(r.hallucination_counts[0] if r.hallucination_counts else 0 for r in results) / n
    )
    avg_hall_final = (
        sum(r.hallucination_counts[-1] if r.hallucination_counts else 0 for r in results) / n
    )
    avg_score_att1 = sum(r.oracle_scores[0] if r.oracle_scores else 0 for r in results) / n
    avg_score_final = sum(r.final_score for r in results) / n

    print(f"\n{'=' * 60}")
    print(f"RESULTS — {args.bench.upper()} ({n} tasks)")
    print(f"{'=' * 60}")
    print(f"  Solved:              {solved}/{n} ({solved / n:.1%})")
    print(f"  Pass@1 (oracle):     {pass_at_1:.1%}")
    print(f"  Avg score att 1:     {avg_score_att1:.1%}")
    print(
        f"  Avg score final:     {avg_score_final:.1%}  (+{(avg_score_final - avg_score_att1):.1%} from oracle loop)"
    )
    print(f"  Hallucinations att1: {avg_hall_att1:.1f} avg/task")
    direction = "down" if avg_hall_final < avg_hall_att1 else "same"
    print(
        f"  Hallucinations final:{avg_hall_final:.1f} avg/task  "
        f"({direction} {abs(avg_hall_final - avg_hall_att1):.1f})"
    )
    print(f"  Results saved to:    {out_path}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
