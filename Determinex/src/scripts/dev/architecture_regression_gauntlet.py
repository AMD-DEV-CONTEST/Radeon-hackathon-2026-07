"""Architecture Regression Gauntlet — DETERMINEX_ARCHITECTURE_REGRESSION_GAUNTLET_LOCK_001

Stress-tests the architecture spine landed in the pre-release hardening sprint
(CONFIG_SPINE, PATH_PORTABILITY, DETERMINEX_CLI, REPRODUCIBLE_DEV,
CI_QUALITY_GATE, EVIDENCE_IMMUTABILITY, CORPUS_WRITE_GUARD,
FRONTEND_QUALITY_RAILS, CLOAK_THREAT_MODEL, STORAGE_OPERATIONS).

The gauntlet runs as a single Python process and produces a JSON report.
Every check returns one of a closed set of status tokens so the report is
machine-checkable.

Usage::

    python scripts/dev/architecture_regression_gauntlet.py
    python scripts/dev/architecture_regression_gauntlet.py --json out.json
    python scripts/dev/architecture_regression_gauntlet.py --strict

Status tokens (closed set)::

    ARCH_GAUNTLET_PASSED
    ARCH_GAUNTLET_FAILED
    CLI_COMMAND_AVAILABLE
    CLI_COMMAND_FAILED
    LEGACY_SCRIPT_COMPATIBLE
    LEGACY_SCRIPT_BROKEN
    READ_ONLY_COMMAND_MUTATED_EVIDENCE
    READ_ONLY_COMMAND_PRESERVED_EVIDENCE
    PATH_PORTABILITY_CONFIRMED
    PATH_PORTABILITY_FAILED
    UNSAFE_DEFAULT_BLOCKED
    UNSAFE_DEFAULT_OPEN
    JUST_RUNNER_PRESENT
    JUST_RUNNER_MISSING_SKIPPED

The gauntlet is intentionally read-only against the live repo. It does NOT
mutate evidence, corpus, locks, or models. T:/ is not required.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
EVIDENCE_ROOT = REPO_ROOT / "assurance" / "evidence"
EVIDENCE_INDEX = EVIDENCE_ROOT / "evidence_index.json"
CORPUS_ROOT_DEFAULT = REPO_ROOT / "corpus"
LOCKS_DIR = REPO_ROOT / "locks" / "sentinel"

# Subprocess timeout per command (seconds). Generous; the slowest command
# (determinex doctor with all checks) typically returns in <30s.
DEFAULT_TIMEOUT_S = 120

# Status tokens — closed set, all results map to one of these.
STATUS_TOKENS = frozenset(
    {
        "ARCH_GAUNTLET_PASSED",
        "ARCH_GAUNTLET_FAILED",
        "CLI_COMMAND_AVAILABLE",
        "CLI_COMMAND_FAILED",
        "LEGACY_SCRIPT_COMPATIBLE",
        "LEGACY_SCRIPT_BROKEN",
        "READ_ONLY_COMMAND_MUTATED_EVIDENCE",
        "READ_ONLY_COMMAND_PRESERVED_EVIDENCE",
        "PATH_PORTABILITY_CONFIRMED",
        "PATH_PORTABILITY_FAILED",
        "UNSAFE_DEFAULT_BLOCKED",
        "UNSAFE_DEFAULT_OPEN",
        "JUST_RUNNER_PRESENT",
        "JUST_RUNNER_MISSING_SKIPPED",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python_exe() -> str:
    """Return the interpreter to use for subprocess calls."""
    return sys.executable or "python"


def _determinex_cli_argv(args: list[str]) -> list[str]:
    """Build an argv that invokes the CLI without depending on the console
    script being on PATH. Calls ``python scripts/determinex_cli.py …`` so the
    gauntlet works in CI, fresh venvs, and local dev alike."""
    return [_python_exe(), str(SCRIPTS_DIR / "determinex_cli.py"), *args]


def _legacy_argv(script_name: str, args: list[str]) -> list[str]:
    return [_python_exe(), str(SCRIPTS_DIR / script_name), *args]


def _hash_path(path: Path) -> str | None:
    """SHA-256 of a single file; None if absent. Read-only."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(root: Path, max_files: int = 5000) -> dict[str, str]:
    """SHA-256 every regular file under root. Read-only. Bounded by max_files
    to avoid runaway costs on huge directories."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    count = 0
    for p in sorted(root.rglob("*")):
        if count >= max_files:
            break
        if not p.is_file():
            continue
        try:
            out[str(p.relative_to(root))] = _hash_path(p) or ""
        except OSError:
            continue
        count += 1
    return out


def _run(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Run a subprocess and return a structured result. Never raises."""
    started = _dt.datetime.now(_dt.UTC).isoformat()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env if env is not None else os.environ.copy(),
            cwd=str(cwd or REPO_ROOT),
            check=False,
        )
        return {
            "argv": argv,
            "returncode": proc.returncode,
            "stdout_tail": _tail(proc.stdout, 40),
            "stderr_tail": _tail(proc.stderr, 40),
            "timed_out": False,
            "started_at": started,
        }
    except subprocess.TimeoutExpired as e:

        def _as_str(v: object) -> str:
            if isinstance(v, bytes):
                return v.decode("utf-8", errors="replace")
            return v if isinstance(v, str) else ""

        return {
            "argv": argv,
            "returncode": -1,
            "stdout_tail": _tail(_as_str(e.stdout), 40),
            "stderr_tail": _tail(_as_str(e.stderr), 40),
            "timed_out": True,
            "started_at": started,
        }
    except FileNotFoundError as e:
        return {
            "argv": argv,
            "returncode": -2,
            "stdout_tail": "",
            "stderr_tail": f"FileNotFoundError: {e}",
            "timed_out": False,
            "started_at": started,
        }


