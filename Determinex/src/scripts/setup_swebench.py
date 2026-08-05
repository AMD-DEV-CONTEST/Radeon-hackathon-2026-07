#!/usr/bin/env python3
"""
scripts/setup_swebench.py — SWE-bench Lite Instance Provisioner
================================================================
Downloads the SWE-bench Lite dataset (300 instances), shallow-clones
each repo at the correct base commit, and extracts issue text.

Usage:
    python scripts/setup_swebench.py --output ~/determinex-swebench
    python scripts/setup_swebench.py --output ~/determinex-swebench --limit 10   # quick test
    DETERMINEX_SWEBENCH_DIR=/mnt/data/determinex-swebench python scripts/setup_swebench.py

After setup:
    python scripts/master_bench.py --suite swebench --swebench-dir ~/determinex-swebench

Requirements:
    pip install datasets   (HuggingFace datasets library)
    git                    (must be on PATH)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# ── SWE-bench Lite dataset source ────────────────────────────────────────────
DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DATASET_SPLIT = "test"


def load_swebench_instances(limit: int | None = None) -> list[dict]:
    """Load SWE-bench Lite instances from HuggingFace."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("ERROR: 'datasets' package not installed.")
        print("  Run: pip install datasets")
        sys.exit(1)

    print(f"Loading {DATASET_NAME} ({DATASET_SPLIT} split)...")
    ds = load_dataset(DATASET_NAME, split=DATASET_SPLIT)
    instances = list(ds)
    print(f"  Loaded {len(instances)} instances")

    if limit:
        instances = instances[:limit]
        print(f"  Limited to {limit} instances")

    return instances


