from radeon_home.rocm_telemetry import parse_rocm_sample, summarize_samples


def test_parse_rocm_sample_normalizes_cloud_json() -> None:
    sample = parse_rocm_sample(
        {
            "card0": {
                "Average Graphics Package Power (W)": "43.5",
                "GPU use (%)": "92",
                "GPU Memory Allocated (VRAM%)": "2",
                "GPU Memory Read/Write Activity (%)": "11",
                "VRAM Total Memory (B)": "51522830336",
                "VRAM Total Used Memory (B)": "1073741824",
            }
        },
        1.25,
    )
    assert sample["elapsed_s"] == 1.25
    assert sample["gpu_use_percent"] == 92.0
    assert sample["power_watts"] == 43.5
    assert sample["vram_used_bytes"] == 1073741824.0


def test_summarize_samples_reports_mean_and_peak() -> None:
    samples = [
        {
            "gpu_use_percent": 20.0,
            "vram_allocated_percent": 1.0,
            "vram_used_bytes": 100.0,
            "vram_total_bytes": 1000.0,
            "power_watts": 30.0,
            "memory_activity_percent": 2.0,
        },
        {
            "gpu_use_percent": 100.0,
            "vram_allocated_percent": 3.0,
            "vram_used_bytes": 300.0,
            "vram_total_bytes": 1000.0,
            "power_watts": 70.0,
            "memory_activity_percent": 8.0,
        },
    ]
    summary = summarize_samples(samples)
    assert summary["sample_count"] == 2
    assert summary["gpu_use_percent"]["mean"] == 60.0
    assert summary["gpu_use_percent"]["peak"] == 100.0
    assert summary["vram_used_bytes"]["peak"] == 300.0
    assert summary["power_watts"]["mean"] == 50.0