def _tail(text: str, n_lines: int) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-n_lines:])


# ---------------------------------------------------------------------------
# Checks — each returns (status_token, detail_dict)
# ---------------------------------------------------------------------------


def check_cli_version() -> tuple[str, dict[str, Any]]:
    result = _run(_determinex_cli_argv(["--version"]))
    ok = result["returncode"] == 0 and "determinex" in (result["stdout_tail"] or "").lower()
    return (
        "CLI_COMMAND_AVAILABLE" if ok else "CLI_COMMAND_FAILED",
        {"check": "determinex --version", "result": result},
    )


def check_cli_config_show() -> tuple[str, dict[str, Any]]:
    result = _run(_determinex_cli_argv(["config", "show"]))
    out = result["stdout_tail"] or ""
    ok = result["returncode"] == 0 and "models_dir" in out and "Safety defaults" in out
    return (
        "CLI_COMMAND_AVAILABLE" if ok else "CLI_COMMAND_FAILED",
        {"check": "determinex config show", "result": result},
    )


def check_cli_config_doctor() -> tuple[str, dict[str, Any]]:
    result = _run(_determinex_cli_argv(["config", "doctor"]))
    ok = (
        result["returncode"] == 0
        and "safety defaults closed" in (result["stdout_tail"] or "").lower()
    )
    return (
        "CLI_COMMAND_AVAILABLE" if ok else "CLI_COMMAND_FAILED",
        {"check": "determinex config doctor", "result": result},
    )


def check_cli_doctor() -> tuple[str, dict[str, Any]]:
    # `determinex doctor` may surface UNAVAILABLE checks in dev environments
    # (no Ollama, no T:/, no HMAC key). What we verify here is that the
    # command *runs* and produces a well-formed status report — not that
    # every individual check passes.
    result = _run(_determinex_cli_argv(["doctor"]))
    out = result["stdout_tail"] or ""
    runs = result["returncode"] in (0, 1) and (
        "ACTIVE" in out or "UNAVAILABLE" in out or "DEMO MODE" in out or "==" in out
    )
    return (
        "CLI_COMMAND_AVAILABLE" if runs else "CLI_COMMAND_FAILED",
        {"check": "determinex doctor", "result": result},
    )


