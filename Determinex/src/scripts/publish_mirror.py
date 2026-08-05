"""Publish this checkout's source/docs onto the curated release mirror.

WHY THIS EXISTS
---------------
`DarthCeltic/Determinex` is a deliberately curated ~46 MB mirror. This dev
checkout is ~10 GB of `.git`, 2,486 commits, and **completely unrelated history**
-- the mirror's `main` commit does not exist in this repository's object store at
all. So `git push origin <branch>` does not do what it looks like it does: it tries
to graft the entire dev history onto the mirror, and GitHub answers `HTTP 500`
(confirmed 2026-07-28, twice, including with `http.postBuffer=500MB`;
`--dry-run` succeeds, so it is the pack, not auth).

There was no tool for this. The mirror had been assembled by hand, which is why
"just push it" kept looking like the obvious move and kept failing.

WHAT IT DOES
------------
Copies the allowlisted paths from this checkout onto the mirror's own history as
one ordinary commit, keeping it small, then pushes that.

THE ALLOWLIST IS DERIVED, NOT MAINTAINED
----------------------------------------
It comes from `git ls-tree origin/main` -- the mirror's own published top level.
A hand-kept list would drift from what is actually published, and the drift would
be silent in the direction that matters: a new directory of corpus data or
evidence quietly appearing in a repo that exists to not contain it. Deriving it
means the mirror can only ever receive paths it already publishes; adding a NEW
top-level entry is a deliberate act requiring `--allow-new-path`.

Default is a dry run. Nothing is pushed without `--push`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Never copied, whatever the mirror's tree says. Belt to the allowlist's braces:
# if one of these ever appears in the mirror it is a leak to fix, not a path to
# faithfully re-sync.
#: Paths inside an otherwise-published top-level entry that must not travel.
#:
#: `corpus` came OFF the NEVER list on 2026-07-31: the corpus is the point of Determinex — the
#: Native Reimplementation Loop feeds real source and a real oracle to a model — so publishing a
#: repo without it ships a hollow product. What cannot travel is the ~150,000 files of VENDORED
#: UPSTREAM SOURCE inside it, for two independent reasons:
#:
#:   SIZE  the pack is 9.73 GiB. GitHub soft-limits at 1 GB and rejects any file over 100 MB.
#:   LAW   those trees are other people's software. Redistribution obliges us to carry each
#:         project's copyright notice and license, and 59 of them still have no license text.
#:
#: So the KNOWLEDGE layer ships — the oracles, our `compile.sh` recipes, eval reports, learned
#: build knowledge, and `canonical_tasks.json`, which pins repository+commit for all 200 tasks —
#: and `determinex corpus fetch` reconstructs any upstream tree from its own maintainers at
#: exactly that commit. Same inputs to the model, nothing re-hosted.
CORPUS_VENDORED_MARKERS = (
    "/source/",  # locked/<tool>/source, pending_unlock/<tier>/<tool>/source
)

#: Inside `per_tool_overrides/<tool>/` only these are ours; the rest of that directory is a
#: complete upstream checkout the recipe happens to sit inside.
CORPUS_OVERRIDE_KEEP = ("compile.sh", "conftest.py", "eval_report.json", "tests.json")

#: Bulk EVIDENCE that belongs in the dataset, not in a git repo. Dropping the vendored source got
#: corpus/ from 158,788 files to 2,351 — but still 908 MB, because 519 `eval_report.json` files are
#: 554 MB of raw per-test output on their own, plus 146 MB of `.bak` archives and 72 MB of training
#: corpus. A git repo is the wrong home for that: every revision keeps a copy forever.
#:
#: Verifiability is not lost. `eval_index.json` records `eval_report_sha256` for each row, so the
#: repo carries a checksum of every report and the dataset carries the report — you can prove the
#: artifact you downloaded is the one the board's number came from.
CORPUS_BULK_EVIDENCE = (
    ".bak",  # pre-bidir backups; never publish a backup
    ".tar.gz",  # submission archives, reproducible from compile.sh
    "/training_corpus/",  # the flywheel's training data
)

#: Basename PREFIXES for bulk evidence. A prefix, not an exact name: matching only
#: `eval_report.json` left `eval_report_tui_v1.json`, `eval_report_v3.json` and friends behind,
#: which is 20 MB of the same raw per-test output under a different filename.
CORPUS_BULK_PREFIXES = ("eval_report",)

#: Individually large reference data that belongs in the dataset. Named explicitly rather than
#: caught by a size threshold, because a size rule would silently start dropping things as files
#: grow, and "the repo quietly stopped shipping X" is the failure mode this repo keeps finding.
# Withheld for SIZE only -- nothing here is private or third-party. Both are back in as of
# 2026-08-01: 36 MB and 8.8 MB are comfortably under GitHub's 50 MB per-file warning, the
# repo total lands near 110 MB against a 1 GB soft limit, and withholding them broke the
# thing the repo exists to provide. `determinex_corpus_api.swebench_stats()` reads the
# inventory and returned {} for every public clone, so the SWE-bench surface the README
# points at did not work for anyone who was not us.
CORPUS_BULK_FILES: tuple[str, ...] = ()

# Exceptions to NEVER, at subtree granularity. A top-level block is the right default --
# `logs/` holds run traces and cloak audits -- but blocking the whole tree also withheld the
# 91 benchmark artifacts the WHITE_PAPER cites BY PATH ("verified
# logs/eval_results/eval_determinex-engineer-v10-dsl_20260415_233437.json"). A claim whose
# evidence is unreachable is a claim on trust. 1.8 MB, scanned, no credentials and no
# personal paths.
NEVER_EXCEPT = (
    "logs/eval_results/",
    # The ProgramBench lock board, 210 entries, tracked, no credentials. Withholding it made
    # the Governance Gates job die on `FileNotFoundError: logs/programbench_lock_board.json`
    # -- the override scan is a gate against a locked tool's compile.sh suppressing test
    # collection, and a gate that cannot read its input is not enforcing anything.
    "logs/programbench_lock_board.json",
    # The evidence INDEX only -- 1.2 MB, not the 273 MB tree around it. `determinex evidence
    # validate` checks that every entry's manifest_path exists, and all 1,837 of them are
    # under locks/sentinel/, which the mirror already publishes. So the index was the single
    # missing file behind two red jobs ("Evidence index not found" and the arch gauntlet's
    # cli.evidence_validate CLI_COMMAND_FAILED). The evidence ARTEFACTS stay unpublished.
    "assurance/evidence/evidence_index.json",
)

NEVER = {
    ".env",
    ".env.local",
    ".git",
    "assurance",
    "logs",
    "sessions",
    ".determinex",
    "node_modules",
    "target",
    ".venv",
    "uv.lock",
}


def run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a git/subprocess command. No shell=True (pre-commit forbids it)."""
    proc = subprocess.run(
        args,
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return proc.stdout


def mirror_allowlist(remote: str, branch: str) -> list[str]:
    """The mirror's own published top-level entries."""
    run(["git", "fetch", remote, branch])
    out = run(["git", "ls-tree", "--name-only", "FETCH_HEAD"])
    entries = [line.strip() for line in out.splitlines() if line.strip()]
    if not entries:
        raise SystemExit(f"{remote}/{branch} has an empty tree -- refusing to guess an allowlist")
    return entries


# Top-level entries whose allowlist is derived at FILE granularity from the mirror rather
# than "everything tracked under the directory". A path lands here when the mirror publishes
# a deliberate handful out of a large local tree -- adding it as a directory would smuggle
# the rest in on the next publish.
#
# `corpus` was here and is deliberately NOT any more. Being in NARROW made the
# `elif top == "corpus"` branch in collect() UNREACHABLE, so filter_corpus -- the function
# written specifically to separate our knowledge layer from vendored upstream source --
# never ran. The documented split (CLAUDE.md, "Corpus Distribution": knowledge layer in the
# repo, vendored trees as a dataset) resolved to ONE published corpus file instead of 1,711,
# and the public repo shipped a product whose knowledge layer was absent.
#
# The reason corpus was narrowed is real and is now handled precisely instead of bluntly:
# GitHub push protection rejected the knowledge layer because secret-DETECTION tools ship
# secret-shaped test fixtures. That is 6 files out of 1,711 (measured), so the fix is to
# name those 6, not to withhold the other 1,705.
NARROW: set[str] = set()

# Files inside the knowledge layer that carry secret-SHAPED strings as test data, because
# the tool they describe is a secret detector. Nothing here is a live credential -- they are
# fixtures like ripsecrets' 82 `sk_live_` samples, published by that project on purpose --
# but GitHub push protection cannot tell the difference and rejects the push. Withheld by
# name, reported on every run, and retrievable from upstream.
CORPUS_SECRET_FIXTURES = {
    "corpus/programbench/specs/sirwart__ripsecrets.34c9e03.json",
    "corpus/programbench/reimpl_skills/ripsecrets_probes.json",
    "corpus/programbench/specs/hairyhenderson__gomplate.05eb3aa.json",
    "corpus/programbench/reimpl_skills/datasurgeon_probes.json",
    "corpus/programbench/specs/drew-alleman__datasurgeon.d257cee.json",
}


def mirror_files_under(entry: str) -> list[str]:
    """The files the mirror actually publishes under `entry` (recursive, FETCH_HEAD)."""
    out = run(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", entry])
    return [line.strip() for line in out.splitlines() if line.strip()]


def tracked_files_under(path: str) -> list[str]:
    """Files git tracks under a path in THIS checkout, so ignored build output and
    untracked scratch never reach the mirror."""
    out = run(["git", "ls-files", "-z", "--", path])
    return [p for p in out.split("\0") if p]


def filter_corpus(paths: list[str]) -> tuple[list[str], int]:
    """Keep the knowledge layer, drop the vendored upstream source.

    Two shapes of vendored tree exist and both must go:

      `.../<tool>/source/**`            a whole upstream checkout under an explicit `source/` dir
      `per_tool_overrides/<tool>/**`    a whole upstream checkout with OUR recipe sitting inside it

    The second is the subtle one: `per_tool_overrides` reads like a directory of our own files, and
    it is 142,750 files of which only ~420 are ours. Everything there is dropped except the four
    recipe filenames, so a new upstream file cannot arrive in the public repo by default.
    """
    kept: list[str] = []
    dropped = 0
    for path in paths:
        posix = path.replace("\\", "/")
        if any(marker in posix for marker in CORPUS_VENDORED_MARKERS):
            dropped += 1
            continue
        if any(marker in posix or posix.endswith(marker) for marker in CORPUS_BULK_EVIDENCE):
            dropped += 1
            continue
        if posix in CORPUS_BULK_FILES:
            dropped += 1
            continue
        if Path(posix).name.startswith(CORPUS_BULK_PREFIXES):
            dropped += 1
            continue
        if "/per_tool_overrides/" in posix:
            # Allowlist by basename, not blocklist by pattern: an unknown file inside a vendored
            # checkout is upstream's until proven otherwise.
            if Path(posix).name not in CORPUS_OVERRIDE_KEEP:
                dropped += 1
                continue
        if posix in CORPUS_SECRET_FIXTURES:
            dropped += 1
            continue
        kept.append(path)
    return kept, dropped


def collect(allowlist: list[str], allow_new: bool) -> tuple[list[str], list[str]]:
    """Resolve the allowlist to a concrete tracked-file list."""
    files: list[str] = []
    skipped: list[str] = []
    for entry in allowlist:
        top = entry.split("/", 1)[0]
        # rstrip the slash on BOTH sides: the exception is written "logs/eval_results/" but
        # the allowlist entry is the bare directory "logs/eval_results", so a naive
        # startswith says no and the exception silently does nothing.
        _entry = entry.replace("\\", "/").rstrip("/")
        if top in NEVER and not _entry.startswith(tuple(e.rstrip("/") for e in NEVER_EXCEPT)):
            skipped.append(f"{entry} (on the never-copy list)")
            continue
        if not (REPO / entry).exists():
            # The mirror publishes something this checkout no longer has. Report
            # it rather than silently deleting it from the mirror.
            skipped.append(f"{entry} (published by the mirror, absent here)")
            continue
        found = tracked_files_under(entry)
        if not found:
            skipped.append(f"{entry} (nothing tracked under it)")
            continue
        if top in NARROW:
            # NARROW paths keep the mirror's own FILE list, not everything tracked under the
            # directory. `corpus` was added to the mirror as a single file
            # (corpus/programbench/build_knowledge.json), but resolving the top-level entry
            # swept all 1,700+ tracked corpus files back in -- and GitHub push protection
            # rejected the push, because the ProgramBench knowledge layer includes
            # secret-detection tools' test corpora (ripsecrets ships 56 sk_live_ strings by
            # design). Deriving at file granularity keeps "the mirror can only receive paths
            # it already publishes" true one level down.
            published = set(mirror_files_under(entry))
            narrowed = [f for f in found if f in published]
            if len(narrowed) != len(found):
                skipped.append(
                    f"{entry} ({len(found) - len(narrowed)} file(s) not published "
                    f"by the mirror; use --allow-new-path to add one)"
                )
            found = narrowed
            if not found:
                continue
        elif top == "corpus":
            kept, dropped = filter_corpus(found)
            if dropped:
                skipped.append(f"{entry} ({dropped} vendored upstream file(s) withheld)")
            found = kept
        files.extend(found)
    if not allow_new:
        return files, skipped
    return files, skipped


def secret_scan(root: Path) -> None:
    """Run the repo's own scanner over the staged mirror before anything is
    committed. The mirror is the public artifact; this is the last gate."""
    scanner = REPO / "scripts" / "security" / "secret_scan.py"
    if not scanner.exists():
        # This is the last gate before a public push; a missing scanner is not a warning.
        raise SystemExit(
            f"secret_scan.py not found at {scanner} -- refusing to publish unscanned content"
        )
    # --root, not cwd. Passing cwd alone was inert and this gate never examined the mirror:
    # secret_scan derives REPO from its own __file__ and ran git with cwd=REPO, so for every
    # publish so far the verdict described the DEVELOPER CHECKOUT while the staged content about
    # to be committed and pushed was never scanned. Proven by running the scanner from an empty
    # non-git directory: it reported "clean -- no secrets in tracked files" and exited 0.
    proc = subprocess.run(
        [sys.executable, str(scanner), "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print("  " + "\n  ".join(proc.stdout.strip().splitlines()[-4:]))
    if proc.returncode != 0:
        raise SystemExit("secret scan FAILED on the staged mirror -- nothing published")
    # The scanner now prints the root it examined. If that is not the mirror, the gate did not do
    # its job and silence would be indistinguishable from success.
    if str(root) not in proc.stdout:
        raise SystemExit(
            f"secret scan did not report scanning the staged mirror ({root}) -- nothing published"
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("-m", "--message", default=None, help="Commit message for the mirror commit")
    ap.add_argument("--push", action="store_true", help="Actually push. Without it, dry run.")
    ap.add_argument(
        "--allow-new-path",
        action="append",
        default=[],
        help="Publish a top-level path the mirror does not already have. Deliberate act.",
    )
    ap.add_argument("--keep", action="store_true", help="Keep the staging worktree for inspection")
    args = ap.parse_args()

    print(f"[1/5] Reading the mirror's own tree from {args.remote}/{args.branch} ...")
    allowlist = mirror_allowlist(args.remote, args.branch)
    # NEVER_EXCEPT paths are unconditional, not derived. The allowlist comes from the
    # mirror's own tree, and the mirror's top-level entry for these is `logs`, which is on
    # NEVER -- so the exception survived exactly one publish (the one that named it via
    # --allow-new-path) and the very next run dropped the entry, saw 91 files present
    # remotely and absent locally, and DELETED them. An exception that has to be re-argued
    # every run is not an exception.
    for exc in NEVER_EXCEPT:
        entry = exc.rstrip("/")
        if entry not in allowlist and (REPO / entry).exists():
            allowlist.append(entry)
    for extra in args.allow_new_path:
        # An explicit --allow-new-path for a NEVER path is a CONTRADICTION: the operator
        # asserts "publish this", the policy asserts "never publish this", and only one of
        # them can be right. Resolving it silently in favour of the policy is what happened
        # to `uv.lock` -- refused on line 3, reported as "published" on the last line, and
        # absent from a fresh clone of the public repo hours later. Either the request is
        # wrong or NEVER is stale; both need a human, and neither is served by a skip line
        # buried among thirty others.
        if extra.split("/", 1)[0] in NEVER and not extra.replace("\\", "/").rstrip("/").startswith(
            tuple(e.rstrip("/") for e in NEVER_EXCEPT)
        ):
            raise SystemExit(
                f"--allow-new-path {extra!r} contradicts the NEVER list, which refuses "
                f"{extra.split('/', 1)[0]!r}. Nothing published. Either drop the flag, or "
                f"remove the entry from NEVER in this file and say why in the commit."
            )
        if extra not in allowlist:
            allowlist.append(extra)
            print(f"      + {extra} (NEW top-level path, explicitly allowed)")
    print(f"      {len(allowlist)} top-level entries published by the mirror")

    print("[2/5] Resolving to tracked files in this checkout ...")
    files, skipped = collect(allowlist, bool(args.allow_new_path))
    print(f"      {len(files)} tracked files to publish")
    for s in skipped:
        print(f"      - skipped {s}")

    total = sum((REPO / f).stat().st_size for f in files if (REPO / f).is_file())
    print(f"      {total / 1048576:.1f} MB")
    if total > 200 * 1048576:
        raise SystemExit(
            f"refusing to publish {total / 1048576:.0f} MB to a curated mirror -- "
            "something is wrong with the allowlist"
        )

    staging = Path(tempfile.mkdtemp(prefix="determinex-mirror-"))
    try:
        print(f"[3/5] Staging the mirror's history in {staging} ...")
        run(
            [
                "git",
                "clone",
                "--branch",
                args.branch,
                "--single-branch",
                run(["git", "remote", "get-url", args.remote]).strip(),
                str(staging),
            ]
        )

        # Replace the tree wholesale: anything the mirror has and we no longer
        # publish should disappear, which a copy-over-the-top would silently keep.
        for child in staging.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()

        for rel in files:
            src, dst = REPO / rel, staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        print("[4/5] Secret scan on the staged mirror ...")
        secret_scan(staging)

        # The staging clone inherits the MIRROR's .gitignore, so `git add -A` silently drops
        # anything it matches -- `archive/` eats all of scripts/archive/. Those files were
        # copied, counted, and reported as published on every prior run, and were never in
        # the remote. Ask git what it refuses BEFORE committing and take them out of the
        # intent list, so "published N files" describes the mirror rather than a wish.
        # `run()` has no stdin channel, and the file list is far past a Windows command
        # line's length limit, so this one call goes direct.
        #
        # -z on BOTH sides, not newlines: text mode translates \n to \r\n on Windows, so
        # git received "scripts/archive/x.py\r" and quoted the \r back into every answer.
        # And NOT --no-index: that flag makes check-ignore judge tracked files too, which
        # reported `.env.example` as refused when the mirror already tracks it and `git add`
        # would update it happily -- it cut the publish set from 11 files to 1.
        ignored = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=str(staging),
            input="\0".join(files),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout.split("\0")
        if ignored:
            drop = {p.strip().replace("\\", "/") for p in ignored if p.strip()}
            files = [f for f in files if f not in drop]
            print(
                f"      - {len(drop)} file(s) refused by the mirror's own .gitignore, "
                f"removed from the publish set: {sorted(drop)[:5]}"
            )

        run(["git", "add", "-A"], cwd=staging)
        status = run(["git", "status", "--porcelain"], cwd=staging)
        if not status.strip():
            print("      mirror already matches this checkout -- nothing to publish")
            return 0
        changed = len(status.strip().splitlines())
        print(f"      {changed} files differ from the published mirror")

        msg = args.message or "chore: sync source and docs from the development checkout"
        run(
            [
                "git",
                "-c",
                "user.name=Determinex Publisher",
                "-c",
                f"user.email={os.environ.get('GIT_AUTHOR_EMAIL', 'noreply@github.com/DarthCeltic')}",
                "commit",
                "-q",
                "-m",
                msg,
            ],
            cwd=staging,
        )

        if not args.push:
            print("[5/5] DRY RUN -- not pushed. Re-run with --push to publish.")
            print(f"      staged commit is in {staging}" if args.keep else "")
            return 0

        print(f"[5/5] Pushing to {args.remote}/{args.branch} ...")
        run(["git", "push", "origin", f"HEAD:{args.branch}"], cwd=staging)

        # "published" used to mean "git push exited 0", which is a claim about a command
        # rather than about the mirror. Read the remote tree back and compare it to what we
        # set out to publish. Without this the operator's only evidence is a word we print.
        print("      verifying the remote tree matches what was published ...")
        run(["git", "fetch", "--quiet", "origin", args.branch], cwd=staging)
        remote = set(
            run(
                ["git", "ls-tree", "-r", "--name-only", f"origin/{args.branch}"], cwd=staging
            ).splitlines()
        )
        missing = sorted(set(files) - remote)
        if missing:
            raise SystemExit(
                f"PUSH SUCCEEDED BUT {len(missing)} FILE(S) ARE NOT IN THE REMOTE TREE: "
                f"{missing[:10]}. The mirror does not contain what this run reported "
                f"publishing -- do not treat it as up to date."
            )
        extra_remote = sorted(remote - set(files))
        if extra_remote:
            print(
                f"      note: {len(extra_remote)} file(s) in the mirror were not in this "
                f"run's file list: {extra_remote[:5]}"
            )
        print(
            f"      published and verified: {len(files)} files present in "
            f"{args.remote}/{args.branch}."
        )
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
