#!/usr/bin/env python3
"""
Determinex ProgramBench Probe

Primary path: run the actual ProgramBench pytest test suite (from blob cache)
against our compiled binary inside the task container. Gives exact failures
with test source code so Claude can fix precisely.

Fallback path: differential probe vs reference binary (for tasks without blobs).

Imported by determinex_programbench_agent.py for the feedback loop.
"""

import json
import os
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

STAGING_ROOT = Path("T:/determinex-programbench/_probe_staging")
DOCKER_ORG = "programbench"
MODEL = "claude-sonnet-4-6"

# HF cache snapshot — populated when eval runs
_HF_SNAPSHOT_ROOT = (
    Path.home() / ".cache/huggingface/hub/datasets--programbench--ProgramBench-Tests/snapshots"
)


# ---------------------------------------------------------------------------
# Blob cache helpers
# ---------------------------------------------------------------------------


def _find_blob_dir(instance_id: str) -> Path | None:
    """Return the local HF snapshot dir for this instance, or None."""
    env_override = os.environ.get("PROGRAMBENCH_BLOB_DIR", "")
    if env_override:
        p = Path(env_override) / instance_id
        return p if p.exists() else None
    if not _HF_SNAPSHOT_ROOT.exists():
        return None
    # Pick the first (newest) snapshot that has this instance
    for snap in sorted(_HF_SNAPSHOT_ROOT.iterdir(), reverse=True):
        p = snap / instance_id
        if p.exists():
            return p
    return None


def get_test_branches(instance_id: str) -> list[tuple[str, Path]]:
    """
    Return [(branch_sha, tar_path), ...] for non-ignored test branches,
    ordered by test count descending so largest branches run first.
    Returns [] if blob data not available.
    """
    blob_dir = _find_blob_dir(instance_id)
    if not blob_dir:
        return []

    tests_json = (
        Path(__file__).parent.parent
        / "T:/Dev/ProgramBench/src/programbench/data/tasks"
        / instance_id
        / "tests.json"
    )
    # Also try relative to ProgramBench repo
    pb_tasks = Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
    if (pb_tasks / instance_id / "tests.json").exists():
        tests_json = pb_tasks / instance_id / "tests.json"

    branches: list[tuple[int, str, Path]] = []
    if tests_json.exists():
        try:
            meta = json.loads(tests_json.read_text(encoding="utf-8"))
            for sha, info in meta.get("branches", {}).items():
                if info.get("ignored", False):
                    continue
                tar = blob_dir / "tests" / f"{sha}.tar.gz"
                if tar.exists():
                    n = len(info.get("tests", []))
                    branches.append((n, sha, tar))
        except Exception:
            pass

    if not branches:
        # Fallback: just use all tars present
        tests_dir = blob_dir / "tests"
        if tests_dir.exists():
            for tar in sorted(tests_dir.glob("*.tar.gz")):
                branches.append((0, tar.stem, tar))

    branches.sort(reverse=True)
    return [(sha, tar) for _, sha, tar in branches]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _image_name(instance_id: str) -> str:
    return f"{DOCKER_ORG}/{instance_id.replace('__', '_1776_')}:task_cleanroom"


def _to_docker_path(p: Path) -> str:
    s = str(p).replace("\\", "/")
    if len(s) > 1 and s[1] == ":":
        return "/" + s[0].lower() + s[2:]
    return s


def _bad_probe(cmd: str) -> bool:
    if "\n" in cmd or "\r" in cmd:
        return True
    if re.search(r"(printf|echo)['\"]", cmd):
        return True
    return False


# ---------------------------------------------------------------------------
# Primary probe: run the actual pytest suite
# ---------------------------------------------------------------------------


