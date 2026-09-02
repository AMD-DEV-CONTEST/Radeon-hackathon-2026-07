from __future__ import annotations

from pathlib import Path

from .legacy_parse_recover import recover_json_line
from .models import (
    LegacyScanItem,
    choose_bucket,
    classify_failure_text,
    compact_failure_evidence,
    compact_text,
    extract_metadata,
    extract_tool,
    infer_language,
    is_replayable,
    stable_hash_text,
)


def classify_raw_line(raw: str, *, path: Path, line_number: int) -> LegacyScanItem:
    record, parse_error = recover_json_line(raw)
    row_hash = stable_hash_text(raw.rstrip("\n"))
    if record is None:
        return LegacyScanItem(
            legacy_row_hash=row_hash,
            path=str(path),
            line_number=line_number,
            bucket="unrecoverable",
            parse_error=parse_error,
            failure_classes=["parse_error"],
        )

    text = compact_text(record)
    failure_text = compact_failure_evidence(record)
    bucket = choose_bucket(record, text)
    return LegacyScanItem(
        legacy_row_hash=row_hash,
        path=str(path),
        line_number=line_number,
        bucket=bucket,
        tool=extract_tool(record, text),
        language_guess=infer_language(record, text),
        verdict=extract_metadata(record, "verdict")
        or extract_metadata(record, "test_result")
        or "unknown",
        test_id=extract_metadata(record, "test_id") or extract_metadata(record, "test_name"),
        eval_json=extract_metadata(record, "eval_json"),
        gate_result_path=extract_metadata(record, "gate_result_path"),
        failure_classes=classify_failure_text(failure_text),
        replayable=is_replayable(record),
    )
