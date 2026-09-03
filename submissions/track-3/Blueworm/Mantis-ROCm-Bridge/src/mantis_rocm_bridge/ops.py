"""Idempotent run markers for evidence-producing jobs."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .contracts import ContractError


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _run_dir(root: str | Path, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ContractError("run_id must contain only letters, numbers, dot, underscore, and hyphen")
    return Path(root) / run_id


def _payload(run_id: str, state: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "state": state,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "details": details or {},
    }


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ContractError(f"marker already exists and will not be overwritten: {path}") from exc


def begin_run(root: str | Path, run_id: str, manifest: dict[str, Any]) -> Path:
    directory = _run_dir(root, run_id)
    if not isinstance(manifest, dict) or not manifest:
        raise ContractError("run manifest must be a non-empty object")
    marker = directory / "started.json"
    _write_once(marker, _payload(run_id, "started", manifest))
    return marker


def finish_run(
    root: str | Path,
    run_id: str,
    state: str,
    details: dict[str, Any] | None = None,
) -> Path:
    if state not in {"completed", "failed", "stopped"}:
        raise ContractError("terminal run state must be completed, failed, or stopped")
    directory = _run_dir(root, run_id)
    if not (directory / "started.json").is_file():
        raise ContractError("cannot finish a run without started.json")
    terminal_markers = [directory / f"{name}.json" for name in ("completed", "failed", "stopped")]
    existing = [path for path in terminal_markers if path.exists()]
    if existing:
        raise ContractError(f"run already has terminal marker: {existing[0]}")
    marker = directory / f"{state}.json"
    _write_once(marker, _payload(run_id, state, details))
    return marker


def get_run_status(root: str | Path, run_id: str) -> str:
    directory = _run_dir(root, run_id)
    for state in ("completed", "failed", "stopped"):
        if (directory / f"{state}.json").is_file():
            return state
    if (directory / "started.json").is_file():
        return "started"
    return "missing"

