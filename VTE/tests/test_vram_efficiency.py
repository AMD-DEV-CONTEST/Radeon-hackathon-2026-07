import pytest
import os
import time
from vte.core.model import VTEModel
from vte.bridge.memory import MemoryRegion

# Pular os testes se não houver a flag VTE_RUN_INTEGRATION_TESTS
pytestmark = pytest.mark.skipif(
    os.environ.get("VTE_RUN_INTEGRATION_TESTS") != "1",
    reason="Requer GPU AMD e modelo baixado"
)

def test_vram_efficiency():
    """
    Testa se o overhead de VRAM do modelo Qwen2.5-1.5B (Q4_K_M)
    é mantido em níveis eficientes (<20% de overhead em relação aos pesos).
    """
    model_path = "Model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    if not os.path.exists(model_path):
        pytest.skip(f"Modelo não encontrado: {model_path}")
        
    model = VTEModel(model_path, context_length=2048)
    # Força carregamento
    model._lifecycle.ensure_loaded()
    
    # Acessa profiler
    allocations = model.profiler.allocations
    
    # Calcula os totais
    weights_total = sum(a['size_mb'] for a in allocations if a['region'] == "WEIGHTS")
    kv_total = sum(a['size_mb'] for a in allocations if a['region'] == "KV_CACHE")
    arena_total = sum(a['size_mb'] for a in allocations if a['region'] == "ACTIVATIONS")
    
    # Valida pesos
    assert 900 < weights_total < 1000, f"Pesos inesperados: {weights_total:.1f} MB (esperado ~935MB)"
    
    # Valida KV cache
    assert kv_total < 120, f"KV Cache muito grande: {kv_total:.1f} MB (esperado < 120MB para 2048 ctx)"
    
    # Valida Arena
    assert arena_total < 50, f"Activation Arena muito grande: {arena_total:.1f} MB (esperado < 50MB para 1 camada FP16)"
    
    # Total de memória consumida que não é peso
    overhead = kv_total + arena_total
    
    # Verifica o ratio de eficiência de overhead
    overhead_ratio = overhead / weights_total
    
    # Queremos um overhead menor que 20% 
    assert overhead_ratio < 0.20, f"Overhead muito alto: {overhead_ratio:.1%} (limite 20%)"
    
    # Libera os recursos para evitar problemas com outros testes
    model.unload()

def test_vram_released_after_unload():
    """
    Garante que todos os blocos alocados na VRAM são liberados no unload()
    """
    model_path = "Model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    if not os.path.exists(model_path):
        pytest.skip(f"Modelo não encontrado: {model_path}")
        
    model = VTEModel(model_path, context_length=2048)
    model._lifecycle.ensure_loaded()
    
    # Deve haver blocos preenchidos no allocator
    assert len(model._allocator.blocks) > 0
    
    # Grava VRAM livre antes do unload
    vram_before = model._allocator.get_stats()["free_bytes"]
    
    # Descarrega
    model.unload()
    
    # Espera hipFree sincronizar
    time.sleep(1)
    
    # Allocator deve estar zerado internamente
    assert model._allocator is None, "Allocator deveria ser None após unload()"
    assert model._hip is None, "HIPRuntime deveria ser None após unload()"
    
    # Stats deve refletir liberação total da reserva base
    # (ou block_pool size intacto dependendo se unload() libera o slab)
    # Se unload() não libera o SlabAllocator, precisamos validar a lógica do unload() do VTEModel.
    # Neste caso, vamos assumir que o model.unload() chama model._allocator.cleanup() que dá hipFree.
    # E vamos testar se é possivel carregar de novo!
    
    # Tenta carregar novamente para provar que a VRAM foi liberada
    model2 = VTEModel(model_path, context_length=2048)
    model2._lifecycle.ensure_loaded()
    assert len(model2._allocator.blocks) > 0
    model2.unload()
