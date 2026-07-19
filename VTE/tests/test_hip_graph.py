import pytest
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.dll_discovery import find_hip_dll
from vte.core.hip_graph_executor import HIPGraphExecutor, GraphCaptureError
from vte.bridge.memory import SlabAllocator
from vte.compiler.ir import IRGraph

def test_hip_graph_api_signatures():
    """Valida se as novas funções C foram mapeadas sem syntax error."""
    if find_hip_dll() is None:
        pytest.skip("AMD HIP SDK não encontrado, pulando validação de grafo.")
        
    hip = HIPRuntime()
    hip.initialize()
    
    try:
        hip.stream_begin_capture()

        hip.stream_end_capture()
    except Exception as e:
        pytest.fail(f"Graph API falhou estruturalmente: {e}")

def test_hip_graph_executor_fallback():
    """Testa se o HIPGraphExecutor sobe a exceção correta se a captura falhar (o que causa o fallback no motor)."""
    if find_hip_dll() is None:
        pytest.skip("AMD HIP SDK não encontrado.")
        
    hip = HIPRuntime()
    hip.initialize()
    allocator = SlabAllocator(hip, 10 * 1024 * 1024)
    allocator.initialize()
    graph = IRGraph()
    
    executor = HIPGraphExecutor(hip, allocator, graph, tensor_mapping={})

    try:
        executor.build_decode_graph()
    except GraphCaptureError:
        pass
    except Exception as e:
        pytest.fail(f"Subiu exceção não tratada ao invés de GraphCaptureError: {e}")
