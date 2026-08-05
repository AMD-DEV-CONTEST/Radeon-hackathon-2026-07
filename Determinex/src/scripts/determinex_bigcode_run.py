"""
scripts/determinex_bigcode_run.py — BigCodeBench harness for Determinex

BigCodeBench tasks require large execution environments (numpy, pandas, sklearn,
PIL, etc.) — we use Docker via WSL for execution, reusing the SWE-bench Docker
infrastructure already on this machine.

Two evaluation modes:
  1. Direct Docker execution (default) — each solution runs in the BigCodeBench
     Docker image which has all dependencies pre-installed.
  2. Local execution — for tasks with only stdlib dependencies (fast, no Docker).

Dataset: bigcode/bigcodebench (HuggingFace)
  - 1140 tasks covering 139 libraries
  - Each task has a function signature + docstring + test code

Usage:
    python scripts/determinex_bigcode_run.py --n 50 --workers 2
    python scripts/determinex_bigcode_run.py --n 100 --subset hard --workers 2
    python scripts/determinex_bigcode_run.py --n 50 --no-docker  # stdlib-only tasks
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
    format="[BCB] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("determinex_bigcode")

# ── Config ────────────────────────────────────────────────────────────────────
_ANTHROPIC_KEY = os.getenv("DETERMINEX_ANTHROPIC_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
_ANTHROPIC_MODEL = os.getenv("DETERMINEX_ANTHROPIC_MODEL", "claude-sonnet-4-6")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEEPSEEK_KEY = os.getenv("DETERMINEX_DEEPSEEK_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
_DEEPSEEK_MODEL = os.getenv("DETERMINEX_DEEPSEEK_MODEL", "deepseek-chat")
_DEEPSEEK_URL = "https://api.deepseek.com/v1"
_DEFAULT_BACKEND = os.getenv("DETERMINEX_BCB_BACKEND", "anthropic")

# Docker image for BigCodeBench execution
BCB_DOCKER_IMAGE = "bigcode/bigcodebench-evaluate:latest"

# Stdlib-only markers — tasks using ONLY these don't need Docker
_STDLIB_ONLY_IMPORTS = frozenset(
    [
        "os",
        "sys",
        "re",
        "json",
        "math",
        "random",
        "time",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "pathlib",
        "typing",
        "string",
        "io",
        "abc",
        "copy",
        "dataclasses",
        "enum",
        "hashlib",
        "heapq",
        "operator",
        "struct",
        "textwrap",
        "threading",
        "queue",
        "unittest",
        "contextlib",
        "inspect",
        "ast",
        "csv",
        "html",
        "xml",
        "urllib",
        "http",
        "socket",
        "email",
        "base64",
        "gzip",
        "zipfile",
        "tempfile",
        "shutil",
        "glob",
        "fnmatch",
        "stat",
        "errno",
    ]
)


# ── LLM call (shared pattern with determinex_livecode_run) ───────────────────────


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
            "system": (
                "You are an expert Python software engineer. "
                "Write correct, complete function implementations that pass all tests. "
                "Follow the exact function signature and docstring provided."
            ),
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
    elif backend == "deepseek":
        if not _DEEPSEEK_KEY:
            log.error("DEEPSEEK_API_KEY not set")
            return ""
        body = {
            "model": _DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "You are an expert Python software engineer."},
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
    else:
        log.error("Unknown backend: %s", backend)
        return ""

    import urllib.error

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            if backend == "anthropic":
                return data["content"][0]["text"].strip()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error("LLM call failed (%s): %s", backend, e)
        return ""


# ── Code extraction ────────────────────────────────────────────────────────────


def _extract_python_code(response: str) -> str:
    m = re.search(r"```python\s*(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    return response.strip()


# ── Docker availability ────────────────────────────────────────────────────────


def _check_docker() -> bool:
    """Check if Docker is accessible via WSL."""
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "docker", "ps"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _pull_bcb_image(max_retries: int = 2) -> bool:
    """Pull BigCodeBench Docker image if not present."""
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["wsl", "-d", "Ubuntu", "docker", "pull", BCB_DOCKER_IMAGE],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                log.info("BCB Docker image ready: %s", BCB_DOCKER_IMAGE)
                return True
            log.warning("docker pull failed (attempt %d): %s", attempt + 1, result.stderr[:200])
        except subprocess.TimeoutExpired:
            log.warning("docker pull timed out (attempt %d)", attempt + 1)
        except Exception as e:
            log.warning("docker pull error: %s", e)
    return False


# ── Execution ─────────────────────────────────────────────────────────────────


def _is_stdlib_only(task: dict) -> bool:
    """Check if a task only imports stdlib modules (no Docker needed)."""
    code_prompt = task.get("code_prompt", "") + task.get("test", "")
    imports = set(re.findall(r"^import\s+(\w+)|^from\s+(\w+)", code_prompt, re.MULTILINE))
    used = {a or b for a, b in imports if (a or b)}
    return used.issubset(_STDLIB_ONLY_IMPORTS)


def _run_local(solution_code: str, test_code: str, timeout: int = 30) -> tuple[bool, str]:
    """Execute solution + tests locally (stdlib-only tasks)."""
    full_code = solution_code + "\n\n" + test_code
    with tempfile.NamedTemporaryFile(
        suffix=".py",
        mode="w",
        delete=False,
        prefix="bcb_local_",
        encoding="utf-8",
    ) as f:
        f.write(full_code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr)[-1000:]
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Local execution timed out (>{timeout}s)"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _run_docker(solution_code: str, test_code: str, timeout: int = 60) -> tuple[bool, str]:
    """Execute solution + tests in BigCodeBench Docker container."""
    full_code = solution_code + "\n\n" + test_code
    # Write to a temp file accessible from WSL
    with tempfile.NamedTemporaryFile(
        suffix=".py",
        mode="w",
        delete=False,
        prefix="bcb_docker_",
        encoding="utf-8",
        dir=tempfile.gettempdir(),
    ) as f:
        f.write(full_code)
        tmp_path = f.name

    # Convert Windows path to WSL path (any drive letter: C:→/mnt/c, D:→/mnt/d, T:→/mnt/t)
    tmp_wsl = re.sub(
        r"^([A-Za-z]):", lambda m: f"/mnt/{m.group(1).lower()}", tmp_path.replace("\\", "/")
    )

    try:
        result = subprocess.run(
            [
                "wsl",
                "-d",
                "Ubuntu",
                "docker",
                "run",
                "--rm",
                "--memory",
                "2g",
                "--cpus",
                "1",
                "--network",
                "none",
                "-v",
                f"{tmp_wsl}:/solution.py:ro",
                BCB_DOCKER_IMAGE,
                "python",
                "/solution.py",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        output = (result.stdout + result.stderr)[-1000:]
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Docker execution timed out (>{timeout}s)"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _execute_task(
    solution_code: str,
    task: dict,
    use_docker: bool = True,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Execute solution against task test code. Routes to Docker or local."""
    test_code = task.get("test", "")
    if not test_code:
        return True, "no test code"

    if use_docker and not _is_stdlib_only(task):
        return _run_docker(solution_code, test_code, timeout=timeout)
    return _run_local(solution_code, test_code, timeout=timeout)


