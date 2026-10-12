#!/usr/bin/env python3
"""
Warden — benchmark artifact manifest generator.

Hashes every input that feeds the benchmark pipeline (scripts, policy YAML,
attack-sample corpus, model GGUF files) and writes a JSON-Lines manifest to
``benchmarks/results/manifest.jsonl``. Committing the manifest beside the
result CSVs gives judges a "measured vs modeled" credibility signal:
anyone can re-run the benchmarks and confirm they came from the exact same
inputs by re-running this script and diffing.

Inspired by RepoMind (AMD Act I winner) — they shipped SHA-256 sums for
their benchmark scripts and raw log files; we do the same.

Usage:
    python scripts/sha256_manifest.py
    python scripts/sha256_manifest.py --out benchmarks/results/manifest.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Roots to scan (relative to repo root). Each entry contributes its files
# to the manifest. We hash file by file, never the whole directory walk.
SCAN_ROOTS = [
    "scripts/*.py",
    "scripts/*.sh",
    "benchmarks/*.py",
    "benchmarks/*.sh",
    "warden/**/*.py",
    "warden/**/*.yaml",
    "policies/*.yaml",
    "data/*.json",
    "attack_samples/**/*.txt",
    "attack_samples/**/*.patch",
    "tests/*.py",
]

# GGUF models are large; hashing them is optional (slow) but high-credibility.
# Tunable via --include-models. Defaults off so `pytest tests/` doesn't pay.
MODEL_GLOBS = [
    "models/*.gguf",
]


def _iter_files(repo_root: Path, globs: list[str]) -> list[Path]:
    """Yield matching files (sorted) under repo_root, deduplicated."""
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in globs:
        for path in sorted(repo_root.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Stream a file SHA-256 (constant memory even for GGUF files)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _git_sha(repo_root: Path) -> str:
    """Best-effort current commit SHA (empty string if not a git repo)."""
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=5.0,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def build_manifest(repo_root: Path, include_models: bool = False) -> list[dict]:
    globs = list(SCAN_ROOTS)
    if include_models:
        globs.extend(MODEL_GLOBS)
    files = _iter_files(repo_root, globs)
    commit_sha = _git_sha(repo_root)
    generated_at = datetime.now(timezone.utc).isoformat()

    entries: list[dict] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        try:
            size = path.stat().st_size
            digest = _sha256(path)
        except OSError as e:
            logger.warning(f"Skipping unreadable file {rel}: {e}")
            continue
        entries.append({
            "path": rel,
            "sha256": digest,
            "size_bytes": size,
            "generated_at": generated_at,
            "commit_sha": commit_sha,
        })
    return entries


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Warden benchmark artifact manifest generator")
    parser.add_argument("--out", default="benchmarks/results/manifest.jsonl",
                        help="Output JSONL manifest path")
    parser.add_argument("--include-models", action="store_true",
                        help="Also hash GGUF model files (slow, large).")
    parser.add_argument("--repo-root", default=".",
                        help="Repo root to scan (default: cwd)")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    entries = build_manifest(repo_root, include_models=args.include_models)

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, sort_keys=True) + "\n")

    print(f"Wrote {len(entries)} manifest entries -> {out_path}")
    if args.include_models:
        print("(model GGUFs included in manifest)")
    else:
        print("(model GGUFs NOT included — pass --include-models to hash them)")

    # Print a short preview to stdout for quick verification.
    if entries:
        print("\nFirst few entries:")
        for e in entries[:3]:
            print(f"  {e['sha256'][:16]}  {e['path']}")


if __name__ == "__main__":
    main()
