#!/usr/bin/env python3
"""Install Lookfile AMD app dependencies without touching the image PyTorch."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

FORBIDDEN = frozenset(
    {
        "torch",
        "torchvision",
        "torchaudio",
        "pytorch",
        "torch-tensorrt",
        "pytorch-triton",
    }
)
SCHEMA_KEYS = frozenset(
    (
        "schema_version",
        "status",
        "reason_code",
        "repo_sha",
        "lock_sha",
        "planned",
        "installed",
        "skipped",
        "torch_before",
        "torch_after",
        "torch_unchanged",
        "pip_command",
        "pip_check_command",
        "pip_check_external_conflicts",
    )
)


def _load_probe():
    path = Path(__file__).with_name("probe_environment.py")
    spec = importlib.util.spec_from_file_location("_amd_probe_environment", path)
    if spec is None or spec.loader is None:
        raise ImportError("probe_environment unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PROBE = _load_probe()
DEPENDENCIES: dict[str, str] = dict(_PROBE.DEPENDENCIES)
canonical_json = _PROBE.canonical_json
torch_fingerprints = _PROBE.torch_fingerprints


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def valid_distribution_name(name: object) -> bool:
    return (
        type(name) is str
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name)
        is not None
    )


def locked_requirements(dependencies: Mapping[str, str] = DEPENDENCIES) -> list[str]:
    planned: list[str] = []
    normalized: set[str] = set()
    for name, version in dependencies.items():
        if type(name) is not str or type(version) is not str:
            raise ValueError("invalid dependency pin")
        if not valid_distribution_name(name):
            raise ValueError(f"invalid dependency name: {name!r}")
        canonical_name = normalize_name(name)
        if canonical_name in normalized:
            raise ValueError(f"duplicate dependency name: {name}")
        normalized.add(canonical_name)
        if canonical_name in FORBIDDEN:
            raise ValueError(f"forbidden package in plan: {name}")
        if not _PROBE.valid_version(version):
            raise ValueError(f"invalid version pin: {name}=={version}")
        planned.append(f"{name}=={version}")
    return planned


def lock_sha(dependencies: Mapping[str, str] = DEPENDENCIES) -> str:
    payload = canonical_json(
        {name: dependencies[name] for name in sorted(dependencies)}
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def current_versions(names: Sequence[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in names:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def packages_to_install(
    dependencies: Mapping[str, str] = DEPENDENCIES,
) -> tuple[list[str], list[str]]:
    install: list[str] = []
    skipped: list[str] = []
    for name, version in dependencies.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            install.append(f"{name}=={version}")
            continue
        if actual == version:
            skipped.append(f"{name}=={version}")
        else:
            install.append(f"{name}=={version}")
    return install, skipped


def snapshot_torch(
    import_torch: Callable[[], Any] = lambda: __import__("torch"),
    fingerprints: Callable[[Any], dict[str, str]] = torch_fingerprints,
) -> dict[str, str] | None:
    try:
        torch = import_torch()
    except Exception:
        return None
    try:
        value = fingerprints(torch)
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    return {str(key): str(item) for key, item in value.items()}


def assert_no_forbidden(specs: Sequence[str]) -> None:
    for spec in specs:
        if type(spec) is not str or spec.count("==") != 1:
            raise ValueError(f"invalid requirement: {spec!r}")
        raw_name, version = spec.split("==", 1)
        if not valid_distribution_name(raw_name) or not _PROBE.valid_version(version):
            raise ValueError(f"invalid requirement: {spec!r}")
        name = normalize_name(raw_name)
        if name in FORBIDDEN:
            raise ValueError(f"refusing to install forbidden package: {spec}")


def build_pip_command(
    specs: Sequence[str], *, python: str = sys.executable
) -> list[str]:
    assert_no_forbidden(specs)
    # --no-deps keeps ROCm torch from being pulled as a transitive requirement.
    return [
        python,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-deps",
        *specs,
    ]


def run_pip(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if not command or command[1:3] != ["-m", "pip"] or "install" not in command:
        raise ValueError("invalid pip command")
    assert_no_forbidden([part for part in command if "==" in part])
    completed = runner(
        list(command),
        check=False,
        text=True,
        capture_output=True,
        env={**os.environ, "PIP_NO_INPUT": "1"},
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "pip install failed")


def run_pip_check(
    *,
    python: str = sys.executable,
    dependencies: Mapping[str, str] = DEPENDENCIES,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[list[str], int]:
    command = [python, "-m", "pip", "check"]
    completed = runner(
        command,
        check=False,
        text=True,
        capture_output=True,
        env={**os.environ, "PIP_NO_INPUT": "1"},
    )
    if completed.returncode == 0:
        return command, 0
    detail = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if isinstance(part, str) and part.strip()
    )
    locked = {normalize_name(name) for name in dependencies}
    external = 0
    for line in detail.splitlines():
        match = re.fullmatch(
            r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s+\S+\s+"
            r"(?:has requirement .+, but you have .+\.|"
            r"requires .+, which is not installed\.|"
            r"is not supported on this platform)",
            line,
        )
        if match is None or normalize_name(match.group(1)) in locked:
            raise RuntimeError("locked dependency check failed")
        external += 1
    if external == 0:
        raise RuntimeError("pip check failed")
    return command, external


def empty_result(repo_sha: str | None, lock: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "PASS",
        "reason_code": "OK",
        "repo_sha": repo_sha,
        "lock_sha": lock,
        "planned": [],
        "installed": [],
        "skipped": [],
        "torch_before": None,
        "torch_after": None,
        "torch_unchanged": False,
        "pip_command": [],
        "pip_check_command": [],
        "pip_check_external_conflicts": 0,
    }


def fail(result: dict[str, Any], reason: str) -> tuple[dict[str, Any], int]:
    result = dict(result)
    result["status"] = "FAIL"
    result["reason_code"] = reason
    return result, 2


def install_dependencies(
    *,
    repo_sha: str | None = None,
    dry_run: bool = False,
    require_torch: bool = True,
    dependencies: Mapping[str, str] = DEPENDENCIES,
    import_torch: Callable[[], Any] = lambda: __import__("torch"),
    fingerprints: Callable[[Any], dict[str, str]] = torch_fingerprints,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python: str = sys.executable,
) -> tuple[dict[str, Any], int]:
    lock = lock_sha(dependencies)
    result = empty_result(repo_sha, lock)
    try:
        planned = locked_requirements(dependencies)
    except ValueError:
        return fail(result, "INVALID_LOCK")
    result["planned"] = planned

    before = snapshot_torch(import_torch, fingerprints)
    result["torch_before"] = before
    if require_torch and before is None:
        return fail(result, "TORCH_MISSING")

    install, skipped = packages_to_install(dependencies)
    result["skipped"] = skipped
    result["installed"] = install
    if install:
        try:
            command = build_pip_command(install, python=python)
        except ValueError:
            return fail(result, "FORBIDDEN_PACKAGE")
        result["pip_command"] = command
    if dry_run:
        result["torch_after"] = before
        result["torch_unchanged"] = before is not None
        result["reason_code"] = "DRY_RUN"
        return result, 0
    if install:
        try:
            run_pip(result["pip_command"], runner=runner)
        except RuntimeError:
            return fail(result, "PIP_FAILED")

    after = snapshot_torch(import_torch, fingerprints)
    result["torch_after"] = after
    if require_torch and after is None:
        return fail(result, "TORCH_MISSING_AFTER")
    if before is not None and after != before:
        return fail(result, "TORCH_DRIFT")
    result["torch_unchanged"] = before is not None and after == before

    versions = current_versions(list(dependencies))
    for name, expected in dependencies.items():
        if versions.get(name) != expected:
            return fail(result, "VERSION_MISMATCH")
    try:
        command, external = run_pip_check(
            python=python, dependencies=dependencies, runner=runner
        )
        result["pip_check_command"] = command
        result["pip_check_external_conflicts"] = external
    except RuntimeError:
        result["pip_check_command"] = [python, "-m", "pip", "check"]
        return fail(result, "PIP_CHECK_FAILED")
    return result, 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install Lookfile dependencies without modifying ROCm torch"
    )
    parser.add_argument("--repo-sha", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-missing-torch",
        action="store_true",
        help="For offline unit tests only; AMD install must see torch",
    )
    parser.add_argument("--json-out", default=None, help="Optional evidence path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result, code = install_dependencies(
        repo_sha=args.repo_sha,
        dry_run=args.dry_run,
        require_torch=not args.allow_missing_torch,
    )
    payload = canonical_json(result) + "\n"
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="ascii")
        os.chmod(path, 0o600)
    else:
        sys.stdout.write(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
