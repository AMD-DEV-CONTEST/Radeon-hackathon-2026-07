"""
frontier_baseline.py — Direct frontier model SWE-bench comparison.

Runs DeepSeek V3 or Claude Sonnet 4.6 directly (no Determinex wrappers) on
SWE-bench instances and outputs predictions.jsonl for Docker eval.

Usage:
  python scripts/frontier_baseline.py --model deepseek --instances 20
  python scripts/frontier_baseline.py --model claude --instances 20
  python scripts/frontier_baseline.py --model deepseek --instance-ids "django__django-11019,..."

Output: logs/swebench/frontier_<model>_<timestamp>/predictions.jsonl
"""

import argparse
import concurrent.futures
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
logging.basicConfig(
    level=logging.INFO,
    format="[FRONTIER] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

REPOS_DIR = Path(os.getenv("DETERMINEX_REPOS_DIR", "T:/determinex-swebench"))
LOGS_DIR = _ROOT / "logs" / "swebench"

# ── Model config ──────────────────────────────────────────────────────────────

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

DEEPSEEK_MODEL = "deepseek/deepseek-chat-v3-0324"
CLAUDE_MODEL = "claude-sonnet-4-6"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


# ── API calls ─────────────────────────────────────────────────────────────────


def call_deepseek(prompt: str, system: str = "", temperature: float = 0.0) -> str:
    import urllib.request

    payload = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system or "You are an expert Python developer."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 8192,
        }
    ).encode()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def call_claude(prompt: str, system: str = "", temperature: float = 1.0) -> str:
    import urllib.request

    payload = json.dumps(
        {
            "model": CLAUDE_MODEL,
            "max_tokens": 8192,
            "temperature": temperature,
            "system": system or "You are an expert Python developer.",
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
        blocks = resp.get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


# ── File discovery ─────────────────────────────────────────────────────────────

_NOISE = frozenset(
    {
        "error",
        "issue",
        "should",
        "would",
        "could",
        "please",
        "stdout",
        "stdin",
        "stderr",
        "sys",
        "os",
        "path",
        "test",
        "tests",
        "assert",
        "format",
        "print",
        "write",
        "read",
        "open",
        "true",
        "false",
        "none",
        "self",
        "args",
        "kwargs",
        "return",
        "raise",
        "import",
        "from",
        "with",
        "file",
        "data",
        "value",
        "result",
        "output",
        "input",
        "name",
        "type",
        "class",
        "object",
        "string",
        "list",
        "dict",
        "tuple",
        "bool",
    }
)


def _is_test_file(p: Path) -> bool:
    name = p.stem.lower()
    if name.startswith("test_") or name.endswith("_test") or name in ("tests", "conftest"):
        return True
    parts = [x.lower() for x in p.parts]
    return "tests" in parts or "test" in parts


def find_relevant_files(
    repo_path: Path, issue: str, fail_tests: str = "", max_files: int = 3
) -> list[Path]:
    keywords = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{4,}\b", issue)
    keywords = [k for k in keywords if k.lower() not in _NOISE][:8]

    # Boost files from FAIL_TO_PASS test paths
    boost: set[str] = set()
    for test_id in re.split(r"[\s,]+", fail_tests):
        m = re.match(r".*[/\\](test_?)?([a-zA-Z0-9_]+)\.py", test_id)
        if m:
            boost.add(m.group(2).lstrip("_").lower())

    scores: dict[Path, float] = {}
    for p in repo_path.rglob("*.py"):
        if _is_test_file(p):
            continue
        if any(part.startswith(".") for part in p.parts):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        score = 0.0
        if p.stem.lower() in boost:
            score += 10.0
        for kw in keywords:
            if f"def {kw}" in content or f"class {kw}" in content:
                score += 3.0
            elif kw in content:
                score += 1.0
        if score > 0:
            scores[p] = score

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [p for p, _ in ranked[:max_files]]


# ── Patch utilities ───────────────────────────────────────────────────────────

SEARCH_REPLACE_FORMAT = """\
Output ONLY search/replace blocks:
<<<SEARCH
[ORIGINAL lines from the source — copy exactly]
===
[FIXED replacement lines]
>>>REPLACE

RULES:
- SEARCH must match the file character-for-character
- Keep SEARCH small: 3-15 lines
- Multiple blocks OK for separate locations
- NEVER output the whole file"""


def _apply_one_block(content: str, search: str, replace: str) -> "str | None":
    if search in content:
        return content.replace(search, replace, 1)
    search_norm = search.replace("\r\n", "\n").replace("\r", "\n")
    content_norm = content.replace("\r\n", "\n").replace("\r", "\n")
    if search_norm in content_norm:
        return content_norm.replace(search_norm, replace, 1)
    content_lines = content_norm.splitlines(keepends=True)
    search_lines = [l.rstrip() for l in search_norm.splitlines()]
    n = len(search_lines)
    if n == 0:
        return None
    for i in range(len(content_lines) - n + 1):
        window = [content_lines[i + j].rstrip("\n").rstrip() for j in range(n)]
        if window == search_lines:
            before = "".join(content_lines[:i])
            after = "".join(content_lines[i + n :])
            replacement = replace if replace.endswith("\n") else replace + "\n"
            return before + replacement + after
    # Leading-whitespace-flexible first line
    if n >= 1:
        search_first_core = search_lines[0].lstrip()
        search_rest = [l.rstrip() for l in search_lines[1:]]
        for i in range(len(content_lines) - n + 1):
            content_first = content_lines[i].rstrip("\n").rstrip()
            if content_first.lstrip() != search_first_core:
                continue
            if n == 1:
                before = "".join(content_lines[:i])
                after = "".join(content_lines[i + 1 :])
                replacement = replace if replace.endswith("\n") else replace + "\n"
                return before + replacement + after
            rest_window = [content_lines[i + 1 + j].rstrip("\n").rstrip() for j in range(n - 1)]
            if rest_window == search_rest:
                before = "".join(content_lines[:i])
                after = "".join(content_lines[i + n :])
                replacement = replace if replace.endswith("\n") else replace + "\n"
                return before + replacement + after
    return None


def parse_and_apply_patch(response: str, repo_path: Path, target_file: Path) -> str:
    original = target_file.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"<{3,7}\s*SEARCH\s*\n(.*?)\n={3,7}\s*\n(.*?)\n>{3,7}\s*REPLACE",
        re.DOTALL | re.IGNORECASE,
    )
    working = original
    applied = 0
    for m in pattern.finditer(response):
        search, replace = m.group(1), m.group(2)
        if not search.strip():
            continue
        result = _apply_one_block(working, search, replace)
        if result:
            working = result
            applied += 1
    if applied == 0:
        return ""
    # Generate unified diff
    import difflib

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            working.splitlines(keepends=True),
            fromfile=f"a/{target_file.relative_to(repo_path)}",
            tofile=f"b/{target_file.relative_to(repo_path)}",
        )
    )
    if not diff_lines:
        return ""
    return "".join(diff_lines)