# ── Prompt builder ─────────────────────────────────────────────────────────────


def _build_prompt(task: dict, failed_output: str = "") -> str:
    task_id = task.get("task_id", "unknown")
    code_prompt = task.get("code_prompt", "")  # function signature + docstring
    libs = task.get("libs", [])

    lib_section = ""
    if libs:
        lib_section = f"\nAvailable libraries: {', '.join(libs)}\n"

    retry_section = ""
    if failed_output:
        retry_section = (
            f"\n\nPREVIOUS ATTEMPT FAILED:\n{failed_output[:400]}\n"
            f"Fix the issue in your new implementation.\n"
        )

    return (
        f"Implement the following Python function.\n\n"
        f"Task: {task_id}\n"
        f"{lib_section}\n"
        f"```python\n{code_prompt}\n```\n"
        f"{retry_section}\n"
        f"Return ONLY the complete Python implementation inside ```python ... ``` fences.\n"
        f"Include all necessary imports inside the function or at the top.\n"
        f"Do NOT include test code. Do NOT include the function signature again — just the body and any helpers.\n"
        f"Wrap your entire response in a single ```python block.\n"
    )


# ── Single task solver ────────────────────────────────────────────────────────


def solve_task(
    task: dict,
    backend: str = _DEFAULT_BACKEND,
    use_docker: bool = True,
    max_retries: int = 2,
    timeout: int = 30,
) -> dict:
    task_id = task.get("task_id", "unknown")
    last_failure = ""
    solution = ""
    passed = False

    for attempt in range(1, max_retries + 2):
        prompt = _build_prompt(task, failed_output=last_failure if attempt > 1 else "")
        response = _call_llm(prompt, backend=backend, temperature=0.05 * attempt)
        if not response:
            continue

        code = _extract_python_code(response)
        if not code:
            last_failure = "Empty response from model."
            continue

        # For attempt 1, try to execute and get feedback
        if attempt < max_retries + 1:
            exec_ok, exec_out = _execute_task(code, task, use_docker=use_docker, timeout=timeout)
            if exec_ok:
                solution = code
                passed = True
                break
            last_failure = exec_out[:400]
            log.debug("[%s] attempt %d failed: %s", task_id, attempt, last_failure[:80])
        else:
            # Last attempt: take whatever we get, final eval will decide
            solution = code

    if not solution:
        return {
            "task_id": task_id,
            "solution": "",
            "passed": False,
            "message": "no solution generated",
            "backend": backend,
        }

    # Final evaluation
    if not passed:
        passed, msg = _execute_task(solution, task, use_docker=use_docker, timeout=timeout)
    else:
        msg = "passed on attempt"

    return {
        "task_id": task_id,
        "solution": solution,
        "passed": passed,
        "message": msg[:200],
        "backend": backend,
    }


