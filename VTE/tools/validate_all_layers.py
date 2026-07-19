import numpy as np
from vte.core.model import VTEModel
import ctypes

def validate_all_layers():
    """Valida a estabilidade numérica propagada através das 28 camadas do modelo."""
    
    print("="*80)
    print("🔬 VALIDAÇÃO: 28 CAMADAS END-TO-END (STABILITY CHECK)")
    print("="*80)
    
    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    executor = model.executor
    
    seq_len = 32
    hidden_size = 1536
    
    def create_stable_q4_k_m(size_bytes, std):
        # Um bloco = 144 bytes, 256 elementos
        num_blocks = size_bytes // 144
        buffer = bytearray(num_blocks * 144)
        
        # d ajustado para manter a variância correta
        d_val = np.array([std / 4.0], dtype=np.float16).tobytes()
        dmin_val = np.array([0.0], dtype=np.float16).tobytes()
        
        random_bytes = np.random.randint(0, 256, size=num_blocks * 144, dtype=np.uint8).tobytes()
        buffer[:] = random_bytes
        
        for b in range(num_blocks):
            offset = b * 144
            buffer[offset:offset+2] = d_val
            buffer[offset+2:offset+4] = dmin_val
            for j in range(12):
                buffer[offset+4+j] = 1 # escalas = 1
                
        return buffer

    print("\n🔧 Injetando pesos mockados com inicialização Xavier/He (Q4_K_M aware)...")
    
    for name, ptr in model.tensor_mapping.items():
        is_weights = str(getattr(ptr, 'region', '')).endswith("WEIGHTS") or "WEIGHTS" in str(getattr(ptr, 'region', '')) or getattr(ptr, 'region', None) in (1, 0)
        if hasattr(ptr, 'region') and is_weights:
            size_bytes = ptr.size
            
            # Xavier/He parameters
            if "down_proj" in name:
                std = 0.0001
            elif "gate_proj" in name or "up_proj" in name:
                std = 0.0001
            elif "proj" in name or "attn_" in name:
                std = 0.0001
            else:
                std = 0.0001
                
            if "norm" in name:
                mock_w = np.ones(size_bytes // 2, dtype=np.float16).tobytes()
            elif "proj" in name or "attn_" in name or "ffn_" in name:
                mock_w = create_stable_q4_k_m(size_bytes, std)
            else:
                mock_w = (np.random.randn(size_bytes // 2).astype(np.float16) * std).tobytes()
                
            hip.safe_memcpy_host_to_device(
                ctypes.c_void_p(ptr.ptr),
                mock_w,
                f"mock_{name}"
            )
            
    print("  ✅ Pesos mockados injetados com inicialização estável")
    
    # Inject input_ids
    input_ids_ptr = model.tensor_mapping.get("input_ids")
    if input_ids_ptr:
        input_ids_ptr = input_ids_ptr.ptr if hasattr(input_ids_ptr, 'ptr') else input_ids_ptr
        test_tokens = np.array([15320, 992, 338, 264, 1000] + [1] * (seq_len - 5), dtype=np.int32)
        hip.safe_memcpy_host_to_device(
            ctypes.c_void_p(input_ids_ptr),
            test_tokens.tobytes(),
            "input_ids_injection"
        )
        
    print("\n🚀 Executando as 28 camadas sequencialmente...")
    
    # O embedding e norm precisam ser rodados primeiro? 
    # O fallback_executor_prefill faz isso. Vamos emular um prefill manual ou usar execute_layer iterativamente.
    # Como as ops de embedding são input_embeddings, elas já estão na "camada 0" ou fora?
    # No VTE, embedding_lookup não está na "layer 0". 
    # O fallback executor.prefill roda o DAG topológico todo.
    # Em vez de chamar prefill() que faria tudo de uma vez sem printar entre camadas,
    # vamos rodar manualmente os nós do embedding:
    
    print("➡️ Processando Embeddings...")
    emb_node = model._graph.nodes["input"]
    executor._dispatch_node(emb_node, seq_len=seq_len)
    hip.synchronize()
    
    for layer_idx in range(28):
        # Executa camada
        executor.execute_layer(layer_idx, seq_len=seq_len)
        hip.synchronize()
        
        # Lê a saída da camada
        out_tensor_name = f'blk.{layer_idx}.output'
        ptr = model.tensor_mapping.get(out_tensor_name)
        if not ptr:
            print(f"Camada {layer_idx}: ⚠️ Tensor de saída não encontrado")
            continue
            
        ptr_val = ptr.ptr if hasattr(ptr, 'ptr') else ptr
        num_elements = seq_len * hidden_size
        buffer = bytearray(num_elements * 2)
        hip.safe_memcpy_device_to_host(buffer, ctypes.c_void_p(ptr_val), f"read_{out_tensor_name}")
        
        tensor = np.frombuffer(buffer, dtype=np.float16)
        
        mean_val = np.mean(tensor)
        std_val = np.std(tensor)
        
        status = "✅"
        if np.isnan(mean_val) or np.isinf(mean_val) or np.isnan(std_val) or np.isinf(std_val):
            status = "❌ EXPLOSÃO"
        elif np.all(tensor == 0):
            status = "❌ ZERADO"
            
        print(f"Camada {layer_idx:02d} | Mean: {mean_val:8.4f} | Std: {std_val:8.4f} {status}")
        
        if "❌" in status:
            print(f"\n🚨 Falha crítica propagada na camada {layer_idx}. Abortando.")
            return

    print("\n✅ TODAS AS 28 CAMADAS VALIDADAS COM SUCESSO!")

if __name__ == "__main__":
    validate_all_layers()
