import pytest
import ctypes
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.errors import HIPSafetyError

def test_prevent_host_copies_isolation():
    hip = HIPRuntime()
    try:
        hip.initialize()
    except Exception:
        pytest.skip("Requer GPU AMD para testar runtime real")
        
    if not hip._initialized:
        hip._initialized = True
        hip._prevent_host_copies = True
        
    ptr = ctypes.c_void_p(0x1000)
    hip._active_allocations[0x1000] = (1024, "weights_layer_1")
    
    dst = bytearray(1024)
    
    with pytest.raises(HIPSafetyError) as excinfo:
        hip.safe_memcpy_device_to_host(dst, ptr, tag="weights_layer_1")
        
    assert "bloqueada para 'weights_layer_1'" in str(excinfo.value)
    
    hip._lib = type('MockLib', (), {'hipMemcpy': lambda *args: 0})()
    
    try:
        hip.safe_memcpy_device_to_host(dst, ptr, tag="logits_output")
    except Exception as e:
        pytest.fail(f"Deveria ter permitido a copia de 'logits', mas falhou com {e}")