def clone_instance(instance: dict, output_dir: Path, shallow: bool = True) -> bool:
    """
    Clone a single SWE-bench instance.

    Each instance has:
      - instance_id: e.g. "django__django-16379"
      - repo: e.g. "django/django"
      - base_commit: the commit to check out before patching
      - problem_statement: the GitHub issue text
    """
    instance_id = instance["instance_id"]
    repo = instance["repo"]
    base_commit = instance["base_commit"]
    problem_statement = instance.get("problem_statement", "")

    inst_dir = output_dir / instance_id
    repo_dir = inst_dir / "repo"
    issue_file = inst_dir / "issue.txt"

    # Skip if already provisioned
    if repo_dir.exists() and issue_file.exists():
        # Verify the checkout is correct
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip().startswith(base_commit[:8]):
                return True  # Already done
        except Exception:
            pass

    # Create instance directory
    inst_dir.mkdir(parents=True, exist_ok=True)

    # Write issue text
    issue_file.write_text(problem_statement, encoding="utf-8")

    # Clone
    clone_url = f"https://github.com/{repo}.git"
    print(f"  Cloning {repo} -> {instance_id}...")

    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)

    try:
        clone_cmd = ["git", "clone"]
        if shallow:
            # Shallow clone, then fetch the specific commit
            clone_cmd += ["--depth", "1", "--no-checkout"]
        clone_cmd += [clone_url, str(repo_dir)]

        result = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            print(f"    FAIL clone: {result.stderr[:200]}")
            return False

        # Fetch the specific base commit
        if shallow:
            # Fetch the exact commit we need
            fetch_result = subprocess.run(
                ["git", "fetch", "--depth", "1", "origin", base_commit],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if fetch_result.returncode != 0:
                # Some repos don't allow fetching by SHA — do a full fetch
                print("    Shallow fetch failed, trying full clone...")
                shutil.rmtree(repo_dir, ignore_errors=True)
                result = subprocess.run(
                    ["git", "clone", clone_url, str(repo_dir)],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if result.returncode != 0:
                    print(f"    FAIL full clone: {result.stderr[:200]}")
                    return False

        # Checkout the base commit
        checkout_result = subprocess.run(
            ["git", "checkout", base_commit],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if checkout_result.returncode != 0:
            print(f"    FAIL checkout {base_commit[:8]}: {checkout_result.stderr[:200]}")
            return False

        return True

    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT cloning {repo}")
        return False
    except Exception as e:
        print(f"    ERROR: {e}")
        return False


def write_manifest(output_dir: Path, instances: list[dict], results: dict):
    """Write a manifest JSON summarizing the provisioned instances."""
    manifest = {
        "dataset": DATASET_NAME,
        "split": DATASET_SPLIT,
        "total_instances": len(instances),
        "provisioned": sum(1 for v in results.values() if v),
        "failed": sum(1 for v in results.values() if not v),
        "instances": {
            iid: {"status": "ready" if ok else "failed", "repo": inst["repo"]}
            for inst, (iid, ok) in zip(instances, results.items())
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest written to: {manifest_path}")


def estimate_disk_usage(instances: list[dict], shallow: bool) -> float:
    """Rough estimate of total disk usage in GB."""
    # Average shallow clone: ~100-200MB, full clone: ~400-800MB
    per_instance_mb = 150 if shallow else 500
    total_gb = len(instances) * per_instance_mb / 1024
    return total_gb


def main():
    parser = argparse.ArgumentParser(
        description="Provision SWE-bench Lite instances for Determinex benchmarking"
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output directory for SWE-bench instances (e.g., ~/determinex-swebench)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of instances to provision (for testing)",
    )
    parser.add_argument(
        "--full-clone",
        action="store_true",
        help="Use full git clone instead of shallow (slower, uses more disk)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip already-provisioned instances (default: True)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be cloned without actually cloning"
    )

    args = parser.parse_args()
    output_dir = Path(args.output)
    shallow = not args.full_clone

    # Check git is available
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        print("ERROR: git not found on PATH")
        sys.exit(1)

    # Load instances
    instances = load_swebench_instances(args.limit)

    # Estimate disk usage
    est_gb = estimate_disk_usage(instances, shallow)
    clone_type = "shallow" if shallow else "full"
    print(f"\nEstimated disk usage ({clone_type} clones): ~{est_gb:.0f} GB")
    print(f"Target directory: {output_dir}")

    # Check free space on target drive
    if output_dir.exists() or output_dir.parent.exists():
        check_path = output_dir if output_dir.exists() else output_dir.parent
        usage = shutil.disk_usage(check_path)
        free_gb = usage.free / (1024**3)
        print(f"Free space on target drive: {free_gb:.1f} GB")

        if free_gb < est_gb * 1.2:  # 20% margin
            print(
                f"WARNING: estimated usage ({est_gb:.0f} GB) is close to free space ({free_gb:.0f} GB)"
            )
            response = input("Continue anyway? [y/N] ")
            if response.lower() != "y":
                sys.exit(0)
    else:
        print("WARNING: target path does not exist yet, will be created")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        repos_seen = set()
        for inst in instances:
            repo = inst["repo"]
            if repo not in repos_seen:
                repos_seen.add(repo)
                count = sum(1 for i in instances if i["repo"] == repo)
                print(f"  {repo}: {count} instances")
        print(f"\nTotal: {len(instances)} instances across {len(repos_seen)} repos")
        return

    # Provision
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}

    print(f"\nProvisioning {len(instances)} instances...\n")

    for i, inst in enumerate(instances):
        iid = inst["instance_id"]
        print(f"[{i + 1}/{len(instances)}] {iid}")
        ok = clone_instance(inst, output_dir, shallow=shallow)
        results[iid] = ok
        status = "OK" if ok else "FAIL"
        print(f"  {status}")

    # Summary
    provisioned = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print(f"\n{'=' * 60}")
    print(f"Provisioned: {provisioned}/{len(instances)}")
    print(f"Failed:      {failed}/{len(instances)}")

    # Actual disk usage
    if output_dir.exists():
        total_size = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
        print(f"Actual disk usage: {total_size / (1024**3):.1f} GB")

    print(f"{'=' * 60}")

    # Write manifest
    write_manifest(output_dir, instances, results)

    # Usage hint
    print("\nTo run SWE-bench evaluation:")
    print(f"  python scripts/master_bench.py --suite swebench --swebench-dir {output_dir}")


if __name__ == "__main__":
    main()
