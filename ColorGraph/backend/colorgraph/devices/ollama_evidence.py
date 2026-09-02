from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OLLAMA_BACKEND_EVIDENCE_VERSION = "colorgraph.ollama-backend-evidence/v1"
_PREFIX_WINDOW_BYTES = 4096
_GPU_LIBRARY_PATTERN = re.compile(
    r"\bgpu memory\b.*?\bid=(?P<device>[^\s]+).*?\blibrary=(?P<library>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


class OllamaLogCursor(BaseModel):
    """Immutable cursor proving that backend evidence was emitted after a request began."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    server_log_path: str = Field(min_length=1)
    started_at: datetime
    start_offset: int = Field(ge=0)
    prefix_start_offset: int = Field(ge=0)
    prefix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OllamaBackendEvidence(BaseModel):
    """Ollama's own scheduler evidence for the accelerator library used by a load."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["colorgraph.ollama-backend-evidence/v1"] = (
        OLLAMA_BACKEND_EVIDENCE_VERSION
    )
    measurement_source: Literal["ollama-server-log-appended-range"] = (
        "ollama-server-log-appended-range"
    )
    server_log_path: str = Field(min_length=1)
    request_started_at: datetime
    captured_at: datetime
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    appended_bytes: int = Field(gt=0)
    appended_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accelerator_library: str = Field(min_length=1)
    accelerator_device_id: str = Field(min_length=1)
    matching_scheduler_lines: int = Field(gt=0)
    expected_accelerator_library: str = Field(min_length=1)
    expected_library_verified: bool


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def default_ollama_server_log_path() -> Path:
    override = os.getenv("COLORGRAPH_OLLAMA_SERVER_LOG", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if os.name == "nt" and local_app_data:
        return (Path(local_app_data) / "Ollama" / "server.log").resolve()
    raise RuntimeError(
        "COLORGRAPH_OLLAMA_SERVER_LOG is required when the Ollama server log "
        "is not at the standard Windows location"
    )


def begin_ollama_backend_evidence(
    path: str | Path | None = None,
) -> OllamaLogCursor:
    """Capture a tamper-evident byte cursor immediately before model generation."""

    log_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_ollama_server_log_path()
    )
    if not log_path.is_file():
        raise RuntimeError(f"Ollama server log is unavailable: {log_path}")
    start_offset = log_path.stat().st_size
    prefix_start = max(0, start_offset - _PREFIX_WINDOW_BYTES)
    with log_path.open("rb") as handle:
        handle.seek(prefix_start)
        prefix = handle.read(start_offset - prefix_start)
    return OllamaLogCursor(
        server_log_path=str(log_path),
        started_at=datetime.now(UTC),
        start_offset=start_offset,
        prefix_start_offset=prefix_start,
        prefix_sha256=_sha256(prefix),
    )


def capture_ollama_backend_evidence(
    cursor: OllamaLogCursor,
    *,
    expected_library: str = "ROCm",
) -> OllamaBackendEvidence:
    """Read only bytes appended after ``cursor`` and bind Ollama's GPU library."""

    normalized_expected = expected_library.strip()
    if not normalized_expected:
        raise ValueError("expected Ollama accelerator library cannot be empty")
    log_path = Path(cursor.server_log_path).resolve()
    if not log_path.is_file():
        raise RuntimeError(f"Ollama server log disappeared: {log_path}")
    end_offset = log_path.stat().st_size
    if end_offset <= cursor.start_offset:
        raise RuntimeError(
            "Ollama did not append accelerator backend evidence after the request began"
        )

    with log_path.open("rb") as handle:
        handle.seek(cursor.prefix_start_offset)
        prefix = handle.read(cursor.start_offset - cursor.prefix_start_offset)
        if _sha256(prefix) != cursor.prefix_sha256:
            raise RuntimeError(
                "Ollama server log prefix changed after the evidence cursor was captured"
            )
        appended = handle.read(end_offset - cursor.start_offset)
    if not appended:
        raise RuntimeError("Ollama server log appended range is empty")

    decoded = appended.decode("utf-8", errors="replace")
    matches: list[tuple[str, re.Match[str]]] = []
    for line in decoded.splitlines():
        match = _GPU_LIBRARY_PATTERN.search(line)
        if match is not None:
            matches.append((line, match))
    if not matches:
        raise RuntimeError(
            "Ollama did not emit a GPU scheduler library line for the fresh model load"
        )

    line, match = matches[-1]
    library = match.group("library")
    device_id = match.group("device")
    verified = library.casefold() == normalized_expected.casefold()
    evidence = OllamaBackendEvidence(
        server_log_path=str(log_path),
        request_started_at=cursor.started_at,
        captured_at=datetime.now(UTC),
        start_offset=cursor.start_offset,
        end_offset=end_offset,
        appended_bytes=len(appended),
        appended_sha256=_sha256(appended),
        matched_line_sha256=_sha256(line.encode("utf-8")),
        accelerator_library=library,
        accelerator_device_id=device_id,
        matching_scheduler_lines=len(matches),
        expected_accelerator_library=normalized_expected,
        expected_library_verified=verified,
    )
    if not verified:
        raise RuntimeError(
            "Ollama accelerator backend mismatch: "
            f"expected {normalized_expected}, observed {library}"
        )
    return evidence
