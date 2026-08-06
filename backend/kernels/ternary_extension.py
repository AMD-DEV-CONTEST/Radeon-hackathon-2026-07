"""Build and call the custom ternary GEMM HIP kernel.

When HIP/ROCm is available, this module compiles ternary_gemm.hip into a
shared library and exposes it as a torch.autograd.Function. On CPU or when
HIP is unavailable it falls back to the reference PyTorch implementation.
"""
import ctypes
import os
import subprocess
import tempfile
import warnings
from pathlib import Path

import numpy as np
import torch

_KERNEL_DIR = Path(__file__).resolve().parent.parent.parent / "kernels"
_HIPCC = os.environ.get("HIPCC", "hipcc")
_LIB_NAME = "libternary_gemm.so"
# Comma-separated gfx targets, e.g. "gfx1100" for RDNA3 desktop cards.
_HIP_OFFLOAD_ARCH = os.environ.get("HIP_OFFLOAD_ARCH", "")


def _compile_kernel() -> str:
    src = _KERNEL_DIR / "ternary_gemm.hip"
    if not src.exists():
        raise FileNotFoundError(f"Kernel source not found at {src}")
    out_dir = Path(tempfile.gettempdir()) / "xray_ternary_gemm"
    out_dir.mkdir(parents=True, exist_ok=True)
    lib_path = out_dir / _LIB_NAME
    cmd = [
        _HIPCC,
        "-O3",
        "-fPIC",
        "-shared",
        "-D__HIP_PLATFORM_AMD__",
        #str(src),
        #"-o",
        #str(lib_path),
    ]
    for arch in filter(None, (a.strip() for a in _HIP_OFFLOAD_ARCH.split(","))):
        cmd.append(f"--offload-arch={arch}")
    cmd += [str(src), "-o", str(lib_path)]
    
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(lib_path)


def _load_kernel():
    try:
        lib_path = _compile_kernel()
        lib = ctypes.CDLL(lib_path)
        lib.launch_ternary_gemm.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        return lib
    except Exception as exc:
        warnings.warn(f"Could not compile/load ternary GEMM kernel: {exc}")
        return None


_LIB = _load_kernel()


def pack_ternary_weights(ternary_weight: torch.Tensor) -> tuple[torch.Tensor, int, int]:
    """Pack int8 tensor of shape (N, K) with values in {-1, 0, 1} into uint8.

    Returns (packed, N, packed_K), where packed_K = ceil(K / 4).
    """
    ternary = ternary_weight.to(torch.int8).cpu().numpy()
    N, K = ternary.shape
    packed_K = (K + 3) // 4
    packed = np.zeros((N, packed_K), dtype=np.uint8)
    for n in range(N):
        for k in range(K):
            lane = k % 4
            pk = k // 4
            val = int(ternary[n, k])
            if val == 1:
                packed[n, pk] |= (0x1 << (lane * 2))
            elif val == -1:
                packed[n, pk] |= (0x2 << (lane * 2))
    return torch.from_numpy(packed), N, packed_K


class TernaryGemmFunction(torch.autograd.Function):
    """Custom ternary GEMM forward pass.

    Backward is not implemented because this is an inference-only kernel.
    """

    @staticmethod
    def forward(ctx, X, W_packed, scales, K):
        if _LIB is None or not X.is_cuda:
            # Fallback to full-precision matmul
            W = _unpack_weights(W_packed, K, scales)
            return torch.matmul(X, W.t())

        M, in_K = X.shape
        N, packed_K = W_packed.shape
        Y = torch.empty(M, N, device=X.device, dtype=torch.float32)
        stream = torch.cuda.current_stream(X.device).cuda_stream
        _LIB.launch_ternary_gemm(
            X.contiguous().data_ptr(),
            W_packed.contiguous().data_ptr(),
            Y.data_ptr(),
            M,
            N,
            K,
            scales.contiguous().data_ptr(),
            ctypes.c_void_p(stream),
        )
        return Y


def _unpack_weights(W_packed: torch.Tensor, K: int, scales: torch.Tensor) -> torch.Tensor:
    packed_K = W_packed.shape[1]
    packed = W_packed.cpu().numpy()
    N = W_packed.shape[0]
    W = np.zeros((N, K), dtype=np.float32)
    for n in range(N):
        for k in range(K):
            lane = k % 4
            pk = k // 4
            val = (packed[n, pk] >> (lane * 2)) & 0x3
            if val == 1:
                W[n, k] = 1.0
            elif val == 2:
                W[n, k] = -1.0
    W *= scales.cpu().numpy().reshape(-1, 1)
    return torch.from_numpy(W).to(W_packed.device)


def ternary_linear(x: torch.Tensor, W_packed: torch.Tensor, scales: torch.Tensor, K: int, bias: torch.Tensor) -> torch.Tensor:
    """Convenience wrapper matching the TernaryLinear API."""
    y = TernaryGemmFunction.apply(x, W_packed, scales, K)
    if bias is not None:
        y = y + bias
    return y