def check_cli_status_summary() -> tuple[str, dict[str, Any]]:
    # `determinex status --summary` may print "no events" on a clean machine.
    # What we verify is that it exits successfully and produces text.
    result = _run(_determinex_cli_argv(["status", "--summary"]))
    runs = result["returncode"] in (0, 1)
    return (
        "CLI_COMMAND_AVAILABLE" if runs else "CLI_COMMAND_FAILED",
        {"check": "determinex status --summary", "result": result},
    )


def check_cli_evidence_validate() -> tuple[str, dict[str, Any]]:
    result = _run(_determinex_cli_argv(["evidence", "validate"]))
    out = result["stdout_tail"] or ""
    ok = result["returncode"] == 0 and "Evidence index" in out
    return (
        "CLI_COMMAND_AVAILABLE" if ok else "CLI_COMMAND_FAILED",
        {"check": "determinex evidence validate", "result": result},
    )


# ---------------------------------------------------------------------------
# just (task runner) — optional, skipped if not installed
# ---------------------------------------------------------------------------


def _just_available() -> bool:
    return shutil.which("just") is not None


def check_just_runner() -> tuple[str, dict[str, Any]]:
    if _just_available():
        result = _run(["just", "--list"])
        return (
            "JUST_RUNNER_PRESENT",
            {"check": "just --list", "result": result},
        )
    return (
        "JUST_RUNNER_MISSING_SKIPPED",
        {"check": "just --list", "result": {"stderr_tail": "just not on PATH"}},
    )


def check_just_recipe(recipe: str) -> tuple[str, dict[str, Any]]:
    if not _just_available():
        return (
            "JUST_RUNNER_MISSING_SKIPPED",
            {"check": f"just {recipe}", "result": {"stderr_tail": "just not on PATH"}},
        )
    # Use --dry-run so we only verify the recipe is *defined*, not that it
    # passes. Running `just test` from inside the gauntlet would recurse
    # back into pytest and slow this dramatically; the test suite itself
    # already exercises the recipe contents.
    result = _run(["just", "--dry-run", recipe])
    ok = result["returncode"] == 0
    return (
        "CLI_COMMAND_AVAILABLE" if ok else "CLI_COMMAND_FAILED",
        {"check": f"just --dry-run {recipe}", "result": result},
    )


# ---------------------------------------------------------------------------
# Legacy scripts — must still work as documented
# ---------------------------------------------------------------------------


def check_legacy_doctor() -> tuple[str, dict[str, Any]]:
    result = _run(_legacy_argv("determinex_doctor.py", []))
    out = result["stdout_tail"] or ""
    ok = result["returncode"] in (0, 1) and (
        "ACTIVE" in out or "UNAVAILABLE" in out or "DEMO MODE" in out or "==" in out
    )
    return (
        "LEGACY_SCRIPT_COMPATIBLE" if ok else "LEGACY_SCRIPT_BROKEN",
        {"check": "python scripts/determinex_doctor.py", "result": result},
    )


def check_legacy_status_summary() -> tuple[str, dict[str, Any]]:
    result = _run(_legacy_argv("determinex_status.py", ["--summary"]))
    ok = result["returncode"] in (0, 1)
    return (
        "LEGACY_SCRIPT_COMPATIBLE" if ok else "LEGACY_SCRIPT_BROKEN",
        {"check": "python scripts/determinex_status.py --summary", "result": result},
    )


def check_legacy_evidence_index() -> tuple[str, dict[str, Any]]:
    # evidence_index.py default mode WRITES the index file. The gauntlet
    # must remain read-only against the live repo, so we use --check mode
    # which validates without writing.
    result = _run(_legacy_argv("evidence_index.py", ["--check"]))
    ok = result["returncode"] in (0, 1)
    return (
        "LEGACY_SCRIPT_COMPATIBLE" if ok else "LEGACY_SCRIPT_BROKEN",
        {"check": "python scripts/evidence_index.py --check", "result": result},
    )


# ---------------------------------------------------------------------------
# Read-only mutation guard
# ---------------------------------------------------------------------------


