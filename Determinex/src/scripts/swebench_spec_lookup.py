"""SWE-bench spec lookup — used by the SWE-bench agent at run-time.

Given an instance_id, returns:
  - The repo's behavioral spec text (from corpus/swebench/repos/<sanitized>/06_repo_spec.md)
  - The instance's index entry (from swebench_instance_index.jsonl)
  - A composed `inject_block` ready to splice into a builder prompt

Designed to be importable from determinex_swebench_agent.py:

    from scripts.swebench_spec_lookup import inject_block_for
    block = inject_block_for(instance_id)
    prompt = ... + block + ...

Or from the CLI for ad-hoc inspection:
    python scripts/swebench_spec_lookup.py django__django-12345
"""

import json
import sys
from functools import lru_cache
from pathlib import Path

CORPUS_BASE = Path(__file__).resolve().parent.parent / "corpus" / "swebench"
INDEX_FILE = CORPUS_BASE / "swebench_instance_index.jsonl"
REPOS_BASE = CORPUS_BASE / "repos"


def sanitize_repo(repo: str) -> str:
    """Mirror the sanitizer used by swebench_repo_spec_generator.py."""
    return repo.replace("/", "__")


@lru_cache(maxsize=1)
def _load_index() -> dict[str, dict]:
    """Load the instance index once per process; lookup by instance_id."""
    if not INDEX_FILE.exists():
        return {}
    out = {}
    with INDEX_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                out[rec["instance_id"]] = rec
            except (json.JSONDecodeError, KeyError):
                pass
    return out


def lookup_instance(instance_id: str) -> dict | None:
    """Return the index record for instance_id, or None if not found."""
    return _load_index().get(instance_id)


def lookup_repo_spec(repo: str) -> str | None:
    """Return the per-repo behavioral spec text, or None if missing."""
    spec_path = REPOS_BASE / sanitize_repo(repo) / "06_repo_spec.md"
    if not spec_path.exists():
        return None
    return spec_path.read_text(encoding="utf-8")


def inject_block_for(instance_id: str, *, max_spec_chars: int = 18000) -> str:
    """
    Compose an inject-ready block for a SWE-bench builder prompt.

    Returns a string like:
      <swebench_repo_spec repo="django/django">
      ...spec text...
      </swebench_repo_spec>
      <swebench_instance_metadata>
      problem_statement: ...
      files_likely_affected: ...
      fail_to_pass: [...]
      </swebench_instance_metadata>

    Returns "" if the instance is unknown (silent — caller falls back to bare prompt).
    """
    rec = lookup_instance(instance_id)
    if not rec:
        return ""
    repo = rec.get("repo", "")
    spec = lookup_repo_spec(repo) or ""
    if len(spec) > max_spec_chars:
        spec = spec[:max_spec_chars] + "\n... [spec truncated to fit context window] ..."

    files = rec.get("files_touched", [])
    fail = rec.get("fail_to_pass_first5", [])
    prob = rec.get("problem_statement", "")

    block_lines = []
    if spec:
        block_lines.append(f'<swebench_repo_spec repo="{repo}">')
        block_lines.append(spec.strip())
        block_lines.append("</swebench_repo_spec>")
    block_lines.append("<swebench_instance_metadata>")
    block_lines.append(f"instance_id: {instance_id}")
    block_lines.append(f"repo: {repo}")
    block_lines.append(f"language: {rec.get('language', 'python')}")
    block_lines.append(f"base_commit: {rec.get('base_commit', '')}")
    if files:
        block_lines.append("files_likely_affected:")
        for f in files[:10]:
            block_lines.append(f"  - {f}")
    if fail:
        block_lines.append(
            f"fail_to_pass (first {len(fail)} of {rec.get('fail_to_pass_count', 0)}):"
        )
        for t in fail:
            block_lines.append(f"  - {t}")
    block_lines.append(f"pass_to_pass_count: {rec.get('pass_to_pass_count', 0)}")
    if prob:
        # Keep the problem statement compact — full text typically already in the agent's main prompt
        block_lines.append("problem_statement_excerpt: |")
        for ln in prob.replace("\r\n", "\n").split("\n")[:10]:
            block_lines.append(f"  {ln[:160]}")
    block_lines.append("</swebench_instance_metadata>")

    return "\n".join(block_lines) + "\n"


def stats() -> dict:
    """Quick stats on the corpus state."""
    idx = _load_index()
    repos = sorted(set(rec["repo"] for rec in idx.values()))
    repos_with_specs = sum(
        1 for r in repos if (REPOS_BASE / sanitize_repo(r) / "06_repo_spec.md").exists()
    )
    return {
        "instances_indexed": len(idx),
        "unique_repos": len(repos),
        "repos_with_specs": repos_with_specs,
        "spec_coverage_pct": 100 * repos_with_specs / max(len(repos), 1),
    }


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] in ("--stats", "-s"):
        s = stats()
        print(json.dumps(s, indent=2))
        sys.exit(0)
    iid = sys.argv[1]
    block = inject_block_for(iid)
    if not block:
        print(f"NOT FOUND: {iid}")
        sys.exit(1)
    print(block)
