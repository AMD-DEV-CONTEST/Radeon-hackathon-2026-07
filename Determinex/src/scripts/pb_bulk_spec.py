#!/usr/bin/env python3
"""pb_bulk_spec.py -- Bulk behavioral-spec harvester for ProgramBench.

Composes the EXISTING canonical extractor (determinex_io_extractor.extract_dir,
AST -> black-box examples) over EVERY tool's per-branch test tarballs in the
local HuggingFace snapshot, producing one reusable "answer key" per tool at
corpus/programbench/specs/<slug>.json.

This is the data layer that makes reimpls writable in BULK: each spec file lists
every test's argv / stdin / env + exact-or-substring expected output (the full
observed behavior), so an author (Claude / Codex / a model) never has to
re-discover what a tool does -- they read the spec and write code that satisfies
every assertion, then validate locally with determinex_local_oracle in ms.

All-local: reads the HF dataset snapshot tarballs. No docker, git, or network.

AUDIT-BEFORE-BUILD: this script does NOT reimplement extraction. It reuses
  - determinex_io_extractor.extract_dir   (canonical example extractor)
  - the HF-snapshot/branch-tarball layout from programbench_fixture_extractor
and only orchestrates them across all 200 tools + ranks tools by how
reimpl-ready their spec is (high exact-assertion coverage, low test count first).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import determinex_io_extractor as iox  # canonical extractor

HF_CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
HF_SNAP_ROOT = HF_CACHE / "datasets--programbench--ProgramBench-Tests" / "snapshots"
TASKS_DIR_ENV = os.environ.get("PB_TASKS_DIR", "")
OUT_DIR = ROOT / "corpus" / "programbench" / "specs"
HF_DATASET_ID = os.environ.get("DETERMINEX_PB_TESTS_DATASET", "programbench/ProgramBench-Tests")


def find_snapshot() -> Path:
    snaps = sorted(HF_SNAP_ROOT.glob("*/"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not snaps and os.environ.get("DETERMINEX_PB_SPEC_AUTO_DOWNLOAD", "1").lower() not in {
        "0",
        "false",
        "no",
    }:
        try:
            from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

            snapshot_download(repo_id=HF_DATASET_ID, repo_type="dataset")
        except Exception as exc:
            sys.exit(f"no HF snapshot under {HF_SNAP_ROOT}; auto-download failed: {exc}")
        snaps = sorted(HF_SNAP_ROOT.glob("*/"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not snaps:
        sys.exit(f"no HF snapshot under {HF_SNAP_ROOT}")
    return snaps[0]


def tool_lang(slug: str) -> str:
    """Read language from the dataset task.yaml if available (cheap, no yaml dep)."""
    if not TASKS_DIR_ENV:
        return ""
    y = Path(TASKS_DIR_ENV) / slug / "task.yaml"
    if not y.exists():
        return ""
    for line in y.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("language:"):
            return line.split(":", 1)[1].strip()
    return ""


def matches_only(slug: str, only: set[str] | None) -> bool:
    if not only:
        return True
    if slug in only:
        return True
    hashless = slug.rsplit(".", 1)[0] if "." in slug else slug
    short = hashless.split("__")[-1]
    return hashless in only or short in only


def harvest_tool(tool_dir: Path) -> dict:
    """Extract + merge examples across all branch tarballs for one tool."""
    slug = tool_dir.name
    tarballs = sorted((tool_dir / "tests").glob("*.tar.gz"))
    merged: dict[tuple, dict] = {}
    n_tests_total = 0
    n_branches = 0
    skipped_total = 0
    with tempfile.TemporaryDirectory(prefix="pbspec_") as td:
        tdp = Path(td)
        for tb in tarballs:
            bdir = tdp / tb.stem.replace(".tar", "")
            bdir.mkdir(parents=True, exist_ok=True)
            try:
                with tarfile.open(tb) as tf:
                    tf.extractall(bdir, filter="data")
            except Exception:
                continue
            n_branches += 1
            cov = iox.extract_dir(bdir)
            n_tests_total += cov.n_tests
            skipped_total += len(cov.skipped)
            for ex in cov.examples:
                d = asdict(ex)
                key = (
                    tuple(d.get("argv") or []),
                    d.get("stdin"),
                    d.get("expect_rc"),
                    d.get("expect_stdout"),
                    tuple(d.get("expect_in") or []),
                )
                merged.setdefault(key, d)  # dedup identical observations across branches
    examples = list(merged.values())
    n_exact = sum(1 for d in examples if d.get("expect_stdout") is not None)
    n_rc = sum(1 for d in examples if d.get("expect_rc") is not None)
    return {
        "slug": slug,
        "language": tool_lang(slug),
        "n_branches": n_branches,
        "n_tests_total": n_tests_total,  # all test fns seen (incl. unextractable)
        "n_examples": len(examples),  # examples with a usable argv+expectation
        "n_with_exact_stdout": n_exact,
        "n_with_rc": n_rc,
        "n_skipped": skipped_total,
        "examples": examples,
    }


def difficulty_rank(spec: dict) -> tuple:
    """Lower = easier to reimpl first. Prefer high exact coverage, fewer tests."""
    n_tests = max(spec["n_tests_total"], 1)
    cover = spec["n_examples"] / n_tests  # how much of behavior is pinned down
    exact_frac = spec["n_with_exact_stdout"] / max(spec["n_examples"], 1)
    # easy = high coverage, high exact fraction, small suite
    score = (1 - cover) * 2 + (1 - exact_frac) + (n_tests / 1000.0)
    return (round(score, 4), n_tests)


def main():
    ap = argparse.ArgumentParser(description="Bulk PB spec harvester")
    ap.add_argument("--only", help="comma-separated slugs to limit to")
    ap.add_argument("--snapshot", help="override HF snapshot path")
    args = ap.parse_args()

    snap = Path(args.snapshot) if args.snapshot else find_snapshot()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None

    tool_dirs = sorted(p for p in snap.iterdir() if p.is_dir() and (p / "tests").is_dir())
    index = []
    for td in tool_dirs:
        if not matches_only(td.name, only):
            continue
        if "testorg__calculator" in td.name:
            continue
        spec = harvest_tool(td)
        (OUT_DIR / f"{spec['slug']}.json").write_text(
            json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        rank = difficulty_rank(spec)
        index.append(
            {
                "slug": spec["slug"],
                "language": spec["language"],
                "n_tests_total": spec["n_tests_total"],
                "n_examples": spec["n_examples"],
                "n_with_exact_stdout": spec["n_with_exact_stdout"],
                "coverage": round(spec["n_examples"] / max(spec["n_tests_total"], 1), 3),
                "difficulty": rank[0],
            }
        )
        print(
            f"{spec['slug']:48s} tests={spec['n_tests_total']:5d} "
            f"ex={spec['n_examples']:5d} exact={spec['n_with_exact_stdout']:5d} "
            f"cov={index[-1]['coverage']:.2f} diff={rank[0]:.2f}"
        )

    index.sort(key=lambda r: r["difficulty"])
    (OUT_DIR / "_index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"\n=== {len(index)} specs written to {OUT_DIR} ===")
    print("=== EASIEST 25 (reimpl these first) ===")
    for r in index[:25]:
        print(
            f"  {r['slug']:46s} {r['language']:6s} tests={r['n_tests_total']:5d} "
            f"cov={r['coverage']:.2f} exact={r['n_with_exact_stdout']:4d}"
        )


if __name__ == "__main__":
    main()
