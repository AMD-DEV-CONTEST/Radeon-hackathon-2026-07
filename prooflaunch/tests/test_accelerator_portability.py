from __future__ import annotations

import unittest

from prooflaunch_remix.accelerator_portability import (
    AcceleratorBackend,
    AcceleratorPortabilityError,
    resolve_accelerator_backend,
)


class AcceleratorPortabilityTests(unittest.TestCase):
    def test_auto_selects_observed_rocm_or_cuda_without_fabrication(self) -> None:
        rocm = resolve_accelerator_backend(
            "auto", gpu_available=True, hip_version="7.2.1", cuda_version=None
        )
        cuda = resolve_accelerator_backend(
            "auto", gpu_available=True, hip_version=None, cuda_version="12.8"
        )
        self.assertIs(rocm.selected_backend, AcceleratorBackend.ROCM)
        self.assertIs(cuda.selected_backend, AcceleratorBackend.CUDA)

    def test_explicit_backend_mismatch_or_cpu_fails_closed(self) -> None:
        with self.assertRaisesRegex(AcceleratorPortabilityError, "requested rocm"):
            resolve_accelerator_backend(
                "rocm", gpu_available=True, hip_version=None, cuda_version="12.8"
            )
        with self.assertRaisesRegex(AcceleratorPortabilityError, "no visible"):
            resolve_accelerator_backend(
                "auto", gpu_available=False, hip_version=None, cuda_version=None
            )


if __name__ == "__main__":
    unittest.main()
