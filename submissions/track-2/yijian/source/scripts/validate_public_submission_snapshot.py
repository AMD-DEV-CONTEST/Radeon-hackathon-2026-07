#!/usr/bin/env python3
"""Validate a generated public source snapshot in isolation and emit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import re
from pathlib import Path
from typing import Any


PUBLIC_DATA_FILES = {"training/data/classical_sft_train.jsonl"}

TESTS = (
    "backend/tests",
    "training/tests",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_health(stdout: str) -> dict[str, Any]:
    """Keep health evidence useful without publishing machine-local paths."""
    try:
        value = json.loads(stdout.strip())
    except (json.JSONDecodeError, TypeError):
        return {"parsed": False}
    if not isinstance(value, dict):
        return {"parsed": False}
    allowed = ("status", "version", "terminologyCount", "engine", "demo", "configured")
    result = {key: value[key] for key in allowed if key in value}
    result["setupErrorPresent"] = bool(value.get("setupError"))
    return result


def pytest_passed_count(stdout: str) -> int | None:
    """Read pytest's final pass count without freezing the validator to an old suite size."""
    matches = re.findall(r"(?:^|\s)(\d+) passed(?:[\s,]|$)", stdout)
    return int(matches[-1]) if matches else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.snapshot.resolve()
    manifest_path = root / "public-snapshot-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hash_mismatches = []
    for item in manifest.get("items") or []:
        path = root / item["path"]
        if not path.is_file() or sha(path) != item["sha256"]:
            hash_mismatches.append(item["path"])
    compile_errors = []
    for path in root.rglob("*.py"):
        try:
            compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            compile_errors.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})
    clean_environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS], cwd=root,
        text=True, encoding="utf-8", errors="replace", capture_output=True,
        timeout=300, env=clean_environment,
    )
    startup_code = (
        "import sys,json;sys.path.insert(0,'backend');import app;"
        "value=app.health();print(json.dumps(value,ensure_ascii=False));"
        "assert value.get('status')=='ok'"
    )
    startup = subprocess.run(
        [sys.executable, "-c", startup_code], cwd=root,
        text=True, encoding="utf-8", errors="replace", capture_output=True,
        timeout=30, env=clean_environment,
    )
    forbidden = [
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file()
        and path.relative_to(root).as_posix() not in PUBLIC_DATA_FILES
        and (
            any(part in {"__pycache__", ".pytest_cache", "workspace", "licensed", "data", "logs", "adapter", "checkpoints"} for part in path.relative_to(root).parts)
            or path.suffix.lower() in {".db", ".sqlite", ".pt", ".pth", ".safetensors", ".mp4", ".wav"}
        )
    ]
    passed_tests = pytest_passed_count(test.stdout)
    gates = {
        "generatorManifestPassed": manifest.get("passed") is True,
        "hashesMatch": not hash_mismatches,
        "pythonCompiles": not compile_errors,
        "allPublicTestsPass": test.returncode == 0 and passed_tests is not None and passed_tests > 0,
        "applicationImportsAndHealthPasses": startup.returncode == 0,
        "forbiddenArtifactsAbsent": not forbidden,
        "secretFindingsZero": int(manifest.get("secretFindings") or 0) == 0,
        "privateDataFindingsZero": int(manifest.get("privateDataFindings") or 0) == 0,
    }
    result: dict[str, Any] = {
        "schemaVersion": "yijian-public-snapshot-validation-v2",
        "passed": all(gates.values()), "gates": gates,
        "files": manifest.get("files"), "secretFindings": manifest.get("secretFindings"),
        "privateDataFindings": manifest.get("privateDataFindings"),
        "manifestSha256": sha(manifest_path), "hashMismatches": hash_mismatches,
        "compileErrors": compile_errors, "forbiddenArtifacts": forbidden,
        "tests": {
            "returnCode": test.returncode,
            "passedCount": passed_tests,
            "summary": test.stdout.strip().splitlines()[-1] if test.stdout.strip() else "",
            "stderr": test.stderr[-1000:],
        },
        "startup": {
            "returnCode": startup.returncode,
            "health": public_health(startup.stdout),
            "stderrPresent": bool(startup.stderr.strip()),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"passed": result["passed"], "gates": gates}, ensure_ascii=False))
    return 0 if result["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
