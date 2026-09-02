#!/usr/bin/env python3
"""Determinex PB eval-readiness gate — the prelook for NATIVE tools.

The reimpl prelook (determinex_local_oracle) runs a Python reimpl vs tests locally.
But native tools (board_cache: fselect/onefetch/sqlite/...) ship as tarballs with
their own compile.sh — and had NO local gate, so every structural/build problem
could only surface via a 15-minute Hetzner eval. That is the bug this fixes:
nothing gets shipped to a Hetzner eval until it passes here.

Two layers, cheapest first:
  1. STATIC (instant, no Docker): is the tarball FLAT (compile.sh at the root, not
     nested under a single slug dir)? does compile.sh emit the `executable` entry?
     -- the nested-dir bug that wasted 4 evals is caught here in milliseconds.
  2. BUILD DRY-RUN (--build, local Docker): run compile.sh in a Linux container and
     confirm it produces the binary + ./executable. Build errors are captured
     LOCALLY -- no Hetzner round-trip to discover a cargo failure.

Also exposes the STALE-IMAGE guard: after any tarball change you MUST drop the
cached `programbench-compiled/<slug>:determinex-cached` image or the eval reuses the
old (broken) build -- failure mode #1.

Usage:
  python scripts/determinex_pb_eval_ready.py <tarball>                 # static gate
  python scripts/determinex_pb_eval_ready.py <tarball> --repack        # auto-flatten nested
  python scripts/determinex_pb_eval_ready.py <tarball> --build [--image rust:latest]
  python scripts/determinex_pb_eval_ready.py --scan <pilot_root> [--repack]
"""

from __future__ import annotations

import argparse
import subprocess
import tarfile
import tempfile
from pathlib import Path

READY = "READY"
NOT_READY = "NOT_READY"


def inspect(tar_path: Path) -> dict:
    """Static, instant structure check. No Docker."""
    out = {
        "tarball": str(tar_path),
        "verdict": NOT_READY,
        "reasons": [],
        "flat": False,
        "compile_at_root": False,
        "emits_executable": False,
        "crlf": False,
        "dot_slash": False,
        "top_entries": [],
    }
    try:
        with tarfile.open(tar_path, "r:gz") as t:
            names = t.getnames()
            # compile.sh content if present
            compile_member = None
            for n in names:
                base = n.lstrip("./")
                if base == "compile.sh":
                    compile_member = n
            top = set()
            for n in names:
                p = n.lstrip("./").split("/")[0]
                if p:
                    top.add(p)
            out["top_entries"] = sorted(top)[:12]
            # ./prefix: PB harness runs `chmod +x ./compile.sh` -- entries must start
            # with "./" or the chmod fails (chmod: cannot access './compile.sh').
            out["dot_slash"] = any(n.startswith("./") for n in names)
            # FLAT = compile.sh sits at the archive root (./compile.sh or compile.sh)
            out["compile_at_root"] = compile_member is not None
            # nested = a single top-level dir that contains everything (no root compile.sh)
            nested = (
                compile_member is None
                and len(top) == 1
                and any(n.lstrip("./").startswith(next(iter(top)) + "/compile.sh") for n in names)
            )
            out["flat"] = out["compile_at_root"] and not nested
            if compile_member:
                f = t.extractfile(compile_member)
                body = f.read().decode("utf-8", "replace") if f else ""
                out["emits_executable"] = "executable" in body
            if nested:
                out["reasons"].append(
                    f"NESTED: compile.sh is under top dir '{next(iter(top))}/' not at root "
                    "-- harness won't find it -> all tests not_run. Repack flat."
                )
            elif not out["compile_at_root"]:
                out["reasons"].append("no compile.sh at archive root")
            if out["compile_at_root"] and not out["emits_executable"]:
                out["reasons"].append("compile.sh does not mention 'executable' entry point")
            if out["flat"] and not out["dot_slash"]:
                out["reasons"].append(
                    "MISSING ./ PREFIX: entries like 'compile.sh' instead of './compile.sh' "
                    "-- PB harness runs `chmod +x ./compile.sh` which fails. Repack with --repack."
                )
            # CRLF in compile.sh => `set -e\r` is an illegal option => build dies =>
            # all tests not_run. (autocrlf=true on Windows is the usual cause.)
            if compile_member and f:
                if b"\r\n" in body.encode("utf-8", "replace") or "\r" in body:
                    out["crlf"] = True
                    out["reasons"].append(
                        "CRLF line endings in compile.sh -- breaks `set -e` (set: Illegal "
                        "option) -> build fails -> all tests not_run. Normalize to LF."
                    )
    except Exception as e:
        out["reasons"].append(f"cannot read tarball: {e}")
        return out
    if out["flat"] and out["emits_executable"] and not out["crlf"] and out["dot_slash"]:
        out["verdict"] = READY
        out["reasons"].append("static OK (flat+./prefix, compile.sh at root, emits executable, LF)")
    return out


