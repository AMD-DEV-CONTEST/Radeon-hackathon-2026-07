"""
scripts/determinex_livecode_run.py — LiveCodeBench harness for Determinex

Dataset: livecodebench/code_generation_lite
  - No training contamination: problems sourced from competitive programming
    platforms after May 2023 (post-GPT-4 cutoff)
  - Three difficulty tiers: easy / medium / hard
  - Each problem has starter code, public test cases, and private test cases

Determinex strategy: use the Architect (Claude Sonnet) directly in single-shot
write-from-scratch mode. No repo cloning needed — problems are self-contained.

Usage:
    python scripts/determinex_livecode_run.py --n 50 --workers 4
    python scripts/determinex_livecode_run.py --n 100 --difficulty easy
    python scripts/determinex_livecode_run.py --n 300 --difficulty all --workers 4 \\
        --out logs/livecode/run_20260503.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="[LCB] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("determinex_livecode")

# ── Backend config (reuses determinex_swebench_agent env vars) ───────────────────
_ANTHROPIC_KEY = os.getenv("DETERMINEX_ANTHROPIC_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
_ANTHROPIC_MODEL = os.getenv("DETERMINEX_ANTHROPIC_MODEL", "claude-sonnet-4-6")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEEPSEEK_KEY = os.getenv("DETERMINEX_DEEPSEEK_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
_DEEPSEEK_MODEL = os.getenv("DETERMINEX_DEEPSEEK_MODEL", "deepseek-chat")
_DEEPSEEK_URL = "https://api.deepseek.com/v1"

_DEFAULT_BACKEND = os.getenv("DETERMINEX_LCB_BACKEND", "anthropic")


# ── LLM call ──────────────────────────────────────────────────────────────────


def _call_llm(prompt: str, backend: str = _DEFAULT_BACKEND, temperature: float = 0.1) -> str:
    import urllib.request

    if backend == "anthropic":
        if not _ANTHROPIC_KEY:
            log.error("ANTHROPIC_API_KEY not set")
            return ""
        body = {
            "model": _ANTHROPIC_MODEL,
            "max_tokens": 4096,
            "temperature": temperature,
            "system": "You are an expert competitive programmer. Write correct, efficient Python solutions.",
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            _ANTHROPIC_URL,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": _ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                return data["content"][0]["text"].strip()
        except Exception as e:
            log.error("Anthropic call failed: %s", e)
            return ""

    elif backend == "deepseek":
        if not _DEEPSEEK_KEY:
            log.error("DEEPSEEK_API_KEY not set")
            return ""
        body = {
            "model": _DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert competitive programmer. Write correct, efficient Python solutions.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 4096,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{_DEEPSEEK_URL}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_DEEPSEEK_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.error("DeepSeek call failed: %s", e)
            return ""

    log.error("Unknown backend: %s", backend)
    return ""


# ── Code extraction ────────────────────────────────────────────────────────────


def _extract_python_code(response: str) -> str:
    """Extract Python code from a markdown-fenced or bare response."""
    # Try ```python ... ``` first
    m = re.search(r"```python\s*(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try ``` ... ```
    m = re.search(r"```\s*(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Return as-is if no fences
    return response.strip()


# ── Test execution ────────────────────────────────────────────────────────────


def _run_test_cases(
    code: str,
    test_cases: list[dict],
    timeout: int = 10,
) -> tuple[bool, str, int, int]:
    """
    Execute solution against a list of test cases.

    test_cases format (LCB standard):
        [{"input": "...", "output": "...", "testtype": "stdin"}]
      or stdin-based: run with stdin=input, compare stdout to output.

    Returns (all_passed, message, passed_count, total_count).
    """
    if not test_cases:
        return True, "no test cases", 0, 0

    passed = 0
    messages = []

    for i, tc in enumerate(test_cases):
        tc_input = tc.get("input", "")
        tc_output = tc.get("output", "").strip()
        tc_type = tc.get("testtype", "stdin")

        with tempfile.NamedTemporaryFile(
            suffix=".py",
            mode="w",
            delete=False,
            prefix="lcb_solution_",
            encoding="utf-8",
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                input=tc_input,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            actual = result.stdout.strip()
            if actual == tc_output:
                passed += 1
            else:
                messages.append(f"TC{i}: expected={tc_output!r} got={actual!r}")
                if result.returncode != 0:
                    messages.append(f"  stderr: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            messages.append(f"TC{i}: TIMEOUT (>{timeout}s)")
        except Exception as e:
            messages.append(f"TC{i}: ERROR: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    total = len(test_cases)
    all_passed = passed == total
    summary = f"{passed}/{total} passed"
    if messages:
        summary += " | " + " | ".join(messages[:3])
    return all_passed, summary, passed, total


# ── Prompt builder ─────────────────────────────────────────────────────────────


def _build_prompt(problem: dict, failed_output: str = "") -> str:
    title = problem.get("question_title", "Problem")
    content = problem.get("question_content", "")
    starter = problem.get("starter_code", "")
    difficulty = problem.get("difficulty", "")
    pub_tests = problem.get("public_test_cases", [])

    # Format a few public test examples
    test_examples = ""
    if pub_tests:
        examples = []
        for tc in pub_tests[:3]:
            examples.append(
                f"Input:\n{tc.get('input', '')}\nExpected Output:\n{tc.get('output', '')}"
            )
        test_examples = "\n\nExample test cases:\n" + "\n\n".join(examples)

    retry_section = ""
    if failed_output:
        retry_section = (
            f"\n\nPREVIOUS ATTEMPT FAILED:\n{failed_output[:400]}\n"
            f"Fix the issue above in your new solution."
        )

    prompt = (
        f"Solve this competitive programming problem in Python.\n\n"
        f"Problem: {title} (Difficulty: {difficulty})\n\n"
        f"{content}\n"
        f"{test_examples}"
        f"{retry_section}\n\n"
    )

    if starter:
        prompt += (
            f"Starter code (complete this):\n```python\n{starter}\n```\n\n"
            f"Return ONLY the complete Python solution — no explanation, no extra prose.\n"
            f"Your code must read from stdin and write to stdout.\n"
        )
    else:
        prompt += (
            "Return ONLY the complete Python solution — no explanation, no extra prose.\n"
            "Your code must read from stdin and write to stdout.\n"
        )

    return prompt


# ── Single instance solver ────────────────────────────────────────────────────


def solve_instance(
    problem: dict,
    backend: str = _DEFAULT_BACKEND,
    max_retries: int = 2,
    test_timeout: int = 10,
) -> dict:
    """Solve a single LiveCodeBench problem."""
    instance_id = problem.get("question_id", "unknown")
    difficulty = problem.get("difficulty", "?")
    pub_tests = problem.get("public_test_cases", [])
    priv_tests = problem.get("private_test_cases", [])

    last_failure = ""
    solution = ""
    code = ""
    pub_passed = False

    for attempt in range(1, max_retries + 2):
        prompt = _build_prompt(problem, failed_output=last_failure if attempt > 1 else "")
        response = _call_llm(prompt, backend=backend, temperature=0.05 * attempt)
        if not response:
            continue

        code = _extract_python_code(response)
        if not code:
            last_failure = "Empty response from model."
            continue

        # Evaluate against public test cases (fast feedback loop)
        if pub_tests:
            pub_passed, pub_msg, _, _ = _run_test_cases(code, pub_tests, timeout=test_timeout)
            if pub_passed:
                solution = code
                break
            last_failure = pub_msg
            log.debug("[%s] attempt %d public tests FAIL: %s", instance_id, attempt, pub_msg[:80])
        else:
            # No public tests — take the first valid code
            solution = code
            break

    if not solution:
        solution = code  # best-effort: last generated code even if public tests failed

    # Evaluate against private test cases (the real score)
    priv_passed_all = False
    priv_msg = "no private tests"
    priv_pass_count = 0
    priv_total = len(priv_tests)

    if solution and priv_tests:
        priv_passed_all, priv_msg, priv_pass_count, _ = _run_test_cases(
            solution,
            priv_tests,
            timeout=test_timeout,
        )

    return {
        "instance_id": instance_id,
        "difficulty": difficulty,
        "solution": solution,
        "passed": priv_passed_all,
        "private_pass_count": priv_pass_count,
        "private_total": priv_total,
        "public_passed": pub_passed,
        "message": priv_msg,
        "backend": backend,
    }


# ── Dataset loader ────────────────────────────────────────────────────────────


def _load_dataset(
    n: int,
    difficulty: str | None = None,
    dataset_name: str = "livecodebench/code_generation_lite",
) -> list[dict]:
    """Load LiveCodeBench instances. Falls back to cached JSONL if HF offline."""
    cache_path = Path(__file__).resolve().parent.parent / "data" / "livecode_cache.jsonl"

    # Try HuggingFace datasets first
    try:
        from datasets import load_dataset  # type: ignore[import]

        ds = load_dataset(dataset_name, split="test", trust_remote_code=True)
        instances = [dict(row) for row in ds]
        log.info("Loaded %d LiveCodeBench instances from HuggingFace", len(instances))

        # Cache for offline use
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            for inst in instances:
                # Serialize test cases properly
                row = dict(inst)
                for k in ("public_test_cases", "private_test_cases"):
                    if isinstance(row.get(k), str):
                        try:
                            row[k] = json.loads(row[k])
                        except Exception:
                            pass
                f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("HuggingFace load failed (%s) — trying local cache", e)
        if not cache_path.exists():
            log.error("No local cache at %s — cannot load dataset", cache_path)
            return []
        instances = []
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    instances.append(json.loads(line))
        log.info("Loaded %d instances from local cache", len(instances))

    # Deserialize test case strings (HF sometimes returns them as JSON strings)
    for inst in instances:
        for k in ("public_test_cases", "private_test_cases"):
            if isinstance(inst.get(k), str):
                try:
                    inst[k] = json.loads(inst[k])
                except Exception:
                    inst[k] = []

    if difficulty and difficulty != "all":
        instances = [x for x in instances if x.get("difficulty", "").lower() == difficulty.lower()]
        log.info("Filtered to %d instances (difficulty=%s)", len(instances), difficulty)

    return instances[:n]


# ── Main runner ───────────────────────────────────────────────────────────────


def run_benchmark(
    n: int = 50,
    difficulty: str | None = None,
    workers: int = 4,
    backend: str = _DEFAULT_BACKEND,
    max_retries: int = 2,
    output_path: str = "logs/livecode/results.jsonl",
    test_timeout: int = 10,
) -> list[dict]:
    log.info(
        "LiveCodeBench: n=%d difficulty=%s workers=%d backend=%s",
        n,
        difficulty or "all",
        workers,
        backend,
    )

    instances = _load_dataset(n, difficulty)
    if not instances:
        log.error("No instances loaded — aborting")
        return []

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(solve_instance, inst, backend, max_retries, test_timeout): inst
            for inst in instances
        }
        for future in as_completed(futures):
            try:
                result = future.result(timeout=300)
                results.append(result)
                solved = sum(1 for r in results if r["passed"])
                elapsed = time.time() - start
                log.info(
                    "[%d/%d] %s → %s (%d/%d private) | Running: %d/%d (%.1f%%) | %.0fs",
                    len(results),
                    len(instances),
                    result["instance_id"],
                    "PASS" if result["passed"] else "FAIL",
                    result["private_pass_count"],
                    result["private_total"],
                    solved,
                    len(results),
                    100 * solved / len(results),
                    elapsed,
                )
            except Exception as e:
                inst = futures[future]
                log.warning("Instance %s raised: %s", inst.get("question_id", "?"), e)
                results.append(
                    {
                        "instance_id": inst.get("question_id", "unknown"),
                        "difficulty": inst.get("difficulty", "?"),
                        "solution": "",
                        "passed": False,
                        "private_pass_count": 0,
                        "private_total": 0,
                        "public_passed": False,
                        "message": str(e),
                        "backend": backend,
                    }
                )

    # Write results
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Final report
    solved = sum(1 for r in results if r["passed"])
    total = len(results)
    by_diff: dict[str, list[bool]] = {}
    for r in results:
        d = r["difficulty"]
        by_diff.setdefault(d, []).append(r["passed"])

    log.info("=" * 60)
    log.info("FINAL: %d/%d = %.1f%%", solved, total, 100 * solved / total if total else 0)
    for diff_name, outcomes in sorted(by_diff.items()):
        pass_count = sum(outcomes)
        log.info(
            "  %-8s %d/%d = %.1f%%",
            diff_name,
            pass_count,
            len(outcomes),
            100 * pass_count / len(outcomes) if outcomes else 0,
        )
    log.info("Results written to: %s", output_path)
    log.info("=" * 60)

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Determinex LiveCodeBench harness")
    p.add_argument("--n", type=int, default=50, help="Number of instances to solve")
    p.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard", "all"],
        default=None,
        help="Filter by difficulty tier",
    )
    p.add_argument("--workers", type=int, default=4, help="Parallel workers")
    p.add_argument("--backend", choices=["anthropic", "deepseek"], default=_DEFAULT_BACKEND)
    p.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry attempts per problem when public tests fail",
    )
    p.add_argument("--timeout", type=int, default=10, help="Seconds per test case")
    p.add_argument("--out", default="logs/livecode/results.jsonl", help="Output JSONL path")
    args = p.parse_args()

    run_benchmark(
        n=args.n,
        difficulty=args.difficulty if args.difficulty != "all" else None,
        workers=args.workers,
        backend=args.backend,
        max_retries=args.max_retries,
        output_path=args.out,
        test_timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
