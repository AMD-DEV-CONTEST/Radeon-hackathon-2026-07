import pytest
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.errors import HIPSafetyError

def test_register_spilling_prevention():
    """Valida que kernels com excesso de VGPRs sao rejeitados."""
    # O compilador CodegenEngine ainda esta stubbed para o futuro (codegen.py não implementado na Phase 4.2 full localmente)
    # Mas garantimos que a API levanta erro.
    try:
        from vte.compiler.codegen import CodegenEngine
        codegen = CodegenEngine()
    except ImportError:
        pytest.skip("CodegenEngine ainda nao disponivel no repo atual.")

    malicious_template = """
    __global__ void kernel_with_too_many_regs(float* output) {
        float reg[200];
        for (int i = 0; i < 200; i++) {
            reg[i] = i * 1.5f;
        }
        output[threadIdx.x] = reg[threadIdx.x % 200];
    }
    """
    from unittest.mock import patch
    import subprocess

    # O CodegenEngine devera lancar erro se detectar register spilling nos pass-remarks do llvm
    with patch('subprocess.run') as mock_run:
        # Simulamos o hipcc retornando 200 VGPRs no stderr
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="VGPRs: 200"
        )
        # Mockamos shutil.which para garantir que ele acha o hipcc
        with patch('shutil.which', return_value="/fake/hipcc"):
            with pytest.raises(Exception, match="VGPR usage|RegisterSpilling"):
                codegen.compile_kernel("malicious_kernel", "gfx1100", mock_code=malicious_template)

def test_grid_size_limits():
    """Valida que grid sizes destrutivos sao bloqueados no HIPRuntime."""
    try:
        hip = HIPRuntime()
        hip.initialize()
    except Exception:
        pytest.skip("Requer GPU AMD nativa.")
        
    # Block max é geralmente 1024, Grid Max é astronomico, mas testamos o block
    mock_kernel = type('MockKernel', (), {'value': 1})()
    
    with pytest.raises(HIPSafetyError, match="Block size"):
        # Bloqueia tamanho de bloco astronomico
        hip.launch_kernel(mock_kernel, grid=(1, 1, 1), block=(2048, 1, 1), args=[])
