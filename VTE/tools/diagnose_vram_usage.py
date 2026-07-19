import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.compiler.sanitizer import GGUFSanitizer
from vte.bridge.memory import SlabAllocator
from vte.bridge.hip_runtime import HIPRuntime
from vte.core.vram_profiler import VRAMProfiler
from vte.compiler.gguf_parser import GGUFParser

def diagnose_vram_usage():
    print("Iniciando diagnostico de VRAM...")
    
    # 1. Carrega metadata
    model_path = "Model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    sanitizer = GGUFSanitizer(model_path)
    sanitizer.validate()
    
    metadata = {
        "embedding_length": sanitizer.header.embedding_length,
        "block_count": sanitizer.header.block_count,
        "context_length": sanitizer.header.context_length
    }
    
    hip = HIPRuntime()
    hip.initialize()
    
    # 2. Faz parser dos tensores e constrói o grafo
    parser = GGUFParser(model_path)
    
    from vte.compiler.qwen_mapper import QwenTensorMapper
    mapper = QwenTensorMapper(parser, metadata)
    
    # 3. Calcula pool necessário
    reqs = mapper.calculate_memory_requirements(2048)
    requested_pool_size = reqs['with_margin']
    
    vram_total = hip.get_device_properties()['total_global_mem']
    allocator = SlabAllocator(hip, vram_total, requested_pool_size=requested_pool_size)
    allocator.initialize()
    
    profiler = VRAMProfiler(allocator)
    
    # 4. Mapeia tensores
    mapper.map_and_allocate_tensors(allocator, hip, profiler=profiler, context_length=2048)
    
    # 4. Imprime diagnostico
    profiler.print_summary()
    
    anomalies = profiler.detect_anomalies()
    
    if anomalies:
        print("\nANOMALIAS DETECTADAS:")
        for anomaly in anomalies:
            print("  " + anomaly)
            
        print("\nSUGESTOES DE OTIMIZACAO:")
        print("1. Reduzir context_length para 2048 se 4096 nao for necessario")
        print("2. Verificar se Activation Arena esta dimensionada para 1 camada")
        print("3. Confirmar que Tied Embeddings estao sendo reutilizados")
        print("4. Verificar se ha duplicacao de RoPE cache")
    else:
        print("\nDiagnostico concluido. Nenhuma anomalia grave na VRAM detectada.")
    
    allocator.cleanup()
    
if __name__ == "__main__":
    diagnose_vram_usage()
