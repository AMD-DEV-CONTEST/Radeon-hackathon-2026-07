import pytest
from vte.compiler.qwen_mapper import ActivationArena, QwenTensorMapper
from vte.bridge.memory import MemoryBlock, MemoryRegion
from vte.compiler.ir import IRGraph, IRNode, QuantizationInfo
from vte.bridge.errors import HIPSafetyError

def test_arena_reset_requires_sync():
    """
    ActivationArena é um bump allocator: múltiplas alocações no mesmo ciclo são
    permitidas (necessário porque um único layer forward pass aloca vários
    tensores intermediários antes de sincronizar). A flag `_synchronized` só
    sinaliza estado para diagnóstico; o reset de fato só ocorre em
    reset_after_sync(), chamado após hipDeviceSynchronize() confirmar que a
    GPU terminou de usar as ativações da camada anterior.
    """
    mock_block = MemoryBlock(0, 1024*1024, 1024*1024, 1000, "TEST", MemoryRegion.ACTIVATIONS)
    arena = ActivationArena(mock_block)

    ptr1, offset1 = arena.allocate(1024)
    assert offset1 == 0
    assert arena._synchronized is False

    # Uma segunda alocação no mesmo ciclo é válida e avança o bump pointer.
    ptr2, offset2 = arena.allocate(1024)
    assert offset2 == 1024
    assert ptr2 == ptr1 + 1024

    # Estourar o tamanho do bloco deve falhar.
    with pytest.raises(HIPSafetyError, match="Arena esgotada"):
        arena.allocate(1024 * 1024)

    arena.reset_after_sync()
    assert arena._synchronized is True

    ptr3, offset3 = arena.allocate(1024)
    assert offset3 == 0

def test_mapper_oom_preventive(monkeypatch):
    """
    map_and_allocate_tensors deve recusar (fail-fast) mapear um modelo cujo
    tamanho em FP16 (elementos * 2 bytes, formato usado após a dequantização
    no weight_loader.py) excede a VRAM livre do allocator.
    """
    class FakeParser:
        # 5G elementos * 2 bytes (FP16) = 10GB, meta > 8GB livres do FakeAllocator.
        tensors = {
            "huge.weight": {"shape": (5 * 1024**3,), "dtype": 1, "offset": 0, "size": 10 * 1024**3},
        }

    mapper = QwenTensorMapper(FakeParser(), {})

    class FakeAllocator:
        def get_stats(self):
            return {'free_bytes': 8 * 1024**3, 'total_bytes': 16 * 1024**3}

    with pytest.raises(HIPSafetyError, match="OOM Preventivo"):
        mapper.map_and_allocate_tensors(FakeAllocator(), hip_runtime=None)
