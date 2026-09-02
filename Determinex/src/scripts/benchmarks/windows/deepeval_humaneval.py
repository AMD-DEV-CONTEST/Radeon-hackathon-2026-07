#!/usr/bin/env python3
"""
deepeval_humaneval.py — Windows-aware HumanEval adaptation for Determinex.

Runs HumanEval problems through the model, then checks whether the generated
code is Windows-portable (no Linux-isms, proper path handling, etc.) in addition
to functional correctness.

Two scoring dimensions per problem:
  1. Functional: does the code pass the HumanEval test suite?
  2. Windows portable: zero Linux-isms, no hardcoded Unix paths

Usage:
    python scripts/benchmarks/windows/deepeval_humaneval.py --model deepseek
    python scripts/benchmarks/windows/deepeval_humaneval.py --model claude --limit 50
    python scripts/benchmarks/windows/deepeval_humaneval.py --model all --limit 164
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")

# Load .env from project root so API keys work when run as background subprocess
_env_file = Path(__file__).parents[3] / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DETERMINEX_ROOT = Path(__file__).parents[3]
LOGS_DIR = DETERMINEX_ROOT / "logs" / "windows_bench"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Windows-portability patterns for Python code ──────────────────────────────

WINDOWS_PORTABILITY_CHECKS = [
    # MUST NOT contain:
    (r"/usr/(?:local|bin|lib|share|include)", False, "Unix /usr/ path"),
    (r"/home/\w+", False, "Unix home path"),
    (r"(?<!['\"])~/", False, "Unix tilde home"),
    (r"/etc/\w+", False, "Unix /etc/ config"),
    (r"/tmp/(?!\w*test)", False, "Unix /tmp/ (use tempfile module)"),
    (r"subprocess\.run\(\s*['\"](?:bash|sh|zsh)", False, "bash subprocess"),
    (r"os\.system\(['\"](?:apt|yum|brew|dnf)\s", False, "Linux package manager via os.system"),
    (r"platform\.system\(\)\s*==\s*['\"]Linux['\"]", False, "Linux platform assumption"),
    (r"os\.path\.expanduser\(['\"]~/", False, "Unix home expansion"),
    (r"pathlib\.Path\(['\"](?:/usr|/etc|/tmp|/home)", False, "Hardcoded Unix path in pathlib"),
    # MUST contain (when file I/O is needed):
    # (these are optional — not all HumanEval problems touch the filesystem)
]

LINUX_ISM_PATTERNS_PYTHON = [
    (r"/usr/(?:local|bin|lib|share)", "Unix /usr/ path"),
    (r"/home/\w+", "Unix home path"),
    (r"~/\.", "Unix dotfile"),
    (r"/etc/\w+", "Unix /etc/ config"),
    (r"/tmp/", "Unix /tmp/"),
    (r"subprocess.*\b(?:bash|sh|zsh)\b", "bash subprocess"),
    (r"os\.system.*(?:apt|yum|brew|chmod|chown)", "Unix system call"),
    (r"platform\.system\(\)\s*==\s*['\"]Linux['\"]", "Linux platform check"),
    (r"os\.path\.expanduser\(['\"]~/", "Unix home expansion"),
    (r"\bchmod\b|\bchown\b", "chmod/chown in code"),
]


def detect_linux_isms(code: str) -> list[tuple[str, str]]:
    hits = []
    for pattern, label in LINUX_ISM_PATTERNS_PYTHON:
        if re.search(pattern, code, re.IGNORECASE):
            hits.append((pattern, label))
    return hits


def check_windows_portability(code: str) -> tuple[float, list[dict]]:
    """
    Score code for Windows portability (0.0–1.0).
    Returns (score, list of check results).
    """
    results = []
    # Run the portability pattern checks
    for pattern, required, description in WINDOWS_PORTABILITY_CHECKS:
        matched = bool(re.search(pattern, code, re.IGNORECASE))
        passed = matched if required else not matched
        results.append(
            {
                "pattern": pattern,
                "required": required,
                "description": description,
                "matched": matched,
                "passed": passed,
            }
        )
    # Also count Linux-isms as automatic deductions
    isms = detect_linux_isms(code)
    linux_ism_count = len(isms)

    if not results:
        base_score = 1.0
    else:
        base_score = sum(1 for r in results if r["passed"]) / len(results)

    # Each Linux-ism deducts 0.1 from base score (floor 0.0)
    portability_score = max(0.0, base_score - linux_ism_count * 0.1)
    return round(portability_score, 3), results


# ── Model generation backends ─────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert Python developer writing cross-platform code.
When your solution touches the filesystem, prefer pathlib.Path and tempfile.
Never hardcode Unix paths (/usr, /tmp, /home, ~/). Use os.path.expandvars or
pathlib for any path construction. Write only the requested function — no main block.\
"""


