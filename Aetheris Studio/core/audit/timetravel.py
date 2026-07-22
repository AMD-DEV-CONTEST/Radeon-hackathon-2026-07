"""Time-Travel (Blackbox Fase C): one-click undo of any agent-applied
write, via a git "shadow ref" the user never sees (`refs/aetheris/
session-<id>`, not `refs/heads/*` -- invisible to `git branch`) and never
has to clean up by hand more than once (a documented `aetheris gc`, not
built in this pass).

v1 scope, deliberately: git repositories only. If the active project
isn't inside a git working tree, `snapshot()` is a silent no-op -- writes
still succeed, just unprotected. The no-git filesystem-snapshot fallback
is the first thing the project's own cut-order drops under time pressure;
not built here.

The one invariant that matters more than anything else in this module:
the user's REAL git state (working index, HEAD, branches, stash) is never
touched. Every plumbing command below runs against a throwaway
GIT_INDEX_FILE, never the repo's real `.git/index`, and restore always
goes through `git cat-file -p` + a direct file write -- NEVER `git
checkout`, which would move the user's actual HEAD/branch.
"""

from __future__ import annotations

import difflib
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.utils.constants import TIMETRAVEL_DIR

logger = logging.getLogger(__name__)


def timetravel_enabled() -> bool:
    return os.getenv("AETHERIS_TIMETRAVEL_ENABLED", "true").lower() == "true"


def _ref_name(session_id: str) -> str:
    return f"refs/aetheris/session-{session_id}"


def _temp_index_path(session_id: str) -> Path:
    Path(TIMETRAVEL_DIR).mkdir(parents=True, exist_ok=True)
    return Path(TIMETRAVEL_DIR) / f"{session_id}.index"


def _project_path() -> Optional[str]:
    from core.utils.project_path import get_active_project_path

    return get_active_project_path() or None


async def _run_git(
    argv: List[str], cwd: str, env: Optional[Dict[str, str]] = None, check: bool = True, strip: bool = True,
) -> Tuple[str, str, int]:
    """Argv form via create_subprocess_exec -- no shell, so no quoting
    concerns for paths with spaces (the class of bug documented against
    tools.py::_run_git's shell-string pattern, deliberately not reused or
    fixed here, see this module's docstring).

    `strip=False` for `cat-file -p`: blob content is real file content,
    where trailing whitespace/newlines are structurally meaningful (a
    file ending in `\\n` vs not is a real difference) -- stripping it here
    the way every OTHER command's single-line output (a commit hash, a
    tree hash) safely can would silently corrupt restored file content.
    Confirmed directly: the first version of this function stripped
    unconditionally and every rollback() round-trip test failed by
    exactly one trailing newline."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "git", *argv, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace").strip()
    if strip:
        out = out.strip()
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(argv)} failed (exit {proc.returncode}): {err}")
    return out, err, proc.returncode


async def _repo_root(project_path: str) -> Optional[str]:
    """None if `project_path` isn't inside a git working tree at all --
    the signal every public function below treats as "silently do
    nothing, Time-Travel just isn't available for this project"."""
    try:
        out, _, rc = await _run_git(["rev-parse", "--show-toplevel"], cwd=project_path, check=False)
        return out if rc == 0 and out else None
    except Exception:
        return None


def _to_repo_relative(abs_project: Path, abs_repo: Path, rel_path: str) -> Optional[str]:
    """rel_path is relative to the ACTIVE PROJECT (matching every existing
    file tool's convention, e.g. tools.py::_resolve_in_project) -- which
    may be a subfolder of the actual git repo root, not the root itself.
    Git plumbing needs paths relative to the repo root, so this re-bases
    once here rather than assuming the two are the same directory."""
    abs_path = (abs_project / rel_path).resolve()
    try:
        return str(abs_path.relative_to(abs_repo)).replace(os.sep, "/")
    except ValueError:
        return None


async def snapshot(session_id: str, rel_paths: List[str], label: str) -> Optional[str]:
    """Commits the CURRENT on-disk content of `rel_paths` onto the
    session's shadow ref, via an isolated GIT_INDEX_FILE (never the
    user's real index). Returns the new commit hash, or None if disabled,
    not a git repo, or the snapshot itself failed for any reason --
    a snapshot failure must NEVER block the real write it's protecting,
    so every error path here degrades to None rather than raising into
    the caller."""
    if not timetravel_enabled() or not session_id or not rel_paths:
        return None
    project_path = _project_path()
    if not project_path:
        return None
    try:
        repo_root = await _repo_root(project_path)
        if not repo_root:
            return None

        abs_project = Path(project_path).resolve()
        abs_repo = Path(repo_root).resolve()
        repo_rel_paths = [
            rp for rp in (
                _to_repo_relative(abs_project, abs_repo, p) for p in rel_paths
            ) if rp is not None
        ]
        if not repo_rel_paths:
            return None

        index_path = _temp_index_path(session_id)
        env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}

        await _run_git(["read-tree", "--empty"], cwd=repo_root, env=env)
        for rp in repo_rel_paths:
            # check=False: a path that doesn't exist yet (the pre-image of
            # a brand-new file write_file is about to create) is expected,
            # not an error -- that one path is just absent from the tree.
            await _run_git(["add", "--force", "--", rp], cwd=repo_root, env=env, check=False)
        tree, _, _ = await _run_git(["write-tree"], cwd=repo_root, env=env)

        ref = _ref_name(session_id)
        parent, _, parent_rc = await _run_git(["rev-parse", ref], cwd=repo_root, check=False)
        commit_argv = ["commit-tree", tree, "-m", label]
        if parent_rc == 0 and parent:
            commit_argv += ["-p", parent]
        commit, _, _ = await _run_git(commit_argv, cwd=repo_root, env=env)
        await _run_git(["update-ref", ref, commit], cwd=repo_root)
        return commit
    except Exception as e:
        logger.warning("Time-Travel snapshot failed (write proceeds unprotected): %s", e)
        return None


