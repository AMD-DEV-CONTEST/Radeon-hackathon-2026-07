r"""
Download all unique repo snapshots from every multi-language SWE-bench variant
to T:\determinex-swebench-ml.

Datasets pulled:
  - SWE-bench/SWE-bench_Multilingual  (300 tasks, 9 langs: C/C++/Go/Java/JS/TS/PHP/Ruby/Rust)
  - ByteDance-Seed/Multi-SWE-bench    (1632 tasks, 7 langs: Java/TS/JS/Go/Rust/C/C++)
  - ByteDance-Seed/Multi-SWE-bench-mini  (400 tasks, subset)

Usage:
    python scripts/download_multilang_repos.py [--dest T:\\determinex-swebench-ml] [--workers 8]
"""

import argparse
import logging
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

log = logging.getLogger("ml-dl")
logging.basicConfig(
    level=logging.INFO,
    format="[DL] %(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Dataset definitions ──────────────────────────────────────────────────────
# Each entry: (hf_dataset_id, split, repo_field)
# repo_field is the column that holds the GitHub slug (org/repo)
DATASETS: list[tuple[str, str, str]] = [
    ("SWE-bench/SWE-bench_Multilingual", "test", "repo"),
    ("ByteDance-Seed/Multi-SWE-bench", "test", "repo"),
]

# Subsets of Multi-SWE-bench by language (each is a separate config)
MULTI_SWE_CONFIGS = ["java", "typescript", "javascript", "go", "rust", "c", "cpp"]

_clone_locks: dict[str, threading.Lock] = {}
_clone_locks_guard = threading.Lock()


def get_lock(key: str) -> threading.Lock:
    with _clone_locks_guard:
        if key not in _clone_locks:
            _clone_locks[key] = threading.Lock()
        return _clone_locks[key]


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def clone_repo(
    repo: str,
    dest_root: Path,
    skip_roots: list[Path],
) -> tuple[str, str]:
    """Clone github.com/{repo} to dest_root. Returns (repo, status)."""
    repo_name = repo.replace("/", "__")
    repo_url = f"https://github.com/{repo}.git"
    dest = dest_root / repo_name

    if dest.exists() and (dest / ".git").exists():
        return repo, "already-exists"

    for skip in skip_roots:
        if (skip / repo_name).exists():
            return repo, f"skip:already-in-{skip.name}"

    lock = get_lock(repo_name)
    with lock:
        if dest.exists() and (dest / ".git").exists():
            return repo, "already-exists"

        log.info("Cloning %s ...", repo)
        rc, out = run(
            ["git", "clone", "-c", "core.longpaths=true", "--depth=500", repo_url, str(dest)]
        )
        if rc != 0:
            log.error("Clone FAILED %s:\n%s", repo, out[-600:])
            return repo, f"FAILED: {out[-200:]}"

        # Deepen so base commits for instances are reachable
        rc2, out2 = run(["git", "fetch", "--depth=2000", "origin"], cwd=dest)
        if rc2 != 0:
            log.warning("Deep-fetch warning %s: %s", repo, out2[-200:])

    log.info("Cloned %s OK", repo)
    return repo, "cloned"


def load_repos_from_dataset(dataset_id: str, split: str, repo_field: str) -> set[str]:
    from datasets import load_dataset  # type: ignore[import-untyped]

    repos: set[str] = set()
    try:
        ds = load_dataset(dataset_id, split=split)
        for row in ds:
            val = row.get(repo_field, "")
            if val and "/" in val:
                repos.add(val)
        log.info("  %s/%s: %d unique repos", dataset_id, split, len(repos))
    except Exception as e:
        log.error("Failed loading %s/%s: %s", dataset_id, split, e)
    return repos


def load_multi_swe_bench_configs() -> set[str]:
    """Multi-SWE-bench organises instances by language config."""
    from datasets import load_dataset  # type: ignore[import-untyped]

    repos: set[str] = set()
    for lang in MULTI_SWE_CONFIGS:
        try:
            ds = load_dataset("ByteDance-Seed/Multi-SWE-bench", lang, split="test")
            before = len(repos)
            for row in ds:
                val = row.get("repo", "") or row.get("instance_id", "").split("__")[0].replace(
                    "__", "/", 1
                )
                if val and "/" in val:
                    repos.add(val)
            log.info("  Multi-SWE-bench lang=%s: %d new repos", lang, len(repos) - before)
        except Exception as e:
            log.warning("  Multi-SWE-bench lang=%s failed: %s", lang, e)
    return repos


def load_all_repos() -> set[str]:
    try:
        import datasets  # noqa: F401
    except ImportError:
        log.error("datasets package not installed — run: pip install datasets")
        sys.exit(1)

    all_repos: set[str] = set()

    # SWE-bench Multilingual (official)
    log.info("Loading SWE-bench/SWE-bench_Multilingual ...")
    all_repos |= load_repos_from_dataset("SWE-bench/SWE-bench_Multilingual", "test", "repo")

    # Multi-SWE-bench (ByteDance) — try plain split first, then per-lang configs
    log.info("Loading ByteDance-Seed/Multi-SWE-bench ...")
    plain = load_repos_from_dataset("ByteDance-Seed/Multi-SWE-bench", "test", "repo")
    if plain:
        all_repos |= plain
    else:
        log.info("  Plain split empty — trying per-language configs ...")
        all_repos |= load_multi_swe_bench_configs()

    log.info("Total unique repos across all multilingual datasets: %d", len(all_repos))
    return all_repos


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dest",
        default=r"T:\determinex-swebench-ml",
        help="Destination root for multilingual repos",
    )
    parser.add_argument(
        "--skip-roots",
        nargs="*",
        default=[r"T:\determinex-swebench", r"T:\determinex-swebench-full"],
        help="Existing repo roots to skip (already cloned)",
    )
    parser.add_argument(
        "--workers", type=int, default=8, help="Parallel clone workers (more = faster, watch RAM)"
    )
    parser.add_argument("--force", action="store_true", help="Re-clone even if dest exists")
    args = parser.parse_args()

    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)

    skip_roots = [Path(s) for s in (args.skip_roots or []) if Path(s).exists()]
    if skip_roots:
        log.info("Skipping repos already in: %s", [str(s) for s in skip_roots])

    repos = load_all_repos()
    if not repos:
        log.error("No repos found — check dataset loading above")
        sys.exit(1)

    need_clone = (
        sorted(repos)
        if args.force
        else [
            r
            for r in sorted(repos)
            if not (dest_root / r.replace("/", "__")).exists()
            and all(not (sk / r.replace("/", "__")).exists() for sk in skip_roots)
        ]
    )
    already = len(repos) - len(need_clone)
    log.info("Repos to clone: %d (skipping %d already present)", len(need_clone), already)

    if not need_clone:
        log.info("All repos already downloaded. Done.")
        return

    done = 0
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(clone_repo, repo, dest_root, skip_roots): repo for repo in need_clone
        }
        for fut in as_completed(futures):
            repo, status = fut.result()
            done += 1
            if status.startswith("FAILED"):
                failed.append(repo)
                log.error("[%d/%d] FAIL  %s", done, len(need_clone), repo)
            else:
                log.info("[%d/%d] %-10s  %s", done, len(need_clone), status, repo)

    log.info("=" * 60)
    log.info(
        "Done.  Cloned: %d  |  Skipped: %d  |  Failed: %d",
        len(need_clone) - len(failed),
        already,
        len(failed),
    )
    if failed:
        log.error("Failed repos:\n  %s", "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
