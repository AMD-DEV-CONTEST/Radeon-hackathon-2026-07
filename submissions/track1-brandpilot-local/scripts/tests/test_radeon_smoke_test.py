from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.radeon_smoke_test import (
    AUTO_SDXL_THRESHOLD_BYTES,
    SD15_MODEL_ID,
    SDXL_MODEL_ID,
    SmokeTestError,
    require_rocm,
    run_with_one_oom_retry,
    select_model,
    write_metadata,
)


class FakeCuda:
    class OutOfMemoryError(RuntimeError):
        pass

    def __init__(self, *, available: bool, count: int = 1, memory: int = 8 * 1024**3):
        self._available = available
        self._count = count
        self._memory = memory

    def is_available(self):
        return self._available

    def device_count(self):
        return self._count

    def get_device_name(self, index):
        return "AMD Radeon Test Device"

    def get_device_properties(self, index):
        return SimpleNamespace(total_memory=self._memory)


def fake_torch(*, hip="7.2.1", available=True, count=1, memory=8 * 1024**3):
    return SimpleNamespace(
        __version__="2.9.1+rocm7.2.1",
        version=SimpleNamespace(hip=hip),
        cuda=FakeCuda(available=available, count=count, memory=memory),
    )


def test_gpu_unavailable_refuses_cpu():
    with pytest.raises(SmokeTestError, match="refusing CPU execution"):
        require_rocm(fake_torch(available=False))


def test_hip_unavailable_refuses_non_rocm():
    with pytest.raises(SmokeTestError, match="torch.version.hip"):
        require_rocm(fake_torch(hip=None))


def test_auto_selects_sd15_below_16_gib():
    assert select_model("auto", AUTO_SDXL_THRESHOLD_BYTES - 1) == ("sd15", SD15_MODEL_ID)


def test_auto_selects_sdxl_at_or_above_16_gib():
    assert select_model("auto", AUTO_SDXL_THRESHOLD_BYTES) == ("sdxl", SDXL_MODEL_ID)


def test_unknown_memory_selects_safe_fallback():
    assert select_model("auto", None) == ("sd15", SD15_MODEL_ID)


def test_one_oom_retry_only(caplog):
    attempts = []
    cleanups = []

    def attempt(reduced_memory):
        attempts.append(reduced_memory)
        if not reduced_memory:
            raise FakeCuda.OutOfMemoryError("HIP out of memory")
        return "real-result"

    with caplog.at_level(logging.INFO):
        result = run_with_one_oom_retry(
            attempt,
            lambda exc: isinstance(exc, FakeCuda.OutOfMemoryError),
            lambda: cleanups.append(True),
            logging.getLogger("test"),
        )
    assert result == "real-result"
    assert attempts == [False, True]
    assert cleanups == [True]


def test_non_oom_error_has_no_retry_or_fallback():
    attempts = []

    def attempt(reduced_memory):
        attempts.append(reduced_memory)
        raise ValueError("real failure")

    with pytest.raises(ValueError, match="real failure"):
        run_with_one_oom_retry(attempt, lambda exc: False, lambda: None, logging.getLogger("test"))
    assert attempts == [False]


def test_metadata_creation(tmp_path):
    metadata_path = tmp_path / "generation-metadata.json"
    write_metadata(metadata_path, {"status": "failed", "output_produced_successfully": False})
    saved = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert saved == {"status": "failed", "output_produced_successfully": False}


def test_model_choices_never_reference_mock():
    assert "mock" not in SDXL_MODEL_ID.lower()
    assert "mock" not in SD15_MODEL_ID.lower()