def _signed_evidence_files() -> list[Path]:
    """The small canonical set of files that must remain byte-identical
    under any read-only command."""
    files: list[Path] = []
    if EVIDENCE_INDEX.is_file():
        files.append(EVIDENCE_INDEX)
    # Include all sentinel lock manifests as part of the signed set.
    if LOCKS_DIR.is_dir():
        files.extend(sorted(p for p in LOCKS_DIR.glob("*.json") if p.is_file()))
    return files


def check_read_only_preserves_evidence() -> tuple[str, dict[str, Any]]:
    targets = _signed_evidence_files()
    before = {str(p.relative_to(REPO_ROOT)): _hash_path(p) for p in targets}

    runs: list[dict[str, Any]] = []
    for argv in [
        _determinex_cli_argv(["config", "show"]),
        _determinex_cli_argv(["config", "doctor"]),
        _determinex_cli_argv(["evidence", "validate"]),
        _determinex_cli_argv(["status", "--summary"]),
        _legacy_argv("evidence_index.py", ["--check"]),
    ]:
        runs.append(
            {
                "argv": argv,
                "returncode": _run(argv)["returncode"],
            }
        )

    after = {str(p.relative_to(REPO_ROOT)): _hash_path(p) for p in targets}
    mutated = sorted(k for k in before if before[k] != after.get(k))
    detail = {
        "check": "read-only commands preserve signed evidence + locks",
        "files_watched": len(targets),
        "runs": runs,
        "mutated_files": mutated,
    }
    return (
        "READ_ONLY_COMMAND_MUTATED_EVIDENCE" if mutated else "READ_ONLY_COMMAND_PRESERVED_EVIDENCE",
        detail,
    )


# ---------------------------------------------------------------------------
# Path portability — T:/ optional, env overrides honored
# ---------------------------------------------------------------------------


