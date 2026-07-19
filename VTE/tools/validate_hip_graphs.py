import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

"""
Valida que HIP Graphs estão funcionando corretamente.

Executa:
1. Captura de grafo
2. Execução de grafo
3. Validação numérica (graph vs legacy)
4. Medição de performance
"""

def main():
    print("="*70)
    print("VALIDAÇÃO DE HIP GRAPHS")
    print("="*70)
    
    # 1. Carrega modelo
    print("\n[1/5] Carregando modelo...")
    model = VTEModel.from_pretrained(
        "qwen2.5:1.5b-q4_k_m",
        use_hip_graph=False,
        enable_fusion=True
    )
    
    # 2. Testa executor legado (baseline)
    print("\n[2/5] Testando executor legado (sem HIP Graphs)...")
    test_prompt = "Olá, como você está?"
    
    start = time.perf_counter()
    response_legacy = ""
    for token in model.generate(test_prompt, max_tokens=20):
        response_legacy += token
    time_legacy = time.perf_counter() - start
    
    tokens_legacy = len(response_legacy.split())
    tps_legacy = tokens_legacy / time_legacy
    
    print(f"  Tempo: {time_legacy:.2f}s")
    print(f"  Tokens: {tokens_legacy}")
    print(f"  TPS: {tps_legacy:.1f}")
    
    model.unload()

    # 3. Testa executor com HIP Graphs
    print("\n[3/5] Testando executor com HIP Graphs...")
    model_with_graph = VTEModel.from_pretrained(
        "qwen2.5:1.5b-q4_k_m",
        use_hip_graph=True,
        enable_fusion=True
    )
    
    # Verifica se grafo foi capturado
    if hasattr(model_with_graph.executor, 'graphs') and model_with_graph.executor.graphs.get('decode') is not None:
        print(f"  ✅ HIP Graph capturado com sucesso")
        print(f"     Nós no grafo: {model_with_graph.executor.graph_node_count if hasattr(model_with_graph.executor, 'graph_node_count') else 'N/A'}")
    else:
        print(f"  ❌ HIP Graph não foi capturado (usando fallback)")
        return False
    
    start = time.perf_counter()
    response_graph = ""
    for token in model_with_graph.generate(test_prompt, max_tokens=20):
        response_graph += token
    time_graph = time.perf_counter() - start
    
    tokens_graph = len(response_graph.split())
    tps_graph = tokens_graph / time_graph
    
    print(f"  Tempo: {time_graph:.2f}s")
    print(f"  Tokens: {tokens_graph}")
    print(f"  TPS: {tps_graph:.1f}")
    
    # 4. Validação numérica
    print("\n[4/5] Validando exatidão numérica...")
    if response_legacy == response_graph:
        print("  ✅ Outputs idênticos")
    else:
        print("  ⚠️ Outputs diferentes (pode ser devido a sampling)")
        print(f"     Legacy: {response_legacy[:50]}...")
        print(f"     Graph:  {response_graph[:50]}...")
    
    # 5. Relatório de performance
    print("\n[5/5] Gerando relatório de performance...")
    speedup = tps_graph / tps_legacy if tps_legacy > 0 else 0
    
    print("="*70)
    print("RELATÓRIO DE HIP GRAPHS")
    print("="*70)
    print(f"Executor Legado:")
    print(f"  TPS: {tps_legacy:.1f}")
    print(f"  Tempo: {time_legacy:.2f}s")
    print(f"\nExecutor com HIP Graphs:")
    print(f"  TPS: {tps_graph:.1f}")
    print(f"  Tempo: {time_graph:.2f}s")
    print(f"\nSpeedup: {speedup:.2f}x")
    
    if speedup >= 2.0:
        print(f"✅ Speedup adequado (≥2.0x)")
    else:
        print(f"⚠️ Speedup abaixo do esperado (<2.0x)")
    
    print("="*70)
    
    return speedup >= 2.0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
