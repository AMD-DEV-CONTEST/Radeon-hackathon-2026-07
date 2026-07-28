import pytest
import ctypes
import numpy as np
from pathlib import Path
from vte.bridge.hip_runtime import HIPRuntime, hipMemcpyHostToDevice, hipMemcpyDeviceToHost

@pytest.mark.gpu_required
def test_hip_end_to_end():
    """Teste completo: init -> malloc -> memcpy -> kernel -> memcpy -> free"""
    from vte.bridge.dll_discovery import find_hip_dll
    if find_hip_dll() is None:
        pytest.skip("AMD HIP SDK não encontrado, pulando teste de hardware.")
        
    with HIPRuntime() as hip:

        arch = hip.get_gpu_architecture()
        
        n = 100
        size_bytes = n * ctypes.sizeof(ctypes.c_float)
        
        a_ptr = hip.safe_malloc(size_bytes, "buffer_A")
        b_ptr = hip.safe_malloc(size_bytes, "buffer_B")
        c_ptr = hip.safe_malloc(size_bytes, "buffer_C")
        
        a_arr = np.linspace(1.0, 100.0, n, dtype=np.float32)
        b_arr = np.linspace(10.0, 1000.0, n, dtype=np.float32)
        
        hip.safe_memcpy_host_to_device(a_ptr, a_arr.tobytes(), "h2d_A")
        hip.safe_memcpy_host_to_device(b_ptr, b_arr.tobytes(), "h2d_B")
        
        source_path = Path("kernels/vector_add.hip")
        hsaco_path = hip.compile_kernel(str(source_path), "vector_add")
        
        module, function = hip.load_kernel(hsaco_path, "vector_add")
        
        block = (64, 1, 1)
        grid = ((n + block[0] - 1) // block[0], 1, 1)
        
        args = [
            a_ptr,
            b_ptr,
            c_ptr,
            ctypes.c_int(n)
        ]
        
        hip.launch_kernel(function, grid, block, args)
        hip.synchronize()
        
        c_bytes = bytearray(size_bytes)
        hip.safe_memcpy_device_to_host(c_bytes, c_ptr, "output")
        
        c_arr = np.frombuffer(c_bytes, dtype=np.float32)
        
        expected = a_arr + b_arr
        np.testing.assert_allclose(c_arr, expected, rtol=1e-5)
        