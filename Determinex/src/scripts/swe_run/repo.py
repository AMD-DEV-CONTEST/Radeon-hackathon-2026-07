"""swe_run/repo.py — Parallel-safe repo cloning + per-instance worktree creation."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from .dataset import _T_CACHE_ROOTS

log = logging.getLogger("swe_run")

# Per-repo clone lock: prevents parallel workers from racing on the same repo dir
_repo_clone_locks: dict[str, threading.Lock] = {}
_repo_clone_locks_guard = threading.Lock()


def clone_repo_at_commit(instance: dict, workdir: Path) -> Path | None:
    """Clone repo to a shared base, then create a per-instance git worktree.

    Parallel-safe: per-repo lock on the shared clone, no lock needed on worktrees
    since each instance gets its own isolated working tree directory.
    """
    repo_url = f"https://github.com/{instance['repo']}.git"
    repo_name = instance["repo"].replace("/", "__")
    iid = instance["instance_id"]
    base_commit = instance.get("base_commit", "HEAD")

    shared_dir = workdir / "_shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    base_clone = shared_dir / repo_name

    # Per-repo lock: only one worker clones / deepens a given repo at a time.
    with _repo_clone_locks_guard:
        if str(base_clone) not in _repo_clone_locks:
            _repo_clone_locks[str(base_clone)] = threading.Lock()
        repo_lock = _repo_clone_locks[str(base_clone)]

    with repo_lock:
        if not base_clone.exists():

            def _find_local_source() -> Path | None:
                # Phase 1: iid-specific path across ALL roots first.
                # T:\determinex-swebench\django__django-11001 has the exact base_commit;
                # T:\determinex-swebench-full\django__django is a shallow generic clone.
                # By scanning iid across all roots before repo_name we avoid picking
                # the shallow generic over the instance-specific deep clone.
                for root in _T_CACHE_ROOTS:
                    candidate = root / iid
                    if not candidate.exists():
                        continue
                    if (candidate / ".git").exists():
                        return candidate
                    if (candidate / "repo" / ".git").exists():
                        return candidate / "repo"
                # Phase 2: generic repo_name across all roots.
                for root in _T_CACHE_ROOTS:
                    candidate = root / repo_name
                    if not candidate.exists():
                        continue
                    if (candidate / ".git").exists():
                        return candidate
                    if (candidate / "repo" / ".git").exists():
                        return candidate / "repo"
                return None

            local_source = _find_local_source()
            if local_source is not None:
                log.info("Using local T: cache: %s", local_source)
                # --no-local forces a proper file-copy clone (works cross-drive).
                r = subprocess.run(
                    [
                        "git",
                        "clone",
                        "-c",
                        "core.autocrlf=false",
                        "-c",
                        "core.longpaths=true",
                        "--no-local",
                        str(local_source),
                        str(base_clone),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            else:
                log.info("Cloning %s ...", repo_url)
                r = subprocess.run(
                    [
                        "git",
                        "clone",
                        "-c",
                        "core.autocrlf=false",
                        "-c",
                        "core.longpaths=true",
                        "--depth=500",
                        repo_url,
                        str(base_clone),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            if r.returncode != 0:
                log.error("Clone failed: %s", r.stderr[:300])
                return None
        else:
            log.info("Shared clone exists: %s", base_clone)

        # Ensure base_commit is reachable (deepen shallow clone if needed).
        def _commit_reachable() -> bool:
            return (
                subprocess.run(
                    ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"],
                    capture_output=True,
                    cwd=base_clone,
                    timeout=10,
                ).returncode
                == 0
            )

        if not _commit_reachable():
            log.info(
                "base_commit %s not in shallow history — unshallowing from origin...",
                base_commit[:8],
            )
            subprocess.run(
                ["git", "fetch", "--unshallow"],
                capture_output=True,
                cwd=base_clone,
                timeout=600,
            )

        if not _commit_reachable():
            # Parallel-run scenario: shared clone was created from another instance's
            # T: cache (e.g. astropy-6938 clone from its iid-specific repo), which
            # is shallow and only has its own base_commit. Try fetching from THIS
            # instance's iid-specific T: cache before hitting GitHub.
            _fetched_local = False
            for _root in _T_CACHE_ROOTS:
                _iid_cand = _root / iid
                if not _iid_cand.exists():
                    continue
                _iid_src = (
                    _iid_cand
                    if (_iid_cand / ".git").exists()
                    else _iid_cand / "repo"
                    if (_iid_cand / "repo" / ".git").exists()
                    else None
                )
                if _iid_src is None:
                    continue
                log.info(
                    "base_commit %s — fetching from iid T: cache %s", base_commit[:8], _iid_src
                )
                # Tag the target commit in the source repo so it has a named ref
                # for 'git fetch' to carry across (detached HEAD commits have no
                # named ref and are silently skipped by a plain git fetch).
                _tag_name = f"_determinex_{base_commit[:12]}"
                subprocess.run(
                    ["git", "tag", "-f", _tag_name, base_commit],
                    capture_output=True,
                    cwd=_iid_src,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "fetch", str(_iid_src)],
                    capture_output=True,
                    cwd=base_clone,
                    timeout=300,
                )
                if _commit_reachable():
                    _fetched_local = True
                    break
            if not _fetched_local:
                log.info(
                    "base_commit %s not in T: cache — fetching from GitHub...", base_commit[:8]
                )
                subprocess.run(
                    ["git", "remote", "set-url", "origin", repo_url],
                    capture_output=True,
                    cwd=base_clone,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "fetch", "-c", "core.longpaths=true", "--depth=2000", "origin"],
                    capture_output=True,
                    cwd=base_clone,
                    timeout=600,
                )

        if not _commit_reachable():
            log.info(
                "base_commit %s still not found — full unshallow from GitHub...", base_commit[:8]
            )
            subprocess.run(
                ["git", "fetch", "-c", "core.longpaths=true", "--unshallow", "origin"],
                capture_output=True,
                cwd=base_clone,
                timeout=900,
            )

    # Per-instance worktree: isolated working tree, no inter-instance interference.
    # Tag makes dangling fetched commits reachable for `git worktree add`.
    subprocess.run(
        ["git", "tag", "-f", f"_determinex_{base_commit[:12]}", base_commit],
        capture_output=True,
        cwd=base_clone,
        timeout=10,
    )
    worktree_path = workdir / iid
    if not worktree_path.exists():
        r = subprocess.run(
            ["git", "worktree", "add", "--force", str(worktree_path), base_commit],
            capture_output=True,
            text=True,
            cwd=base_clone,
            timeout=60,
        )
        if r.returncode != 0:
            log.error("Worktree add failed for %s: %s", iid, r.stderr[:300])
            return None
        log.info("Worktree created: %s @ %s", iid, base_commit[:8])
    else:
        log.info("Worktree exists: %s", worktree_path)

    subprocess.run(
        ["git", "checkout", "--", "."],
        capture_output=True,
        cwd=worktree_path,
        timeout=15,
    )
    return worktree_path
