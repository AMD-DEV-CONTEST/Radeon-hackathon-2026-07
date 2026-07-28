import pytest
import os
from pathlib import Path
from vte.core.model import VTEModel
from vte.bridge.errors import HIPSafetyError

def test_gguf_corruption_runtime(tmp_path):
    """Valida que corrupcao do arquivo GGUF durante execucao e detectada."""
    # O validador da fase 2 verifica headers e offsets do GGUF.
    # Vamos criar um arquivo GGUF fake e quebrar sua assinatura
    fake_gguf = tmp_path / "fake.gguf"
    
    # Assinatura GGUF valida em hex: 47 47 55 46 (GGUF)
    # Escreve assinatura invalida
    fake_gguf.write_bytes(b"BADF\x00\x00\x00\x00")
    
    with pytest.raises(Exception):
        model = VTEModel(fake_gguf)
        model._load()

def test_integer_overflow_shapes():
    """Valida que integer overflow em shapes e detectado."""
    # Shapes acima de 2^31 causam problemas de casting se nao forçado int64
    from vte.bridge.hip_runtime import HIPRuntime
    
    malicious_size = (2**31) * (2**31)
    
    hip = HIPRuntime()
    hip.initialize()
    # Se tentar alocar via safe_malloc, deve estourar a capacidade fisica
    with pytest.raises(HIPSafetyError, match="acima da VRAM total"):
        hip.safe_malloc(malicious_size)
