#!/usr/bin/env python3
"""pb_upstream_identity_scan.py -- Tier 1 (manifest+copyright-header) + Tier 2 (diff against
real pinned upstream) source-identity check: is a "locked" ProgramBench submission actually a
model reimplementation, or the real upstream project's own source with identifiers left intact?

This is an 8th provenance dimension, distinct from every existing one:
  1. determinex_pb_provenance_guard.py            -- gaming (reads test identity / embeds golden output)
  2. pb_provenance_verify.py                       -- builds from source (not a shipped binary)
  3. pb_provenance_calibrate.py / determinex_copyright_guard.py -- output similarity vs REGISTERED refs
  4. pb_native_source_guard.py                     -- native language, not a Python wrapper
  5. pb_override_scan.py                           -- eval harness not tampered with
  6. pb_board_guard.py                             -- board invariants (passed==total etc.)
  7. pb_parity_claim_guard.py                       -- doc framing/claims

None of the above ask "IS this submission's source actually the real upstream project, just
with authors/headers intact (or stripped)?" -- exactly the class of miss that invalidated the
original "65 locks" claim (yq's go.mod literally declaring `module github.com/mikefarah/yq/v4`)
and, per the 2026-07-16 re-check, still lurking in verified_locks.json today: `isona__dirble`
carries a verbatim `nccgroup/dirble` copyright header, and `chmln__handlr`'s Cargo.toml `authors`
field carries the real upstream maintainer's personal email.

Ground truth for (repository, pinned commit) comes from determinex_corpus_api.task_provenance()
-- never re-derive it by grepping T:/Dev/ProgramBench's filesystem directly. That was a real
miss this session: a provenance check found the data by hand-crawling task.yaml files instead
of querying the corpus, even though pb_canonical_tasks.py had already indexed all ~200 tasks'
repository+commit into corpus/programbench/canonical_tasks.json a week earlier.

Tier 1 (cheap, offline, any language): manifest field scan (Cargo.toml [package].authors/
repository/homepage, go.mod module, package.json author/repository, pyproject.toml/setup.py
author/url) for a literal match against the real upstream owner/repo, plus a copyright/license
header regex scan across the first ~40 lines of every source file.

Tier 2 (needs network): shallow-clone the pinned commit read-only into a tempdir (no writes
back anywhere -- unlike pb_fetch_source.py, which restores files into per_tool_overrides, this
only compares), then byte-compare every file present in both trees and report % identical.

Usage:
  python scripts/pb_upstream_identity_scan.py scan SLUG [--no-network]
  python scripts/pb_upstream_identity_scan.py scan-locks [--no-network]   # every verified_locks.json entry
  python scripts/pb_upstream_identity_scan.py --guard                    # exit 1 on any un-flagged
                                                                          # PROVEN/STRONG hit among locks
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import determinex_corpus_api as corpus_api  # noqa: E402

ROOT = _HERE.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"
VERIFIED_LOCKS = ROOT / "corpus" / "programbench" / "verified_locks.json"
SCAN_CACHE = ROOT / "corpus" / "programbench" / "upstream_identity_scan_results.json"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

_SRC_EXT = (
    ".rs",
    ".go",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".py",
    ".js",
    ".ts",
    ".rb",
    ".php",
    ".java",
    ".kt",
    ".swift",
)

# manifest filename -> regex fields worth pulling for identity comparison
_MANIFEST_FIELD_PATTERNS = {
    "Cargo.toml": [
        ("authors", re.compile(r"^\s*authors\s*=\s*\[(.*?)\]", re.M)),
        ("repository", re.compile(r'^\s*repository\s*=\s*"([^"]+)"', re.M)),
        ("homepage", re.compile(r'^\s*homepage\s*=\s*"([^"]+)"', re.M)),
    ],
    "go.mod": [
        ("module", re.compile(r"^\s*module\s+(\S+)", re.M)),
    ],
    "package.json": [
        (
            "repository",
            re.compile(r'"repository"\s*:\s*(?:\{[^}]*"url"\s*:\s*"([^"]+)"|"([^"]+)")'),
        ),
        ("author", re.compile(r'"author"\s*:\s*"([^"]+)"')),
        ("homepage", re.compile(r'"homepage"\s*:\s*"([^"]+)"')),
    ],
    "pyproject.toml": [
        ("authors", re.compile(r"^\s*authors\s*=\s*\[(.*?)\]", re.M | re.S)),
        ("homepage", re.compile(r'^\s*(?:homepage|Homepage)\s*=\s*"([^"]+)"', re.M)),
    ],
    "setup.py": [
        ("author", re.compile(r'author\s*=\s*[\'"]([^\'"]+)[\'"]')),
        ("url", re.compile(r'url\s*=\s*[\'"]([^\'"]+)[\'"]')),
    ],
}

_COPYRIGHT_RE = re.compile(
    r"(Copyright\s*(?:\(C\)|©)?\s*\d{4}[^\n]{0,120}|Released as open source by [^\n]{0,80}|"
    r"This file is part of [^\n]{0,80})",
    re.I,
)


def _repo_owner(repository: str) -> str:
    return repository.split("/")[0] if "/" in repository else repository


def _repo_name_only(repository: str) -> str:
    return repository.split("/")[-1]


def extract_submission(slug: str, dest: Path) -> Path | None:
    """Extract corpus/programbench/locked/<slug>/submission.tar.gz into dest. Returns the
    extraction root, or None if no archive exists for this slug."""
    tarball = LOCKED / slug / "submission.tar.gz"
    if not tarball.exists():
        return None
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(dest)  # noqa: S202 -- trusted internal archive, not user-supplied
    return dest


def tier1_manifest_scan(src_dir: Path, repository: str) -> dict[str, Any]:
    owner = _repo_owner(repository).lower()
    repo_name = _repo_name_only(repository).lower()
    hits: list[dict[str, Any]] = []
    for manifest_name, fields in _MANIFEST_FIELD_PATTERNS.items():
        for path in src_dir.rglob(manifest_name):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for field_name, pattern in fields:
                m = pattern.search(text)
                if not m:
                    continue
                value = next((g for g in m.groups() if g), "").strip()
                if not value:
                    continue
                low = value.lower()
                matches_upstream = owner in low or repo_name in low
                if matches_upstream:
                    hits.append(
                        {
                            "file": str(path.relative_to(src_dir)),
                            "field": field_name,
                            "value": value[:200],
                            "matches_upstream_identity": True,
                        }
                    )
    return {"hits": hits, "match_count": len(hits)}


def tier1_header_scan(src_dir: Path, repository: str) -> dict[str, Any]:
    owner = _repo_owner(repository).lower()
    repo_name = _repo_name_only(repository).lower()
    hits: list[dict[str, Any]] = []
    for path in src_dir.rglob("*"):
        if not path.is_file() or path.suffix not in _SRC_EXT:
            continue
        try:
            head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:40])
        except Exception:
            continue
        for m in _COPYRIGHT_RE.finditer(head):
            snippet = m.group(0)[:200]
            low = snippet.lower()
            matches_upstream = owner in low or repo_name in low
            hits.append(
                {
                    "file": str(path.relative_to(src_dir)),
                    "snippet": snippet,
                    "matches_upstream_identity": matches_upstream,
                }
            )
    return {"hits": hits, "match_count": sum(1 for h in hits if h["matches_upstream_identity"])}


def _clone_url(repository: str) -> str:
    return f"https://github.com/{repository}.git"


def tier2_upstream_diff(
    src_dir: Path, repository: str, commit: str, *, network: bool = True
) -> dict[str, Any]:
    if not network:
        return {"skipped": True, "reason": "--no-network"}
    url = _clone_url(repository)
    with tempfile.TemporaryDirectory() as td:
        clone_dir = Path(td) / "upstream"
        r = subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            return {"error": f"clone failed: {r.stderr[-300:]}"}
        co = subprocess.run(
            ["git", "-C", str(clone_dir), "checkout", commit],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if co.returncode != 0:
            subprocess.run(
                ["git", "-C", str(clone_dir), "fetch", "--depth", "1", "origin", commit],
                capture_output=True,
                timeout=300,
            )
            co = subprocess.run(
                ["git", "-C", str(clone_dir), "checkout", commit],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if co.returncode != 0:
                return {"error": f"checkout {commit} failed: {co.stderr[-300:]}"}

        upstream_files = {
            p.relative_to(clone_dir).as_posix(): p
            for p in clone_dir.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }
        submission_files = {
            p.relative_to(src_dir).as_posix(): p for p in src_dir.rglob("*") if p.is_file()
        }
        common = set(upstream_files) & set(submission_files)
        identical = 0
        differing = 0
        for rel in common:
            try:
                up_bytes = upstream_files[rel].read_bytes()
                sub_bytes = submission_files[rel].read_bytes()
                # Normalize CRLF/LF before comparing: a local git checkout's autocrlf setting
                # (or the submission tarball's own line-ending choice) produces byte differences
                # with zero code-content meaning -- confirmed on dirble/main.rs 2026-07-16 (100%
                # content-identical, 0% raw-byte-identical, purely from Windows checkout CRLF).
                if up_bytes == sub_bytes or up_bytes.replace(b"\r\n", b"\n") == sub_bytes.replace(
                    b"\r\n", b"\n"
                ):
                    identical += 1
                else:
                    differing += 1
            except Exception:
                differing += 1
        compared = identical + differing
        pct_identical = round(100.0 * identical / compared, 1) if compared else 0.0
        return {
            "upstream_file_count": len(upstream_files),
            "submission_file_count": len(submission_files),
            "compared_file_count": compared,
            "identical_file_count": identical,
            "differing_file_count": differing,
            "upstream_only_count": len(set(upstream_files) - set(submission_files)),
            "submission_only_count": len(set(submission_files) - set(upstream_files)),
            "pct_identical_of_compared": pct_identical,
        }


def compute_verdict(tier1_manifest: dict, tier1_header: dict, tier2: dict) -> str:
    if tier1_header.get("match_count", 0) > 0:
        return "UPSTREAM_SOURCE_PROVEN"
    if tier1_manifest.get("match_count", 0) > 0:
        return "UPSTREAM_SOURCE_STRONG_EVIDENCE"
    pct = tier2.get("pct_identical_of_compared")
    if pct is not None:
        if pct >= 60.0:
            return "UPSTREAM_SOURCE_STRONG_EVIDENCE"
        if pct < 15.0:
            return "LIKELY_GENUINE_REIMPL"
    return "INCONCLUSIVE"


def scan_slug(slug: str, *, network: bool = True) -> dict[str, Any]:
    prov = corpus_api.task_provenance(slug)
    if prov is None:
        return {
            "slug": slug,
            "error": "no canonical_tasks.json entry found via corpus API "
            "(run: python scripts/pb_canonical_tasks.py to refresh the index)",
        }

    with tempfile.TemporaryDirectory() as td:
        src_dir = extract_submission(slug, Path(td) / "submission")
        if src_dir is None:
            return {
                "slug": slug,
                "repository": prov.repository,
                "commit": prov.commit,
                "error": f"no submission.tar.gz at {LOCKED / slug}",
            }

        tier1_manifest = tier1_manifest_scan(src_dir, prov.repository or "")
        tier1_header = tier1_header_scan(src_dir, prov.repository or "")
        tier2 = tier2_upstream_diff(
            src_dir, prov.repository or "", prov.commit or "", network=network
        )

    verdict = compute_verdict(tier1_manifest, tier1_header, tier2)
    return {
        "slug": slug,
        "repository": prov.repository,
        "commit": prov.commit,
        "provenance_source": "determinex_corpus_api.task_provenance (canonical_tasks.json)",
        "tier1_manifest": tier1_manifest,
        "tier1_header": tier1_header,
        "tier2_upstream_diff": tier2,
        "verdict": verdict,
    }


def scan_all_locks(*, network: bool = True) -> list[dict[str, Any]]:
    data = json.loads(VERIFIED_LOCKS.read_text(encoding="utf-8"))
    results = []
    for slug in data.get("locks", {}):
        results.append(scan_slug(slug, network=network))
    return results


def load_scan_cache() -> dict[str, Any]:
    if not SCAN_CACHE.exists():
        return {"results": {}}
    return json.loads(SCAN_CACHE.read_text(encoding="utf-8"))


def save_scan_cache(results: list[dict[str, Any]]) -> None:
    cache = load_scan_cache()
    for r in results:
        if "slug" in r:
            cache["results"][r["slug"]] = r
    SCAN_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def guard() -> int:
    """CI-style gate: exit 1 if any verified_locks.json entry has a cached scan verdict of
    UPSTREAM_SOURCE_PROVEN or UPSTREAM_SOURCE_STRONG_EVIDENCE. Reads the cache written by
    `scan-locks` rather than re-scanning live (Tier 2 needs network, which CI may not have) --
    run `scan-locks` on a schedule / before archiving a new lock, then `--guard` to enforce."""
    cache = load_scan_cache().get("results", {})
    data = json.loads(VERIFIED_LOCKS.read_text(encoding="utf-8"))
    violations = []
    for slug in data.get("locks", {}):
        result = cache.get(slug)
        if result is None:
            violations.append({"slug": slug, "reason": "never scanned -- run `scan-locks` first"})
            continue
        if result.get("error"):
            violations.append({"slug": slug, "reason": f"unverifiable: {result['error']}"})
            continue
        if result.get("verdict") in ("UPSTREAM_SOURCE_PROVEN", "UPSTREAM_SOURCE_STRONG_EVIDENCE"):
            violations.append({"slug": slug, "reason": result["verdict"]})
    if violations:
        print(json.dumps({"guard": "FAIL", "violations": violations}, indent=2))
        return 1
    print(json.dumps({"guard": "OK", "checked": len(data.get("locks", {}))}, indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scan", "scan-locks"], nargs="?")
    parser.add_argument("slug", nargs="?")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--guard", action="store_true")
    args = parser.parse_args(argv)

    if args.guard:
        return guard()

    if args.command == "scan":
        if not args.slug:
            print("usage: pb_upstream_identity_scan.py scan SLUG [--no-network]")
            return 1
        result = scan_slug(args.slug, network=not args.no_network)
        save_scan_cache([result])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "scan-locks":
        results = scan_all_locks(network=not args.no_network)
        save_scan_cache(results)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    print("usage: pb_upstream_identity_scan.py <scan SLUG | scan-locks> [--no-network] | --guard")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
