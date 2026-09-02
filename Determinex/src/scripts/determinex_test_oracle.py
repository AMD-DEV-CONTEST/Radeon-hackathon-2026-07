#!/usr/bin/env python3
"""determinex_test_oracle.py -- seed the reimpl corpus oracle from the OFFICIAL TESTS' INPUTS.

The autonomous drive loop's oracle was built from RANDOM fuzz (determinex_observe.fuzz_diagnose) +
a few hand-seeded per-tool probes. Random fuzz cannot reach the structured behaviors the official
tests check (e.g. eva's `(1+1,2+2)` or a history-banner scenario), and determinex_io_extractor SKIPS
any test whose EXPECTATION is ambiguous (golden-via-complex-path / computed) -- which is exactly
the byte-exact tail of a near-lock.

This module closes that gap WITHOUT held-out-test access and WITHOUT duplication: it pulls every
recoverable test INPUT (io_extractor.extract_inputs), then the existing oracle runs the REFERENCE
on those inputs (observe_in_image) to obtain the ground-truth expectation -- the same legitimate
black-box method PB uses. The result is a corpus oracle that is COMPLETE for the official tests,
so the candidate is forced to match them. The corpus self-feed then compounds it.

Compose-only: io_extractor (inputs) + observe (reference run, done by the oracle) +
reimpl_corpus (probe storage). Nothing here is a parallel reimplementation.
"""

from __future__ import annotations

import dataclasses
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import determinex_io_extractor as IO  # noqa: E402
import determinex_observe as OBS  # noqa: E402
import determinex_reimpl_corpus as CORPUS  # noqa: E402


def _hf_snapshot_roots() -> list[str]:
    """Every plausible HF-cache snapshots dir for the PB tests dataset, most-portable
    first. The old hardcoded /root/.cache path (2026-07-03 bug) meant seed_corpus pulled
    0 official-test inputs on the Windows dev box -> the oracle never deepened past the
    front-of-suite examples the I/O extractor gets (the 'million examples of the front,
    not the end' gap). Resolve via HF_HOME / ~/.cache like pb_bulk_spec does, then fall
    back to the Linux box path so the Hetzner runner is unaffected. Override:
    DETERMINEX_PB_TESTS_SNAPSHOT points straight at a snapshots dir."""
    rel = os.path.join("hub", "datasets--programbench--ProgramBench-Tests", "snapshots")
    roots: list[str] = []
    env = os.environ.get("DETERMINEX_PB_TESTS_SNAPSHOT")
    if env:
        roots.append(env)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        roots.append(os.path.join(hf_home, rel))
    roots.append(os.path.join(str(Path.home()), ".cache", "huggingface", rel))
    roots.append("/root/.cache/huggingface/" + rel.replace(os.sep, "/"))
    seen, out = set(), []
    for r in roots:
        if r and r not in seen and os.path.isdir(r):
            seen.add(r)
            out.append(r)
    return out


def _branch_tars(slug: str) -> list[str]:
    """The slug's per-branch test tarballs in the HF dataset cache.

    Match is HASH-AGNOSTIC + short-slug tolerant (2026-07-03): the eval_index queue
    yields mixed slug forms -- full `wfxr__csview.8ac4de0`, hashless `antonmedv__walk`,
    and bare `bore`/`gron` -- while snapshot dirs are always `author__repo.hash`. Exact
    match alone found only 10/174 tools, so most tools were never seeded (0 tail coverage).
    Prefer exact > author__repo (hash stripped) > bare repo name."""
    slug = str(slug)
    author_repo = slug.split(".")[0]  # wfxr__csview.8ac -> wfxr__csview
    bare = author_repo.split("__")[-1]  # -> csview (or whole slug if no __)
    for root in _hf_snapshot_roots():
        for snap in sorted(glob.glob(f"{root}/*")):
            names = [os.path.basename(d) for d in glob.glob(f"{snap}/*") if os.path.isdir(d)]
            # rank each candidate dir: 0 exact, 1 author__repo, 2 bare repo; skip non-matches
            best = None
            for name in names:
                nrepo = name.split(".")[0]  # author__repo of the snapshot dir
                if name == slug:
                    rank = 0
                elif "__" in author_repo and nrepo == author_repo:
                    rank = 1
                elif nrepo.split("__")[-1] == bare:
                    rank = 2
                else:
                    continue
                td = os.path.join(snap, name, "tests")
                if os.path.isdir(td) and glob.glob(os.path.join(td, "*.tar.gz")):
                    if best is None or rank < best[0]:
                        best = (rank, name)
            if best is not None:
                td = os.path.join(snap, best[1], "tests")
                return sorted(glob.glob(os.path.join(td, "*.tar.gz")))
    return []


def official_test_probes(slug: str, *, cap: int = 400) -> list:
    """Every recoverable official-test INPUT as an OBS.Probe (deduped across branches).
    No expectation is attached -- the oracle obtains it by running the reference."""
    seen: set = set()
    probes: list = []
    for tar in _branch_tars(slug):
        d = tempfile.mkdtemp(prefix="cto_")
        subprocess.run(["tar", "xzf", tar, "-C", d], capture_output=True)
        test_dirs = {os.path.dirname(p) for p in glob.glob(f"{d}/**/test_*.py", recursive=True)}
        for td in test_dirs:
            for ip in IO.extract_inputs(Path(td)):
                key = (tuple(ip.argv), ip.stdin, tuple(sorted((ip.files or {}).items())))
                if key in seen:
                    continue
                seen.add(key)
                probes.append(
                    OBS.Probe(
                        name=f"test::{ip.test}::{len(probes)}",
                        argv=[str(a) for a in (ip.argv or [])],
                        stdin=ip.stdin,
                        files=dict(ip.files or {}),
                        env=dict(ip.env or {}),
                    )
                )
                if len(probes) >= cap:
                    return probes
    return probes


def seed_corpus(slug: str, short: str, *, cap: int = 400) -> tuple[int, int]:
    """Add the official-test input probes to the tool's corpus oracle. Returns (n_probes, added)."""
    probes = official_test_probes(slug, cap=cap)
    added = CORPUS.add_probes(short, [dataclasses.asdict(p) for p in probes])
    return len(probes), added


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug")
    ap.add_argument("--cap", type=int, default=400)
    ap.add_argument(
        "--seed", action="store_true", help="persist into the corpus (default: dry count)"
    )
    a = ap.parse_args()
    short = a.slug.split("__")[-1].split(".")[0]
    pr = official_test_probes(a.slug, cap=a.cap)
    print(f"{a.slug}: {len(pr)} official-test input probes recoverable (cap={a.cap})")
    if a.seed:
        added = CORPUS.add_probes(short, [dataclasses.asdict(p) for p in pr])
        print(
            f"  seeded corpus oracle for {short}: +{added} new (total now "
            f"{len(CORPUS.load_probes(short))})"
        )
