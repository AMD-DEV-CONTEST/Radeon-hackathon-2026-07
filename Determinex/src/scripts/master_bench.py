import argparse
import json
import os
import re
import sys

import requests
from tqdm import tqdm

try:
    from evalplus.data import get_human_eval_plus, get_mbpp_plus
except ImportError:
    print("Warning: evalplus not installed. Run: pip install evalplus")

try:
    from bigcodebench.data import get_bigcodebench
except ImportError:
    print("Warning: bigcodebench not installed. Run: pip install bigcodebench datasets")


OLLAMA_API_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/generate"


def extract_code_block(text, language="python"):
    """
    Extracts purely the first compilable code block from a response,
    ignoring whatever Rosetta DSL wrapper was generated.
    """
    pattern = rf"```{language}[ \t]*\n(.*?)```"
    matches = re.findall(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    if matches:
        return matches[0].strip()

    # Fallback to any generic code block if language wasn't specified
    pattern_generic = r"```\n(.*?)```"
    matches_generic = re.findall(pattern_generic, text, flags=re.DOTALL)
    if matches_generic:
        return matches_generic[0].strip()

    return text.strip()  # If all else fails, return raw


def query_ollama(model, prompt):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0},  # Absolute deterministic benchmarking
    }
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("response", "")
    except Exception as e:
        print(f"Ollama API Error: {e}")
        return ""


