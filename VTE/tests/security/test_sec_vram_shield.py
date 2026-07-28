import pytest
import gc
import random
from vte.core.model import VTEModel
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.core.gpu_monitor import GPUMonitor

def test_memory_leak_detection_over_time():
    """Detecta memory leaks executando ciclos de load/unload repetidos."""
    try:
        hip = HIPRuntime()
        hip.initialize()
    except Exception:
        pytest.skip("Requer GPU AMD nativa.")

    allocator = SlabAllocator(hip, 1024 * 1024 * 100)
    allocator.initialize()
    
    monitor = GPUMonitor(hip)
    gc.collect()
    baseline_vram = monitor._get_vram_allocated_mb()
    
    for i in range(100):
        ptr1 = allocator.allocate(1024 * 1024, tag=f"iter_{i}_w", region=MemoryRegion.WEIGHTS)
        ptr2 = allocator.allocate(1024 * 512, tag=f"iter_{i}_kv", region=MemoryRegion.KV_CACHE)
        
        allocator.free(ptr1)
        allocator.free(ptr2)
        gc.collect()

    final_vram = monitor._get_vram_allocated_mb()
    leaked_mb = final_vram - baseline_vram
    
    assert leaked_mb < 1.0, f"Memory leak detectado: {leaked_mb:.2f}MB vazados"


def test_slab_allocator_defragmentation():
    """Testa que o Slab Allocator nao fragmenta apos alocacoes/liberacoes aleatorias."""
    try:
        hip = HIPRuntime()
        hip.initialize()
    except Exception:
        pytest.skip("Requer GPU AMD nativa.")
        
    total_vram = 1024 * 1024 * 256
    allocator = SlabAllocator(hip, total_vram)
    allocator.initialize()
    
    blocks = []
    for i in range(1000):
        size = random.randint(1024 * 10, 1024 * 100) 
        block = allocator.allocate(size, tag=f"test_{i}", region=MemoryRegion.SCRATCH)
        if block:
            blocks.append((block, size))
            
    random.shuffle(blocks)
    half = len(blocks) // 2
    
    for block_ptr, size in blocks[:half]:
        allocator.free(block_ptr)
        
    total_free = sum(size for _, size in allocator.free_list)
    
    giant_block = allocator.allocate(int(total_free * 0.5), tag="giant", region=MemoryRegion.SCRATCH)
    
    assert giant_block is not None, "Fragmentacao imposta detectada, sem resgate do guardian."
