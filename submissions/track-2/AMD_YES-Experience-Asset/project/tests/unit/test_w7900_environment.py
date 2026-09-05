from __future__ import annotations

import pytest

from scripts.capture_w7900_environment import validate_w7900_hardware_profile

MIB = 1024 * 1024


@pytest.mark.parametrize("processor_count", [48, 96])
def test_official_pod_generic_device_name_matches_stable_w7900_profile(
    processor_count: int,
) -> None:
    profile = validate_w7900_hardware_profile(
        device_name_raw="AMD Radeon Graphics",
        gpu_arch_raw="gfx1100:sramecc-:xnack-",
        compute_units=processor_count,
        memory_bytes=49136 * MIB,
    )

    assert profile == {
        "gpu_profile": "AMD Radeon PRO W7900 48GB",
        "gpu_profile_match": True,
        "gpu_device_name_raw": "AMD Radeon Graphics",
        "gpu_arch": "gfx1100",
        "gpu_compute_units": processor_count,
        "gpu_memory_bytes": 49136 * MIB,
    }


@pytest.mark.parametrize(
    ("gpu_arch", "compute_units", "memory_bytes"),
    [
        ("gfx1030", 96, 49136 * MIB),
        ("gfx1100", 64, 49136 * MIB),
        ("gfx1100", 96, 24 * 1024**3),
    ],
)
def test_marketing_name_cannot_override_a_non_w7900_hardware_profile(
    gpu_arch: str,
    compute_units: int,
    memory_bytes: int,
) -> None:
    with pytest.raises(RuntimeError, match="expected the W7900 hardware profile"):
        validate_w7900_hardware_profile(
            device_name_raw="AMD Radeon PRO W7900",
            gpu_arch_raw=gpu_arch,
            compute_units=compute_units,
            memory_bytes=memory_bytes,
        )
