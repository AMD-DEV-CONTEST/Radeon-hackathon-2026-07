"""
THEMIS GitHub Tool
Handles PR diff retrieval with two-path fallback and rate-limit-aware API calls.
"""

import time
import asyncio
import subprocess
import tempfile
import os
from typing import Optional
from github import Github, GithubException
from github.PullRequest import PullRequest

from backend.config import get_settings

settings = get_settings()


def _get_github_client() -> Github:
    """Return GitHub client (authenticated if token available, else unauthenticated for public repos)."""
    if settings.github_token:
        return Github(settings.github_token, retry=3)
    return Github(retry=3)


def safe_github_call(func, *args, **kwargs):
    """
    Execute a GitHub API call with automatic rate-limit handling.
    Retries once after waiting for the rate limit reset window.
    """
    try:
        return func(*args, **kwargs)
    except GithubException as e:
        if e.status in (403, 429):
            # Extract reset time from headers
            reset_time = int(
                e.headers.get("x-ratelimit-reset", time.time() + settings.github_rate_limit_pause)
            )
            wait = max(reset_time - time.time() + 5, settings.github_rate_limit_pause)
            time.sleep(wait)
            return func(*args, **kwargs)  # Retry once
        raise


def format_diff_from_api_files(files) -> str:
    """
    Convert GitHub PullRequestFile objects into a unified diff string.
    Handles binary files, renames, and deleted files gracefully.
    """
    parts = []
    for f in files:
        # Skip binary files
        if f.patch is None:
            parts.append(f"# Binary file: {f.filename} (skipped)")
            continue
        # Handle renames
        if f.previous_filename and f.previous_filename != f.filename:
            parts.append(f"# Renamed: {f.previous_filename} → {f.filename}")
        parts.append(f"diff --git a/{f.filename} b/{f.filename}")
        parts.append(f.patch)
    return "\n".join(parts)


async def git_clone_diff(repo_name: str, base_sha: str, head_sha: str) -> str:
    """
    Fallback: shallow clone the repo and compute diff locally.
    Used when PR has >280 files (near 300-file API limit).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_url = f"https://x-access-token:{settings.github_token}@github.com/{repo_name}.git"
        # Shallow clone base only
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=50", "--filter=blob:none",
            clone_url, tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Fetch both SHAs
        for sha in (base_sha, head_sha):
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", tmpdir, "fetch", "--depth=1", "origin", sha,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

        # Generate diff
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", tmpdir, "diff", base_sha, head_sha,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")


async def get_pr_diff(repo_name: str, pr_number: int) -> tuple[str, dict]:
    """
    Retrieve a PR diff using two-path strategy:
    - Path 1: GitHub API (fast, ≤280 files)
    - Path 2: git clone fallback (no file limit)

    Returns:
        (diff_string, metadata_dict)
    """
    g = _get_github_client()
    repo = safe_github_call(g.get_repo, repo_name)
    pr: PullRequest = safe_github_call(repo.get_pull, pr_number)

    metadata = {
        "title": pr.title,
        "author": pr.user.login,
        "base_branch": pr.base.ref,
        "head_branch": pr.head.ref,
        "base_sha": pr.base.sha,
        "head_sha": pr.head.sha,
        "pr_number": pr_number,
        "repo": repo_name,
        "html_url": pr.html_url,
    }

    try:
        files = list(safe_github_call(pr.get_files))
        if len(files) > settings.github_max_files:
            raise ValueError(f"PR has {len(files)} files — exceeds {settings.github_max_files} limit")

        diff = format_diff_from_api_files(files)
        metadata["file_count"] = len(files)
        metadata["retrieval_method"] = "api"
        return diff, metadata

    except (GithubException, ValueError):
        # Fallback to git clone
        diff = await git_clone_diff(repo_name, pr.base.sha, pr.head.sha)
        metadata["retrieval_method"] = "git_clone"
        metadata["file_count"] = diff.count("\ndiff --git")
        return diff, metadata


def post_pr_comment(repo_name: str, pr_number: int, body: str) -> str:
    """Post a review comment on a PR. Returns the comment URL."""
    g = _get_github_client()
    repo = safe_github_call(g.get_repo, repo_name)
    pr = safe_github_call(repo.get_pull, pr_number)
    comment = safe_github_call(pr.create_issue_comment, body)
    return comment.html_url


def create_fix_pr(
    repo_name: str,
    base_branch: str,
    fix_branch: str,
    patch_content: str,
    patch_filename: str,
    title: str,
    body: str,
) -> str:
    """
    Create a fix PR on the target repo with the generated patch.
    REQUIRES HUMAN APPROVAL before calling (HITL gate in orchestrator).
    Returns the PR URL.
    """
    g = _get_github_client()
    repo = safe_github_call(g.get_repo, repo_name)

    # Get base SHA
    base_ref = safe_github_call(repo.get_branch, base_branch)
    base_sha = base_ref.commit.sha

    # Create fix branch
    try:
        safe_github_call(
            repo.create_git_ref,
            ref=f"refs/heads/{fix_branch}",
            sha=base_sha,
        )
    except GithubException as e:
        if e.status == 422:  # Branch already exists
            pass
        else:
            raise

    # Get or create the file
    try:
        existing = safe_github_call(repo.get_contents, patch_filename, ref=fix_branch)
        safe_github_call(
            repo.update_file,
            path=patch_filename,
            message=f"fix: THEMIS automated security fix — {title}",
            content=patch_content,
            sha=existing.sha,
            branch=fix_branch,
        )
    except GithubException:
        safe_github_call(
            repo.create_file,
            path=patch_filename,
            message=f"fix: THEMIS automated security fix — {title}",
            content=patch_content,
            branch=fix_branch,
        )

    # Open PR
    pr = safe_github_call(
        repo.create_pull,
        title=title,
        body=body,
        head=fix_branch,
        base=base_branch,
    )
    return pr.html_url