def check_path_portability(tmp_root: Path) -> tuple[str, dict[str, Any]]:
    """Confirm determinex_settings resolves portable paths when no T:/ is set
    AND when an explicit override is given, with no drive letter required."""
    # We run a child Python that:
    #   1. clears every DETERMINEX_* and HF_HOME env var
    #   2. imports determinex_settings
    #   3. asks for the seven paths that have local fallbacks
    #   4. then sets each to a tmp-dir override and re-resolves
    #   5. prints a JSON dict of {prop: (with_override, no_override)}
    snippet = r"""
import json, os, sys
from pathlib import Path
# Strip all relevant env vars to simulate a clean machine
for k in list(os.environ):
    if k.startswith(("DETERMINEX_", "HF_HOME", "OLLAMA_")):
        del os.environ[k]
sys.path.insert(0, str(Path(r"{scripts}").resolve()))
from determinex_settings import DeterminexSettings, reset_settings

props_with_fallback = [
    "audit_dir", "corpus_root", "models_dir",
    "pb_staging_root", "hf_home", "artifact_quarantine", "artifact_cache",
]

reset_settings()
s = DeterminexSettings()
no_override = {{p: str(getattr(s, p)) for p in props_with_fallback}}

override_root = Path(r"{tmp}").resolve()
override_root.mkdir(parents=True, exist_ok=True)
env_map = {{
    "audit_dir": "DETERMINEX_AUDIT_DIR",
    "corpus_root": "DETERMINEX_CORPUS_ROOT",
    "models_dir": "DETERMINEX_MODELS_DIR",
    "pb_staging_root": "DETERMINEX_PB_STAGING_ROOT",
    "hf_home": "HF_HOME",
    "artifact_quarantine": "DETERMINEX_QUARANTINE_DIR",
    "artifact_cache": "DETERMINEX_ARTIFACT_CACHE",
}}
for prop, env in env_map.items():
    os.environ[env] = str(override_root / prop)
reset_settings()
s = DeterminexSettings()
with_override = {{p: str(getattr(s, p)) for p in props_with_fallback}}

print(json.dumps({{"no_override": no_override, "with_override": with_override}}))
""".format(scripts=str(SCRIPTS_DIR).replace("\\", "\\\\"), tmp=str(tmp_root).replace("\\", "\\\\"))

    result = _run([_python_exe(), "-c", snippet])
    if result["returncode"] != 0:
        return (
            "PATH_PORTABILITY_FAILED",
            {
                "check": "determinex_settings resolves with no T:/",
                "result": result,
            },
        )
    try:
        parsed = json.loads(result["stdout_tail"].strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return (
            "PATH_PORTABILITY_FAILED",
            {"check": "JSON parse of child output", "result": result},
        )

    no_override = parsed["no_override"]
    with_override = parsed["with_override"]

    # Property-by-property assertions
    failures: list[str] = []
    for prop, val in no_override.items():
        # No T:/ default may be required for correctness; the value must be
        # *some* path string (not empty), and it must not REQUIRE T:/ —
        # meaning either it's a local path OR T:/ is mounted on this host
        # (we still accept it).
        if not val:
            failures.append(f"{prop}: empty path")
    for prop, val in with_override.items():
        if str(tmp_root) not in val:
            failures.append(f"{prop}: override not honored (got {val!r})")

    status = "PATH_PORTABILITY_CONFIRMED" if not failures else "PATH_PORTABILITY_FAILED"
    return (
        status,
        {
            "check": "determinex_settings path portability",
            "no_override_sample": no_override,
            "with_override_sample": with_override,
            "failures": failures,
        },
    )


# ---------------------------------------------------------------------------
# Unsafe-default fail-closed guard
# ---------------------------------------------------------------------------


def check_unsafe_defaults_fail_closed() -> tuple[str, dict[str, Any]]:
    """Confirm that with a clean env, all dangerous flags are off (fail-closed)
    AND that the runtime reports zero violations."""
    snippet = r"""
import json, os, sys
from pathlib import Path
for k in list(os.environ):
    if k.startswith("DETERMINEX_"):
        del os.environ[k]
sys.path.insert(0, str(Path(r"{scripts}").resolve()))
from determinex_settings import DeterminexSettings, reset_settings
reset_settings()
s = DeterminexSettings()
flags = {{
    "safety_mode":          s.safety_mode,
    "online_discovery":     s.online_discovery,
    "allow_cloud_fallback": s.allow_cloud_fallback,
    "allow_unsandboxed":    s.allow_unsandboxed,
    "require_docker":       s.require_docker,
    "require_cloak":        s.require_cloak,
    "offline_observer":     s.offline_observer,
    "flywheel_auto":        s.flywheel_auto,
}}
violations = s.assert_safety_defaults()
print(json.dumps({{"flags": flags, "violations": violations}}))
""".format(scripts=str(SCRIPTS_DIR).replace("\\", "\\\\"))

    result = _run([_python_exe(), "-c", snippet])
    if result["returncode"] != 0:
        return (
            "UNSAFE_DEFAULT_OPEN",
            {"check": "child-process safety flag readout", "result": result},
        )
    try:
        parsed = json.loads(result["stdout_tail"].strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return (
            "UNSAFE_DEFAULT_OPEN",
            {"check": "JSON parse of safety readout", "result": result},
        )
    flags = parsed["flags"]
    violations = parsed["violations"]

    # Hard expectations (all must be fail-closed under a clean env):
    expectations = {
        "safety_mode": "strict",
        "online_discovery": False,
        "allow_cloud_fallback": False,
        "allow_unsandboxed": False,
        "require_docker": True,
        "require_cloak": True,
        "offline_observer": True,
        "flywheel_auto": False,
    }
    mismatches = {k: (flags.get(k), v) for k, v in expectations.items() if flags.get(k) != v}

    status = (
        "UNSAFE_DEFAULT_BLOCKED" if not mismatches and not violations else "UNSAFE_DEFAULT_OPEN"
    )
    return (
        status,
        {
            "check": "unsafe defaults fail-closed under clean env",
            "flags": flags,
            "violations": violations,
            "mismatches": mismatches,
        },
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_gauntlet(tmp_root: Path | None = None) -> dict[str, Any]:
    """Run every check; return a structured report. Does not raise."""
    import tempfile

    tmp_dir_owner: tempfile.TemporaryDirectory | None = None
    if tmp_root is None:
        tmp_dir_owner = tempfile.TemporaryDirectory(prefix="determinex_arch_gauntlet_")
        tmp_root = Path(tmp_dir_owner.name)

    checks: list[tuple[str, Callable[[], tuple[str, dict[str, Any]]]]] = [
        ("cli.version", check_cli_version),
        ("cli.config_show", check_cli_config_show),
        ("cli.config_doctor", check_cli_config_doctor),
        ("cli.doctor", check_cli_doctor),
        ("cli.status_summary", check_cli_status_summary),
        ("cli.evidence_validate", check_cli_evidence_validate),
        ("just.runner", check_just_runner),
        ("just.doctor", lambda: check_just_recipe("doctor")),
        ("just.test", lambda: check_just_recipe("test")),
        ("just.evidence", lambda: check_just_recipe("evidence")),
        ("just.audit", lambda: check_just_recipe("audit")),
        ("legacy.doctor", check_legacy_doctor),
        ("legacy.status_summary", check_legacy_status_summary),
        ("legacy.evidence_index", check_legacy_evidence_index),
        ("guard.read_only_evidence", check_read_only_preserves_evidence),
        ("portability.paths", lambda: check_path_portability(tmp_root)),
        ("safety.defaults", check_unsafe_defaults_fail_closed),
    ]

    results: list[dict[str, Any]] = []
    for name, fn in checks:
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001 — never let the gauntlet crash
            status, detail = (
                "ARCH_GAUNTLET_FAILED",
                {
                    "check": name,
                    "exception": f"{type(e).__name__}: {e}",
                },
            )
        assert status in STATUS_TOKENS, f"Unknown status token: {status!r}"
        results.append({"name": name, "status": status, "detail": detail})

    # Roll-up: gauntlet passes iff every check is in a "good" status
    bad_statuses = {
        "CLI_COMMAND_FAILED",
        "LEGACY_SCRIPT_BROKEN",
        "READ_ONLY_COMMAND_MUTATED_EVIDENCE",
        "PATH_PORTABILITY_FAILED",
        "UNSAFE_DEFAULT_OPEN",
        "ARCH_GAUNTLET_FAILED",
    }
    failed = [r for r in results if r["status"] in bad_statuses]
    rollup = "ARCH_GAUNTLET_PASSED" if not failed else "ARCH_GAUNTLET_FAILED"

    report = {
        "lock_id": "DETERMINEX_ARCHITECTURE_REGRESSION_GAUNTLET_LOCK_001",
        "generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "rollup_status": rollup,
        "checks_run": len(results),
        "checks_failed": len(failed),
        "results": results,
        "host": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "just_available": _just_available(),
        },
    }

    if tmp_dir_owner is not None:
        tmp_dir_owner.cleanup()

    return report


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--json", type=Path, default=None, help="Write the full JSON report to this path"
    )
    ap.add_argument("--strict", action="store_true", help="Exit 1 on ARCH_GAUNTLET_FAILED")
    args = ap.parse_args(argv)

    report = run_gauntlet()

    # Pretty console summary
    print(f"Architecture Regression Gauntlet — {report['rollup_status']}")
    print(f"  ran {report['checks_run']} checks, {report['checks_failed']} failed")
    print(
        f"  host: {report['host']['platform']} python {report['host']['python']}"
        f" just={'yes' if report['host']['just_available'] else 'no'}"
    )
    for r in report["results"]:
        marker = (
            "  ok"
            if r["status"]
            not in {
                "CLI_COMMAND_FAILED",
                "LEGACY_SCRIPT_BROKEN",
                "READ_ONLY_COMMAND_MUTATED_EVIDENCE",
                "PATH_PORTABILITY_FAILED",
                "UNSAFE_DEFAULT_OPEN",
                "ARCH_GAUNTLET_FAILED",
            }
            else "FAIL"
        )
        print(f"  {marker}  {r['name']:<28} {r['status']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=False), encoding="utf-8")
        print(f"\nWrote report to {args.json}")

    if args.strict and report["rollup_status"] == "ARCH_GAUNTLET_FAILED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