def run_pytest_probe(
    instance_id: str,
    compile_sh: str,
    files: dict[str, str],
    timeout: int = 600,
    max_branches: int = 99,
) -> tuple[list[dict], str, int, int]:
    """
    Compile our code then run the actual ProgramBench pytest test suite.

    Returns (failures, raw_output, passed, total)
    failures = list of {"test": str, "message": str, "source": str}

    Falls back to ("COMPILE_FAILED", ...) signal if compile fails.
    Falls back to ([], "NO_BLOBS", 0, 0) if no blob data available.
    """
    branches = get_test_branches(instance_id)
    if not branches:
        return [], "NO_BLOBS", 0, 0

    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    staging = STAGING_ROOT / str(uuid.uuid4())
    staging.mkdir()

    try:
        # Write our source files
        (staging / "compile.sh").write_text(
            compile_sh.replace("\r\n", "\n"), newline="\n", encoding="utf-8"
        )
        for fname, content in files.items():
            fpath = staging / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content.replace("\r\n", "\n"), newline="\n", encoding="utf-8")

        # Build probe script: compile once, then run each branch
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "cp -r /mnt/src/. /workspace/",
            "cd /workspace",
            "chmod +x compile.sh",
            "./compile.sh >/tmp/compile_out.txt 2>&1 || {",
            "  echo 'PROBE_COMPILE_FAILED'",
            "  cat /tmp/compile_out.txt",
            "  exit 1",
            "}",
            "chmod +x /workspace/executable 2>/dev/null || true",
            # Back up the executable so tar extractions can't clobber it
            "cp /workspace/executable /tmp/_executable_backup 2>/dev/null || true",
            "set +e",
        ]

        blob_mounts: list[tuple[str, str]] = []  # (host_docker_path, container_path)
        for i, (sha, tar_path) in enumerate(branches[:max_branches]):
            cname = f"/mnt/blobs/branch_{i}.tar.gz"
            blob_mounts.append((_to_docker_path(tar_path), cname))
            script_lines += [
                "",
                f"echo 'BRANCH_START:{sha}'",
                "cd /workspace",
                "rm -rf eval/ executable",  # nuke both — tar contains reference binary
                f"tar -xzf {cname} -C /workspace/ 2>/dev/null || true",
                # Branch tarballs may ship 'executable' as a symlink to 'executable_cov'
                # (a coverage-instrumented reference binary). A plain `cp` follows the
                # symlink and tries to overwrite the read-only Rust ELF — silently failing
                # under set+e and leaving the reference binary in place.  Remove the symlink
                # first so our backup is installed as a fresh regular file.
                "rm -f /workspace/executable",
                "if [ -f /tmp/_executable_backup ]; then",
                "  cp /tmp/_executable_backup /workspace/executable",
                "else",
                f"  (cd /workspace && bash compile.sh >/tmp/recompile_{sha}.txt 2>&1)",
                "fi",
                "chmod +x /workspace/executable 2>/dev/null || true",
                "if [ ! -f /workspace/executable ]; then",
                f"  echo 'BRANCH_NO_EXECUTABLE:{sha}'",
                f"  cat /tmp/recompile_{sha}.txt 2>/dev/null | tail -20",
                "fi",
                # Use eval/run.sh if present (mirrors official ProgramBench eval exactly).
                # Fallback to direct pytest for branches that pre-date run.sh convention.
                "if [ -f /workspace/eval/run.sh ]; then",
                "  cd /workspace",
                "  chmod +x eval/run.sh",
                f"  bash eval/run.sh --junitxml=/tmp/results_{sha}.xml 2>&1 | tail -80",
                "  # run.sh may write results.xml inside eval/ — check both locations",
                f"  if [ ! -f /tmp/results_{sha}.xml ] && [ -f /workspace/eval/results.xml ]; then",
                f"    cp /workspace/eval/results.xml /tmp/results_{sha}.xml",
                "  fi",
                "else",
                "  PYTHONPATH=/workspace/eval/tests:$PYTHONPATH python3 -m pytest eval/ --tb=short -q --no-header -p no:warnings \\",
                f"    --junit-xml=/tmp/results_{sha}.xml 2>&1 | tail -80",
                "fi",
                f"echo 'JUNIT_START:{sha}'",
                f"cat /tmp/results_{sha}.xml 2>/dev/null || echo '<testsuite/>'",
                f"echo 'JUNIT_END:{sha}'",
                f"echo 'BRANCH_END:{sha}'",
            ]

        script_lines.append("echo 'PROBE_ALL_DONE'")

        probe_sh = "\n".join(script_lines) + "\n"
        (staging / "probe.sh").write_text(
            probe_sh.replace("\r\n", "\n"), newline="\n", encoding="utf-8"
        )

        src_path = _to_docker_path(staging)
        img = _image_name(instance_id)

        # Build docker command with all volume mounts
        cmd = ["docker", "run", "--rm", "-v", f"{src_path}:/mnt/src:ro"]
        for host_p, cname in blob_mounts:
            # strip /mnt/blobs prefix to get container path
            cfile = cname
            cmd += ["-v", f"{host_p}:{cfile}:ro"]
        cmd += [img, "bash", "-c", "bash /mnt/src/probe.sh"]

        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        raw = result.stdout.decode("utf-8", errors="replace") + result.stderr.decode(
            "utf-8", errors="replace"
        )

        if "PROBE_COMPILE_FAILED" in raw:
            compile_err = raw.split("PROBE_COMPILE_FAILED", 1)[1][:2000]
            return [], "COMPILE_FAILED\n" + compile_err, 0, 0

        if "PROBE_ALL_DONE" not in raw:
            # Distinguish: did we start any branches at all?
            started = raw.count("BRANCH_START:")
            ended = raw.count("BRANCH_END:")
            if started > ended:
                hung_branch = re.search(r"BRANCH_START:([0-9a-f]+)", raw.split("BRANCH_END:")[-1])
                hung_sha = hung_branch.group(1) if hung_branch else "unknown"
                signal = (
                    f"BINARY_HUNG: your executable did not exit on branch {hung_sha}. "
                    f"It consumed the full probe timeout. This usually means an infinite loop "
                    f"in one of the modes being tested (check --suggest, --syntax, --syntax-suggest, "
                    f"and --transform modes for non-terminating loops). "
                    f"Started={started} branches, completed={ended}."
                )
            else:
                signal = "PROBE_CRASH: docker container exited before completing all branches."
            return [], signal + "\n" + raw[-500:], 0, 0

        # Parse JUnit XML blocks
        failures, passed, total = _parse_junit_blocks(raw, branches[:max_branches], staging)
        return failures, raw, passed, total

    except subprocess.TimeoutExpired:
        # The entire probe docker run exceeded the timeout ceiling
        return (
            [],
            (
                "BINARY_HUNG: probe hit the hard timeout ceiling — your executable "
                "never terminated during one of the test branches. Check all output "
                "modes for infinite loops, especially --suggest, --syntax-suggest, "
                "and --transform on inputs with backticks or unclosed constructs."
            ),
            0,
            0,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _parse_junit_blocks(
    raw: str,
    branches: list[tuple[str, Path]],
    staging: Path,
) -> tuple[list[dict], int, int]:
    """Parse all JUNIT_START/END blocks from raw output, return (failures, passed, total)."""
    all_failures: list[dict] = []
    total_passed = 0
    total_tests = 0

    # Extract test source snippets from staged tars (already extracted during run)
    # We'll extract inline from the tarballs for lookup
    test_sources: dict[str, str] = {}  # test_id -> source snippet

    for sha, tar_path in branches:
        pattern = rf"JUNIT_START:{sha}\n(.*?)JUNIT_END:{sha}"
        m = re.search(pattern, raw, re.DOTALL)
        if not m:
            continue
        xml_text = m.group(1).strip()

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue

        for tc in root.iter("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            test_id = f"{classname}.{name}" if classname else name
            total_tests += 1

            fail_el = tc.find("failure") or tc.find("error")
            if fail_el is None:
                total_passed += 1
                continue

            message = (fail_el.get("message") or "") + "\n" + (fail_el.text or "")
            message = message.strip()[:600]

            # Try to get source code for this test
            source = test_sources.get(test_id, "")
            if not source:
                source = _extract_test_source(tar_path, test_id)
                test_sources[test_id] = source

            all_failures.append(
                {
                    "test": test_id,
                    "message": message,
                    "source": source,
                    "branch": sha,
                }
            )

    return all_failures, total_passed, total_tests


def _extract_test_source(tar_path: Path, test_id: str) -> str:
    """
    Extract the source of a test function from a branch tarball.
    test_id like 'eval.tests.test_01_basic.test_help_flag'
    """
    try:
        # test_id: eval.tests.test_01_basic.test_help_flag
        parts = test_id.split(".")
        # Find the module part and function name
        # Last part is function name, rest is module path
        func_name = parts[-1].split("[")[0]  # strip parametrize brackets
        module_path = "/".join(parts[:-1]) + ".py"  # eval/tests/test_01_basic.py

        result = subprocess.run(
            ["tar", "-xzOf", str(tar_path), module_path],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""
        src = result.stdout.decode("utf-8", errors="replace")

        # Extract just the function
        lines = src.splitlines()
        start = None
        for i, line in enumerate(lines):
            if re.match(rf"^def {re.escape(func_name)}\s*[\(:]", line):
                start = i
                break
        if start is None:
            return ""

        # Collect function body (until next def/class at same indent or EOF)
        body = [lines[start]]
        for line in lines[start + 1 :]:
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            body.append(line)
            if len(body) > 30:
                break

        return "\n".join(body)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Format failure report for Claude
# ---------------------------------------------------------------------------


def format_failure_report(failures: list[dict], max_failures: int = 12) -> str:
    if not failures:
        return ""

    lines = [
        f"Pytest test failures ({len(failures)} total). "
        f"Your implementation compiles but fails the ACTUAL eval test suite.",
        "",
        "Each failure shows the test function being run and the assertion error.",
        "Fix your implementation so ALL these tests pass.",
        "",
    ]

    for i, f in enumerate(failures[:max_failures]):
        lines.append(f"=== Failure {i + 1}: {f['test']} ===")
        if f.get("source"):
            lines.append("TEST CODE:")
            lines.append(f["source"])
            lines.append("")
        lines.append("FAILURE:")
        lines.append(f["message"][:400])
        lines.append("")

    if len(failures) > max_failures:
        # Show a summary of remaining failure test names
        remaining = failures[max_failures:]
        lines.append(f"... and {len(remaining)} more failures:")
        for f in remaining[:20]:
            lines.append(f"  - {f['test']}")
        lines.append("")

    lines += [
        "Fix your implementation to pass all failing tests.",
        "Pay close attention to: exact output format, exit codes, flag behavior, error messages.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Local syntax pre-check (fast, zero Docker cost)
# ---------------------------------------------------------------------------


def local_syntax_check(compile_sh: str, files: dict[str, str]) -> tuple[bool, str]:
    import sys as _sys
    import tempfile

    errors: list[str] = []

    try:
        r = subprocess.run(
            ["bash", "-n", "-"],
            input=compile_sh.encode("utf-8"),
            capture_output=True,
            timeout=5,
        )
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace")
            if "syntax error" in stderr.lower() and "WSL" not in stderr and "execvpe" not in stderr:
                errors.append("compile.sh bash syntax error:\n" + stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    for fname, content in files.items():
        if not fname.endswith(".py"):
            continue
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8"
            ) as f:
                f.write(content)
                tmp = f.name
            r = subprocess.run(
                [_sys.executable, "-m", "py_compile", tmp],
                capture_output=True,
                timeout=5,
            )
            Path(tmp).unlink(missing_ok=True)
            if r.returncode != 0:
                msg = r.stderr.decode("utf-8", errors="replace").replace(tmp, fname)
                errors.append(f"{fname} syntax error:\n{msg}")
        except subprocess.TimeoutExpired:
            pass

    if errors:
        return False, "\n\n".join(errors)
    return True, ""


# ---------------------------------------------------------------------------
# Fallback: differential probe vs reference binary (no blob data)
# ---------------------------------------------------------------------------


def run_differential(
    instance_id: str,
    compile_sh: str,
    files: dict[str, str],
    probe_cmds: list[str],
    timeout: int = 300,
) -> tuple[list[dict], str]:
    """
    Fallback probe when no blob data is available.
    Runs probe_cmds against ref binary and our binary, compares outputs.
    Returns (failures, raw_output)
    failures = list of {"cmd": str, "expected": str, "actual": str}
    """
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    staging = STAGING_ROOT / str(uuid.uuid4())
    staging.mkdir()

    try:
        (staging / "compile.sh").write_text(
            compile_sh.replace("\r\n", "\n"), newline="\n", encoding="utf-8"
        )
        for fname, content in files.items():
            fpath = staging / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content.replace("\r\n", "\n"), newline="\n", encoding="utf-8")

        lines = [
            "#!/bin/bash",
            "cp /workspace/executable /tmp/ref_exec 2>/dev/null || true",
            "chmod +x /tmp/ref_exec 2>/dev/null || true",
            "cp -r /mnt/src/. /workspace/",
            "cd /workspace",
            "chmod +x compile.sh",
            "./compile.sh >/tmp/compile_out.txt 2>&1",
            "COMPILE_RC=$?",
            "if [ $COMPILE_RC -ne 0 ]; then",
            "  echo 'PROBE_COMPILE_FAILED'",
            "  cat /tmp/compile_out.txt",
            "  exit 1",
            "fi",
            "chmod +x /workspace/executable",
            "PASS=0",
            "FAIL=0",
        ]

        for i, cmd in enumerate(probe_cmds):
            ref_cmd = cmd.replace("BINARY", "/tmp/ref_exec")
            our_cmd = cmd.replace("BINARY", "/workspace/executable")
            safe_cmd = cmd.replace("'", "'\\''")
            lines += [
                "",
                f"REF_OUT=$({ref_cmd} 2>&1)",
                f"OUR_OUT=$({our_cmd} 2>&1)",
                "REF_NORM=$(echo \"$REF_OUT\" | sed 's|/tmp/ref_exec|BINARY|g; s|/workspace/executable|BINARY|g')",
                "OUR_NORM=$(echo \"$OUR_OUT\" | sed 's|/tmp/ref_exec|BINARY|g; s|/workspace/executable|BINARY|g')",
                'if [ "$REF_NORM" = "$OUR_NORM" ]; then',
                "  PASS=$((PASS+1))",
                "else",
                "  FAIL=$((FAIL+1))",
                f"  echo 'PROBE_FAIL_{i}'",
                f"  echo 'CMD:{safe_cmd}'",
                "  echo 'EXPECTED_START'",
                '  echo "$REF_OUT"',
                "  echo 'EXPECTED_END'",
                "  echo 'ACTUAL_START'",
                '  echo "$OUR_OUT"',
                "  echo 'ACTUAL_END'",
                "fi",
            ]

        lines += ["", 'echo "PROBE_SUMMARY pass=$PASS fail=$FAIL"', "[ $FAIL -eq 0 ]"]
        probe_sh = "\n".join(lines) + "\n"
        (staging / "probe.sh").write_text(
            probe_sh.replace("\r\n", "\n"), newline="\n", encoding="utf-8"
        )

        docker_path = _to_docker_path(staging)
        img = _image_name(instance_id)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{docker_path}:/mnt/src:ro",
                img,
                "bash",
                "-c",
                "bash /mnt/src/probe.sh",
            ],
            capture_output=True,
            timeout=timeout,
        )
        raw = result.stdout.decode("utf-8", errors="replace") + result.stderr.decode(
            "utf-8", errors="replace"
        )

        if "PROBE_COMPILE_FAILED" in raw:
            return [], raw
        return _parse_diff_failures(raw), raw

    except subprocess.TimeoutExpired:
        return [], "probe.sh timed out"
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _parse_diff_failures(raw: str) -> list[dict]:
    failures: list[dict] = []
    chunks = re.split(r"PROBE_FAIL_\d+", raw)
    for chunk in chunks[1:]:
        cmd = expected = actual = ""
        m = re.search(r"CMD:(.+)", chunk)
        if m:
            cmd = m.group(1).strip()
        m = re.search(r"EXPECTED_START\n(.*?)EXPECTED_END", chunk, re.DOTALL)
        if m:
            expected = m.group(1).strip()
        m = re.search(r"ACTUAL_START\n(.*?)ACTUAL_END", chunk, re.DOTALL)
        if m:
            actual = m.group(1).strip()
        if cmd or expected or actual:
            failures.append({"cmd": cmd, "expected": expected, "actual": actual})
    return failures


# ---------------------------------------------------------------------------
# Observer (disabled until re-tuned)
# ---------------------------------------------------------------------------


def observer_diagnose(
    instance_id: str, failures: list[dict], observations: str, model: str | None = None
) -> str:
    """Disabled — Observer v6-dsl hallucinates code instead of plain-text diagnosis."""
    return ""


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pytest probe a single ProgramBench submission")
    parser.add_argument("--instance", required=True)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--max-branches", type=int, default=99)
    parser.add_argument("--raw-out", type=Path)
    args = parser.parse_args()

    compile_sh = (args.source_dir / "compile.sh").read_text(encoding="utf-8")
    files = {
        p.name: p.read_text(encoding="utf-8")
        for p in args.source_dir.iterdir()
        if p.name != "compile.sh" and p.is_file()
    }

    branches = get_test_branches(args.instance)
    print(f"Found {len(branches)} test branches")
    if not branches:
        print("No blob data — cannot probe")
        exit(1)

    failures, raw, passed, total = run_pytest_probe(
        args.instance,
        compile_sh,
        files,
        max_branches=args.max_branches,
    )
    if args.raw_out:
        args.raw_out.parent.mkdir(parents=True, exist_ok=True)
        args.raw_out.write_text(raw, encoding="utf-8", errors="replace")
    print(f"\n{passed}/{total} passed  ({len(failures)} failures)")
    print(format_failure_report(failures))