# ── Main solve loop ───────────────────────────────────────────────────────────


def solve_instance(
    instance: dict,
    model_name: str,
    repos_dir: Path,
) -> dict:
    iid = instance["instance_id"]
    issue = instance.get("problem_statement", "")
    fail_tests = " ".join(instance.get("FAIL_TO_PASS", []))
    repo_name = instance["repo"].replace("/", "__")
    repo_path = repos_dir / iid / "repo"

    if not repo_path.exists():
        # Try alternative layout: repos_dir/repo_name/repo
        repo_path = repos_dir / repo_name / "repo"
    if not repo_path.exists():
        log.warning("[%s] Repo not found at %s", iid, repo_path)
        return {"instance_id": iid, "model_patch": "", "model_name_or_path": model_name}

    log.info("[%s] Finding relevant files...", iid)
    relevant = find_relevant_files(repo_path, issue, fail_tests, max_files=3)
    if not relevant:
        log.warning("[%s] No relevant files found", iid)
        return {"instance_id": iid, "model_patch": "", "model_name_or_path": model_name}

    # Build file context
    file_blocks = []
    for f in relevant:
        rel = f.relative_to(repo_path)
        content = f.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        shown = "\n".join(f"{i + 1:4d}: {l}" for i, l in enumerate(lines[:200]))
        if len(lines) > 200:
            shown += f"\n... ({len(lines) - 200} more lines)"
        file_blocks.append(f"=== {rel} ===\n{shown}")

    fail_section = f"\nFailing tests (must pass after fix):\n{fail_tests}" if fail_tests else ""
    file_context = "\n\n".join(file_blocks)

    prompt = (
        f"Fix this GitHub bug:\n\n"
        f"Issue:\n{issue[:5000]}"
        f"{fail_section}\n\n"
        f"Source files:\n{file_context}\n\n"
        f"Identify the root cause and output the minimal fix.\n\n"
        f"{SEARCH_REPLACE_FORMAT}"
    )

    system = (
        "You are an expert Python engineer. Fix the bug precisely. "
        "Output ONLY search/replace blocks. SEARCH must match verbatim."
    )

    log.info("[%s] Calling %s...", iid, model_name)
    try:
        if model_name == "deepseek":
            response = call_deepseek(prompt, system=system)
        elif model_name == "claude":
            response = call_claude(prompt, system=system)
        else:
            raise ValueError(f"Unknown model: {model_name}")
    except Exception as e:
        log.error("[%s] API error: %s", iid, e)
        return {"instance_id": iid, "model_patch": "", "model_name_or_path": model_name}

    # Try to apply patch to each relevant file
    patch = ""
    for target_file in relevant:
        p = parse_and_apply_patch(response, repo_path, target_file)
        if p:
            patch += p

    log.info("[%s] Patch: %d chars", iid, len(patch))
    return {"instance_id": iid, "model_patch": patch, "model_name_or_path": model_name}


