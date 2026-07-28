import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

"""
Benchmark completo de performance do VTE.

Mede:
1. Throughput (tokens/s) em diferentes configurações
2. Latência de prefill
3. Uso de recursos (VRAM, GPU, CPU)
"""

def benchmark_configuration(name: str, use_fusion: bool, use_graphs: bool):
    """Benchmark uma configuração específica"""
    print(f"\n{'='*70}")
    print(f"BENCHMARK: {name}")
    print(f"Fusion: {use_fusion}, HIP Graphs: {use_graphs}")
    print(f"{'='*70}")
    
    # Carrega modelo com configuração
    model = VTEModel.from_pretrained(
        "qwen2.5:1.5b-q4_k_m",
        use_hip_graph=use_graphs,
        enable_fusion=use_fusion
    )
    
    # Warmup
    print("Warmup...")
    for _ in model.generate("Test", max_tokens=5): pass
    
    # Benchmark de decode (geração)
    print("\nBenchmark de Decode (geração de texto)...")
    test_prompt = "Explique o que é inteligência artificial em uma frase."
    
    times = []
    for i in range(5):  # 5 iterações
        start = time.perf_counter()
        response = ""
        for token in model.generate(test_prompt, max_tokens=50):
            response += token
        elapsed = time.perf_counter() - start
        
        tokens = len(response.split())
        tps = tokens / elapsed
        times.append(tps)
        
        print(f"  Iteração {i+1}: {tps:.1f} tokens/s")
    
    avg_tps = sum(times) / len(times)
    min_tps = min(times)
    max_tps = max(times)
    
    print(f"\nResultados:")
    print(f"  TPS médio: {avg_tps:.1f}")
    print(f"  TPS mín:   {min_tps:.1f}")
    print(f"  TPS máx:   {max_tps:.1f}")
    
    # Benchmark de prefill
    print("\nBenchmark de Prefill (processamento de prompt)...")
    long_prompt = " ".join(["Test"] * 512)  # ~512 tokens
    
    start = time.perf_counter()
    for _ in model.generate(long_prompt, max_tokens=1): pass
    prefill_time = time.perf_counter() - start
    
    print(f"  Tempo de prefill (512 tokens): {prefill_time*1000:.1f}ms")
    
    # Uso de recursos
    print("\nUso de recursos:")
    vram_usage = model.get_vram_usage()
    if vram_usage:
        print(f"  VRAM: {vram_usage.get('total_mb', 0):.1f} MB")
        vram_mb = vram_usage.get('total_mb', 0)
    else:
        vram_mb = 0
    
    # Cleanup
    model.unload()
    
    return {
        'name': name,
        'avg_tps': avg_tps,
        'min_tps': min_tps,
        'max_tps': max_tps,
        'prefill_time_ms': prefill_time * 1000,
        'vram_mb': vram_mb
    }

def main():
    print("="*70)
    print("BENCHMARK COMPLETO DE PERFORMANCE")
    print("="*70)
    
    results = []
    
    # Configuração 1: Baseline (sem otimizações)
    results.append(benchmark_configuration(
        "Baseline (sem otimizações)",
        use_fusion=False,
        use_graphs=False
    ))
    
    # Configuração 2: Apenas Kernel Fusion
    results.append(benchmark_configuration(
        "Apenas Kernel Fusion",
        use_fusion=True,
        use_graphs=False
    ))
    
    # Configuração 3: Apenas HIP Graphs
    results.append(benchmark_configuration(
        "Apenas HIP Graphs",
        use_fusion=False,
        use_graphs=True
    ))
    
    # Configuração 4: Ambas otimizações
    results.append(benchmark_configuration(
        "Kernel Fusion + HIP Graphs",
        use_fusion=True,
        use_graphs=True
    ))
    
    # Relatório comparativo
    print("\n" + "="*70)
    print("RELATÓRIO COMPARATIVO")
    print("="*70)
    print(f"{'Configuração':<40} {'TPS':<10} {'Prefill':<10} {'VRAM':<10}")
    print("-"*70)
    
    for result in results:
        print(
            f"{result['name']:<40} "
            f"{result['avg_tps']:<10.1f} "
            f"{result['prefill_time_ms']:<10.1f}ms "
            f"{result['vram_mb']:<10.1f}MB"
        )
    
    # Calcula speedups
    baseline_tps = results[0]['avg_tps']
    print("\nSpeedups relativos ao baseline:")
    for result in results[1:]:
        speedup = result['avg_tps'] / baseline_tps if baseline_tps > 0 else 0
        print(f"  {result['name']}: {speedup:.2f}x")
    
    print("="*70)
    
    # Valida meta de performance
    final_tps = results[-1]['avg_tps']
    if final_tps >= 100:
        print(f"✅ Meta atingida: {final_tps:.1f} TPS (meta: ≥100 TPS)")
    else:
        print(f"⚠️ Meta não atingida: {final_tps:.1f} TPS (meta: ≥100 TPS)")
    
    print("="*70)

if __name__ == "__main__":
    main()