def _normalize_lf(root: Path):
    """Strip CRLF from shell scripts so `set -e` doesn't choke on \\r."""
    for p in root.rglob("*.sh"):
        try:
            b = p.read_bytes()
            if b"\r" in b:
                p.write_bytes(b.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        except Exception:
            pass


# pytest addopt -> the pip package that provides it. A pytest.ini that sets one of
# these without the plugin installed makes pytest abort -> 0 collected -> all
# not_run (the silent-fail class). The upfront fix: ensure compile.sh installs it.
_PLUGIN_FOR_OPT = {
    "--timeout": "pytest-timeout",
    "--cov": "pytest-cov",
    "--forked": "pytest-forked",
    "--numprocesses": "pytest-xdist",
    "-n": "pytest-xdist",
    "--randomly": "pytest-randomly",
    "--asyncio-mode": "pytest-asyncio",
    "--benchmark": "pytest-benchmark",
    "--reruns": "pytest-rerunfailures",
}


def _ensure_plugins(base: Path) -> list[str]:
    """If compile.sh's pytest.ini sets addopts requiring a plugin, inject the
    matching `pip install` into compile.sh (network is available at build time).
    Returns the list of plugins ensured."""
    csh = base / "compile.sh"
    if not csh.exists():
        return []
    body = csh.read_text(encoding="utf-8", errors="replace")
    need = set()
    for opt, pkg in _PLUGIN_FOR_OPT.items():
        if (
            opt in body
            and f"install -q {pkg}" not in body
            and f"install {pkg}" not in body
            and f"pip3 install -q {pkg}" not in body
        ):
            need.add(pkg)
    if not need:
        return []
    inject = "".join(
        f"pip3 install -q {pkg} 2>/dev/null || pip install -q {pkg} 2>/dev/null || true\n"
        for pkg in sorted(need)
    )
    # insert right after the shebang so the plugin exists before any pytest runs
    lines = body.splitlines(keepends=True)
    at = 1 if lines and lines[0].startswith("#!") else 0
    lines.insert(
        at, "# determinex upfront: ensure pytest plugins its pytest.ini requires\n" + inject
    )
    csh.write_text("".join(lines), encoding="utf-8", newline="\n")
    return sorted(need)


def repack_flat(tar_path: Path) -> bool:
    """Flatten a single-top-dir nesting AND/OR normalize CRLF shell scripts to LF,
    AND ensure required pytest plugins are installed by compile.sh, then repack.
    Returns True if it rewrote the tarball."""
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(tar_path, "r:gz") as t:
            names = [n.lstrip("./") for n in t.getnames() if n.strip("./")]
            tops = {n.split("/")[0] for n in names}
            t.extractall(td)
        base = Path(td)
        # nested? descend into the single top dir holding compile.sh
        if len(tops) == 1 and (base / next(iter(tops)) / "compile.sh").exists():
            base = base / next(iter(tops))
        if not (base / "compile.sh").exists():
            return False
        _normalize_lf(base)
        _ensure_plugins(base)
        # CRITICAL: PB harness does `docker exec tar -xzf - -C /workspace/` which
        # requires the `./` prefix on every entry so tar places them at /workspace/
        # not relative to the tar process cwd. arcname MUST start with `./`.
        with tarfile.open(tar_path, "w:gz") as t:
            for child in sorted(base.iterdir()):
                t.add(child, arcname="./" + child.name)
    return True


def build_dryrun(tar_path: Path, image: str) -> dict:
    """Run compile.sh in a local Docker container; confirm it builds `executable`.
    Diagnoses build failures LOCALLY instead of via a Hetzner eval."""
    res = {"built": False, "log_tail": "", "image": image}
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(tar_path, "r:gz") as t:
            t.extractall(td)
        ws = Path(td)
        # handle a flat or single-nested layout
        if not (ws / "compile.sh").exists():
            subs = [d for d in ws.iterdir() if (d / "compile.sh").exists()]
            if subs:
                ws = subs[0]
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ws}:/workspace",
            "-w",
            "/workspace",
            image,
            "sh",
            "-c",
            "sh compile.sh >build_dryrun.log 2>&1; echo RC=$?; "
            "ls -la executable 2>&1; tail -30 build_dryrun.log",
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            out = p.stdout + p.stderr
            res["log_tail"] = out[-1500:]
            res["built"] = "executable" in out and "RC=0" in out
        except Exception as e:
            res["log_tail"] = f"docker run failed: {e}"
    return res