def _gen_deepseek(prompt: str) -> str:
    import openai

    client = openai.OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def _gen_claude(prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text if msg.content else ""


def _gen_gpt(prompt: str) -> str:
    import openai

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def _gen_local(prompt: str, model_tag: str) -> str:
    import requests

    payload = {
        "model": model_tag,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    r = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def generate(prompt: str, model: str, local_model: str = "") -> tuple[str, float]:
    t0 = time.time()
    if model == "deepseek":
        out = _gen_deepseek(prompt)
    elif model == "claude":
        out = _gen_claude(prompt)
    elif model == "gpt":
        out = _gen_gpt(prompt)
    elif model == "local":
        out = _gen_local(prompt, local_model)
    else:
        raise ValueError(f"Unknown model: {model}")
    return out, round(time.time() - t0, 2)


# ── Code extraction ───────────────────────────────────────────────────────────


def extract_code(raw: str, entry_point: str) -> str:
    """Extract the function definition from raw model output."""
    # Strip markdown fences
    raw = re.sub(r"```python\n?", "", raw)
    raw = re.sub(r"```\n?", "", raw)

    # Try to find the function def
    lines = raw.split("\n")
    func_lines = []
    in_func = False
    for line in lines:
        if re.match(rf"^def {re.escape(entry_point)}\s*\(", line):
            in_func = True
        if in_func:
            func_lines.append(line)
            # Stop after we exit the function's indentation block
            if func_lines and len(func_lines) > 1:
                if line and not line[0].isspace() and line.strip() and not line.startswith("def "):
                    func_lines.pop()
                    break
    if func_lines:
        return "\n".join(func_lines)
    return raw.strip()


# ── Functional evaluation (run HumanEval tests) ───────────────────────────────


def run_functional_tests(problem: dict, code: str, timeout: int = 10) -> tuple[bool, str]:
    """
    Run the HumanEval test suite for one problem.
    Returns (passed, error_message).
    """
    test_code = problem.get("test", "")
    entry_point = problem.get("entry_point", "")
    prompt_prefix = problem.get("prompt", "")

    # Build the full test script
    full_script = f"{prompt_prefix}\n{code}\n\n{test_code}\n\ncheck({entry_point})\n"

    tmp = Path(tempfile.gettempdir()) / f"humaneval_{entry_point}_{int(time.time())}.py"
    try:
        tmp.write_text(full_script, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(tmp)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[-500:]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        tmp.unlink(missing_ok=True)


# ── HumanEval dataset loader ──────────────────────────────────────────────────


def load_humaneval(limit: int, filter_str: str) -> list[dict]:
    """Load HumanEval problems from HuggingFace datasets."""
    try:
        import datasets

        ds = datasets.load_dataset("openai/openai_humaneval", split="test", trust_remote_code=True)
        problems = []
        for ex in ds:
            if filter_str and filter_str.lower() not in str(ex).lower():
                continue
            problems.append(dict(ex))
            if len(problems) >= limit:
                break
        print(f"  Loaded {len(problems)} HumanEval problems")
        return problems
    except ImportError:
        print("  datasets not installed. pip install datasets")
        return []
    except Exception as e:
        print(f"  Failed to load HumanEval: {e}")
        return []


# ── Main eval loop ────────────────────────────────────────────────────────────


def run_eval(
    model: str, local_model: str, limit: int, filter_str: str, skip_functional: bool
) -> None:
    problems = load_humaneval(limit, filter_str)
    if not problems:
        print("No problems loaded. Exiting.")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    model_label = model if model != "local" else f"local_{local_model.split(':')[0]}"
    out_path = LOGS_DIR / f"{ts}_humaneval_{model_label}.json"

    print("\nDeterminex Windows HumanEval")
    print(f"Model: {model_label}  Problems: {len(problems)}")
    print("=" * 60)

    results = []
    functional_pass = 0
    portability_sum = 0.0
    linux_ism_total = 0

    for i, prob in enumerate(problems, 1):
        task_id = prob.get("task_id", f"task_{i}")
        entry_point = prob.get("entry_point", "solve")
        print(f"[{i}/{len(problems)}] {task_id} ({entry_point})")

        try:
            response, latency = generate(prob["prompt"], model, local_model)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append(
                {
                    "task_id": task_id,
                    "error": str(e),
                    "functional": False,
                    "portability_score": 0.0,
                    "linux_ism_count": 0,
                }
            )
            continue

        code = extract_code(response, entry_point)
        port_score, port_checks = check_windows_portability(code)
        isms = detect_linux_isms(code)
        linux_ism_total += len(isms)

        func_passed = None
        func_error = ""
        if not skip_functional:
            func_passed, func_error = run_functional_tests(prob, code)
            if func_passed:
                functional_pass += 1

        portability_sum += port_score

        status_parts = []
        if func_passed is not None:
            status_parts.append("FUNC:OK" if func_passed else "FUNC:FAIL")
        status_parts.append(f"PORT:{port_score:.0%}")
        if isms:
            status_parts.append(f"[{len(isms)} linux-isms]")
        print(f"  {' '.join(status_parts)}  ({latency:.1f}s)")
        if isms:
            print(f"    isms: {', '.join(l for _, l in isms)}")

        results.append(
            {
                "task_id": task_id,
                "entry_point": entry_point,
                "model": model_label,
                "functional": func_passed,
                "portability_score": port_score,
                "portability_checks": port_checks,
                "linux_ism_count": len(isms),
                "linux_isms": [l for _, l in isms],
                "latency_s": latency,
                "func_error": func_error[:500] if func_error else "",
            }
        )

    n = len(results)
    func_rate = functional_pass / n if n else 0.0
    port_avg = portability_sum / n if n else 0.0

    summary = {
        "model": model_label,
        "timestamp": ts,
        "problems_run": n,
        "functional_pass_rate": round(func_rate, 3),
        "functional_pass_count": functional_pass,
        "avg_portability_score": round(port_avg, 3),
        "total_linux_isms": linux_ism_total,
        "linux_ism_rate": round(linux_ism_total / n, 2) if n else 0,
        "results": results,
    }
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"RESULTS — {model_label} (HumanEval)")
    if not skip_functional:
        print(f"  Functional pass rate:    {func_rate:.1%} ({functional_pass}/{n})")
    print(f"  Avg Windows portability: {port_avg:.1%}")
    print(f"  Linux-ism injections:    {linux_ism_total} ({summary['linux_ism_rate']:.1f}/problem)")
    print(f"  Results: {out_path}")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Determinex Windows HumanEval")
    ap.add_argument(
        "--model", choices=["deepseek", "claude", "gpt", "local", "all"], default="deepseek"
    )
    ap.add_argument("--local-model", default="qwen2.5-coder:14b-instruct-q4_K_M")
    ap.add_argument("--limit", type=int, default=164, help="Max problems (HumanEval has 164)")
    ap.add_argument("--filter", default="", help="Filter problems by keyword")
    ap.add_argument(
        "--skip-functional",
        action="store_true",
        help="Skip functional test execution (portability check only)",
    )
    args = ap.parse_args()

    models = ["deepseek", "claude", "gpt", "local"] if args.model == "all" else [args.model]
    for m in models:
        run_eval(m, args.local_model, args.limit, args.filter, args.skip_functional)


if __name__ == "__main__":
    main()
