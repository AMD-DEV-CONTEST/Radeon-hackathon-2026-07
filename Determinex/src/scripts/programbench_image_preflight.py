#!/usr/bin/env python3
"""Preflight ProgramBench image and executable plumbing for one task.

Checks:
  1. The normalized ProgramBench cleanroom image exists locally.
  2. The cleanroom image starts without stale ProgramBench stash residue.
  3. The reference repo executable exists at /workspace/executable.
  4. Optional submission.tar.gz has a clean root-level archive shape.
  5. Optional candidate source dir compiles to a real ./executable file.
  6. The candidate executable survives ProgramBench's move-to-/opt hash step.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
from pathlib import Path

STASHED = "/opt/programbench-stashed-executable-do-not-modify"
DEFAULT_DOCKER_CPUS = "1"


def image_name(instance_id: str) -> str:
    return f"programbench/{instance_id.replace('__', '_1776_')}:task_cleanroom"


def docker_path(path: Path) -> str:
    s = str(path.resolve()).replace("\\", "/")
    if len(s) > 2 and s[1] == ":":
        return "/" + s[0].lower() + s[2:]
    return s


def run(cmd: list[str], *, timeout: int = 300) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def docker_run_base() -> list[str]:
    raw_cpus = os.environ.get("DETERMINEX_PB_DOCKER_CPUS", DEFAULT_DOCKER_CPUS).strip()
    try:
        cpus = str(max(1, min(int(float(raw_cpus)), 1)))
    except ValueError:
        cpus = DEFAULT_DOCKER_CPUS
    return [
        "docker",
        "run",
        "--rm",
        "--cpus",
        cpus,
        "-e",
        "PB_MAKE_JOBS=1",
        "-e",
        "MAKEFLAGS=-j1",
    ]


def check_image(image: str) -> bool:
    rc, out = run(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            "{{.Id}} {{.Created}} {{json .RepoTags}}",
        ],
        timeout=60,
    )
    if rc != 0:
        print(f"FAIL image missing: {image}")
        print(out.strip())
        return False
    print(f"OK image present: {image}")
    print(out.strip())
    return True


def check_cleanroom_state(image: str) -> bool:
    script = (
        "set -e; "
        f"test ! -e {STASHED}; "
        "test -d /workspace; "
        "test -x /workspace/executable; "
        "sha256sum /workspace/executable"
    )
    rc, out = run([*docker_run_base(), image, "bash", "-lc", script], timeout=120)
    if rc != 0:
        print("FAIL image cleanroom state is dirty or missing /workspace/executable")
        print(out.strip())
        return False
    print("OK cleanroom state:")
    print(out.strip())
    return True


def check_reference_executable(image: str) -> bool:
    script = "test -x /workspace/executable && sha256sum /workspace/executable"
    rc, out = run([*docker_run_base(), image, "bash", "-lc", script], timeout=120)
    if rc != 0:
        print("FAIL reference executable missing or not executable at /workspace/executable")
        print(out.strip())
        return False
    print("OK reference executable:")
    print(out.strip())
    return True


def check_submission_tar(submission_tar: Path) -> bool:
    if not submission_tar.exists():
        print(f"FAIL submission tar missing: {submission_tar}")
        return False
    bad: list[str] = []
    names: list[str] = []
    try:
        with tarfile.open(submission_tar, "r:gz") as tf:
            for member in tf.getmembers():
                name = member.name.lstrip("./")
                names.append(name)
                parts = Path(name).parts
                if name.startswith("source/") or "/source/" in name:
                    bad.append(f"nested source path: {member.name}")
                if "__pycache__" in parts or name.endswith(".pyc"):
                    bad.append(f"python cache artifact: {member.name}")
                if member.issym() and Path(name).name == "executable":
                    bad.append(f"executable is archived as symlink: {member.name}")
    except tarfile.TarError as exc:
        print(f"FAIL cannot read submission tar: {exc}")
        return False

    if "compile.sh" not in names:
        bad.append("missing root compile.sh")
    root_files = {Path(name).parts[0] for name in names if name and Path(name).parts}
    if root_files == {"source"}:
        bad.append("archive root contains only source/")

    if bad:
        print("FAIL dirty submission archive:")
        for item in bad[:20]:
            print(f"  - {item}")
        return False
    print(f"OK clean submission archive: {submission_tar}")
    return True


def check_candidate(image: str, source_dir: Path) -> bool:
    if not source_dir.is_dir():
        print(f"FAIL source dir missing: {source_dir}")
        return False
    mount = docker_path(source_dir)
    script = (
        "set -e; "
        "rm -rf /tmp/pb-preflight && mkdir -p /tmp/pb-preflight; "
        "cp -r /mnt/src/. /tmp/pb-preflight/; "
        "cd /tmp/pb-preflight; "
        "rm -f ./executable; "
        "chmod +x ./compile.sh; "
        "./compile.sh; "
        "test -f ./executable; "
        "test ! -L ./executable; "
        f"rm -f {STASHED}; "
        f"mv ./executable {STASHED}; "
        f"sha256sum {STASHED}"
    )
    rc, out = run(
        [*docker_run_base(), "-v", f"{mount}:/mnt/src:ro", image, "bash", "-lc", script],
        timeout=900,
    )
    if rc != 0:
        print("FAIL candidate executable plumbing")
        print(out.strip())
        return False
    print("OK candidate executable stashes and hashes:")
    print(out.strip())
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight ProgramBench image/executable plumbing."
    )
    parser.add_argument("instance_id", help="Full instance id, e.g. jqlang__jq.b33a763")
    parser.add_argument(
        "--source-dir", type=Path, help="Optional candidate source dir containing compile.sh"
    )
    parser.add_argument("--submission-tar", type=Path, help="Optional submission.tar.gz to inspect")
    args = parser.parse_args()

    image = image_name(args.instance_id)
    ok = check_image(image)
    if ok:
        ok = check_cleanroom_state(image) and ok
    if ok:
        ok = check_reference_executable(image) and ok
    if ok and args.submission_tar:
        ok = check_submission_tar(args.submission_tar) and ok
    if ok and args.source_dir:
        ok = check_candidate(image, args.source_dir) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
