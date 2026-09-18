"""Capture a reproducible, non-destructive project baseline on Windows or Linux."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "baseline"


def _run(name: str, command: list[str]) -> bool:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    content = result.stdout
    if result.stderr:
        content += f"\n[stderr]\n{result.stderr}"
    content += f"\n[exit_code]\n{result.returncode}\n"
    (OUTPUT / name).write_text(content, encoding="utf-8")
    return result.returncode == 0


def _config_hashes() -> dict[str, str]:
    paths = sorted((ROOT / "configs").rglob("*.yaml"))
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def _database_schema() -> dict[str, Any]:
    candidates = sorted(
        path
        for path in (ROOT / "workspace").rglob("*.db")
        if path.is_file() and not path.is_symlink()
    )
    databases: list[dict[str, Any]] = []
    for path in candidates:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE type IN ('table', 'index', 'view') ORDER BY type, name"
            ).fetchall()
        databases.append(
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "objects": [
                    {"type": kind, "name": name, "sql": sql}
                    for kind, name, sql in rows
                ],
            }
        )
    return {"databases": databases, "note": "No database is created or modified."}


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    checks = [
        _run("git-commit.txt", ["git", "rev-parse", "HEAD"]),
        _run("python-version.txt", [sys.executable, "--version"]),
        _run("pip-freeze.txt", [sys.executable, "-m", "pip", "freeze"]),
        _run("pytest.txt", [sys.executable, "-m", "pytest", "-q"]),
        _run("ruff.txt", [sys.executable, "-m", "ruff", "check", "src", "tests"]),
        _run("mypy.txt", [sys.executable, "-m", "mypy", "src"]),
        _run(
            "smoke.json",
            [
                sys.executable,
                "-m",
                "buildguard.cli",
                "smoke-test",
                "--config",
                "configs/app.yaml",
            ],
        ),
    ]
    (OUTPUT / "config-hashes.json").write_text(
        json.dumps(_config_hashes(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "database-schema.json").write_text(
        json.dumps(_database_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
