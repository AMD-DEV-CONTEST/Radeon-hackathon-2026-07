from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


def _project_src_path() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


if str(_project_src_path()) not in sys.path:
    sys.path.insert(0, str(_project_src_path()))

from xenix.config import ensure_app_dirs, get_app_paths  # noqa: E402
from xenix.observability import load_or_create_install_id  # noqa: E402
from xenix.services.storage.layout import database_path  # noqa: E402


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="create_diagnostic_bundle")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output zip path. Defaults to temp/xenix-diagnostic-<timestamp>.zip.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(list(argv) if argv is not None else None)
    paths = ensure_app_dirs(get_app_paths())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = args.output or (paths.temp / f"xenix-diagnostic-{stamp}.zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "install_id": load_or_create_install_id(paths),
        "runtime_home_class": "custom" if os.getenv("XENIX_APP_HOME") else "default",
        "sqlite": _sqlite_summary(database_path(paths)),
    }

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=True))
        _write_if_exists(bundle, paths.config / "telemetry.json", "config/telemetry.json")
        _write_if_exists(bundle, paths.logs / "xenix.log", "logs/xenix.log")
        for task_log in sorted((paths.artifacts / "ml-tasks").glob("*/logs.jsonl")):
            bundle.write(task_log, f"artifacts/ml-tasks/{task_log.parent.name}/logs.jsonl")

    print(output_path)
    return 0


def _write_if_exists(bundle: zipfile.ZipFile, path: Path, archive_name: str) -> None:
    if path.exists() and path.is_file():
        bundle.write(path, archive_name)


def _sqlite_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    with sqlite3.connect(path) as connection:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
    return {
        "exists": True,
        "user_version": user_version,
        "table_counts": counts,
    }


if __name__ == "__main__":
    raise SystemExit(main())