async def rollback(target_commit: str, rel_paths: List[str]) -> Dict:
    """Restores `rel_paths` to their content at `target_commit`, writing
    directly to the working tree via `git cat-file -p` -- never
    `git checkout` (which would move HEAD/the current branch)."""
    project_path = _project_path()
    if not project_path:
        return {"error": "No active project.", "exit_code": 1}
    repo_root = await _repo_root(project_path)
    if not repo_root:
        return {"error": "The active project is not a git repository.", "exit_code": 1}

    abs_project = Path(project_path).resolve()
    abs_repo = Path(repo_root).resolve()
    restored: List[str] = []
    errors: List[str] = []

    for rel in rel_paths:
        repo_rel = _to_repo_relative(abs_project, abs_repo, rel)
        if repo_rel is None:
            errors.append(f"{rel}: outside the repository")
            continue
        out, err, rc = await _run_git(
            ["cat-file", "-p", f"{target_commit}:{repo_rel}"], cwd=repo_root, check=False, strip=False,
        )
        if rc != 0:
            errors.append(f"{rel}: not present in snapshot {target_commit[:8]} ({err or 'no such path'})")
            continue
        try:
            abs_path = (abs_project / rel).resolve()
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(out, encoding="utf-8")
            restored.append(rel)
        except Exception as e:
            errors.append(f"{rel}: {e}")

    if errors and not restored:
        return {"error": "; ".join(errors), "exit_code": 1}
    output = f"Restored: {', '.join(restored)}" if restored else ""
    if errors:
        output += ("\n" if output else "") + "Errors:\n" + "\n".join(errors)
    return {"output": output, "exit_code": 1 if errors else 0, "restored": restored}


async def preview_rollback(target_commit: str, rel_paths: List[str]) -> Dict:
    """Read-only: what `rollback` WOULD change, without touching disk.
    Diffs the current working-tree content against the blob at
    target_commit -- pure Python (difflib), no real `git diff` needed
    since nothing here touches the index."""
    project_path = _project_path()
    if not project_path:
        return {"error": "No active project.", "exit_code": 1}
    repo_root = await _repo_root(project_path)
    if not repo_root:
        return {"error": "The active project is not a git repository.", "exit_code": 1}

    abs_project = Path(project_path).resolve()
    abs_repo = Path(repo_root).resolve()
    diffs = []

    for rel in rel_paths:
        repo_rel = _to_repo_relative(abs_project, abs_repo, rel)
        if repo_rel is None:
            continue
        old_out, _, old_rc = await _run_git(
            ["cat-file", "-p", f"{target_commit}:{repo_rel}"], cwd=repo_root, check=False, strip=False,
        )
        old_content = old_out if old_rc == 0 else ""
        abs_path = (abs_project / rel).resolve()
        try:
            current_content = abs_path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError):
            current_content = ""
        diff_lines = list(difflib.unified_diff(
            current_content.splitlines(keepends=True),
            old_content.splitlines(keepends=True),
            fromfile=f"{rel} (current)",
            tofile=f"{rel} (snapshot {target_commit[:8]})",
        ))
        diffs.append({"path": rel, "diff": "".join(diff_lines)})

    return {"mode": "single" if len(rel_paths) <= 1 else "range", "diffs": diffs, "exit_code": 0}


async def list_snapshots(session_id: str) -> List[Dict]:
    """The Blackbox Time-Travel timeline's data source -- `git log` on the
    session's own shadow ref. Empty list (not an error) if the ref
    doesn't exist yet, or the project isn't a git repo."""
    project_path = _project_path()
    if not project_path:
        return []
    repo_root = await _repo_root(project_path)
    if not repo_root:
        return []

    ref = _ref_name(session_id)
    out, _, rc = await _run_git(
        ["log", ref, "--format=%H%x1f%ct%x1f%s", "--date-order"], cwd=repo_root, check=False,
    )
    if rc != 0 or not out:
        return []

    snapshots = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        commit_hash, ts, message = parts
        try:
            ts_int = int(ts)
        except ValueError:
            continue
        # Which paths this specific snapshot's tree covers -- needed by the
        # UI to know what to pass to preview_rollback/rollback for a given
        # entry, since each snapshot's tree only ever contains the files
        # that particular call touched (see snapshot()'s `read-tree --empty`
        # + targeted `add --force`), not the whole repo.
        paths_out, _, paths_rc = await _run_git(
            ["ls-tree", "-r", "--name-only", commit_hash], cwd=repo_root, check=False,
        )
        paths = paths_out.splitlines() if paths_rc == 0 else []
        snapshots.append({"commit": commit_hash, "ts": ts_int, "message": message, "paths": paths})
    return snapshots
