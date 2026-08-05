#!/usr/bin/env python3
"""Determinex Crucible -- the local containerized proving chamber.

A benchmark-agnostic engine that BUILDS a program and runs its REAL test suite
inside a container under reference conditions, returning deterministic per-test
verdicts. It is the local replica of any remote eval harness: same inputs (a
workspace with a build step + a shipped test suite + a base image), same per-test
truth (passed / failure / error / skipped / not_run) -- but local, fast, and
free, so the per-test failures that are the actual path to 100% are visible
without a remote round-trip.

It is deliberately NOT tied to any single benchmark. ProgramBench is one input
shape; SWE-bench, a greenfield idea, or a plain repo are others. The Crucible
only needs: a workdir, an image, a build command, a test command, and where the
JUnit lands. It composes with:
  - determinex_pb_eval_ready  (gate: flatten/LF/structure BEFORE the crucible runs)
  - determinex_oracle         (reuses Failure / OracleResult / JUnit parsing)
  - determinex_eval_report    (the result is the same shape the readers consume)

Containerized execution is the approved sandbox per the security posture
(workspace-bounded volume, no host mutation); network is left to the image's
build needs and can be denied with --no-network.

Usage:
  python scripts/determinex_crucible.py <workdir> --image rust:latest \
      --build "sh compile.sh" --test "python3 -m pytest -q eval/tests --junitxml=cj.xml" \
      --junit cj.xml
  python scripts/determinex_crucible.py <workdir> --image <img> --build-only
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_oracle import _junit_failures  # noqa: E402  (reuse JUnit parser)

try:  # reuse the existing compile.sh legitimacy guard -- do NOT reimplement it
    from pb_override_scan import classify_compile_sh
except Exception:  # pragma: no cover
    classify_compile_sh = None

# build-log markers: did compile.sh actually compile, or fall back to a bundled binary?
_FRESH_MARKERS = (
    "Compiling ",
    "Finished release",
    "Finished `release`",
    "go build",
    "gcc ",
    "cc -",
    "rustc ",
    "cargo build",
)
_BUNDLED_MARKERS = (
    "using bundled binary",
    "bundled binary if present",
    "using bundled elf",
    "source build absent",
    "installed from bundled",
    "task-image elf",
    "falling back",
    "pre-built",
    "prebuilt binary",
)

# A real from-source build is language-general; cargo emits "Compiling/Finished" but
# go/cc/make/etc. are silent on success. So the robust fresh signal is: the compile.sh
# actually INVOKES a compiler AND the build succeeded AND no bundled-fallback was emitted.
import re as _re

_REAL_BUILD_RE = _re.compile(
    r"\b(go\s+build|go\s+install|cargo\s+build|cargo\s+install|\bmake\b|cmake|"
    r"\bcc\b|\bgcc\b|\bg\+\+\b|\bclang\b|rustc|\btsc\b|\blein\b|mvn|gradle|"
    r"npm\s+(run\s+)?build|yarn\s+build|python[0-9.]*\s+[^\n]*setup\.py|pip\s+install\s+\.|"
    r"meson|ninja|cabal\s+build|dotnet\s+build|swift\s+build|zig\s+build)\b"
)


def _has_real_build_cmd(text: str) -> bool:
    return bool(_REAL_BUILD_RE.search(text or ""))


@dataclass
class CrucibleResult:
    image: str
    build_ok: bool
    build_log_tail: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    not_run: int = 0
    failures: list = field(default_factory=list)  # [{test_id,name,text,status}]
    note: str = ""
    fresh_build: bool = False  # actually compiled from source this run
    used_bundled: bool = False  # fell back to a prebuilt/bundled binary (NOT proper)
    compile_legitimacy: str = ""  # pb_override_scan verdict on compile.sh (GREEN/RED/...)
    collect_ok: bool = True  # pytest collected tests without error
    collect_error: str = ""  # the silent-fail reason (missing plugin / import / etc.)

    @property
    def score(self):
        return self.passed / self.total if self.total else 0.0

    def summary(self):
        if not self.build_ok:
            return f"BUILD-FAILED in {self.image} -- {self.note}"
        if not self.collect_ok:
            return f"COLLECT-FAIL -- {self.collect_error}"
        prov = (
            "from-source"
            if self.fresh_build
            else ("BUNDLED-FALLBACK(not-proper)" if self.used_bundled else "build-unknown")
        )
        return (
            f"{self.passed}/{self.total} ({100 * self.score:.1f}%) "
            f"fail={self.failed} err={self.errored} skip={self.skipped} "
            f"not_run={self.not_run} [{prov}]"
        )


def _docker_ok() -> bool:
    return shutil.which("docker") is not None


def resolve_base_image(slug: str) -> str:
    """slug -> the REFERENCE base image PB itself builds/tests in, so the Crucible
    compiles from source with full parity (right toolchain + pinned deps), not a
    generic toolchain image. Mirrors programbench.constants.image_name_from_instance_id:
    `programbench/{slug with '__'->'_1776_'}:task`. Docker auto-pulls if absent.
    Closes the documented gap (proper-method-loop step 4): generic rust:latest can't
    build many tools from source (fselect -> BUNDLED-FALLBACK); the :task image can.
    Override with PROGRAMBENCH_DOCKER_ORG / PROGRAMBENCH_IMAGE_TAG if needed."""
    org = os.environ.get("PROGRAMBENCH_DOCKER_ORG", "programbench")
    tag = os.environ.get("PROGRAMBENCH_IMAGE_TAG", "task")
    return f"{org}/{slug.replace('__', '_1776_')}:{tag}"


# pytest addopts that REQUIRE a plugin -> the pip package that provides it.
# A missing one makes pytest abort at startup ("unrecognized arguments: --X")
# => zero tests collected => all not_run => silent fail. This map names the fix.
_PLUGIN_FOR_OPT = {
    "--timeout": "pytest-timeout",
    "--cov": "pytest-cov",
    "--forked": "pytest-forked",
    "--numprocesses": "pytest-xdist",
    "-n": "pytest-xdist",
    "--randomly": "pytest-randomly",
    "--asyncio": "pytest-asyncio",
    "--benchmark": "pytest-benchmark",
    "--hypothesis": "hypothesis",
    "--rerun": "pytest-rerunfailures",
}


def diagnose_collection(text: str) -> str:
    """Extract the silent-fail reason from a pytest --collect-only output.
    Returns '' if collection looked fine, else a human + fix string."""
    import re

    m = re.search(r"unrecognized arguments?:\s*(\S+)", text)
    if m:
        opt = m.group(1).split("=")[0]
        pkg = _PLUGIN_FOR_OPT.get(opt, _PLUGIN_FOR_OPT.get(opt.rstrip("0123456789"), None))
        fix = f" -> pip install {pkg}" if pkg else " -> install the providing plugin"
        return f"MISSING PYTEST PLUGIN for '{opt}' (pytest aborts -> 0 collected){fix}"
    for pat, label in (
        (r"ModuleNotFoundError: No module named ['\"]?([\w.]+)", "MISSING MODULE"),
        (r"ImportError: (.+)", "IMPORT ERROR"),
        (r"(\d+) errors? during collection", "COLLECTION ERROR"),
        (r"fixture '(\w+)' not found", "MISSING FIXTURE"),
    ):
        mm = re.search(pat, text)
        if mm:
            return f"{label}: {mm.group(1) if mm.groups() else mm.group(0)}"
    if re.search(r"no tests ran|collected 0 items", text):
        return "ZERO TESTS COLLECTED (empty suite or a collection guard hid them)"
    return ""


def _count_junit(xml_path: Path):
    """Return (total, passed, failed, errored, skipped) from a JUnit XML."""
    import xml.etree.ElementTree as ET

    total = passed = failed = errored = skipped = 0
    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:
        return 0, 0, 0, 0, 0
    for tc in root.iter("testcase"):
        total += 1
        if tc.find("failure") is not None:
            failed += 1
        elif tc.find("error") is not None:
            errored += 1
        elif tc.find("skipped") is not None:
            skipped += 1
        else:
            passed += 1
    return total, passed, failed, errored, skipped


def run(
    workdir: Path,
    image: str,
    build_cmd: str,
    test_cmd: str | None,
    junit_rel: str = "crucible_junit.xml",
    timeout: int = 1800,
    no_network: bool = False,
    expected_total: int | None = None,
    require_fresh: bool = False,
    collect_check: bool = False,
) -> CrucibleResult:
    """Build (and optionally test) a workspace inside `image`. Per-test truth.
    require_fresh=True rejects a build that fell back to a bundled/prebuilt binary
    (the proper way is a real from-source compile -- bundled binaries have unclear
    provenance and are not reproducible)."""
    if not _docker_ok():
        return CrucibleResult(image=image, build_ok=False, note="docker not available on host")
    # pre-build legitimacy guard on compile.sh (reuse pb_override_scan, no reimpl)
    legit = ""
    csh = workdir / "compile.sh"
    if classify_compile_sh and csh.exists():
        verdict, reasons = classify_compile_sh(csh.read_text(encoding="utf-8", errors="replace"))
        legit = verdict
        if verdict == "RED":
            return CrucibleResult(
                image=image,
                build_ok=False,
                compile_legitimacy=verdict,
                note=f"compile.sh RED (cheat patterns): {reasons[:2]}",
            )
    # derive the collection path from the test command (default: discover from cwd)
    collect_path = ""
    if test_cmd:
        for tok in test_cmd.split():
            if "/" in tok and not tok.startswith("-"):
                collect_path = tok
                break
    # script run inside the container: build, then a COLLECT-ONLY probe (catches the
    # missing-plugin / import / zero-collected silent-fail class in seconds), then test.
    inner = f"set +e\n{build_cmd}\nBUILD_RC=$?\necho __BUILD_RC=$BUILD_RC\n"
    # Surface build logs that compile.sh conventionally redirects to a file
    # (e.g. `cargo build 2>build.err`) so fresh-vs-bundled detection actually sees
    # the "Compiling.../Finished release" markers instead of an empty stdout.
    inner += (
        "echo __BUILDLOG_START\nfor _bl in build.err build.log cargo.log; do "
        '[ -f "$_bl" ] && cat "$_bl"; done\necho __BUILDLOG_END\n'
    )
    if test_cmd or collect_check:
        inner += (
            f"echo __COLLECT_START\npython3 -m pytest --collect-only -q {collect_path} "
            f"2>&1\necho __COLLECT_RC=$?\necho __COLLECT_END\n"
        )
    if test_cmd and not collect_check:
        inner += f"{test_cmd}\necho __TEST_RC=$?\n"
    net = ["--network", "none"] if no_network else []
    cmd = [
        "docker",
        "run",
        "--rm",
        *net,
        "-v",
        f"{workdir}:/workspace",
        "-w",
        "/workspace",
        image,
        "sh",
        "-c",
        inner,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return CrucibleResult(image=image, build_ok=False, note="timeout")
    except Exception as e:
        return CrucibleResult(image=image, build_ok=False, note=f"docker error: {e}")

    out = p.stdout + "\n" + p.stderr
    build_ok = "__BUILD_RC=0" in out
    res = CrucibleResult(
        image=image,
        build_ok=build_ok,
        compile_legitimacy=legit,
        build_log_tail=out[-1500:] if not build_ok else "",
    )
    # provenance: did it actually compile from source, or fall back to a bundled binary?
    # FRESH = build succeeded AND no bundled-fallback message AND (explicit compile
    # output OR compile.sh genuinely invokes a compiler). The compile-cmd check makes
    # this language-general: cargo prints "Compiling/Finished", but go/cc/make are
    # silent on success, so marker-only detection wrongly rejected real Go/C builds.
    low = out.lower()
    res.used_bundled = any(m in low for m in _BUNDLED_MARKERS)
    csh_text = csh.read_text(encoding="utf-8", errors="replace") if csh.exists() else ""
    res.fresh_build = (
        build_ok
        and not res.used_bundled
        and (any(m in out for m in _FRESH_MARKERS) or _has_real_build_cmd(csh_text))
    )
    if not build_ok:
        res.note = "build step returned non-zero"
        return res
    if require_fresh and not res.fresh_build:
        res.build_ok = False
        res.note = (
            "NOT a from-source build (bundled-binary fallback or no compile "
            "evidence) -- refusing per require_fresh. Provide deps/reference image."
        )
        return res

    # COLLECTION PRELOOK: did pytest even collect? (catches the missing-plugin /
    # import / zero-collected silent-fail class that otherwise shows as all-not_run)
    if "__COLLECT_START" in out:
        seg = out.split("__COLLECT_START", 1)[1].split("__COLLECT_END", 1)[0]
        res.collect_error = diagnose_collection(seg)
        res.collect_ok = not res.collect_error
        if collect_check:  # fast prelook mode: report collection health, skip full suite
            res.note = (
                f"COLLECT-FAIL: {res.collect_error}"
                if res.collect_error
                else "collect-only OK (suite collects cleanly)"
            )
            return res
        if not res.collect_ok:  # full run, but collection is broken -> surface it now
            res.note = f"COLLECTION BROKEN (would silently 0/N not_run): {res.collect_error}"
            return res

    junit = workdir / junit_rel
    if test_cmd and junit.exists():
        res.failures = [asdict(f) for f in _junit_failures(junit)]
        t, pa, fa, er, sk = _count_junit(junit)
        res.total, res.passed, res.failed, res.errored, res.skipped = t, pa, fa, er, sk
        # not_run = tests known to the suite (expected_total) but absent from JUnit
        if expected_total and expected_total > t:
            res.not_run = expected_total - t
            res.total = expected_total
    elif test_cmd:
        res.note = "tests ran but no JUnit produced (check --junit path / test cmd)"
    else:
        res.note = "build-only (no test command)"
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Determinex Crucible -- local containerized proving harness"
    )
    ap.add_argument(
        "workdir", type=Path, help="flat, eval-ready workspace (run the eval-ready gate first)"
    )
    ap.add_argument(
        "--slug",
        default=None,
        help="PB tool slug (author__tool.sha); auto-resolves the REFERENCE base "
        "image (programbench/<slug>:task) for build parity. Overrides --image.",
    )
    ap.add_argument(
        "--image", default=None, help="container image (use the REFERENCE base image for parity)"
    )
    ap.add_argument("--build", default="sh compile.sh", help="build command inside the container")
    ap.add_argument("--test", default=None, help="test command (omit for --build-only)")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--junit", default="crucible_junit.xml", help="JUnit path relative to workdir")
    ap.add_argument(
        "--expected-total", type=int, default=None, help="suite size, to compute not_run"
    )
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument(
        "--require-fresh",
        action="store_true",
        help="reject a bundled-binary fallback; demand a real from-source compile",
    )
    ap.add_argument(
        "--collect-check",
        action="store_true",
        help="fast prelook: build + pytest --collect-only only (catch missing-plugin / "
        "import / zero-collected silent-fail without running the full suite)",
    )
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    image = a.image or (resolve_base_image(a.slug) if a.slug else None)
    if not image:
        ap.error("need --slug (auto-resolves the reference image) or --image")
    test_cmd = None if a.build_only else a.test
    r = run(
        a.workdir,
        image,
        a.build,
        test_cmd,
        a.junit,
        a.timeout,
        a.no_network,
        a.expected_total,
        a.require_fresh,
        a.collect_check,
    )
    if a.json:
        print(json.dumps(asdict(r), indent=2))
    else:
        print(f"CRUCIBLE [{a.workdir.name}] {r.summary()}")
        if not r.build_ok and r.build_log_tail:
            for line in r.build_log_tail.splitlines()[-10:]:
                print(f"  {line}")
        for f in r.failures[:15]:
            print(f"  FAIL {f['name']}: {f['text'][:90].strip()}")
    return 0 if (r.build_ok and r.failed == 0 and r.errored == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
