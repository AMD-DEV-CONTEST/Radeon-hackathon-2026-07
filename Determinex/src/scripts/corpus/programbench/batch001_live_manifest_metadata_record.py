from __future__ import annotations

from pathlib import Path
from typing import Any

from corpus.programbench.programbench_platform_record import (
    make_platform_record,
    verify_platform_record,
    write_platform_record,
)


def make_live_manifest_metadata_record(
    *,
    record_type: str,
    schema_version: str,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return make_platform_record(
        record_type=record_type,
        schema_version=schema_version,
        status=status,
        payload=payload,
    )


def write_live_manifest_metadata_record(record: dict[str, Any], output_dir: Path) -> Path:
    return write_platform_record(record, output_dir, name_key="record_id")


def verify_live_manifest_metadata_record(record: dict[str, Any]) -> bool:
    return verify_platform_record(record)
