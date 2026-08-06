from __future__ import annotations

from pathlib import Path

import pytest

from colorgraph.devices.ollama_evidence import (
    begin_ollama_backend_evidence,
    capture_ollama_backend_evidence,
)


def _append(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(value)


def test_fresh_ollama_rocm_scheduler_line_is_bound_to_appended_range(
    tmp_path: Path,
) -> None:
    log = tmp_path / "server.log"
    log.write_text("old library=CUDA evidence must not be reused\n", encoding="utf-8")
    cursor = begin_ollama_backend_evidence(log)

    _append(
        log,
        (
            'time=2026-07-31T12:00:00+08:00 level=INFO source=sched.go:491 '
            'msg="gpu memory" id=GPU-AMD-123 library=ROCm '
            'available="15.0 GiB" free="15.0 GiB"\n'
        ),
    )
    evidence = capture_ollama_backend_evidence(cursor)

    assert evidence.accelerator_library == "ROCm"
    assert evidence.accelerator_device_id == "GPU-AMD-123"
    assert evidence.expected_library_verified is True
    assert evidence.start_offset == cursor.start_offset
    assert evidence.appended_bytes > 0


def test_cuda_scheduler_line_cannot_satisfy_rocm_gate(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text("server started\n", encoding="utf-8")
    cursor = begin_ollama_backend_evidence(log)
    _append(
        log,
        (
            'time=2026-07-31T12:00:00+08:00 level=INFO source=sched.go:491 '
            'msg="gpu memory" id=GPU-NVIDIA-123 library=CUDA available="12 GiB"\n'
        ),
    )

    with pytest.raises(RuntimeError, match="expected ROCm, observed CUDA"):
        capture_ollama_backend_evidence(cursor)


def test_stale_log_without_new_backend_line_is_rejected(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text(
        'msg="gpu memory" id=GPU-OLD library=ROCm available="15 GiB"\n',
        encoding="utf-8",
    )
    cursor = begin_ollama_backend_evidence(log)
    _append(log, "POST /api/generate 200\n")

    with pytest.raises(RuntimeError, match="fresh model load"):
        capture_ollama_backend_evidence(cursor)
