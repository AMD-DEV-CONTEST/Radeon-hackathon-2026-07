#!/usr/bin/env python3
"""determinex_platform_screen.py -- refuse cross-platform data hazards before they
become capability verdicts.

WHY THIS EXISTS
---------------
In one night, on one machine, these seven hazards each produced a WRONG ANSWER rather
than an error. Two of them printed a perfect zero that was indistinguishable from
"the model cannot do this":

  1. CRLF in a file executed by /bin/sh      -> "Syntax error: word unexpected"
  2. a Windows path passed to a Linux shell  -> "C:DevRadeon...: command not found"
  3. MSYS path conversion of a container arg -> "working directory 'W:/' is invalid"
  4. exec bit lost crossing a tar/host bound -> 0/234, looked like total model failure
  5. host binary graded vs in-container truth-> 0/234, looked like total model failure
  6. env var colliding with an OS-reserved   -> float('<repo>/0.6')
     name (TEMP on Windows)
  7. non-UTF-8 bytes in captured output      -> mojibake in every log line

The through-line is the same one this codebase keeps relearning: a silent wrong answer
is worse than a loud failure, and "0/N" must never be reportable until the transport
has been cleared. These checks are cheap; run them at the boundary, not after.

USAGE
-----
    from determinex_platform_screen import screen_posix_script, screen_container_argv, \
        screen_env_names, screen_output_text, screen_executable, screen_repo_files

    screen_posix_script(path)          # before `sh script.sh` in a container
    screen_container_argv(argv)        # before docker run/exec
    screen_executable(tar_member_mode) # before relying on +x after transfer

    python scripts/determinex_platform_screen.py [path ...]   # CI sweep
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

__all__ = [
    "PlatformHazard",
    "screen_posix_script",
    "screen_container_argv",
    "screen_env_names",
    "screen_output_text",
    "screen_executable",
    "screen_repo_files",
    "main",
]

# A drive-letter path or a backslash path -- meaningless inside a Linux container.
_WINPATH = re.compile(r"(?:^|[\s\"'=])[A-Za-z]:[\\/]|\\\\[^\\]|(?<![:\w])\\[A-Za-z]")
# Git LFS pointer files masquerade as content: small text where a binary is expected.
_LFS_POINTER = b"version https://git-lfs.github.com/spec/"
# Names Windows already owns; exporting these silently rewrites something else.
_RESERVED_ENV = {
    "TEMP",
    "TMP",
    "PATH",
    "COMSPEC",
    "SYSTEMROOT",
    "WINDIR",
    "PROGRAMFILES",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "OS",
    "PATHEXT",
}


class PlatformHazard(RuntimeError):
    """A cross-platform hazard that would produce a wrong answer rather than an error."""


def screen_posix_script(path: str | Path, *, text: str | None = None) -> None:
    """A script about to be executed by /bin/sh must have LF endings and no BOM.

    CRLF costs you `Syntax error: word unexpected (expecting "do")` on the first loop --
    which reads as a broken script, not as a line-ending problem.
    """
    p = Path(path)
    raw = p.read_bytes() if text is None else text.encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PlatformHazard(f"{p.name}: UTF-8 BOM -- /bin/sh will fail on the shebang line")
    if b"\r\n" in raw:
        n = raw.count(b"\r\n")
        raise PlatformHazard(
            f"{p.name}: {n} CRLF line ending(s) in a script destined for /bin/sh. "
            f"Write it with newline='\\n'."
        )


def screen_container_argv(argv: list[str]) -> None:
    """No host path may reach a container command line."""
    skip_next = False
    for a in argv:
        if skip_next:
            skip_next = False  # this is a bind-mount SPEC; a host path here is correct
            continue
        if a in ("-v", "--volume", "--mount"):
            skip_next = True  # the host path is the NEXT argument, not this one
            continue
        if a.startswith(("--volume=", "--mount=")):
            continue
        if _WINPATH.search(a):
            raise PlatformHazard(
                f"host path {a!r} in a container argv -- the container has no such path. "
                f"If Git Bash mangled it, set MSYS_NO_PATHCONV=1."
            )


def screen_env_names(names) -> None:
    """Refuse env var names the host OS already owns."""
    bad = sorted({n.upper() for n in names} & _RESERVED_ENV)
    if bad and os.name == "nt":
        raise PlatformHazard(
            f"env name(s) {bad} are reserved by Windows; setting them silently changes "
            f"something else (TEMP=0.6 became 'C:\\...\\0.6'). Prefix them, e.g. SAMPLE_TEMP."
        )


def screen_output_text(text: str, *, where: str = "output") -> None:
    """Captured output containing U+FFFD was decoded with the wrong codec."""
    if "\ufffd" in text:
        raise PlatformHazard(
            f"{where}: contains U+FFFD replacement characters -- decoded with the wrong "
            f"codec. Capture with encoding='utf-8' (PYTHONUTF8=1 / PYTHONIOENCODING=utf-8)."
        )


def screen_executable(mode: int, name: str) -> None:
    """Something that must run has to carry +x after transfer.

    Windows has no execute bit, so a tar built there arrives 0644 and every invocation
    fails with 'permission denied' -- which looks exactly like a program that produced no
    output. Measured 2026-07-31: 0/234 probes, mistaken for total model failure.
    """
    if not mode & 0o111:
        raise PlatformHazard(
            f"{name}: mode {mode:o} has no execute bit after transfer. Set it explicitly "
            f"(tar filter / chmod 0755) or every run fails as 'permission denied'."
        )


def screen_repo_files(paths) -> list[str]:
    """Report Git LFS pointers being read as if they were real content."""
    bad = []
    for p in paths:
        try:
            head = Path(p).open("rb").read(120)
        except OSError:
            continue
        if head.startswith(_LFS_POINTER):
            bad.append(str(p))
    return bad


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    roots = [Path(a) for a in args] or [Path("scripts"), Path("docker")]
    problems: list[str] = []
    checked = 0
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*.sh") if p.is_file()]
        for f in files:
            checked += 1
            try:
                screen_posix_script(f)
            except PlatformHazard as e:
                problems.append(str(e))
    lfs = screen_repo_files(
        [p for r in roots if r.exists() and r.is_dir() for p in r.rglob("*") if p.is_file()][:4000]
    )
    for p in lfs:
        problems.append(f"{p}: Git LFS pointer, not content")
    print(f"platform screen: {checked} script(s) checked")
    for p in problems:
        print(f"  HAZARD: {p}")
    if problems:
        print(f"{len(problems)} hazard(s)")
        return 1
    print("clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
