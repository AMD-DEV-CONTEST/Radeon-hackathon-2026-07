#!/usr/bin/env python3
"""
secret_scan.py -- find leaked API keys / secrets in the working tree and history
================================================================================
Defensive security for YOUR machine, independent of any product claim. Scans for
provider-key shapes (Anthropic / Google / OpenAI / DeepSeek / generic) so a live
secret never sits in a tracked file or in pushed git history.

    python scripts/security/secret_scan.py            # scan tracked working tree
    python scripts/security/secret_scan.py --history  # also scan ALL git history
    python scripts/security/secret_scan.py --pushed   # only what the REMOTE has

Prints REDACTED matches (first/last few chars) and a clear verdict. Exit 1 if any
secret is found in a place that could leak (tracked file, or pushed history).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# provider key shapes (kept tight to avoid false positives)
PATTERNS = {
    "anthropic": re.compile(r"sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,}"),
    "google": re.compile(r"AIzaSy[A-Za-z0-9_-]{30,}"),
    "openai": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{40,}"),
    "deepseek": re.compile(r"\bsk-[a-f0-9]{32}\b"),
    "aws": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
_SKIP = (
    ".env.example",
    "package-lock.json",
    ".lock",
    ".bak",
    "/secret_scan.py",
    ".pre-commit-config.yaml",
)


def _redact(s: str) -> str:
    return s[:8] + "..." + s[-4:] if len(s) > 14 else s[:4] + "..."


# Values that are published placeholders, not credentials. These are matched against the MATCHED
# TEXT, which is the only place they can work: `AWS_KEY_PLACEHOLDER` was listed in
# _FALSE_POSITIVE, but that regex is applied to the PATH, so the content entries in it were dead
# weight. Kept deliberately tiny and exact -- a substring allowlist over content is how a scanner
# stops finding real keys.
_PLACEHOLDER_VALUES = frozenset(
    {
        # AWS's own documentation example key, used across the world in docs and test fixtures. It
        # appears here as input to a secret-detection tool benchmark.
        "AWS_KEY_PLACEHOLDER",
    }
)

#: Adjudicated occurrences in HISTORY, keyed by `(commit_prefix, path)` — never by content.
#:
#: WHY NOT `_PLACEHOLDER_VALUES`. The private-key pattern matches only the HEADER
#: (`-----BEGIN RSA PRIVATE KEY-----`); the body never reaches the allowlist. Putting that header
#: in a content allowlist would blind this scanner to every real RSA key in the repository
#: forever — exactly what the note above forbids. So the exemption is per-occurrence: one commit,
#: one path, adjudicated once, with the reason recorded. Any NEW private-key header, anywhere,
#: including in the same file, still fires.
#:
#: Each entry must state what was checked, not merely that it is fine.
_ADJUDICATED_HISTORY = {
    (
        "7895020b9",
        "tests/test_corpus_share_optin.py",
    ): (
        "Redaction-test fixture, not a credential: the key body is the literal string `abc` "
        "(`-----BEGIN RSA PRIVATE KEY-----\\nabc\\n-----END RSA PRIVATE KEY-----`). The test's "
        "whole purpose is to plant a key-shaped string and assert the corpus share path redacts "
        "it. There is nothing to rotate. The working tree no longer contains the literal — it "
        "builds the header by concatenation — so this exists only in the commit that predates "
        "that change. Verified 2026-08-03 by reading the blob at that commit."
    ),
}


def _scan_text(text: str) -> list[tuple[str, str]]:
    hits = []
    for name, pat in PATTERNS.items():
        for m in pat.findall(text):
            if m in _PLACEHOLDER_VALUES:
                continue
            hits.append((name, _redact(m)))
    return hits


# A deliberately LOOSE, POSIX-ERE-safe superset of PATTERNS, used only to let git narrow the
# candidate set. Exact matching is always done afterwards in Python by _scan_text, so this only
# has to preserve recall -- it may over-match freely.
#
# It exists because git's regex dialects are not PCRE and disagree with each other: `git grep -E`
# and `git log -G` both reject `(?:` with "Invalid preceding regular expression", and `\b` is not
# portable either. `git grep -P` works here but requires a PCRE-enabled build, and `git log -G`
# ignores --perl-regexp for the pickaxe. Depending on any of that is how the tracked-tree scan
# came to silently match nothing for months. Nothing below uses a construct outside POSIX ERE.
_GIT_PREFILTER_ERE = "|".join(
    (
        "sk-ant-api[0-9]{2}-",
        "AIzaSy",
        "sk-[A-Za-z0-9_-]{20,}",
        "AKIA[0-9A-Z]{16}",
        "-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
)


class GitUnavailable(RuntimeError):
    """Raised when git could not be consulted, so "no findings" means nothing.

    This used to be `except Exception: return ""`, which made a scanner FAILURE indistinguishable
    from a clean tree: git missing, a bad --root, or the 180 s timeout expiring on this ~10 GB
    history all yielded zero files, zero findings, "clean", and exit 0. For the gate that runs
    immediately before a public push, silence and safety must never look alike.
    """


def _git(args: list[str], root: Path | None = None, timeout: int = 180) -> str:
    # decode as utf-8 with replacement so binary blobs (parquet, etc.) and
    # non-cp1252 bytes never crash the scan on Windows.
    cwd = Path(root) if root is not None else REPO
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise GitUnavailable(f"git is not installed or not on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitUnavailable(
            f"git {' '.join(args[:2])} timed out after {timeout}s in {cwd}; "
            f"the scan did NOT complete"
        ) from exc
    except OSError as exc:
        raise GitUnavailable(f"git could not be run in {cwd}: {exc}") from exc
    # `git grep` exits 1 for "no matches", which is a legitimate empty result. Anything above
    # that is a real failure (not a repository, bad pathspec, ...) and must not read as clean.
    if r.returncode > 1:
        detail = (r.stderr or b"").decode("utf-8", errors="replace").strip()[:400]
        raise GitUnavailable(
            f"git {' '.join(args[:2])} failed (exit {r.returncode}) in {cwd}: {detail}"
        )
    return (r.stdout or b"").decode("utf-8", errors="replace")


# Paths that legitimately contain key-SHAPED strings -- NOT your secrets:
#  - corpus/ is benchmark TOOL data (upstream test vectors / fixtures), e.g.
#    ripsecrets' own fixtures, mbedtls/openssl/age crypto test PEMs, the AWS
#    documentation example key. These ship with the tools; they are not credentials.
#  - the secret-detection tooling + its tests contain key SHAPES by design.
# Tightened 2026-07-29. `testdata` and `crypto` were bare substrings matched anywhere in the
# path, so they exempted far more than the upstream fixtures they were meant for: measured
# 3,615 tracked files matching `testdata` and 1,722 matching `crypto`, including 18 outside
# corpus/ such as assurance/evidence/approval_signature_cryptographic_binding/. Any future path
# happening to contain either word became silently unscanned. Both are now whole path segments,
# and corpus/ (which is what actually holds the upstream test vectors) is still excluded outright.
_FALSE_POSITIVE = re.compile(
    r"^corpus/|/corpus/|ripsecrets|secret_scan|secret_scanner|test_secret"
    r"|\.parquet$|\.env\.example$"
    r"|(?:^|/)testdata(?:/|$)|(?:^|/)test_vectors(?:/|$)|(?:^|/)crypto(?:/|$)"
    r"|detect.?secret|gitleaks|trufflehog|AWS_KEY_PLACEHOLDER",
    re.I,
)


def scan_tracked(root: Path | None = None) -> dict:
    """Fast native scan via `git grep` (handles 100k+ tracked files instantly).

    `root` exists because publish_mirror.py invokes this scanner on the STAGED MIRROR and calls
    its own docstring "the last gate" before the public push. It passed cwd= to the subprocess,
    which was inert: REPO is derived from __file__ and _git hardcoded cwd=REPO, so the verdict
    described the developer checkout while the content about to be published was never examined.
    """
    base = Path(root) if root is not None else REPO
    out: dict = {}
    # The loose ERE prefilter, so this works on any git build. `-lE` with the real PCRE patterns
    # exited 128 every time ("Invalid preceding regular expression") and, with the old
    # exception-swallowing _git, printed "clean" having matched nothing. `-lP` works here but
    # silently requires a PCRE-enabled git. _scan_text does the exact matching either way.
    alt = _GIT_PREFILTER_ERE
    # -lP, not -lE. THE PATTERNS ARE PCRE: `sk-(?:proj-)?...` and
    # `-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----` use non-capturing groups, and the
    # deepseek pattern uses `\b`. POSIX ERE rejects `(?:`, so `git grep -lE` exited 128 with
    # "Invalid preceding regular expression" -- EVERY TIME, on every invocation. Combined with
    # the old `except Exception: return ""`, that meant scan_tracked() returned {} and the tool
    # printed "clean -- no secrets in tracked files" and exited 0 having matched nothing at all.
    # This scanner had therefore never scanned anything; the bug was invisible precisely because
    # the failure path and the clean path produced identical output.
    try:
        files = _git(
            ["grep", "-lE", alt, "--", ":!*.lock", ":!*package-lock.json"], root=base
        ).splitlines()
    except GitUnavailable:
        # Last resort: enumerate everything and match in Python. Slower, but a scan that cannot
        # run must never report clean.
        files = _git(["ls-files"], root=base).splitlines()
    for rel in files:
        if any(s in rel for s in _SKIP) or _FALSE_POSITIVE.search(rel):
            continue
        p = base / rel
        try:
            if p.stat().st_size > 2_000_000:
                continue
            hits = _scan_text(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if hits:
            out[rel] = hits
    return out


def scan_history(remotes_only: bool, root: Path | None = None) -> dict:
    """Scan git history for secrets, letting git do the searching.

    REWRITTEN 2026-07-30 because the previous design could not finish. It listed every
    add/modify in history, filtered by filename, then ran `git show <commit>:<path>` **once per
    blob** -- thousands of subprocesses on this ~10 GB history. Measured: `--pushed` ran for over
    ten minutes without completing, which is why the pushed-history scan had never actually
    produced a result, and why the legal packet's "pushed_secret_scan" was false while its pasted
    transcript claimed history had been checked.

    Now a single `git log -G<pattern> --perl-regexp` does the regex search inside git across all
    diffs, and only CONFIRMED hits -- normally none -- are fetched individually to redact and
    report. One subprocess in the clean case instead of thousands.

    The filename filter is gone with it: it existed to make the slow path tolerable and it was a
    correctness hole (a key pasted into a .py or .ps1 was invisible). git now searches every diff
    regardless of extension.
    """
    base = Path(root) if root is not None else REPO
    rev = "--remotes" if remotes_only else "--all"
    out: dict = {}

    # -G searches added/removed diff lines, using git's pickaxe regex -- which is POSIX ERE and
    # rejects the PCRE in PATTERNS even with --perl-regexp. So git gets the loose ERE prefilter and
    # _scan_text below does the exact matching. A long timeout: this walks the whole history once,
    # and a timeout raises GitUnavailable rather than being mistaken for "no secrets".
    # --no-textconv: without it git runs any configured textconv/diff driver while building diffs
    # and dies on the first blob a driver cannot handle ("E: unsupported filetype ... page.doc /
    # fatal: unable to read files to diff"), aborting the entire history scan. We want raw bytes
    # here anyway -- a secret is a secret whether or not a .doc renders.
    log = _git(
        [
            "log",
            rev,
            "--no-textconv",
            f"-G{_GIT_PREFILTER_ERE}",
            "--name-only",
            "--pretty=format:%H",
        ],
        root=base,
        timeout=1800,
    )

    commit = ""
    seen: set[str] = set()
    for line in log.splitlines():
        if re.fullmatch(r"[0-9a-f]{40}", line.strip()):
            commit = line.strip()
            continue
        rel = line.strip()
        if not rel or any(s in rel for s in _SKIP) or _FALSE_POSITIVE.search(rel):
            continue
        key = f"{commit}:{rel}"
        if key in seen:
            continue
        seen.add(key)
        # Only reached for a commit git already matched, so this stays cheap.
        try:
            blob = _git(["show", key], root=base)
        except GitUnavailable:
            continue
        hits = _scan_text(blob)
        if hits and (commit[:9], rel) in _ADJUDICATED_HISTORY:
            # Adjudicated once, with the reason recorded next to the entry. Skipped SILENTLY is
            # wrong -- an exemption nobody can see is how one outlives its premise -- so it is
            # reported in its own bucket instead of being folded into "clean".
            out.setdefault("__adjudicated__", []).append((commit[:9], rel))
            continue
        if hits:
            out.setdefault(rel, []).append((commit[:9], hits))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex secret scanner")
    ap.add_argument("--history", action="store_true", help="scan ALL git history")
    ap.add_argument("--pushed", action="store_true", help="scan only remote/pushed history")
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository to scan (defaults to this checkout). Use this to scan a "
        "staged mirror rather than the developer tree.",
    )
    args = ap.parse_args()

    root = args.root or REPO
    print(f"=== secret scan: tracked working tree ({root}) ===")
    try:
        tracked = scan_tracked(root=root)
    except GitUnavailable as exc:
        # Fail closed. A scan that could not run must never print a clean verdict.
        print(f"  SCAN FAILED: {exc}")
        print("\n=== verdict ===")
        print("  UNKNOWN: the scan did not complete, so nothing here says the tree is clean.")
        return 2
    if tracked:
        for rel, hits in tracked.items():
            for name, red in hits:
                print(f"  LEAK  {rel}: {name} {red}")
    else:
        print("  clean -- no secrets in tracked files")

    pushed_bad = False
    if args.pushed or args.history:
        scope = "remote/pushed" if args.pushed else "ALL"
        print(f"\n=== secret scan: {scope} git history ===")
        try:
            hist = scan_history(remotes_only=args.pushed, root=root)
        except GitUnavailable as exc:
            print(f"  SCAN FAILED: {exc}")
            print("\n=== verdict ===")
            print("  UNKNOWN: history scan did not complete, so nothing here clears the history.")
            return 2
        adjudicated = hist.pop("__adjudicated__", [])
        if hist:
            for rel, recs in hist.items():
                for commit, hits in recs:
                    for name, red in hits:
                        leaked = " (PUSHED -- ROTATE NOW)" if args.pushed else " (local history)"
                        print(f"  {commit} {rel}: {name} {red}{leaked}")
                        if args.pushed:
                            pushed_bad = True
        else:
            print(f"  clean -- no secrets in {scope} history")
        # Printed whether or not anything else was found. An exemption that is invisible is how
        # one outlives its premise; this keeps each one, and its reason, in front of whoever
        # reads the scan.
        for commit, rel in adjudicated:
            print(f"  {commit} {rel}: ADJUDICATED not a credential")
            print(f"      {_ADJUDICATED_HISTORY[(commit, rel)]}")

    print("\n=== verdict ===")
    if tracked or pushed_bad:
        print("  ACTION REQUIRED: a secret is in a leakable location. Rotate the key(s)")
        print("  and remove from tracking/history. See docs/SECURITY_POSTURE.md.")
        return 1
    # State only what was actually examined. This line used to read "no secret in tracked files
    # or pushed history" UNCONDITIONALLY -- including when neither --pushed nor --history was
    # given, so it asserted a property of the history that had not been looked at. That exact
    # string is captured verbatim into the legal_public_distribution evidence packet, whose own
    # pushed_secret_scan field is false.
    if args.pushed:
        print("  OK: no secret in tracked files or pushed history.")
    elif args.history:
        print("  OK: no secret in tracked files; ALL local history scanned (see note below).")
    else:
        print("  OK: no secret in tracked files.")
        print("  NOTE: git history was NOT scanned. Re-run with --pushed before publishing.")
    if args.history:
        print("  (Any matches above were LOCAL-only history -- not leaked off-box, but")
        print("   rotate + scrub if the box could be accessed. See docs/SECURITY_POSTURE.md.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
