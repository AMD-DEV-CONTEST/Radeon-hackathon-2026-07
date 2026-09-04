"""Fail-closed registry for external Cs sorption benchmarks.

The scientific calibration gate consumes only
``nuclidepath-cs-exchange-observations-1`` datasets.  Public files, values
reconstructed from a published ``q`` measurement, and points digitized from
figures are useful benchmarks, but they are not interchangeable with that
strict observation contract.  This module validates a separate registry so
those materials remain traceable without accidentally opening promotion.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


REGISTRY_SCHEMA = "nuclidepath-cs-benchmark-registry-1"
BENCHMARK_STATUSES = (
    "public_raw",
    "derived_from_public_raw",
    "digitized_derived",
)
PROMOTION_STATUS = "not_eligible_for_observation_dataset"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BenchmarkRegistryError(ValueError):
    """Raised when a benchmark registry is incomplete or unsafe."""


def _keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise BenchmarkRegistryError(
            f"{label} contains unsupported keys: {', '.join(sorted(unknown))}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkRegistryError(f"{label} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, label: str) -> str:
    result = _text(value, label)
    if not _SHA256.fullmatch(result):
        raise BenchmarkRegistryError(f"{label} must be a lowercase SHA-256 digest")
    return result


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise BenchmarkRegistryError(f"{label} must be a list of strings")
    result = tuple(_text(item, f"{label} entry") for item in value)
    if not result or len(set(result)) != len(result):
        raise BenchmarkRegistryError(f"{label} must be non-empty and duplicate-free")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchmarkRegistryError(f"{label} must be a non-negative integer")
    return value


def _safe_data_file(root: Path, value: Any, label: str) -> Path:
    relative = Path(_text(value, label))
    if relative.is_absolute() or ".." in relative.parts:
        raise BenchmarkRegistryError(f"{label} must be a relative repository path")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise BenchmarkRegistryError(f"{label} escapes the registry directory") from exc
    if candidate == Path(root / "manifest.json").resolve():
        raise BenchmarkRegistryError(f"{label} must point to a data file")
    return candidate


@dataclass(frozen=True)
class BenchmarkEntry:
    """One external benchmark with immutable provenance and file metadata."""

    dataset_id: str
    data_status: str
    data_file: str
    row_count: int
    columns: tuple[str, ...]
    calibration_eligible: bool
    source_hashes: Mapping[str, str]


def _parse_entry(value: Any, index: int, root: Path) -> BenchmarkEntry:
    label = f"entries[{index}]"
    if not isinstance(value, Mapping):
        raise BenchmarkRegistryError(f"{label} must be an object")
    _keys(value, {
        "dataset_id", "data_status", "calibration_eligible", "promotion_status",
        "source", "retrieval", "data_file", "columns", "row_count",
        "transformation", "source_hashes", "file_sha256",
    }, label)

    dataset_id = _text(value.get("dataset_id"), f"{label}.dataset_id")
    data_status = _text(value.get("data_status"), f"{label}.data_status")
    if data_status not in BENCHMARK_STATUSES:
        raise BenchmarkRegistryError(
            f"{label}.data_status must be one of {BENCHMARK_STATUSES}"
        )
    if value.get("calibration_eligible") is not False:
        raise BenchmarkRegistryError(
            f"{label}.calibration_eligible must be false for external benchmarks"
        )
    if value.get("promotion_status") != PROMOTION_STATUS:
        raise BenchmarkRegistryError(
            f"{label}.promotion_status must remain {PROMOTION_STATUS!r}"
        )

    source = value.get("source")
    if not isinstance(source, Mapping):
        raise BenchmarkRegistryError(f"{label}.source must be an object")
    _keys(source, {"title", "publisher", "source_url", "doi", "license_url", "permission"}, f"{label}.source")
    for key in ("title", "publisher", "source_url", "doi", "license_url", "permission"):
        _text(source.get(key), f"{label}.source.{key}")

    retrieval = value.get("retrieval")
    if not isinstance(retrieval, Mapping):
        raise BenchmarkRegistryError(f"{label}.retrieval must be an object")
    _keys(retrieval, {"retrieved_at", "method"}, f"{label}.retrieval")
    _text(retrieval.get("retrieved_at"), f"{label}.retrieval.retrieved_at")
    _text(retrieval.get("method"), f"{label}.retrieval.method")

    transformation = value.get("transformation")
    if not isinstance(transformation, Mapping):
        raise BenchmarkRegistryError(f"{label}.transformation must be an object")
    _keys(transformation, {"method", "derived_fields", "limitations"}, f"{label}.transformation")
    _text(transformation.get("method"), f"{label}.transformation.method")
    _string_list(transformation.get("derived_fields"), f"{label}.transformation.derived_fields")
    _string_list(transformation.get("limitations"), f"{label}.transformation.limitations")

    source_hashes = value.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise BenchmarkRegistryError(f"{label}.source_hashes must be a non-empty object")
    parsed_hashes = {
        _text(key, f"{label}.source_hashes key"): _sha256(digest, f"{label}.source_hashes[{key}]")
        for key, digest in source_hashes.items()
    }

    columns = _string_list(value.get("columns"), f"{label}.columns")
    data_file = _text(value.get("data_file"), f"{label}.data_file")
    path = _safe_data_file(root, data_file, f"{label}.data_file")
    if path.suffix.lower() != ".csv":
        raise BenchmarkRegistryError(f"{label}.data_file must be a CSV")
    if not path.is_file():
        raise BenchmarkRegistryError(f"{label}.data_file does not exist: {data_file}")
    expected_digest = _sha256(value.get("file_sha256"), f"{label}.file_sha256") if "file_sha256" in value else None
    if expected_digest is None:
        raise BenchmarkRegistryError(f"{label}.file_sha256 is required")
    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise BenchmarkRegistryError(
            f"{label}.file_sha256 mismatch: expected {expected_digest}, got {actual_digest}"
        )

    expected_rows = _nonnegative_int(value.get("row_count"), f"{label}.row_count")
    if expected_rows == 0:
        raise BenchmarkRegistryError(f"{label}.row_count must be positive")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(columns):
            raise BenchmarkRegistryError(f"{label}.columns do not match the CSV header")
        if "dataset_id" not in columns or "observation_id" not in columns:
            raise BenchmarkRegistryError(f"{label} CSV must identify dataset and observation")
        if "measurement_status" not in columns:
            raise BenchmarkRegistryError(f"{label} CSV must expose measurement_status")
        seen: set[str] = set()
        count = 0
        for row_index, row in enumerate(reader, start=2):
            count += 1
            if row.get("dataset_id") != dataset_id:
                raise BenchmarkRegistryError(
                    f"{label} row {row_index} has a mismatched dataset_id"
                )
            observation_id = _text(row.get("observation_id"), f"{label} row {row_index}.observation_id")
            if observation_id in seen:
                raise BenchmarkRegistryError(f"{label} contains duplicate observation_id {observation_id}")
            seen.add(observation_id)
            status = _text(row.get("measurement_status"), f"{label} row {row_index}.measurement_status")
            if status == "measured_traceable":
                raise BenchmarkRegistryError(
                    f"{label} cannot label external benchmark rows measured_traceable"
                )
        if count != expected_rows:
            raise BenchmarkRegistryError(
                f"{label}.row_count says {expected_rows}, CSV contains {count} rows"
            )

    return BenchmarkEntry(
        dataset_id=dataset_id,
        data_status=data_status,
        data_file=data_file,
        row_count=expected_rows,
        columns=columns,
        calibration_eligible=False,
        source_hashes=parsed_hashes,
    )


def validate_benchmark_registry(manifest_path: str | Path) -> tuple[BenchmarkEntry, ...]:
    """Validate a registry manifest and every referenced CSV file.

    The returned entries are metadata only.  They are deliberately not
    accepted by :class:`ObservationDataset` or by the promotion gate.
    """

    manifest = Path(manifest_path)
    if manifest.name != "manifest.json":
        raise BenchmarkRegistryError("manifest_path must point to manifest.json")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkRegistryError(f"cannot read registry manifest: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise BenchmarkRegistryError("registry manifest must be an object")
    _keys(payload, {"schema", "registry_id", "entries"}, "registry")
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise BenchmarkRegistryError("unsupported benchmark registry schema")
    _text(payload.get("registry_id"), "registry.registry_id")
    entries = payload.get("entries")
    if isinstance(entries, (str, bytes)) or not isinstance(entries, list) or not entries:
        raise BenchmarkRegistryError("registry.entries must be a non-empty list")
    parsed = tuple(_parse_entry(value, index, manifest.parent) for index, value in enumerate(entries))
    ids = [entry.dataset_id for entry in parsed]
    if len(set(ids)) != len(ids):
        raise BenchmarkRegistryError("registry dataset_id values must be unique")
    return parsed
