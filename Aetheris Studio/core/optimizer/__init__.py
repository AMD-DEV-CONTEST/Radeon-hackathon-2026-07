"""
Aetheris ROCm Kernel Optimizer Subsystem.
Provides isolated, autonomous kernel optimization loops for AMD Radeon (RDNA3) GPUs using deterministic parameter variations, byte-identical validation, empirical benchmark metrology, and cryptographic Flight Recorder logging.
"""

import os


def is_optimizer_enabled() -> bool:
    return os.getenv("AETHERIS_OPTIMIZER_ENABLED", "false").lower() == "true"
