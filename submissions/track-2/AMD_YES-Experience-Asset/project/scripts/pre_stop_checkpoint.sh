#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: run this command inside the team Git repository."
  exit 1
fi

branch="$(git branch --show-current)"
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
dirty="$(git status --short)"
failures=0

echo "Branch: ${branch:-DETACHED}"
if head_line="$(git log -1 --oneline 2>/dev/null)"; then
  echo "HEAD:   $head_line"
else
  echo "HEAD:   UNBORN (no commit yet)"
fi

if [[ -n "$dirty" ]]; then
  echo
  echo "FAIL: uncommitted changes exist:"
  printf '%s\n' "$dirty"
  failures=$((failures + 1))
else
  echo "PASS: working tree is clean."
fi

if [[ -z "$upstream" ]]; then
  echo "FAIL: the current branch has no upstream remote."
  failures=$((failures + 1))
else
  ahead="$(git rev-list --count "$upstream"..HEAD)"
  behind="$(git rev-list --count HEAD.."$upstream")"
  echo "Upstream: $upstream (ahead=$ahead, behind=$behind)"

  if (( ahead > 0 )); then
    echo "FAIL: $ahead local commit(s) have not been pushed."
    failures=$((failures + 1))
  fi
  if (( behind > 0 )); then
    echo "WARN: the local branch is behind its last fetched upstream by $behind commit(s)."
  fi
fi

if (( failures > 0 )); then
  echo
  echo "Checkpoint failed. Review, commit, and explicitly push before destroying the pod."
  echo "This script never commits or pushes automatically."
  exit 1
fi

echo
echo "PASS: source-code checkpoint is safe relative to the last fetched upstream."
echo "Large artifacts still require their own approved backup plan."