def run_evalplus(suite="humaneval", model="determinex-engineer-v10-dsl"):
    print(f"--- Running {suite.upper()} on {model} ---")
    if suite == "humaneval":
        problems = get_human_eval_plus()
    else:
        problems = get_mbpp_plus()

    output_file = f"eval_results_{suite}_{model.replace(':', '_')}.jsonl"

    # Check what's already done in case of resume
    completed = set()
    if os.path.exists(output_file):
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    completed.add(json.loads(line)["task_id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    with open(output_file, "a", encoding="utf-8") as f:
        for task_id, problem in tqdm(problems.items(), total=len(problems)):
            if task_id in completed:
                continue

            prompt = problem["prompt"]
            if suite == "humaneval":
                # Ensure the model knows it needs to return the completed function
                full_prompt = f"Please complete the following Python function. Return ONLY the code in a ```python block.\n\n```python\n{prompt}\n```"
            else:
                full_prompt = f"Please solve the following Python programming task. Return ONLY the code in a ```python block.\n\n{prompt}"

            raw_res = query_ollama(model, full_prompt)
            solution = extract_code_block(raw_res, language="python")

            # Write to evalplus expected format
            json.dump({"task_id": task_id, "solution": solution}, f)
            f.write("\n")
            f.flush()

    print(f"Saved generations to {output_file}.")
    print(f"Run scoring via: python -m evalplus.evaluate --dataset {suite} --samples {output_file}")


def run_bigcodebench(model="determinex-engineer-v10-dsl"):
    print(f"--- Running BigCodeBench on {model} ---")
    problems = get_bigcodebench()
    output_file = f"eval_results_bcb_{model.replace(':', '_')}.json"

    # BCB expects a list of objects in JSON format for the new CLI
    results = []

    for task_id, problem in tqdm(problems.items(), total=len(problems)):
        prompt = problem["complete_prompt"]
        full_prompt = f"Please complete the following Python snippet. Make sure to import any libraries you need. Return ONLY the code in a ```python block.\n\n```python\n{prompt}\n```"

        raw_res = query_ollama(model, full_prompt)
        solution = extract_code_block(raw_res, language="python")

        results.append({"task_id": task_id, "solution": solution})

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Saved generations to {output_file}.")
    print(f"Run scoring via: bigcodebench.evaluate --samples {output_file}")


def run_swebench_lite(model="determinex-engineer:latest", data_dir=None, observer_model=None):
    """
    SWE-bench Lite evaluation using the Enterprise Codebase Explorer.

    Scans for pre-cloned SWE-bench instances in data_dir (default: swebench/),
    each structured as: swebench/<instance_id>/repo/ + swebench/<instance_id>/issue.txt

    For each instance:
      1. Loads the repo via CodebaseExplorer
      2. Reads the issue text
      3. Runs the fix pipeline (localize → plan → patch → validate)
      4. Records success/failure + patch diff

    Reports overall resolution rate.
    """
    obs = observer_model or model
    print("--- Running SWE-bench Lite ---")
    print(f"  Builder:  {model}")
    print(f"  Observer: {obs}")

    # Set model env vars so the explorer uses the right models
    os.environ["DETERMINEX_BUILDER_MODEL"] = model
    os.environ["DETERMINEX_OBSERVER_MODEL"] = obs

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from codebase_explorer import CodebaseExplorer
    except ImportError:
        print("Error: codebase_explorer.py not found in scripts/")
        return

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if data_dir is None:
        # Auto-discover: check all drives for existing determinex-swebench dir
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hive"))
            from hardware import get_hw_profile

            hw = get_hw_profile()

            # 1. Check for existing data on any drive
            existing = hw.find_data_path("determinex-swebench")
            if existing:
                data_dir = str(existing)
                print(f"  Auto-discovered SWE-bench data: {data_dir}")
            else:
                # 2. Check the project-local swebench/ dir
                local = os.path.join(root, "swebench")
                if os.path.isdir(local):
                    data_dir = local
                else:
                    # 3. Suggest the best drive for setup
                    best = hw.best_data_path("determinex-swebench", min_free_gb=50.0)
                    if best:
                        print(f"  No SWE-bench data found. Best location: {best}")
                        print(f"  To provision: python scripts/setup_swebench.py --output {best}")
                    else:
                        print("  No drive with 50+ GB free found for SWE-bench data.")
                    data_dir = local  # Fall through to the error message below
        except ImportError:
            data_dir = os.path.join(root, "swebench")

    if not os.path.isdir(data_dir):
        print(f"SWE-bench data directory not found: {data_dir}")
        print("To set up SWE-bench instances:")
        print("  python scripts/setup_swebench.py --output ~/determinex-swebench")
        return

    instances = []
    for name in sorted(os.listdir(data_dir)):
        inst_dir = os.path.join(data_dir, name)
        repo_dir = os.path.join(inst_dir, "repo")
        issue_file = os.path.join(inst_dir, "issue.txt")
        if os.path.isdir(repo_dir) and os.path.isfile(issue_file):
            instances.append((name, repo_dir, issue_file))

    if not instances:
        print(f"No SWE-bench instances found in {data_dir}/")
        print("Expected structure: swebench/<id>/repo/ + swebench/<id>/issue.txt")
        return

    print(f"Found {len(instances)} SWE-bench instances")
    output_file = f"eval_results_swebench_{model.replace(':', '_')}.jsonl"

    resolved = 0
    total = len(instances)

    with open(output_file, "a", encoding="utf-8") as f:
        for i, (instance_id, repo_dir, issue_file) in enumerate(instances):
            print(f"\n[{i + 1}/{total}] {instance_id}")

            try:
                issue_text = open(issue_file, encoding="utf-8").read().strip()
            except Exception as e:
                print(f"  Error reading issue: {e}")
                continue

            try:
                explorer = CodebaseExplorer(repo_dir)
                result = explorer.fix(issue_text)

                entry = {
                    "instance_id": instance_id,
                    "model": model,
                    "resolved": result.success,
                    "attempts": result.attempts,
                    "files_modified": result.files_modified,
                    "error": result.error,
                }

                if result.success:
                    resolved += 1
                    print(
                        f"  ✓ RESOLVED ({result.attempts} attempts, "
                        f"{len(result.files_modified)} files)"
                    )
                    # Save patch
                    patch_file = os.path.join(os.path.dirname(repo_dir), "determinex_patch.diff")
                    with open(patch_file, "w", encoding="utf-8") as pf:
                        pf.write(result.patch_diff)
                else:
                    print(f"  ✗ FAILED ({result.attempts} attempts): {result.error}")

                json.dump(entry, f)
                f.write("\n")
                f.flush()

            except Exception as e:
                print(f"  ✗ ERROR: {e}")
                json.dump(
                    {
                        "instance_id": instance_id,
                        "model": model,
                        "resolved": False,
                        "error": str(e),
                    },
                    f,
                )
                f.write("\n")
                f.flush()

    rate = (resolved / total * 100) if total > 0 else 0
    print(f"\n{'=' * 60}")
    print(f"SWE-bench Lite Results: {resolved}/{total} resolved ({rate:.1f}%)")
    print(f"Results saved to: {output_file}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Determinex Master API Benchmark Runner")
    parser.add_argument(
        "--model", type=str, default="determinex-engineer:latest", help="Ollama model string"
    )
    parser.add_argument(
        "--suite",
        type=str,
        choices=["humaneval", "mbpp", "bigcodebench", "swebench", "all"],
        default="all",
        help="Suite to run",
    )
    parser.add_argument(
        "--swebench-dir",
        type=str,
        default=None,
        help="Path to SWE-bench instances (default: swebench/)",
    )
    parser.add_argument(
        "--observer-model",
        type=str,
        default=None,
        help="Observer model for SWE-bench (default: same as --model)",
    )

    args = parser.parse_args()

    if args.suite in ["humaneval", "all"]:
        run_evalplus("humaneval", args.model)
    if args.suite in ["mbpp", "all"]:
        run_evalplus("mbpp", args.model)
    if args.suite in ["bigcodebench", "all"]:
        run_bigcodebench(args.model)
    if args.suite in ["swebench", "all"]:
        run_swebench_lite(args.model, args.swebench_dir, args.observer_model)
