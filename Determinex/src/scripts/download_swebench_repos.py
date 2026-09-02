r"""
Download all unique repo snapshots from SWE-bench Full + Verified to T: drive.
Skips repos already present in T:\determinex-swebench (Lite repos).

Usage:
    python scripts/download_swebench_repos.py --dest T:\determinex-swebench-full
"""

import argparse
import logging
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

log = logging.getLogger("downloader")
logging.basicConfig(
    level=logging.INFO,
    format="[DL] %(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

DATASETS = [
    ("princeton-nlp/SWE-bench_Verified", "test"),
    ("princeton-nlp/SWE-bench", "test"),
]

_clone_locks: dict[str, threading.Lock] = {}
_clone_locks_guard = threading.Lock()


def get_lock(key: str) -> threading.Lock:
    with _clone_locks_guard:
        if key not in _clone_locks:
            _clone_locks[key] = threading.Lock()
        return _clone_locks[key]


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def clone_repo(repo: str, dest_root: Path, lite_root: Path | None) -> tuple[str, str]:
    """Clone a GitHub repo to dest_root/<repo_name>. Returns (repo, status)."""
    repo_name = repo.replace("/", "__")
    repo_url = f"https://github.com/{repo}.git"
    dest = dest_root / repo_name

    # Already cloned in dest
    if dest.exists():
        return repo, "already-exists"

    # Already cloned in Lite root — copy/link instead
    if lite_root and (lite_root / repo_name).exists():
        log.info("Skipping %s — already in Lite root", repo_name)
        return repo, "in-lite"

    lock = get_lock(repo_name)
    with lock:
        if dest.exists():
            return repo, "already-exists"

        log.info("Cloning %s ...", repo)
        rc, out = run(["git", "clone", "--depth=500", repo_url, str(dest)])
        if rc != 0:
            log.error("Clone failed for %s:\n%s", repo, out[-500:])
            return repo, f"FAILED: {out[-200:]}"

        # Fetch more history so base commits are reachable
        rc2, out2 = run(["git", "fetch", "--depth=2000", "origin"], cwd=dest)
        if rc2 != 0:
            log.warning("Deep fetch warning for %s: %s", repo, out2[-200:])

    log.info("Cloned %s OK", repo)
    return repo, "cloned"


def load_unique_repos(dataset_ids: list[tuple[str, str]]) -> set[str]:
    """Load HuggingFace datasets and return set of unique repo names."""
    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        log.error("datasets package not installed — run: pip install datasets")
        sys.exit(1)

    repos: set[str] = set()
    for dataset_id, split in dataset_ids:
        log.info("Loading %s / %s ...", dataset_id, split)
        try:
            ds = load_dataset(dataset_id, split=split)
            for row in ds:
                repos.add(row["repo"])
            log.info("  → %d unique repos from %s", len(repos), dataset_id)
        except Exception as e:
            log.error("Failed to load %s: %s", dataset_id, e)

    return repos


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=r"T:\determinex-swebench-full", help="Destination root")
    parser.add_argument(
        "--lite-root",
        default=r"T:\determinex-swebench",
        help="Existing Lite repo root (skip repos already there)",
    )
    parser.add_argument("--workers", type=int, default=6, help="Parallel clone workers")
    parser.add_argument("--no-skip-lite", action="store_true", help="Don't skip repos in Lite root")
    args = parser.parse_args()

    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)

    lite_root = Path(args.lite_root) if not args.no_skip_lite else None
    if lite_root and not lite_root.exists():
        log.warning("Lite root %s not found — not skipping", lite_root)
        lite_root = None

    repos = load_unique_repos(DATASETS)
    log.info("Total unique repos across Full+Verified: %d", len(repos))

    # Filter out already-cloned
    to_clone = [r for r in repos if not (dest_root / r.replace("/", "__")).exists()]
    in_lite = [r for r in to_clone if lite_root and (lite_root / r.replace("/", "__")).exists()]
    need_clone = [r for r in to_clone if r not in in_lite]

    log.info(
        "Already in dest: %d | In Lite root: %d | Need clone: %d",
        len(repos) - len(to_clone),
        len(in_lite),
        len(need_clone),
    )

    if not need_clone:
        log.info("All repos already downloaded.")
        return

    done = 0
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(clone_repo, repo, dest_root, lite_root): repo for repo in need_clone}
        for fut in as_completed(futures):
            repo, status = fut.result()
            done += 1
            if status.startswith("FAILED"):
                failed.append(repo)
                log.error("[%d/%d] FAIL %s — %s", done, len(need_clone), repo, status)
            else:
                log.info("[%d/%d] %s — %s", done, len(need_clone), repo, status)

    log.info("=" * 60)
    log.info("Done. Cloned: %d | Failed: %d", len(need_clone) - len(failed), len(failed))
    if failed:
        log.error("Failed repos: %s", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