# ── Dataset loader ────────────────────────────────────────────────────────────


def _load_dataset(
    n: int,
    subset: str | None = None,
) -> list[dict]:
    cache_path = Path(__file__).resolve().parent.parent / "data" / "bigcode_cache.jsonl"

    try:
        from datasets import load_dataset  # type: ignore[import]

        split = "v0.1.2_hard" if subset == "hard" else "v0.1.2"
        ds = load_dataset("bigcode/bigcodebench", split=split, trust_remote_code=True)
        instances = [dict(row) for row in ds]
        log.info("Loaded %d BigCodeBench instances (split=%s)", len(instances), split)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            for inst in instances:
                f.write(json.dumps(inst) + "\n")
    except Exception as e:
        log.warning("HuggingFace load failed (%s) — trying local cache", e)
        if not cache_path.exists():
            log.error("No local cache at %s", cache_path)
            return []
        instances = []
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    instances.append(json.loads(line))
        log.info("Loaded %d instances from cache", len(instances))

    return instances[:n]


# ── Main runner ───────────────────────────────────────────────────────────────


def run_benchmark(
    n: int = 50,
    subset: str | None = None,
    workers: int = 2,
    backend: str = _DEFAULT_BACKEND,
    use_docker: bool = True,
    max_retries: int = 2,
    output_path: str = "logs/bigcode/results.jsonl",
    timeout: int = 30,
) -> list[dict]:
    log.info(
        "BigCodeBench: n=%d subset=%s workers=%d backend=%s docker=%s",
        n,
        subset or "all",
        workers,
        backend,
        use_docker,
    )

    if use_docker:
        if not _check_docker():
            log.warning("Docker not accessible — falling back to local execution")
            use_docker = False
        else:
            _pull_bcb_image()

    instances = _load_dataset(n, subset)
    if not instances:
        log.error("No instances loaded — aborting")
        return []

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(solve_task, inst, backend, use_docker, max_retries, timeout): inst
            for inst in instances
        }
        for future in as_completed(futures):
            try:
                result = future.result(timeout=300)
                results.append(result)
                solved = sum(1 for r in results if r["passed"])
                log.info(
                    "[%d/%d] %s → %s | %.1f%%",
                    len(results),
                    len(instances),
                    result["task_id"],
                    "PASS" if result["passed"] else "FAIL",
                    100 * solved / len(results),
                )
            except Exception as e:
                inst = futures[future]
                log.warning("Task %s raised: %s", inst.get("task_id", "?"), e)
                results.append(
                    {
                        "task_id": inst.get("task_id", "unknown"),
                        "solution": "",
                        "passed": False,
                        "message": str(e),
                        "backend": backend,
                    }
                )

    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    solved = sum(1 for r in results if r["passed"])
    total = len(results)
    log.info("=" * 60)
    log.info("FINAL: %d/%d = %.1f%%", solved, total, 100 * solved / total if total else 0)
    log.info("Results written to: %s", output_path)
    log.info("=" * 60)
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Determinex BigCodeBench harness")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--subset", choices=["hard", "all"], default=None)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--backend", choices=["anthropic", "deepseek"], default=_DEFAULT_BACKEND)
    p.add_argument("--no-docker", action="store_true", help="Skip Docker, run locally")
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--timeout", type=int, default=30, help="Seconds per task execution")
    p.add_argument("--out", default="logs/bigcode/results.jsonl")
    args = p.parse_args()

    run_benchmark(
        n=args.n,
        subset=args.subset if args.subset != "all" else None,
        workers=args.workers,
        backend=args.backend,
        use_docker=not args.no_docker,
        max_retries=args.max_retries,
        output_path=args.out,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