def stale_image_hint(tar_path: Path) -> str:
    slug = tar_path.parent.name if tar_path.name == "submission.tar.gz" else tar_path.stem
    return (
        f"docker rmi -f programbench-compiled/{slug}:determinex-cached  "
        "# MUST run before re-eval after any tarball change (failure mode #1)"
    )


def _report(r: dict):
    mark = "OK " if r["verdict"] == READY else "XX "
    print(
        f"  [{mark}] {Path(r['tarball']).name}  flat={r['flat']} dot_slash={r['dot_slash']} "
        f"exec={r['emits_executable']} top={r['top_entries'][:3]}"
    )
    for reason in r["reasons"]:
        print(f"         - {reason}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Determinex PB eval-readiness gate (native-tool prelook)"
    )
    ap.add_argument("tarball", nargs="?", type=Path)
    ap.add_argument("--scan", type=Path, help="pilot root: check every */submission.tar.gz")
    ap.add_argument("--repack", action="store_true", help="auto-flatten nested tarballs")
    ap.add_argument("--build", action="store_true", help="local Docker build dry-run")
    ap.add_argument("--image", default="rust:latest", help="image for --build dry-run")
    a = ap.parse_args(argv)

    targets = []
    if a.scan:
        targets = sorted(a.scan.glob("*/submission.tar.gz")) + sorted(a.scan.glob("*.tar.gz"))
    elif a.tarball:
        targets = [a.tarball]
    else:
        ap.error("give a <tarball> or --scan <dir>")

    not_ready = 0
    for tb in targets:
        r = inspect(tb)
        if (
            r["verdict"] != READY
            and a.repack
            and (not r["flat"] or r["crlf"] or not r["dot_slash"])
        ):
            if repack_flat(tb):
                print(f"  repacked flat: {tb.name}")
                r = inspect(tb)
        _report(r)
        if r["verdict"] != READY:
            not_ready += 1
        if a.build and r["verdict"] == READY:
            b = build_dryrun(tb, a.image)
            print(
                f"         build dry-run: {'BUILT' if b['built'] else 'BUILD-FAILED'} ({a.image})"
            )
            if not b["built"]:
                for line in b["log_tail"].splitlines()[-8:]:
                    print(f"           {line}")
        if r["verdict"] != READY or (a.build):
            print(f"         guard: {stale_image_hint(tb)}")
    print(
        f"\n{len(targets) - not_ready}/{len(targets)} eval-ready"
        + (f"  ({not_ready} NOT ready)" if not_ready else "")
    )
    return 1 if not_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
