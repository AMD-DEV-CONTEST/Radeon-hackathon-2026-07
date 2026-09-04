import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_scientific_benchmark_document_matches_canonical_artifact():
    artifact = json.loads(
        (ROOT / "artifacts/amd-2026-07-28/scientific/transport-benchmark.json").read_text()
    )
    document = (ROOT / "docs/AMD_SCIENTIFIC_BENCHMARK.md").read_text()
    records = {
        (record["batch_size"], record["backend"]): record
        for record in artifact["records"]
    }
    backends = (
        "python-scalar-float64",
        "torch-cpu-float64",
        "torch-cuda-float64",
        "torch-cuda-float32",
    )
    for size in (1, 128, 4096, 65536):
        for backend in backends:
            measured = records[(size, backend)]["evaluations_per_s"]
            assert f"{measured:,.0f} eval/s" in document

    scalar = records[(65536, "python-scalar-float64")]["evaluations_per_s"]
    for backend in backends[1:]:
        speedup = records[(65536, backend)]["evaluations_per_s"] / scalar
        assert f"**{speedup:.2f}×**" in document