# ── Dataset loading ───────────────────────────────────────────────────────────


def load_instances(instance_ids: list[str] | None = None, max_n: int | None = None) -> list[dict]:
    from datasets import load_dataset

    log.info("Loading SWE-bench Lite dataset...")
    dataset = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    instances = list(dataset)
    if instance_ids:
        id_set = set(instance_ids)
        instances = [i for i in instances if i["instance_id"] in id_set]
    elif max_n:
        instances = instances[:max_n]
    log.info("Using %d instances", len(instances))
    return instances


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Frontier baseline for SWE-bench comparison")
    parser.add_argument("--model", choices=["deepseek", "claude"], required=True)
    parser.add_argument("--instances", type=int, default=None, help="Max instances")
    parser.add_argument(
        "--instance-ids", type=str, default=None, help="Comma-separated instance IDs"
    )
    parser.add_argument("--repos-dir", type=str, default=str(REPOS_DIR))
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()

    repos_dir = Path(args.repos_dir)
    instance_ids = [x.strip() for x in args.instance_ids.split(",")] if args.instance_ids else None
    instances = load_instances(instance_ids=instance_ids, max_n=args.instances)

    run_id = f"frontier_{args.model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = LOGS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.jsonl"

    log.info("Run ID: %s", run_id)
    log.info("Output: %s", pred_path)

    predictions = []

    if args.parallel > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = {
                pool.submit(solve_instance, inst, args.model, repos_dir): inst for inst in instances
            }
            for fut in concurrent.futures.as_completed(futs):
                try:
                    pred = fut.result()
                    predictions.append(pred)
                    log.info(
                        "Completed: %s → %d patch chars",
                        pred["instance_id"],
                        len(pred["model_patch"]),
                    )
                except Exception as e:
                    inst = futs[fut]
                    log.error("Failed %s: %s", inst["instance_id"], e)
    else:
        for inst in instances:
            pred = solve_instance(inst, args.model, repos_dir)
            predictions.append(pred)

    with open(pred_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")

    patched = sum(1 for p in predictions if p["model_patch"])
    log.info("Done: %d/%d patched", patched, len(predictions))
    log.info("Predictions: %s", pred_path)
    log.info("")
    log.info("To evaluate:")
    log.info("  wsl -d Ubuntu python3 -m swebench.harness.run_evaluation \\")
    log.info("    --dataset_name princeton-nlp/SWE-bench_Lite \\")
    log.info("    --split test \\")
    log.info(
        "    --predictions_path /mnt/c/Dev/Determinex/logs/swebench/%s/predictions.jsonl \\", run_id
    )
    log.info("    --max_workers 4 --run_id %s", run_id)


if __name__ == "__main__":
    main()
