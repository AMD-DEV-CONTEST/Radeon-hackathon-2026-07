import json
from pathlib import Path
import shutil

import pytest

from nuclear_agent.dataset_registry import (
    BENCHMARK_STATUSES,
    BenchmarkRegistryError,
    validate_benchmark_registry,
)
from nuclear_agent.scientific_validation import ALLOWED_DATA_STATUSES


REGISTRY = Path(__file__).parents[1] / "data" / "benchmarks" / "cs" / "manifest.json"


def test_external_registry_validates_all_separate_benchmarks():
    entries = validate_benchmark_registry(REGISTRY)
    assert [entry.dataset_id for entry in entries] == [
        "epa-safety-light-cation-v1",
        "fuller-2014-fig1",
        "dubus-2023-fig2",
    ]
    assert [entry.row_count for entry in entries] == [27, 21, 25]
    assert all(entry.calibration_eligible is False for entry in entries)
    assert set(BENCHMARK_STATUSES).isdisjoint(ALLOWED_DATA_STATUSES)


def test_registry_rejects_an_attempt_to_promote_a_benchmark(tmp_path):
    temp_registry = tmp_path / "manifest.json"
    shutil.copy2(REGISTRY, temp_registry)
    for data_file in REGISTRY.parent.glob("*.csv"):
        shutil.copy2(data_file, tmp_path / data_file.name)
    payload = json.loads(temp_registry.read_text(encoding="utf-8"))
    payload["entries"][0]["calibration_eligible"] = True
    temp_registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BenchmarkRegistryError, match="calibration_eligible"):
        validate_benchmark_registry(temp_registry)


def test_registry_rejects_a_stale_file_digest(tmp_path):
    temp_registry = tmp_path / "manifest.json"
    shutil.copy2(REGISTRY, temp_registry)
    for data_file in REGISTRY.parent.glob("*.csv"):
        shutil.copy2(data_file, tmp_path / data_file.name)
    csv_path = tmp_path / "epa_safety_light_cation.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(BenchmarkRegistryError, match="file_sha256 mismatch"):
        validate_benchmark_registry(temp_registry)
