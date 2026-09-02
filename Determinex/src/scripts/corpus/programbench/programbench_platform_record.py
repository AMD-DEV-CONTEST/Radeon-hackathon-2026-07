from __future__ import annotations

from pathlib import Path
from typing import Any

from corpus.programbench.codex_completion_campaign_record import (
    make_campaign_record,
    verify_campaign_record,
    write_campaign_record,
)


def make_platform_record(
    *,
    record_type: str,
    schema_version: str,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return make_campaign_record(
        record_type=record_type,
        schema_version=schema_version,
        status=status,
        payload=payload,
    )


def verify_platform_record(record: dict[str, Any]) -> bool:
    return verify_campaign_record(record)


def write_platform_record(
    record: dict[str, Any], output_dir: Path, *, name_key: str = "record_id"
) -> Path:
    return write_campaign_record(record, output_dir, name_key=name_key)
