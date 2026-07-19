import pytest
import ctypes
import time
from vte.bridge.errors import HIPSafetyError
from vte.bridge.hip_runtime import HIPRuntime, MemoryGuardianOOMError
from vte.bridge.watchdog import KernelWatchdog
from vte.config import MAX_GRID_DIMENSIONS

@pytest.fixture
def mock_hip():
    """Mock do HIPRuntime para testes de firewall, focado nas validações puras de Python."""

    from unittest.mock import patch, MagicMock
    
    with patch('vte.bridge.dll_discovery.find_hip_dll', return_value='dummy.dll'), \
         patch('ctypes.CDLL'):
        runtime = HIPRuntime()
        runtime._initialized = True
        runtime._vram_total = 16 * 1024 * 1024 * 1024
        
        runtime.get_device_properties = MagicMock(return_value={
        "max_threads_per_block": 1024,
        "shared_mem_per_block": 65536
    })
        yield runtime

def test_lds_overflow_prevention(mock_hip):
    """Prova que a GPU não explodirá ao requisitar mais de 64KB de LDS."""
    with pytest.raises(HIPSafetyError, match="LDS Overflow bloqueado"):

        mock_hip.launch_kernel(
            ctypes.c_void_p(123), 
            grid=(1, 1, 1), 
            block=(32, 1, 1), 
            args=[], 
            shared_mem=65537
        )

def test_kernel_grid_bomb(mock_hip):
    """Prova que Grid Bomb (que congelaria o Windows) é rechaçada pela matemática."""
    with pytest.raises(HIPSafetyError, match="Grid Bomb bloqueada"):
        mock_hip.launch_kernel(
            ctypes.c_void_p(123), 
            grid=(9999999, 9999, 1),
            block=(32, 1, 1), 
            args=[], 
            shared_mem=0
        )

def test_null_pointer_dereference(mock_hip):
    """Prova que ponteiros Nulos ou Dangling não chegam ao Driver AMD (prevenindo TDR/BSOD)."""

    with pytest.raises(HIPSafetyError, match="não rastreado"):
        mock_hip.safe_free(ctypes.c_void_p(0))
        
    with pytest.raises(HIPSafetyError, match="não rastreado"):
        mock_hip.safe_free(ctypes.c_void_p(999))
        
    with pytest.raises(HIPSafetyError, match="não rastreado"):
        mock_hip.safe_memcpy_host_to_device(ctypes.c_void_p(0), b"dados maliciosos")

def test_watchdog_panic_isolation(mock_hip):
    """Prova que o Watchdog entra em PANIC MODE e corta suprimentos (fila) sem chamar hard reset."""
    watchdog = KernelWatchdog(mock_hip)
    watchdog.start()
    try:

        exec_id = watchdog.register_execution("teste_pesado", estimated_ms=10, timeout_multiplier=2.0)
        
        time.sleep(0.3)
        
        assert watchdog.is_panic_state() is True, "Watchdog deveria ter ativado o Panic Mode!"
        
        assert watchdog.should_abort(exec_id) is True, "O kernel atrasado não foi abortado!"
        
    finally:
        watchdog.stop()
