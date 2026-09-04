import json
from pathlib import Path

ROOT=Path(__file__).parents[1]
ART=ROOT/"artifacts/amd-2026-07-28/platform-current"


def load(name): return json.loads((ART/name).read_text())


def test_amd_platform_evidence_is_current_complete_and_fp64_parity_passes():
    fp64=load("platform-fp64.json")
    assert fp64["source_revision"] == "5edb8ce24b690810efad703f7550650192598118"
    assert fp64["hip"] == "7.2.53211-e1a6bc5663"
    assert fp64["device_name"] == "AMD Radeon Graphics"
    assert fp64["pipeline"]["evaluations"] == 147456
    assert fp64["pipeline"]["speedup_vs_scalar"] > 100
    assert fp64["pipeline"]["max_relative_error"] < 1e-12
    assert fp64["gcs_tensor_kernel"]["max_relative_error"] < 1e-12
    assert fp64["pipeline"]["peak_memory_allocated_bytes"] > 0


def test_amd_fp32_is_explicitly_lower_precision_and_within_reporting_gate():
    fp32=load("platform-fp32.json")
    assert fp32["dtype"] == "float32"
    assert fp32["pipeline"]["speedup_vs_scalar"] > 100
    assert 0 < fp32["pipeline"]["max_relative_error"] < 1e-4
    assert 0 < fp32["gcs_tensor_kernel"]["max_relative_error"] < 1e-5


def test_amd_hash_manifest_is_retained_for_canonical_benchmark_artifacts():
    lines=(ART/"SHA256SUMS").read_text().splitlines()
    entries={Path(line.split()[1]).name:line.split()[0] for line in lines}
    for name in ("platform-fp64.json","platform-fp32.json","primary-gcs-exact-batch-fp64.json",
                 "primary-gcs-exact-batch-fp32.json","preflight.txt"):
        assert name in entries and len(entries[name]) == 64


def test_documentation_values_are_derived_from_canonical_artifact():
    fp64=load("platform-fp64.json")
    doc=(ROOT/"docs/AMD_PLATFORM_BENCHMARK.md").read_text()
    assert f"{fp64['pipeline']['speedup_vs_scalar']:.2f}×" in doc
    assert f"{fp64['pipeline']['median_s']*1000:.3f} ms" in doc
    assert "No HMC/NUTS performance claim" in doc
