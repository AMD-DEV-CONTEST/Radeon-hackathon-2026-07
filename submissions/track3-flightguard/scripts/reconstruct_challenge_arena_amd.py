#!/usr/bin/env python3
"""Reconstruct the frozen Challenge Arena commit and run its untouched runner.

The submitted runner is bound to the source commit that produced the evidence.
This launcher verifies the submitted bytes, reconstructs that commit in a
temporary worktree, and materializes the exact submitted runner and config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_REL = Path("submissions/track3-flightguard")
RUNNER_REL = PACKAGE_REL / "scripts/run_challenge_arena_amd.py"
CONFIG_REL = PACKAGE_REL / "configs/challenge_arena_v1.json"
SUMMARY_REL = (
    PACKAGE_REL
    / "submission/evidence/challenge-arena/challenge-arena-summary.json"
)
CRITICAL_SOURCE_REL = PACKAGE_REL / "src/flightguard"

FROZEN_SOURCE_COMMIT = "49777136e77504cc90016d1308ee0768e5e81b9e"
EXPECTED_RUNNER_SHA256 = (
    "cd0898cde2630a686f3cbded0463c06f20dc7b3e9c8a742b4df7ed95ba21c4d6"
)
EXPECTED_CONFIG_SHA256 = (
    "af30cfdaaecb1b00ec477a2a22b96eeaf25b328327b11a43f04f1e570045173d"
)
EXPECTED_SUMMARY_SHA256 = (
    "91b18677fa9fcb5f05acead2aa3fb4324188b44173ea85fda75c67e2dcb129ee"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="reconstruct and validate the frozen runner without using a GPU",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="existing directory in which to create the temporary worktree",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("compare", "noop", "kill"))
    parser.add_argument("--domain-profile", choices=("adversarial", "heldout"))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--pairs", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--log-every", type=int, default=250)
    args = parser.parse_args()
    required = ("output", "mode", "domain_profile", "seed", "pairs", "steps")
    if not args.validate_only:
        missing = [name for name in required if getattr(args, name) is None]
        if missing:
            flags = ", ".join(
                "--" + name.replace("_", "-") for name in missing
            )
            parser.error(
                "the following arguments are required unless --validate-only "
                f"is used: {flags}"
            )
    return args


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(
    *args: str,
    cwd: Path = REPO_ROOT,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=text,
    )


def committed_bytes(revision: str, path: Path) -> bytes:
    return git("show", f"{revision}:{path.as_posix()}", text=False).stdout


def require_git_quiet(*args: str, failure: str) -> None:
    result = git(*args, check=False)
    if result.returncode == 1:
        raise RuntimeError(failure)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with rc={result.returncode}: "
            f"{result.stderr.strip()}"
        )


def validate_repository() -> tuple[str, bytes, bytes]:
    top = Path(git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if top != REPO_ROOT.resolve():
        raise RuntimeError(f"launcher repository mismatch: {top} != {REPO_ROOT}")

    head = git("rev-parse", "HEAD").stdout.strip()
    runner_bytes = committed_bytes("HEAD", RUNNER_REL)
    config_bytes = committed_bytes("HEAD", CONFIG_REL)
    summary_bytes = committed_bytes("HEAD", SUMMARY_REL)
    actual = {
        "runner": sha256_bytes(runner_bytes),
        "config": sha256_bytes(config_bytes),
        "summary": sha256_bytes(summary_bytes),
    }
    expected = {
        "runner": EXPECTED_RUNNER_SHA256,
        "config": EXPECTED_CONFIG_SHA256,
        "summary": EXPECTED_SUMMARY_SHA256,
    }
    if actual != expected:
        raise RuntimeError(f"frozen artifact SHA mismatch: {actual}")

    config = json.loads(config_bytes)
    summary = json.loads(summary_bytes)
    if config.get("source_commit") != FROZEN_SOURCE_COMMIT:
        raise RuntimeError("frozen config source_commit mismatch")
    bindings = summary.get("bindings", {})
    if bindings.get("runner", {}).get("sha256") != EXPECTED_RUNNER_SHA256:
        raise RuntimeError("summary runner binding mismatch")
    if bindings.get("config", {}).get("sha256") != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("summary config binding mismatch")

    ancestor = git(
        "merge-base",
        "--is-ancestor",
        FROZEN_SOURCE_COMMIT,
        head,
        check=False,
    )
    if ancestor.returncode == 1:
        raise RuntimeError("frozen source commit is not an ancestor of HEAD")
    if ancestor.returncode != 0:
        raise RuntimeError(
            "unable to verify frozen source ancestry: "
            f"{ancestor.stderr.strip()}"
        )
    require_git_quiet(
        "diff",
        "--quiet",
        FROZEN_SOURCE_COMMIT,
        head,
        "--",
        CRITICAL_SOURCE_REL.as_posix(),
        failure="execution-critical source differs from the frozen commit",
    )
    require_git_quiet(
        "diff",
        "--quiet",
        "--",
        CRITICAL_SOURCE_REL.as_posix(),
        failure="unstaged execution-critical source changes are present",
    )
    require_git_quiet(
        "diff",
        "--cached",
        "--quiet",
        "--",
        CRITICAL_SOURCE_REL.as_posix(),
        failure="staged execution-critical source changes are present",
    )
    untracked = git(
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        CRITICAL_SOURCE_REL.as_posix(),
    ).stdout.strip()
    if untracked:
        raise RuntimeError(
            f"untracked execution-critical source files are present: {untracked}"
        )
    return head, runner_bytes, config_bytes


def write_exclusive(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(mode)


def materialize(
    worktree: Path,
    runner_bytes: bytes,
    config_bytes: bytes,
) -> tuple[Path, Path]:
    runner = worktree / RUNNER_REL
    config = worktree / CONFIG_REL
    write_exclusive(runner, runner_bytes, 0o755)
    write_exclusive(config, config_bytes, 0o644)
    if sha256_file(runner) != EXPECTED_RUNNER_SHA256:
        raise RuntimeError("post-write runner SHA mismatch")
    if sha256_file(config) != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("post-write config SHA mismatch")
    return runner, config


def validate_materialized_runner(
    runner: Path,
    package_root: Path,
    pyc: Path,
) -> None:
    py_compile.compile(str(runner), cfile=str(pyc), doraise=True)
    help_run = subprocess.run(
        [sys.executable, str(runner), "--help"],
        cwd=package_root,
        text=True,
        capture_output=True,
    )
    if help_run.returncode != 0:
        raise RuntimeError(
            f"materialized runner --help failed: {help_run.stderr.strip()}"
        )
    if "--mode {compare,noop,kill}" not in help_run.stdout:
        raise RuntimeError("materialized runner --help surface mismatch")


def runner_command(args: argparse.Namespace, runner: Path) -> list[str]:
    assert args.output is not None
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    return [
        sys.executable,
        str(runner),
        "--output",
        str(output),
        "--mode",
        str(args.mode),
        "--domain-profile",
        str(args.domain_profile),
        "--seed",
        str(args.seed),
        "--pairs",
        str(args.pairs),
        "--steps",
        str(args.steps),
        "--log-every",
        str(args.log_every),
    ]


def main() -> int:
    args = parse_args()
    head, runner_bytes, config_bytes = validate_repository()
    work_root = args.work_root.expanduser().resolve() if args.work_root else None
    if work_root is not None and not work_root.is_dir():
        raise NotADirectoryError(f"work-root is not a directory: {work_root}")

    added = False
    primary_error: BaseException | None = None
    with tempfile.TemporaryDirectory(
        prefix="flightguard-arena-base-",
        dir=work_root,
    ) as temporary:
        temporary_root = Path(temporary)
        worktree = temporary_root / "base-worktree"
        try:
            git("worktree", "add", "--detach", str(worktree), FROZEN_SOURCE_COMMIT)
            added = True
            reconstructed_head = git(
                "rev-parse",
                "HEAD",
                cwd=worktree,
            ).stdout.strip()
            if reconstructed_head != FROZEN_SOURCE_COMMIT:
                raise RuntimeError("reconstructed worktree HEAD mismatch")
            runner, _ = materialize(worktree, runner_bytes, config_bytes)
            package_root = worktree / PACKAGE_REL
            if args.validate_only:
                validate_materialized_runner(
                    runner,
                    package_root,
                    temporary_root / "frozen-runner.pyc",
                )
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "mode": "validate-only",
                            "submission_head": head,
                            "reconstructed_head": reconstructed_head,
                            "runner_sha256": sha256_file(runner),
                            "config_sha256": EXPECTED_CONFIG_SHA256,
                        },
                        sort_keys=True,
                    )
                )
                return 0

            print(
                json.dumps(
                    {
                        "status": "STARTING",
                        "submission_head": head,
                        "reconstructed_head": reconstructed_head,
                        "runner_sha256": EXPECTED_RUNNER_SHA256,
                        "config_sha256": EXPECTED_CONFIG_SHA256,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            completed = subprocess.run(
                runner_command(args, runner),
                cwd=package_root,
            )
            return completed.returncode
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if added:
                cleanup = git(
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                    check=False,
                )
                if cleanup.returncode != 0:
                    message = (
                        "failed to remove exact temporary worktree "
                        f"{worktree}: {cleanup.stderr.strip()}"
                    )
                    if primary_error is None:
                        raise RuntimeError(message)
                    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
