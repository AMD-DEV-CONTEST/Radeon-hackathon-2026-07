"""Shared, read-only source and canonical-state helpers for benchmark cases."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from xenix.services.llm.messages import DatasetBlock, blocks_from_payload

from .contracts import BenchmarkCaseServices, BenchmarkInputError


@dataclass(frozen=True)
class AttachedSourceState:
    external_sha256: str
    source_dataset_ids: tuple[str, ...]
    registered_dataset_sha256: dict[str, str]


def capture_attached_source_state(
    *,
    source_path: Path,
    snapshot: Any,
    services: BenchmarkCaseServices,
) -> AttachedSourceState:
    source_dataset_ids = source_dataset_ids_from_snapshot(snapshot)
    registered_hashes: dict[str, str] = {}
    for dataset_id in source_dataset_ids:
        dataset = services.datasets.get_dataset(dataset_id)
        registered_path = Path(dataset.source_path)
        if not registered_path.is_file():
            raise BenchmarkInputError("registered_source_unreadable")
        registered_hashes[dataset_id] = sha256_file(registered_path)
    return AttachedSourceState(
        external_sha256=sha256_file(source_path),
        source_dataset_ids=tuple(source_dataset_ids),
        registered_dataset_sha256=registered_hashes,
    )


def attached_source_unchanged(
    *,
    source_path: Path,
    source_state: AttachedSourceState,
    services: BenchmarkCaseServices,
) -> bool:
    if sha256_file(source_path) != source_state.external_sha256:
        return False
    try:
        return all(
            sha256_file(Path(services.datasets.get_dataset(dataset_id).source_path)) == digest
            for dataset_id, digest in source_state.registered_dataset_sha256.items()
        )
    except Exception:
        return False


def source_dataset_ids_from_snapshot(snapshot: Any) -> list[str]:
    dataset_ids: list[str] = []
    for message in getattr(snapshot, "messages", []):
        if enum_value(getattr(message, "kind", None)) != "user":
            continue
        payload = getattr(message, "content_payload", None)
        for block in blocks_from_payload(payload if isinstance(payload, dict) else None):
            if isinstance(block, DatasetBlock) and block.dataset_id not in dataset_ids:
                dataset_ids.append(block.dataset_id)
    return dataset_ids


def canonical_completion(snapshot: Any) -> bool:
    messages = list(getattr(snapshot, "messages", []))
    if not messages or any(enum_value(getattr(message, "kind", None)) == "pending_llm_sampling" for message in messages):
        return False
    terminal = messages[-1]
    return enum_value(getattr(terminal, "kind", None)) == "assistant" and not bool(
        getattr(terminal, "refusal", None)
    )


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest().upper()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")
