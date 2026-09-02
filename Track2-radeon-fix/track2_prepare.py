#!/usr/bin/env python3
"""Prepare public SWE-bench repositories at their task base commits.

This creates a local manifest that ``track2_eval.py`` can consume. It never
checks out a gold patch or test patch; official grading remains delegated to
the SWE-bench Docker evaluator.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def _repo_cache_path(root: Path, repo: str) -> Path:
    return root / ".repo-cache" / repo.replace("/", "__")


def _prepare_repo(root: Path, task: dict[str, Any]) -> Path:
    root = root.resolve()
    # Accept both the historical nested dataset rows and the current flat
    # public manifest.  The latter deliberately contains only the four
    # agent-visible task fields and is what cloud runs consume.
    public = task.get("task", task)
    repo = str(public["repo"])
    commit = str(public["base_commit"])
    instance_id = str(task["instance_id"])
    cache = _repo_cache_path(root, repo)
    destination = root / instance_id
    url = f"https://github.com/{repo}.git"
    if not (cache / ".git").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(cache)])
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=cache,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not present:
        _run(["git", "fetch", "--quiet", "origin", commit], cwd=cache)

    # A worktree shares the filtered repository objects but has an independent
    # index and working tree.  This avoids downloading django/sympy repeatedly
    # while preserving task-level isolation for every ablation.
    if destination.exists() and not (destination / ".git").exists():
        shutil.rmtree(destination)
    if not (destination / ".git").exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "worktree", "add", "--detach", "--quiet", str(destination), commit], cwd=cache)
    else:
        _run(["git", "reset", "--hard", "--quiet", commit], cwd=destination)
        _run(["git", "clean", "-fdx", "-q"], cwd=destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks_file", type=Path, required=True)
    parser.add_argument("--workspace_root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    tasks: list[dict[str, Any]] = []
    with args.tasks_file.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                tasks.append(json.loads(line))

    args.workspace_root.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8") as handle:
        for index, task in enumerate(tasks, 1):
            workspace = _prepare_repo(args.workspace_root, task)
            manifest_task = dict(task)
            manifest_task["cwd"] = str(workspace)
            handle.write(json.dumps(manifest_task, ensure_ascii=False) + "\n")
            print(f"[{index}/{len(tasks)}] {task['instance_id']} -> {workspace}")


if __name__ == "__main__":
    main()
