"""
THEMIS Security Sanitizer
Strips prompt injection attempts from diff content before it enters any agent prompt.
"""

import re
from typing import Optional


# Known prompt injection patterns (case-insensitive)
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|previous\s+|above\s+)?instructions?",
    r"you\s+are\s+now",
    r"system\s+prompt",
    r"forget\s+(everything|all)",
    r"act\s+as\s+",
    r"disregard\s+",
    r"new\s+instruction",
    r"override\s+",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
    r"pretend\s+(you\s+are|to\s+be)",
    r"from\s+now\s+on",
    r"your\s+true\s+self",
]

_COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS
]

# Maximum diff size — reject anything above this
MAX_DIFF_BYTES = 512_000  # 512KB


def sanitize_diff(diff: str, repo: Optional[str] = None) -> str:
    """
    Sanitize a GitHub PR diff before injecting it into an agent prompt.

    Steps:
    1. Enforce size limit
    2. Strip prompt injection patterns
    3. Wrap in code fence (reduces injection risk)
    4. Optionally prefix with repo metadata

    Args:
        diff: Raw diff string from GitHub API or git clone
        repo: Optional repo name for context (e.g. "owner/repo")

    Returns:
        Sanitized diff string, safe for inclusion in LLM prompt
    """
    if not diff:
        return "```diff\n# Empty diff\n```"

    # 1. Enforce size limit
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        diff = diff.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        diff += "\n\n# [DIFF TRUNCATED AT 512KB — analyse visible portion only]"

    # 2. Strip injection patterns
    injection_count = 0
    for pattern in _COMPILED_PATTERNS:
        new_diff, n = pattern.subn("[REDACTED]", diff)
        diff = new_diff
        injection_count += n

    # 3. Wrap in code fence
    header = f"# Repository: {repo}\n" if repo else ""
    sanitized = f"```diff\n{header}{diff}\n```"

    # 4. Log if injections were found (return count in comment for observability)
    if injection_count > 0:
        sanitized += f"\n<!-- sanitizer: {injection_count} injection pattern(s) redacted -->"

    return sanitized


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename from a PR diff to prevent path traversal.
    """
    # Remove any path traversal attempts
    filename = re.sub(r"\.\./", "", filename)
    filename = re.sub(r"^/+", "", filename)
    # Allow only safe characters
    filename = re.sub(r"[^a-zA-Z0-9._/\-]", "_", filename)
    return filename[:512]  # Max filename length


def is_safe_repo_name(repo_name: str) -> bool:
    """
    Validate a GitHub repo name (owner/repo format).
    """
    pattern = r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$"
    return bool(re.match(pattern, repo_name)) and len(repo_name) < 200
