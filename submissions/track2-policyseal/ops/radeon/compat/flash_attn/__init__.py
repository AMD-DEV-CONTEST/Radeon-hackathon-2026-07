"""ROCm namespace shim for the vendor flash-attn package.

The Radeon image includes Triton sources alongside a CUDA-only package initializer.
Extending the package path exposes those pure Triton helpers without importing the
unavailable CUDA extension.
"""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
__version__ = "2.8.3-rocm-namespace"
